/*
 * Baileys transport only: receives, preserves full raw messages, serialises
 * each source JID, reconnects, and sends durable backend outbox items.
 * Business/HLA calculation never runs in this Node process.
 */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import axios from 'axios';
import YAML from 'yaml';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import makeWASocket, { DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState } from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
// Desktop passes a generated JSON runtime file. JSON is also valid YAML.
const runtimeConfigPath = process.env.COBO_RUNTIME_CONFIG_PATH || path.join(root, 'config.yaml');
const config = YAML.parse(fs.readFileSync(runtimeConfigPath, 'utf8'));
const wa = config.whatsapp || {};
const backendUrl = process.env.BACKEND_URL || wa.backend_url || 'http://127.0.0.1:8015';
const secret = process.env.BRIDGE_SECRET || '';
const headers = secret ? { 'X-Bridge-Secret': secret } : {};
const http = axios.create({ baseURL: backendUrl, timeout: 30_000, headers });
const log = P({ level: process.env.LOG_LEVEL || 'info' });
const debugLogPath = path.join(root, 'debug.log');
function debugTrace(label, fields = {}) {
  const line = `${new Date().toISOString()} [NODE ${label}] ${JSON.stringify(fields)}`;
  log.info(fields, label);
  try { fs.appendFileSync(debugLogPath, `${line}\n`, 'utf8'); } catch (error) { log.warn({ error: error.message }, 'debug.log write failed'); }
}
let activeTasks = 0;
const waitingTasks = [];

const normalise = value => String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
const isJid = value => /@(g\.us|newsletter|s\.whatsapp\.net|lid)$/.test(String(value));
const contactName = value => normalise(String(value).split('^', 1)[0]);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// A typed destination is resolved against the account's current WhatsApp
// groups on every connection. Keep this deliberately conservative: it exists
// for a small spelling mistake, never to guess between similarly named groups.
function nameSimilarity(leftValue, rightValue) {
  const left = normalise(leftValue).toLowerCase();
  const right = normalise(rightValue).toLowerCase();
  if (!left || !right) return 0;
  if (left === right) return 1;
  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let row = 1; row <= left.length; row += 1) {
    const current = [row];
    for (let column = 1; column <= right.length; column += 1) {
      current[column] = Math.min(
        current[column - 1] + 1,
        previous[column] + 1,
        previous[column - 1] + (left[row - 1] === right[column - 1] ? 0 : 1),
      );
    }
    previous.splice(0, previous.length, ...current);
  }
  return 1 - previous[right.length] / Math.max(left.length, right.length);
}

async function withGlobalLimit(task) {
  const max = Math.max(1, Number(wa.max_parallel_jids || 8));
  if (activeTasks >= max) await new Promise(resolve => waitingTasks.push(resolve));
  activeTasks += 1;
  try { return await task(); }
  finally {
    activeTasks -= 1;
    waitingTasks.shift()?.();
  }
}

const sessions = [];
for (const client of config.clients || []) {
  for (const session of client.sessions || []) {
    sessions.push({ client, session, input: new Map(), output: new Map(), queues: new Map(), socket: null, reconnecting: false, groupsReady: false, groupResolution: null, flushing: false });
  }
}

function configuredInputs(runtime) {
  return [...(runtime.session.in_contacts || []), ...(runtime.session.in_channels || [])].map(contactName);
}

function configuredOutputs(runtime) {
  const groups = runtime.session.out_contacts || {};
  const values = [];
  for (const section of Object.values(groups)) {
    for (const targets of Object.values(section || {})) values.push(...(Array.isArray(targets) ? targets : [targets]));
  }
  for (const job of runtime.session.scheduler?.jobs || []) values.push(...(job.targets || []));
  return values.map(normalise);
}

async function resolveGroups(runtime) {
  const groups = await runtime.socket.groupFetchAllParticipating();
  const byName = new Map();
  for (const group of Object.values(groups)) {
    const key = normalise(group.subject).toLowerCase();
    if (!byName.has(key)) byName.set(key, []);
    byName.get(key).push(group);
  }
  const jidForName = (item, { allowFuzzy = false } = {}) => {
    if (isJid(item)) return item;
    const requestedName = normalise(item);
    const matches = byName.get(requestedName.toLowerCase()) || [];
    if (matches.length === 1) return matches[0].id;
    if (matches.length > 1) log.error({ item, jids: matches.map(group => group.id) }, 'Duplicate WhatsApp group name; rename one group so config remains name-only');
    if (!allowFuzzy || requestedName.length < 5) return null;
    const candidates = Object.values(groups)
      .map(group => ({ group, score: nameSimilarity(requestedName, group.subject) }))
      .filter(candidate => candidate.score >= 0.88)
      .sort((a, b) => b.score - a.score);
    const [best, second] = candidates;
    // A second close result makes this unsafe. Do not route a customer's game
    // until the user chooses/types an unambiguous group name.
    if (best && (!second || best.score - second.score >= 0.05)) {
      log.warn({ requested: item, resolved: best.group.subject, score: Math.round(best.score * 100) }, 'Fuzzy WhatsApp output group match');
      return best.group.id;
    }
    if (best) log.error({ item, candidates: candidates.slice(0, 2).map(candidate => ({ name: candidate.group.subject, score: Math.round(candidate.score * 100) })) }, 'Ambiguous fuzzy WhatsApp output group match; choose the exact group name');
    return null;
  };
  runtime.input.clear(); runtime.output.clear();
  runtime.groupNames = new Map();
  for (const group of Object.values(groups)) runtime.groupNames.set(group.id, group.subject || group.id);
  for (const item of configuredInputs(runtime)) {
    // Inputs are deliberately exact-only: a fuzzy match here could make the
    // bot read a different customer's chat. Output destinations below are
    // allowed a guarded typo correction.
    const jid = jidForName(item);
    if (jid) runtime.input.set(jid, isJid(item) ? jid : item);
    else log.warn({ item }, 'Configured input group not found');
  }
  for (const item of configuredOutputs(runtime)) {
    const jid = jidForName(item, { allowFuzzy: true });
    if (jid && runtime.input.has(jid)) {
      // Never echo an accepted play back into a customer/input group. This is
      // almost always an accidental route selection and makes delivery look
      // like it vanished because it appears in the source chat.
      log.error({ item, jid, input_name: runtime.input.get(jid) }, 'Output group cannot be the same as an input group');
    } else if (jid) runtime.output.set(normalise(item), jid);
    else log.warn({ item }, 'Configured output group not found');
  }
  const mappings = new Map();
  const addMapping = (name, jid, role) => {
    const groupName = normalise(name);
    const key = groupName.toLowerCase();
    if (!groupName || !jid) return;
    const row = mappings.get(key) || { group_name: groupName, group_name_key: key, jid, roles: [] };
    if (!row.roles.includes(role)) row.roles.push(role);
    mappings.set(key, row);
  };
  // Keep every WhatsApp group locally available to the desktop picker. The
  // picker still stores a human-readable name, while this bridge resolves the
  // current JID on every connection.
  for (const group of Object.values(groups)) addMapping(group.subject, group.id, 'available');
  for (const [jid, name] of runtime.input) addMapping(name, jid, 'input');
  for (const [name, jid] of runtime.output) addMapping(runtime.groupNames.get(jid) || name, jid, 'output');
  await http.post('/groups/sync', {
    client_name: runtime.client.client_name,
    session_name: runtime.session.session_name,
    mappings: [...mappings.values()],
  });
  log.info({ session: runtime.session.session_name, inputs: runtime.input.size, outputs: runtime.output.size }, 'Groups resolved');
}

async function ensureGroups(runtime) {
  if (runtime.groupsReady) return;
  if (!runtime.groupResolution) {
    runtime.groupResolution = resolveGroups(runtime)
      .then(() => { runtime.groupsReady = true; })
      .finally(() => { runtime.groupResolution = null; });
  }
  await runtime.groupResolution;
}

function textOf(message) {
  return textFromContent(message.message || {});
}

function textFromContent(value) {
  // WhatsApp uses different containers for normal text, captions and quoted
  // messages. Keep this one extractor so cancel works for all text replies.
  if (value?.ephemeralMessage?.message) return textFromContent(value.ephemeralMessage.message);
  if (value?.viewOnceMessage?.message) return textFromContent(value.viewOnceMessage.message);
  if (value?.viewOnceMessageV2?.message) return textFromContent(value.viewOnceMessageV2.message);
  value = value || {};
  return value.conversation || value.extendedTextMessage?.text || value.imageMessage?.caption || value.videoMessage?.caption || value.documentMessage?.caption || '';
}

function quoteOf(message) {
  const value = message.message || {};
  const context =
    value.extendedTextMessage?.contextInfo ||
    value.imageMessage?.contextInfo ||
    value.videoMessage?.contextInfo ||
    value.documentMessage?.contextInfo ||
    null;
  const quoted = context?.quotedMessage;
  return {
    quoted_text: quoted ? textFromContent(quoted) : '',
    quoted_message_id: context?.stanzaId || null,
  };
}

function timestampOf(message) {
  const value = message.messageTimestamp;
  if (typeof value === 'number') return value;
  if (typeof value === 'string') return Number(value) || 0;
  if (value && typeof value.low === 'number') return value.low;
  return 0;
}

function runSerial(runtime, jid, task) {
  // Same JID: exact input order. Different JIDs: independent Promise chains.
  const previous = runtime.queues.get(jid) || Promise.resolve();
  const next = previous.catch(() => undefined).then(task).finally(() => {
    if (runtime.queues.get(jid) === next) runtime.queues.delete(jid);
  });
  runtime.queues.set(jid, next);
  return next;
}

async function sendOutbox(runtime, item) {
  if (item.channel !== 'whatsapp') return;
  // A normal source reply / LIMIT CHECK targets an input customer group.
  // Table and fast-forward items normally target an output group.
  const outputRequired = Boolean(item.market || item.settlement_payload);
  const configuredInputTarget = [...runtime.input.entries()]
    .find(([, name]) => normalise(name).toLowerCase() === normalise(item.target).toLowerCase())?.[0];
  let target = runtime.output.get(normalise(item.target)) || (!outputRequired ? configuredInputTarget : null) || (isJid(item.target) ? item.target : null);
  debugTrace('Outbox route trace', {
    id: item._id, requested_target: item.target, market: item.market || null,
    priority: item.priority, output_required: outputRequired,
    output_names: [...runtime.output.keys()], input_names: [...runtime.input.values()],
    resolved_target: target || null,
  }, 'Outbox route trace');
  let fallback = false;
  // Old legacy files often contain a symbolic route such as ALL_MARKET while
  // the desktop has successfully resolved exactly one real output group. Use
  // that sole output for play/table traffic rather than dropping a valid play.
  if (!target && outputRequired && runtime.output.size === 1) {
    target = [...runtime.output.values()][0];
    fallback = true;
  }
  if (!target) {
    const error = new Error(`Unknown WhatsApp group target: ${item.target}`);
    error.invalidTarget = true;
    throw error;
  }
  const options = item.quote ? { quoted: item.quote } : undefined;
  const sent = await runtime.socket.sendMessage(target, { text: item.text }, options);
  return { sent, target, targetName: runtime.groupNames?.get(target) || item.target || target, fallback };
}

async function flushOutbox(runtime) {
  // Timer, connection.open and incoming events can all request a flush. One
  // sender per linked account preserves priority/order and avoids two network
  // sends racing for the same table.
  if (!runtime.socket || runtime.flushing) return;
  runtime.flushing = true;
  try {
    const { data } = await http.post(`/outbox/claim?client_name=${encodeURIComponent(runtime.client.client_name)}&session_name=${encodeURIComponent(runtime.session.session_name)}&limit=50`);
    for (const item of data.items || []) {
      let whatsappAccepted = false;
      try {
        // This durable write happens before WhatsApp send. If it cannot be
        // recorded, do not send: a later retry could otherwise duplicate a
        // table after a failed /delivery callback.
        await http.post(`/outbox/${item._id}/attempt`);
        const delivery = await sendOutbox(runtime, item);
        if (delivery.fallback) log.warn({ configured_target: item.target, target: delivery.targetName, target_jid: delivery.target }, 'Legacy output route replaced by sole resolved output group');
        whatsappAccepted = true;
        await http.post(`/outbox/${item._id}/delivery`, { target_jid: delivery.target, sent_message: delivery.sent });
        await http.post(`/outbox/${item._id}/result?sent=true`);
        log.info({ id: item._id, target: delivery.targetName, target_jid: delivery.target, priority: item.priority }, 'Outbox sent');
      } catch (error) {
        const detail = error?.message || String(error);
        if (error?.invalidTarget) {
          await http.post(`/outbox/${item._id}/invalid-target?error=${encodeURIComponent(detail)}`).catch(() => undefined);
          log.error({ id: item._id, target: item.target, detail }, 'Outbox stopped: output group is not configured');
        } else if (whatsappAccepted) {
          // Do not set retry here. WhatsApp may already have accepted the
          // message while /delivery was unavailable. Backend restart changes
          // it to explicit `uncertain`, never a duplicate automatic send.
          await http.post(`/outbox/${item._id}/uncertain?error=${encodeURIComponent(detail)}`).catch(() => undefined);
          log.error({ id: item._id, detail }, 'Outbox send is unconfirmed; not retrying automatically');
        } else {
          await http.post(`/outbox/${item._id}/result?sent=false&error=${encodeURIComponent(detail)}`).catch(() => undefined);
          log.warn({ id: item._id, detail }, 'Outbox will retry before send');
        }
      }
    }
  } finally {
    runtime.flushing = false;
  }
}

async function startSession(runtime) {
  // One auth state belongs to exactly one WhatsApp linked device. Multi-session
  // installs automatically get separate subfolders unless explicitly overridden.
  const defaultAuth = sessions.length === 1 ? (wa.auth_dir || './auth_info/default') : path.join(wa.auth_dir || './auth_info', runtime.session.session_name);
  const authDir = path.resolve(root, runtime.session.auth_dir || defaultAuth);
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion();
  const socket = makeWASocket({ version, auth: state, logger: log.child({ session: runtime.session.session_name }), markOnlineOnConnect: true, syncFullHistory: false, generateHighQualityLinkPreview: false });
  runtime.socket = socket;

  socket.ev.on('creds.update', saveCreds);
  socket.ev.on('connection.update', async update => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) qrcode.generate(qr, { small: true });
    if (connection === 'open') {
      runtime.reconnecting = false;
      runtime.groupsReady = false;
      log.info({ session: runtime.session.session_name }, 'WhatsApp connected');
      try { await ensureGroups(runtime); await flushOutbox(runtime); } catch (error) { log.error(error, 'Initial group/outbox setup failed'); }
      return;
    }
    if (connection === 'close') {
      const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      runtime.socket = null;
      if (loggedOut) { log.error('Logged out: delete only this auth_dir and scan QR again'); return; }
      if (!runtime.reconnecting) {
        runtime.reconnecting = true;
        log.warn({ code }, 'Connection closed; reconnecting');
        await sleep(Number(wa.reconnect_delay_ms || 2500));
        startSession(runtime).catch(error => log.error(error, 'Reconnect failed'));
      }
    }
  });

  socket.ev.on('messages.upsert', ({ messages, type }) => {
    if (!['notify', 'append'].includes(type)) return;
    for (const message of messages) {
      const jid = message.key?.remoteJid;
      const text = textOf(message);
      if (!jid || message.key?.fromMe || jid === 'status@broadcast' || !text) continue;
      runSerial(runtime, jid, () => withGlobalLimit(async () => {
        // Offline messages can arrive immediately after connection.open. Wait for
        // group name -> JID resolution instead of dropping them during startup.
        await ensureGroups(runtime);
        if (runtime.input.has(jid)) {
          log.info({ jid, id: message.key.id, text: text.slice(0, 80) }, 'Incoming');
          const quote = quoteOf(message);
          await http.post('/incoming', {
            client_name: runtime.client.client_name, session_name: runtime.session.session_name,
            source_jid: jid, source_name: runtime.input.get(jid), message_id: message.key.id,
            participant: message.key.participant || message.key.participantPn || null,
            text, message_timestamp: timestampOf(message), raw_message: message, ...quote,
          });
        } else if ([...runtime.output.values()].includes(jid) && text.trim().toLowerCase() === String(runtime.session.processing?.trigger_contains || 'last').trim().toLowerCase()) {
          log.info({ jid, id: message.key.id }, 'Output settlement trigger');
          await http.post('/settlement/output-trigger', {
            client_name: runtime.client.client_name,
            session_name: runtime.session.session_name,
            output_jid: jid,
            message_id: message.key.id,
            text,
          });
        } else {
          return;
        }
        await flushOutbox(runtime);
      })).catch(error => log.error({ jid, error: error.message }, 'Incoming processing failed'));
    }
  });

  // Persistent outbox makes scheduler/restart delivery reliable without polling WhatsApp.
  const timer = setInterval(() => flushOutbox(runtime).catch(error => log.debug(error, 'Outbox unavailable')), Number(wa.outbox_poll_ms || 500));
  socket.ev.on('connection.update', update => { if (update.connection === 'close' && runtime.socket !== socket) clearInterval(timer); });
}

for (const runtime of sessions) startSession(runtime).catch(error => log.error(error, 'Session failed to start'));

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
