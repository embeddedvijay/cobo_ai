const pages = [...document.querySelectorAll('.page')];
const nav = [...document.querySelectorAll('.nav')];
const tabs = [...document.querySelectorAll('.tab')];
let summary;
let overrideTargetGroup = '';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

function goto(name) {
  pages.forEach(page => page.classList.toggle('active', page.id === name));
  nav.forEach(button => button.classList.toggle('active', button.dataset.page === name));
}
function gotoTab(name) {
  tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
  document.querySelectorAll('.tab-page').forEach(page => page.classList.toggle('active', page.id === name));
}
function config() { return summary?.config || {}; }
function groups() { return Object.entries(config().in_contacts || {}).map(([name, rule]) => ({ name, ...rule })); }
function timings() { return Object.entries(config().fixed_market_time || {}); }

function renderSummary(next) {
  summary = next || summary;
  const client = summary?.clientName || 'Workspace';
  $('#clientName').textContent = client;
  $('#contactCount').textContent = `${summary?.contactCount || 0} active`;
  $('#marketCount').textContent = `${summary?.marketCount || 0} timings`;
  $('#metricCards').innerHTML = [
    ['Input Groups', summary?.contactCount || 0, 'Configured customer groups'],
    ['Market Timings', summary?.marketCount || 0, 'Open and close rules'],
    ['Service Status', $('#botState')?.textContent || 'Stopped', 'Local workspace service'],
    ['Today Play', '—', 'Available while service runs']
  ].map(([label, value, note], i) => `<div class="metric metric-${i}"><small>${label}</small><strong>${esc(value)}</strong><span>${note}</span></div>`).join('');
  $('#customerList').innerHTML = groups().map(item => `<div class="row"><b>${esc(item.name)}</b><span>LD ${esc(item.LD ?? 100)}% · Limit ₹${esc(item.Limit ?? 0)}</span></div>`).join('') || '<p class="muted">No input group configured.</p>';
  $('#marketList').innerHTML = timings().slice(0, 8).map(([name]) => `<div class="market"><b>${esc(name.replaceAll('_', ' '))}</b><span>Active</span></div>`).join('') || '<p class="muted">No market timings available.</p>';
  renderManagers();
}
function currentConfig() { return structuredClone(config()); }
async function mutate(change) {
  try {
    const next = currentConfig();
    change(next);
    const saved = await window.cobo.saveConfig(JSON.stringify(next));
    renderSummary(saved);
    $('#saveMessage').textContent = 'Changes saved.';
  } catch (error) {
    $('#saveMessage').textContent = error.message;
  }
}
function directorFor(group) {
  return group.Director || { all_table: '', all_fast_forward: '', market_overrides: {} };
}
function rateInput(group, key) {
  return esc(group.win_rate?.[key] ?? '');
}
function renderManagers() {
  const groupRoot = $('#groupManager');
  if (groupRoot) groupRoot.innerHTML = groups().map(({ name, ...group }) => {
    const director = directorFor(group);
    const overrides = director.market_overrides || {};
    const overrideRows = Object.entries(overrides).map(([market, route]) => `
      <div class="override-row" data-group="${esc(name)}" data-market="${esc(market)}">
        <b>${esc(market)}</b>
        <label>Table<input data-route="table" value="${esc(route?.table || '')}" placeholder="Group name"></label>
        <label>Forward<input data-route="fast_forward" value="${esc(route?.fast_forward || '')}" placeholder="Group name"></label>
        <button class="icon danger" data-action="delete-override">−</button>
      </div>`).join('');
    return `
      <article class="group-card" data-group="${esc(name)}">
        <div class="group-head"><label>Customer group name<input class="group-name" value="${esc(name)}"></label><button class="icon danger" data-action="delete-group">Delete</button></div>
        <div class="field-grid">
          <label>LD %<input data-field="LD" type="number" min="0" max="100" value="${esc(group.LD ?? 100)}"></label>
          <label>Limit (₹)<input data-field="Limit" type="number" min="0" value="${esc(group.Limit ?? 0)}"></label>
          <label class="toggle-field">Instant Cutting<input data-field="instant_cutting" type="checkbox" ${group.instant_cutting ? 'checked' : ''}></label>
        </div>
        <fieldset><legend>Delivery destinations</legend>
          <div class="field-grid two">
            <label>All Table<input data-director="all_table" value="${esc(director.all_table || '')}" placeholder="Output group name"></label>
            <label>All Forward<input data-director="all_fast_forward" value="${esc(director.all_fast_forward || '')}" placeholder="Output group name"></label>
          </div>
          <div class="override-title">Market-wise destinations <button class="text-button" data-action="add-override">＋ Add market destination</button></div>
          <div class="override-list">${overrideRows || '<span class="muted">All markets use the destinations above.</span>'}</div>
        </fieldset>
        <fieldset><legend>Win Rate</legend><div class="rate-grid">
          ${['ANK', 'Jodi', 'SP', 'DP', 'TP', 'FS', 'HS', 'Commission'].map(key => `<label>${key}${key === 'Commission' ? ' %' : ''}<input data-rate="${key}" type="number" value="${rateInput(group, key)}"></label>`).join('')}
        </div></fieldset>
      </article>`;
  }).join('') || '<p class="muted">No input group configured. Add your first customer group.</p>';

  const root = $('#marketManager');
  if (root) root.innerHTML = timings().map(([name, row]) => `
    <div class="timing-row" data-market-key="${esc(name)}">
      <label>Market<input class="market-key" value="${esc(name)}"></label>
      <label>Active days<input data-time="day" type="number" min="0" max="7" value="${esc(row?.[1] ?? 6)}"></label>
      <label>Start (H / M)<div><input data-time="startHour" type="number" min="0" max="23" value="${esc(row?.[0]?.hour ?? 0)}"><input data-time="startMinute" type="number" min="0" max="59" value="${esc(row?.[0]?.minute ?? 0)}"></div></label>
      <label>End (H / M)<div><input data-time="endHour" type="number" min="0" max="23" value="${esc(row?.[2]?.hour ?? 0)}"><input data-time="endMinute" type="number" min="0" max="59" value="${esc(row?.[2]?.minute ?? 0)}"></div></label>
      <button class="icon danger" data-action="delete-market">Delete</button>
    </div>`).join('') || '<p class="muted">No market timings available.</p>';
}
function groupData(next, name) {
  next.in_contacts ||= {};
  return next.in_contacts[name];
}
function log(value) {
  const out = $('#logs');
  out.textContent = `${out.textContent}\n${value}`.trim().slice(-12000);
  out.scrollTop = out.scrollHeight;
}
function setService(status) {
  const label = status.running ? 'Running' : 'Stopped';
  $('#botState').textContent = label;
  $('#botDot').classList.toggle('running', Boolean(status.running));
  if (status.code !== undefined) log(`Service stopped with code ${status.code}`);
  if (summary) renderSummary(summary);
}

nav.forEach(button => button.addEventListener('click', () => goto(button.dataset.page)));
document.querySelectorAll('[data-goto]').forEach(button => button.addEventListener('click', () => goto(button.dataset.goto)));
tabs.forEach(button => button.addEventListener('click', () => gotoTab(button.dataset.tab)));

$('#groupManager').addEventListener('change', event => {
  const card = event.target.closest('.group-card'); if (!card) return;
  const oldName = card.dataset.group;
  const row = event.target.closest('.override-row');
  mutate(next => {
    const group = groupData(next, oldName); if (!group) return;
    if (row && event.target.dataset.route) {
      group.Director ||= {}; group.Director.market_overrides ||= {};
      group.Director.market_overrides[row.dataset.market] ||= {};
      group.Director.market_overrides[row.dataset.market][event.target.dataset.route] = event.target.value.trim();
    } else if (event.target.classList.contains('group-name')) {
      const newName = event.target.value.trim();
      if (newName && newName !== oldName) { next.in_contacts[newName] = group; delete next.in_contacts[oldName]; }
    } else if (event.target.dataset.field) {
      group[event.target.dataset.field] = event.target.type === 'checkbox' ? event.target.checked : Number(event.target.value || 0);
    } else if (event.target.dataset.director) {
      group.Director ||= {}; group.Director[event.target.dataset.director] = event.target.value.trim();
    } else if (event.target.dataset.rate) {
      group.win_rate ||= {}; group.win_rate[event.target.dataset.rate] = Number(event.target.value || 0);
    }
  });
});
$('#groupManager').addEventListener('click', event => {
  const card = event.target.closest('.group-card'); if (!card) return;
  const name = card.dataset.group;
  if (event.target.dataset.action === 'delete-group') mutate(next => delete next.in_contacts[name]);
  if (event.target.dataset.action === 'add-override') {
    overrideTargetGroup = name;
    const group = config().in_contacts?.[name] || {};
    const director = directorFor(group);
    $('#overrideForm').elements.table.value = director.all_table || '';
    $('#overrideForm').elements.forward.value = director.all_fast_forward || '';
    $('#overrideDialog').showModal();
  }
  if (event.target.dataset.action === 'delete-override') {
    const row = event.target.closest('.override-row');
    mutate(next => delete next.in_contacts[name].Director.market_overrides[row.dataset.market]);
  }
});
$('#marketManager').addEventListener('change', event => {
  const line = event.target.closest('.timing-row'); if (!line) return;
  const oldKey = line.dataset.marketKey;
  mutate(next => {
    const timing = next.fixed_market_time?.[oldKey]; if (!timing) return;
    if (event.target.classList.contains('market-key')) {
      const key = event.target.value.trim(); if (key && key !== oldKey) { next.fixed_market_time[key] = timing; delete next.fixed_market_time[oldKey]; }
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
  const line = event.target.closest('.timing-row');
  if (line && event.target.dataset.action === 'delete-market') mutate(next => delete next.fixed_market_time[line.dataset.marketKey]);
});
$('#addGroup').addEventListener('click', () => $('#groupDialog').showModal());
$('#addMarket').addEventListener('click', () => $('#marketDialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $('#' + button.dataset.close).close()));
$('#groupForm').addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const name = String(data.get('name')).trim();
  if (!name) return;
  mutate(next => {
    next.in_contacts ||= {};
    next.in_contacts[name] = {
      LD: Number(data.get('ld') || 100),
      Limit: Number(data.get('limit') || 0),
      instant_cutting: data.get('instant') === 'on',
      Director: { all_table: String(data.get('allTable') || '').trim(), all_fast_forward: String(data.get('allForward') || '').trim(), market_overrides: {} },
      win_rate: {
        ANK: Number(data.get('ank') || 0), Jodi: Number(data.get('jodi') || 0),
        SP: Number(data.get('sp') || 0), DP: Number(data.get('dp') || 0),
        TP: Number(data.get('tp') || 0), FS: Number(data.get('fs') || 0),
        HS: Number(data.get('hs') || 0), Commission: Number(data.get('commission') || 0)
      }
    };
  });
  event.currentTarget.reset();
  $('#groupDialog').close();
});
$('#overrideForm').addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const market = String(data.get('market')).trim();
  if (!market || !overrideTargetGroup) return;
  mutate(next => {
    const group = groupData(next, overrideTargetGroup);
    group.Director ||= {}; group.Director.market_overrides ||= {};
    group.Director.market_overrides[market] = {
      table: String(data.get('table') || '').trim(),
      fast_forward: String(data.get('forward') || '').trim()
    };
  });
  event.currentTarget.reset();
  $('#overrideDialog').close();
  overrideTargetGroup = '';
});
$('#marketForm').addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const name = String(data.get('name')).trim();
  if (!name) return;
  mutate(next => {
    next.fixed_market_time ||= {};
    next.fixed_market_time[name] = [
      { hour: Number(data.get('startHour') || 0), minute: Number(data.get('startMinute') || 0), second: 0 },
      Number(data.get('days') || 0),
      { hour: Number(data.get('endHour') || 0), minute: Number(data.get('endMinute') || 0), second: 0 }
    ];
  });
  event.currentTarget.reset();
  $('#marketDialog').close();
});
async function chooseWorkspace() {
  try { const state = await window.cobo.chooseBotDirectory(); log(state.botDirectory ? `Workspace folder: ${state.botDirectory}` : 'Workspace folder unchanged.'); }
  catch (error) { alert(error.message); }
}
async function startService() {
  try { await window.cobo.startBot(); log('Service started.'); }
  catch (error) { alert(error.message); }
}
async function saveOnly() {
  try { const next = await window.cobo.saveConfig(JSON.stringify(config())); renderSummary(next); $('#saveMessage').textContent = 'Changes saved.'; }
  catch (error) { $('#saveMessage').textContent = error.message; }
}
$('#chooseBot').addEventListener('click', chooseWorkspace);
$('#launchService').addEventListener('click', startService);
$('#stopBot').addEventListener('click', () => window.cobo.stopBot());
$('#saveConfig').addEventListener('click', saveOnly);
$('#saveRestart').addEventListener('click', async () => { await saveOnly(); await window.cobo.stopBot(); await startService(); });

window.cobo.onLog(log);
window.cobo.onStatus(setService);
(async () => {
  const state = await window.cobo.state();
  renderSummary(state.summary);
  setService(state);
})();