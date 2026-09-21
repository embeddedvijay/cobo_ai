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
const KEEP_ALIVE_INTERVAL_MS = 25_000;
const CONNECT_TIMEOUT_MS = 60_000;
const DEFAULT_QUERY_TIMEOUT_MS = 120_000;
const CONNECT_WATCHDOG_MS = 90_000;
const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 60_000;
const OUTBOX_STABILITY_MS = 10_000;
const FLAP_WINDOW_MS = 5 * 60_000;
const CRITICAL_FLAP_COUNT = 5;
const CRITICAL_SEND_PAUSE_MS = 5 * 60_000;
function debugTrace(label, fields = {}) {
  const line = `${new Date().toISOString()} [NODE ${label}] ${JSON.stringify(fields)}`;
  log.info(fields, label);
  try { fs.appendFileSync(debugLogPath, `${line}\n`, 'utf8'); } catch (error) { log.warn({ error: error.message }, 'debug.log write failed'); }
}
// Create the file immediately at service start, so `tail -f ../debug.log`
// works before the first WhatsApp message reaches the delivery code.
debugTrace('service started', { cwd: process.cwd(), debug_log: debugLogPath, keep_alive_ms: KEEP_ALIVE_INTERVAL_MS, connect_timeout_ms: CONNECT_TIMEOUT_MS, query_timeout_ms: DEFAULT_QUERY_TIMEOUT_MS, connect_watchdog_ms: CONNECT_WATCHDOG_MS });
let activeTasks = 0;
const waitingTasks = [];

const normalise = value => String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
const isJid = value => /@(g\.us|newsletter|s\.whatsapp\.net|lid)$/.test(String(value));
const contactName = value => normalise(String(value).split('^', 1)[0]);
function processIsAlive(pid) {
  try { process.kill(Number(pid), 0); return true; } catch { return false; }
}

function acquireSessionLock(runtime, authDir) {
  if (runtime.lockPath) return;
  const lockPath = path.join(authDir, '.cobo-bridge.lock');
  fs.mkdirSync(authDir, { recursive: true });
  try {
    fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, started_at: new Date().toISOString() }), { flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    let previous = {};
    try { previous = JSON.parse(fs.readFileSync(lockPath, 'utf8')); } catch { /* corrupt stale lock */ }
    if (previous.pid && processIsAlive(previous.pid)) {
      const duplicate = new Error(`Another Cobo bridge is already using this WhatsApp auth (PID ${previous.pid})`);
      duplicate.code = 'COBO_AUTH_LOCKED';
      throw duplicate;
    }
    fs.unlinkSync(lockPath);
    fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, started_at: new Date().toISOString() }), { flag: 'wx' });
  }
  runtime.lockPath = lockPath;
  debugTrace('WhatsApp auth lock acquired', { session: runtime.session.session_name, lock_path: lockPath, pid: process.pid });
}

function releaseSessionLocks() {
  for (const runtime of sessions) {
    if (!runtime.lockPath) continue;
    try {
      const owner = JSON.parse(fs.readFileSync(runtime.lockPath, 'utf8'));
      if (Number(owner.pid) === process.pid) fs.unlinkSync(runtime.lockPath);
    } catch { /* lock is already gone */ }
  }
}

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
    sessions.push({ client, session, input: new Map(), output: new Map(), queues: new Map(), socket: null, connecting: false, connected: false, connectedAt: 0, reconnectTimer: null, reconnectAttempts: 0, connectWatchdog: null, outboxTimer: null, disconnectTimes: [], deliveryPausedUntil: 0, groupsReady: false, groupResolution: null, flushing: false, lockPath: null });
  }
}

function clearRuntimeTimers(runtime) {
  if (runtime.connectWatchdog) clearTimeout(runtime.connectWatchdog);
  runtime.connectWatchdog = null;
  if (runtime.outboxTimer) clearInterval(runtime.outboxTimer);
  runtime.outboxTimer = null;
}

function scheduleReconnect(runtime, reason) {
  if (runtime.reconnectTimer || runtime.socket || runtime.connecting) return;
  const attempt = runtime.reconnectAttempts;
  const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * (2 ** Math.min(attempt, 5)));
  runtime.reconnectAttempts += 1;
  debugTrace('WhatsApp reconnect scheduled', { session: runtime.session.session_name, reason, attempt: attempt + 1, delay_ms: delay });
  runtime.reconnectTimer = setTimeout(() => {
    runtime.reconnectTimer = null;
    startSession(runtime).catch(error => {
      runtime.connecting = false;
      debugTrace('WhatsApp reconnect start failed', { session: runtime.session.session_name, error: error.message });
      scheduleReconnect(runtime, 'start_failed');
    });
  }, delay);
}

function holdOutbox(runtime) {
  const now = Date.now();
  if (!runtime.connected || !runtime.socket) return 'socket_not_connected';
  if (runtime.deliveryPausedUntil > now) return 'critical_network_pause';
  if (runtime.deliveryPausedUntil) {
    runtime.deliveryPausedUntil = 0;
    debugTrace('Critical network pause cleared', { session: runtime.session.session_name });
  }
  if (now - runtime.connectedAt < OUTBOX_STABILITY_MS) return 'connection_stabilising';
  return '';
}

function recordDisconnect(runtime, code) {
  const now = Date.now();
  runtime.disconnectTimes = [...runtime.disconnectTimes, now].filter(value => now - value <= FLAP_WINDOW_MS);
  if (runtime.disconnectTimes.length >= CRITICAL_FLAP_COUNT) {
    runtime.deliveryPausedUntil = now + CRITICAL_SEND_PAUSE_MS;
    debugTrace('Critical network flap: outgoing delivery safely paused', {
      session: runtime.session.session_name, close_code: code || null,
      disconnects_in_window: runtime.disconnectTimes.length, pause_ms: CRITICAL_SEND_PAUSE_MS,
    });
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
  debugTrace('Groups resolved', {
    session: runtime.session.session_name,
    inputs: [...runtime.input.entries()].map(([jid, name]) => ({ jid, name })),
    outputs: [...runtime.output.entries()].map(([name, jid]) => ({ name, jid })),
  });
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
  const socket = runtime.socket;
  const holdReason = holdOutbox(runtime);
  if (holdReason) {
    const error = new Error(`WhatsApp delivery held: ${holdReason}`);
    error.deliveryHeld = true;
    throw error;
  }
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
  let sent;
  try {
    sent = await socket.sendMessage(target, { text: item.text }, options);
  } catch (error) {
    // After a WhatsApp send is attempted, a network/transport error cannot
    // prove whether WhatsApp accepted it. Safety wins over auto-retry: the
    // record becomes uncertain, never a possible duplicate game/table.
    error.deliveryUncertain = true;
    throw error;
  }
  if (runtime.socket !== socket || !runtime.connected) {
    const error = new Error('WhatsApp connection changed after send acknowledgement');
    error.deliveryUncertain = true;
    throw error;
  }
  return { sent, target, targetName: runtime.groupNames?.get(target) || item.target || target, fallback };
}

async function flushOutbox(runtime) {
  // Timer, connection.open and incoming events can all request a flush. One
  // sender per linked account preserves priority/order and avoids two network
  // sends racing for the same table.
  const holdReason = holdOutbox(runtime);
  if (holdReason || runtime.flushing) return;
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
        } else if (whatsappAccepted || error?.deliveryUncertain) {
          // Do not set retry here. WhatsApp may already have accepted the
          // message while /delivery was unavailable. Backend restart changes
          // it to explicit `uncertain`, never a duplicate automatic send.
          await http.post(`/outbox/${item._id}/uncertain?error=${encodeURIComponent(detail)}`).catch(() => undefined);
          log.error({ id: item._id, detail }, 'Outbox send is unconfirmed; not retrying automatically');
        } else if (error?.deliveryHeld) {
          // This item was claimed just as the connection became unstable.
          // Return it to the durable queue; no WhatsApp send was attempted.
          await http.post(`/outbox/${item._id}/result?sent=false&error=${encodeURIComponent(detail)}`).catch(() => undefined);
          debugTrace('Outbox held before WhatsApp send', { id: item._id, detail });
          break;
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
  // One runtime/socket per linked WhatsApp auth. This protects the sender-key
  // store and prevents a 440 reconnect storm from duplicate local sockets.
  if (runtime.connecting || runtime.socket || runtime.reconnectTimer) {
    debugTrace('WhatsApp start ignored', { session: runtime.session.session_name, connecting: runtime.connecting, has_socket: Boolean(runtime.socket), reconnect_pending: Boolean(runtime.reconnectTimer) });
    return;
  }
  runtime.connecting = true;
  // One auth state belongs to exactly one WhatsApp linked device. Multi-session
  // installs automatically get separate subfolders unless explicitly overridden.
  const defaultAuth = sessions.length === 1 ? (wa.auth_dir || './auth_info/default') : path.join(wa.auth_dir || './auth_info', runtime.session.session_name);
  const authDir = path.resolve(root, runtime.session.auth_dir || defaultAuth);
  try {
    acquireSessionLock(runtime, authDir);
  } catch (error) {
    runtime.connecting = false;
    debugTrace('WhatsApp session not started', { session: runtime.session.session_name, auth_dir: authDir, error: error.message, code: error.code || null });
    return;
  }
  let state; let saveCreds; let version;
  try {
    ({ state, saveCreds } = await useMultiFileAuthState(authDir));
    ({ version } = await fetchLatestBaileysVersion());
  } catch (error) {
    runtime.connecting = false;
    debugTrace('WhatsApp startup preparation failed', { session: runtime.session.session_name, error: error.message });
    scheduleReconnect(runtime, 'startup_preparation_failed');
    return;
  }
  const socket = makeWASocket({
    version, auth: state, logger: log.child({ session: runtime.session.session_name }),
    markOnlineOnConnect: true, syncFullHistory: false, generateHighQualityLinkPreview: false,
    fireInitQueries: false, keepAliveIntervalMs: KEEP_ALIVE_INTERVAL_MS,
    connectTimeoutMs: CONNECT_TIMEOUT_MS, defaultQueryTimeoutMs: DEFAULT_QUERY_TIMEOUT_MS,
  });
  runtime.socket = socket;
  runtime.connected = false;
  runtime.connectWatchdog = setTimeout(() => {
    if (runtime.socket !== socket || runtime.connected) return;
    debugTrace('WhatsApp connect watchdog timeout', { session: runtime.session.session_name, timeout_ms: CONNECT_WATCHDOG_MS });
    runtime.socket = null;
    runtime.connecting = false;
    runtime.connected = false;
    runtime.connectedAt = 0;
    clearRuntimeTimers(runtime);
    recordDisconnect(runtime, 'watchdog_timeout');
    try { socket.end(new Error('Cobo connection watchdog timeout')); } catch { /* socket is already closed */ }
    scheduleReconnect(runtime, 'watchdog_timeout');
  }, CONNECT_WATCHDOG_MS);

  socket.ev.on('creds.update', saveCreds);
  socket.ev.on('connection.update', async update => {
    const { connection, lastDisconnect, qr } = update;
    const closeCode = connection === 'close' ? new Boom(lastDisconnect?.error)?.output?.statusCode : null;
    debugTrace('connection update', { session: runtime.session.session_name, connection: connection || null, close_code: closeCode, qr_received: Boolean(qr) });
    if (qr) qrcode.generate(qr, { small: true });
    if (connection === 'open') {
      if (runtime.socket !== socket) return;
      runtime.connecting = false;
      runtime.connected = true;
      runtime.connectedAt = Date.now();
      runtime.reconnectAttempts = 0;
      if (runtime.connectWatchdog) clearTimeout(runtime.connectWatchdog);
      runtime.connectWatchdog = null;
      runtime.groupsReady = false;
      debugTrace('WhatsApp connected', { session: runtime.session.session_name });
      try { await ensureGroups(runtime); await flushOutbox(runtime); } catch (error) { log.error(error, 'Initial group/outbox setup failed'); }
      return;
    }
    if (connection === 'close') {
      // A prior watchdog/socket must never tear down its newer reconnect.
      if (runtime.socket !== socket) return;
      const code = closeCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      runtime.socket = null;
      runtime.connecting = false;
      runtime.connected = false;
      runtime.connectedAt = 0;
      runtime.groupsReady = false;
      clearRuntimeTimers(runtime);
      if (!loggedOut) recordDisconnect(runtime, code);
      if (loggedOut) { debugTrace('WhatsApp logged out', { code, auth_dir: runtime.session.auth_dir || null }); return; }
      scheduleReconnect(runtime, `close_${code || 'unknown'}`);
    }
  });

  socket.ev.on('messages.upsert', ({ messages, type }) => {
    debugTrace('messages upsert', { type, count: messages?.length || 0 });
    if (!['notify', 'append'].includes(type)) {
      debugTrace('messages ignored', { reason: 'unsupported_upsert_type', type });
      return;
    }
    for (const message of messages) {
      const jid = message.key?.remoteJid;
      const text = textOf(message);
      if (!jid || message.key?.fromMe || jid === 'status@broadcast' || !text) {
        debugTrace('messages ignored', {
          reason: !jid ? 'missing_jid' : message.key?.fromMe ? 'from_me' : jid === 'status@broadcast' ? 'status_broadcast' : 'empty_text',
          jid: jid || null, id: message.key?.id || null,
        });
        continue;
      }
      runSerial(runtime, jid, () => withGlobalLimit(async () => {
        // Offline messages can arrive immediately after connection.open. Wait for
        // group name -> JID resolution instead of dropping them during startup.
        await ensureGroups(runtime);
        if (runtime.input.has(jid)) {
          debugTrace('Incoming accepted', { jid, source_name: runtime.input.get(jid), id: message.key.id, text: text.slice(0, 120) });
          const quote = quoteOf(message);
          await http.post('/incoming', {
            client_name: runtime.client.client_name, session_name: runtime.session.session_name,
            source_jid: jid, source_name: runtime.input.get(jid), message_id: message.key.id,
            participant: message.key.participant || message.key.participantPn || null,
            text, message_timestamp: timestampOf(message), raw_message: message, ...quote,
          });
        } else if ([...runtime.output.values()].includes(jid) && text.trim().toLowerCase() === String(runtime.session.processing?.trigger_contains || 'last').trim().toLowerCase()) {
          debugTrace('Output settlement trigger', { jid, id: message.key.id, text: text.slice(0, 120) });
          await http.post('/settlement/output-trigger', {
            client_name: runtime.client.client_name,
            session_name: runtime.session.session_name,
            output_jid: jid,
            message_id: message.key.id,
            text,
          });
        } else {
          debugTrace('Incoming ignored', {
            reason: 'jid_not_configured_as_input_or_output_trigger', jid, id: message.key.id,
            text: text.slice(0, 120), configured_inputs: [...runtime.input.entries()], configured_outputs: [...runtime.output.entries()],
          });
          return;
        }
        await flushOutbox(runtime);
      })).catch(error => {
        debugTrace('Incoming processing failed', {
          jid, error: error.message, status: error.response?.status || null,
          response: error.response?.data || null,
        });
      });
    }
  });

  // Persistent outbox makes scheduler/restart delivery reliable without polling WhatsApp.
  runtime.outboxTimer = setInterval(() => {
    if (runtime.socket === socket && runtime.connected) flushOutbox(runtime).catch(error => log.debug(error, 'Outbox unavailable'));
  }, Number(wa.outbox_poll_ms || 500));
}

for (const runtime of sessions) startSession(runtime).catch(error => log.error(error, 'Session failed to start'));

process.on('exit', releaseSessionLocks);
process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
