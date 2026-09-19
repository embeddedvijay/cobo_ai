const pages = [...document.querySelectorAll('.page')];
const nav = [...document.querySelectorAll('.nav')];
let summary;

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));

function goto(name) {
  pages.forEach(page => page.classList.toggle('active', page.id === name));
  nav.forEach(button => button.classList.toggle('active', button.dataset.page === name));
}

function contacts() {
  return Object.entries(summary?.config?.in_contacts || {}).map(([name, data]) => ({ name, ...data }));
}
function markets() { return Object.keys(summary?.config?.fixed_market_time || {}); }

function renderSummary(next) {
  summary = next || null;
  const client = summary?.clientName || 'Cobo AI';
  $('#clientName').textContent = client;
  $('#clientEmail').textContent = summary ? `local JSON · ${summary.contactCount} groups` : 'Local desktop control';
  $('#configState').textContent = summary ? 'Loaded' : 'Not loaded';
  $('#contactCount').textContent = `${summary?.contactCount || 0} contacts`;
  $('#marketCount').textContent = `${summary?.marketCount || 0} markets`;
  const data = contacts();
  $('#metricCards').innerHTML = data.slice(0, 5).map(item =>
    `<div class="metric"><b>${esc(item.name)}</b><small>LIMIT: ${esc(item.Limit || '—')}</small><div><span>PLAY</span><strong>0</strong><span>WIN</span><strong>0</strong></div></div>`
  ).join('') || '<div class="metric muted">Import JSON to load customers.</div>';
  $('#customerList').innerHTML = data.map(item =>
    `<div class="row"><b>${esc(item.name)}</b><span>LD ${esc(item.LD || '—')} · Limit ${esc(item.Limit || '—')}</span></div>`
  ).join('') || '<p class="muted">No configured customers.</p>';
  $('#marketList').innerHTML = markets().map(name =>
    `<div class="market"><b>${esc(name.replaceAll('_', ' '))}</b><span>Configured</span></div>`
  ).join('') || '<p class="muted">No market timing data.</p>';
  $('#configSummary').innerHTML = summary
    ? `<dl><dt>Client</dt><dd>${esc(client)}</dd><dt>Input groups</dt><dd>${summary.contactCount}</dd><dt>Markets</dt><dd>${summary.marketCount}</dd></dl>`
    : 'No JSON configuration imported.';
  renderManagers();
}

function readConfig() {
  const parsed = JSON.parse($('#jsonEditor').value || '{}');
  return Array.isArray(parsed) ? parsed[0] : parsed;
}
function writeConfig(config) {
  $('#jsonEditor').value = JSON.stringify(config, null, 2);
  if (summary) {
    summary.config = config;
    summary.contactCount = Object.keys(config.in_contacts || {}).length;
    summary.marketCount = Object.keys(config.fixed_market_time || {}).length;
  }
  renderSummary(summary);
}
function timeValue(row, index, field) {
  const value = row?.[index]?.[field];
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}
function routeValue(director, base, field) {
  return director?.market_overrides?.[base]?.[field] || '';
}

function renderManagers() {
  const groups = summary?.config?.in_contacts || {};
  $('#groupManager').innerHTML = Object.entries(groups).map(([name, group]) => {
    const director = group.Director || {};
    const overrides = director.market_overrides || {};
    const overrideRows = Object.keys(overrides).map(base => `
      <div class="override-row" data-group="${esc(name)}" data-market="${esc(base)}">
        <b>${esc(base)}</b>
        <input data-field="table" value="${esc(routeValue(director, base, 'table'))}" placeholder="Table output group">
        <input data-field="fast_forward" value="${esc(routeValue(director, base, 'fast_forward'))}" placeholder="Fast-forward group">
        <button class="icon danger" data-action="delete-override">−</button>
      </div>`).join('');
    return `
      <article class="group-card" data-group="${esc(name)}">
        <div class="group-head"><input class="group-name" value="${esc(name)}" aria-label="Contact name"><button class="icon danger" data-action="delete-group">Delete</button></div>
        <div class="field-grid">
          <label>LD %<input data-field="LD" type="number" min="0" max="100" value="${esc(group.LD ?? 100)}"></label>
          <label>Limit<input data-field="Limit" type="number" min="0" value="${esc(group.Limit ?? 0)}"></label>
          <label class="toggle-field">Instant cutting<input data-field="instant_cutting" type="checkbox" ${group.instant_cutting ? 'checked' : ''}></label>
        </div>
        <fieldset><legend>Director — default for all markets</legend>
          <div class="field-grid"><label>All table<input data-director="all_table" value="${esc(director.all_table || '')}" placeholder="ALL_MARKET"></label>
          <label>All fast-forward<input data-director="all_fast_forward" value="${esc(director.all_fast_forward || '')}" placeholder="ALL_MARKET"></label></div>
          <div class="override-title">Market-wise overrides <button class="text-button" data-action="add-override">＋ Add override</button></div>
          <div class="override-list">${overrideRows || '<span class="muted">No overrides — default route will be used.</span>'}</div>
        </fieldset>
        <fieldset><legend>Win rate</legend><div class="rate-grid">
          ${['ANK','Jodi','SP','DP','TP','FS','HS','Commission'].map(key => `<label>${key}<input data-rate="${key}" type="number" value="${esc(group.win_rate?.[key] ?? '')}"></label>`).join('')}
        </div></fieldset>
      </article>`;
  }).join('') || '<p class="muted">No input groups. Add your first WhatsApp customer group.</p>';

  const rows = summary?.config?.fixed_market_time || {};
  $('#marketManager').innerHTML = Object.entries(rows).map(([name, row]) => `
    <div class="timing-row" data-market-key="${esc(name)}">
      <input class="market-key" value="${esc(name)}" aria-label="Market key">
      <label>Day<input data-time="day" type="number" min="0" max="6" value="${esc(row?.[1] ?? 6)}"></label>
      <label>Start<input data-time="startHour" type="number" min="0" max="23" value="${timeValue(row,0,'hour')}"><input data-time="startMinute" type="number" min="0" max="59" value="${timeValue(row,0,'minute')}"></label>
      <label>End<input data-time="endHour" type="number" min="0" max="23" value="${timeValue(row,2,'hour')}"><input data-time="endMinute" type="number" min="0" max="59" value="${timeValue(row,2,'minute')}"></label>
      <button class="icon danger" data-action="delete-market">Delete</button>
    </div>`).join('') || '<p class="muted">No market timings.</p>';
}

function mutate(callback) {
  try { const config = readConfig(); callback(config); writeConfig(config); }
  catch (error) { $('#saveMessage').textContent = `Invalid JSON: ${error.message}`; }
}

$('#groupManager').addEventListener('input', event => {
  const card = event.target.closest('[data-group]'); if (!card) return;
  const oldName = card.dataset.group;
  mutate(config => {
    const group = config.in_contacts?.[oldName]; if (!group) return;
    if (event.target.classList.contains('group-name')) {
      const newName = event.target.value.trim();
      if (newName && newName !== oldName) { config.in_contacts[newName] = group; delete config.in_contacts[oldName]; }
    } else if (event.target.dataset.field) {
      group[event.target.dataset.field] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    } else if (event.target.dataset.director) {
      group.Director ||= {}; group.Director[event.target.dataset.director] = event.target.value.trim();
    } else if (event.target.dataset.rate) {
      group.win_rate ||= {}; group.win_rate[event.target.dataset.rate] = Number(event.target.value || 0);
    } else {
      const row = event.target.closest('[data-market]');
      if (!row || !event.target.dataset.field) return;
    }
  });
});
$('#groupManager').addEventListener('change', event => {
  const row = event.target.closest('.override-row'); if (!row) return;
  mutate(config => {
    const group = config.in_contacts?.[row.dataset.group]; if (!group) return;
    group.Director ||= {}; group.Director.market_overrides ||= {};
    group.Director.market_overrides[row.dataset.market] ||= {};
    group.Director.market_overrides[row.dataset.market][event.target.dataset.field] = event.target.value.trim();
  });
});
$('#groupManager').addEventListener('click', event => {
  const card = event.target.closest('[data-group]'); if (!card) return;
  if (event.target.dataset.action === 'delete-group') mutate(config => delete config.in_contacts[card.dataset.group]);
  if (event.target.dataset.action === 'add-override') {
    const market = prompt('Market base name, e.g. SRIDEVI_DAY'); if (!market) return;
    mutate(config => {
      const group = config.in_contacts[card.dataset.group]; group.Director ||= {}; group.Director.market_overrides ||= {};
      group.Director.market_overrides[market.trim()] = { table: group.Director.all_table || '', fast_forward: group.Director.all_fast_forward || '' };
    });
  }
  if (event.target.dataset.action === 'delete-override') {
    const row = event.target.closest('.override-row');
    mutate(config => delete config.in_contacts[row.dataset.group].Director.market_overrides[row.dataset.market]);
  }
});
$('#marketManager').addEventListener('input', event => {
  const row = event.target.closest('[data-market-key]'); if (!row) return;
  const oldKey = row.dataset.marketKey;
  mutate(config => {
    const timing = config.fixed_market_time?.[oldKey]; if (!timing) return;
    if (event.target.classList.contains('market-key')) {
      const key = event.target.value.trim(); if (key && key !== oldKey) { config.fixed_market_time[key] = timing; delete config.fixed_market_time[oldKey]; }
      return;
    }
    const field = event.target.dataset.time; if (!field) return;
    if (field === 'day') timing[1] = Number(event.target.value || 0);
    if (field === 'startHour') timing[0].hour = Number(event.target.value || 0);
    if (field === 'startMinute') timing[0].minute = Number(event.target.value || 0);
    if (field === 'endHour') timing[2].hour = Number(event.target.value || 0);
    if (field === 'endMinute') timing[2].minute = Number(event.target.value || 0);
  });
});
$('#marketManager').addEventListener('click', event => {
  const row = event.target.closest('[data-market-key]'); if (!row || event.target.dataset.action !== 'delete-market') return;
  mutate(config => delete config.fixed_market_time[row.dataset.marketKey]);
});

function log(line) { const el = $('#logs'); el.textContent = `${el.textContent}\n${line}`.trim().slice(-12000); el.scrollTop = el.scrollHeight; }
function setBot(status) { $('#botState').textContent = status.running ? 'Running' : 'Stopped'; $('#botDot').classList.toggle('running', Boolean(status.running)); if (status.code !== undefined) log(`Bot stopped with code ${status.code}`); }

nav.forEach(button => button.addEventListener('click', () => goto(button.dataset.page)));
document.querySelectorAll('[data-goto]').forEach(button => button.addEventListener('click', () => goto(button.dataset.goto)));

async function importConfig() {
  try { const next = await window.cobo.chooseConfig(); if (!next) return; const data = await window.cobo.loadConfig(); $('#jsonEditor').value = data.raw; renderSummary(next); log(`Config imported: ${next.clientName}`); }
  catch (error) { alert(error.message); }
}
async function saveConfig() {
  try { const next = await window.cobo.saveConfig($('#jsonEditor').value); renderSummary(next); $('#saveMessage').textContent = 'Saved locally.'; return next; }
  catch (error) { $('#saveMessage').textContent = error.message; throw error; }
}
async function chooseBot() { try { const state = await window.cobo.chooseBotDirectory(); log(state.botDirectory ? `Bot folder: ${state.botDirectory}` : 'Bot folder unchanged.'); } catch (error) { alert(error.message); } }
async function launch() { try { await window.cobo.startBot(); goto('dashboard'); log('npm start launched with desktop runtime config.'); } catch (error) { alert(error.message); goto('config'); } }

$('#importConfig').addEventListener('click', importConfig);
$('#saveConfig').addEventListener('click', () => saveConfig().catch(() => undefined));
$('#chooseBot').addEventListener('click', chooseBot);
$('#launchBot').addEventListener('click', launch);
$('#dashboardLaunch').addEventListener('click', launch);
$('#stopBot').addEventListener('click', () => window.cobo.stopBot());
$('#addGroup').addEventListener('click', () => {
  const name = prompt('Input WhatsApp group name'); if (!name) return;
  mutate(config => { config.in_contacts ||= {}; config.in_contacts[name.trim()] = { LD: 100, Limit: 0, instant_cutting: false, Director: { all_table: '', all_fast_forward: '', market_overrides: {} }, win_rate: { ANK: 9.5, Jodi: 95, SP: 150, DP: 300, TP: 600, FS: 10000, HS: 1000, Commission: 0 } }; });
});
$('#addMarket').addEventListener('click', () => {
  const name = prompt('Market key, e.g. KALYAN_DAY_OP'); if (!name) return;
  mutate(config => { config.fixed_market_time ||= {}; config.fixed_market_time[name.trim()] = [{ hour: 0, minute: 0, second: 0 }, 6, { hour: 0, minute: 0, second: 0 }]; });
});
$('#saveRestart').addEventListener('click', async () => { try { await saveConfig(); await window.cobo.stopBot(); await launch(); } catch {} });
window.cobo.onLog(log); window.cobo.onStatus(setBot);

(async () => {
  const state = await window.cobo.state(); renderSummary(state.summary); setBot(state);
  if (state.summary) { const data = await window.cobo.loadConfig(); $('#jsonEditor').value = data.raw; renderManagers(); }
})();