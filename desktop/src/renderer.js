const pages = [...document.querySelectorAll('.page')];
const nav = [...document.querySelectorAll('.nav')];
const tabs = [...document.querySelectorAll('.control-tab')];
let summary;
let selectedMarketKey = '';
let overrideTargetGroup = '';
let selectedMarketDays = new Set();
let loadedTransactions = [];
let loadedTransactionDetails = {};
let dashboardMarket = '';
let dashboardContact = '';
let dashboardLoading = false;
let finalOptionsLoaded = false;
let availableOutputGroups = [];

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const setMessage = value => { const el = $('#saveMessage'); if (el) el.textContent = value; };

function goto(page) {
  pages.forEach(item => item.classList.toggle('active', item.id === page));
  nav.forEach(item => item.classList.toggle('active', item.dataset.page === page));
  if (page === 'config') showConfigHome();
  if (page === 'dashboard') loadDashboard();
  if (page === 'results') loadResults();
  if (page === 'transactions') loadTransactions();
}
function showConfigHome() { $('#configHome').hidden = false; $('#configDetail').hidden = true; }
function showConfigDetail(tab = 'timings') { $('#configHome').hidden = true; $('#configDetail').hidden = false; gotoTab(tab); }
function gotoTab(tab) {
  tabs.forEach(item => item.classList.toggle('active-tab', item.dataset.tab === tab));
  document.querySelectorAll('.tab-page').forEach(item => item.classList.toggle('active', item.id === tab));
}
function getConfig() { return summary?.config || {}; }
function cloneConfig() { return structuredClone(getConfig()); }
function timingRows() { return Object.entries(getConfig().fixed_market_time || {}); }
function contacts() { return Object.entries(getConfig().in_contacts || {}); }
function pretty(key) { return key.replace(/_(OP|CL)$/, '').replaceAll('_', ' '); }
function phase(key) { return key.endsWith('_CL') ? 'Close' : 'Open'; }
function hm(row, index) { return String(row?.[index]?.hour ?? 0).padStart(2,'0') + ':' + String(row?.[index]?.minute ?? 0).padStart(2,'0'); }
function todayBusinessDate() { const date = new Date(); return `${String(date.getFullYear()).slice(-2)}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`; }
function validBusinessDate(value) { return /^\d{2}-\d{2}-\d{2}$/.test(value || ''); }
function daysFor(key, row) {
  const saved = getConfig().market_days?.[key];
  return Array.isArray(saved) ? saved.map(Number) : Array.from({ length: Number(row?.[1] || 0) }, (_, index) => index);
}
function destinationNames(kind, current = '') {
  const values = new Set(availableOutputGroups);
  const usable = value => value && !['forward', 'table', 'select table group', 'select forward group'].includes(String(value).trim().toLowerCase());
  if (usable(current) && (availableOutputGroups.includes(current) || String(current).endsWith('@g.us'))) values.add(current);
  contacts().forEach(([, group]) => {
    const director = group.Director || {};
    const field = kind === 'table' ? 'all_table' : 'all_fast_forward';
    if (usable(director[field]) && availableOutputGroups.includes(String(director[field]))) values.add(String(director[field]));
    Object.values(director.market_overrides || {}).forEach(route => {
      if (usable(route?.[kind]) && availableOutputGroups.includes(String(route[kind]))) values.add(String(route[kind]));
    });
  });
  return [...values].sort((a, b) => a.localeCompare(b));
}
function destinationOptions(kind, current = '') {
  const label = kind === 'table' ? 'Select table group' : 'Select forward group';
  const selected = destinationNames(kind, current).includes(current) ? current : '';
  const options = destinationNames(kind, current)
    .map(value => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value)}</option>`).join('');
  return `<option value="" ${selected ? '' : 'selected'}>${label}</option>${options}`;
}
function destinationSelect(kind, current, attribute) {
  return `<select ${attribute}>${destinationOptions(kind, current)}</select>`;
}
function destinationInput(kind, current, attribute) {
  const placeholder = kind === 'table' ? 'Select group or paste @g.us JID' : 'Select group or paste @g.us JID';
  return `<input ${attribute} list="outputGroupNames" value="${esc(current || '')}" placeholder="${placeholder}">`;
}
function prepareGroupDialog() {
  $('#groupAllTable').innerHTML = destinationOptions('table');
  $('#groupAllForward').innerHTML = destinationOptions('fast_forward');
}
async function loadOutputGroups() {
  if (!window.cobo.outputGroups) return;
  try {
    const data = await window.cobo.outputGroups();
    availableOutputGroups = [...new Set(data.groups || [])];
    const list = $('#outputGroupNames');
    if (list) list.innerHTML = availableOutputGroups.map(name => `<option value="${esc(name)}"></option>`).join('');
    loadGroupMappings();
    renderGroups();
  } catch (_) { availableOutputGroups = []; const list = $('#outputGroupNames'); if (list) list.innerHTML = ''; renderGroups(); }
}
async function loadGroupMappings() {
  const root = $('#groupMappings');
  if (!root || !window.cobo.groupMappings) return;
  try {
    const data = await window.cobo.groupMappings();
    const rows = data.mappings || [];
    root.innerHTML = rows.length ? rows.map(row => `<div class="group-mapping"><b>${esc(row.name)}</b><span>${esc(row.jid)}</span><i>${esc((row.roles || []).join(' · ') || 'available')}</i></div>`).join('') : 'No resolved mapping yet. Start Service and wait a few seconds.';
  } catch (error) { root.textContent = `Mapping read failed: ${error.message}`; }
}

const money = value => `₹${Number(value || 0).toLocaleString('en-IN')}`;
const messagePreview = value => esc(value || '').replace(/\n/g, '<br>');
function liveMessageCard(row) {
  return `<article class="live-message" data-record-id="${esc(row.id)}"><div><b>${esc(row.group)}</b><span>${esc(row.market || 'Unknown market')} · ${esc(row.time || '—')}</span></div><div class="live-raw">${messagePreview(row.message)}</div><strong>${money(row.total)}</strong><button class="reject-live" data-action="reject-live">Reject</button></article>`;
}
function liveMarketCard(row, index) {
  const colour = ['red','violet','blue','green'][index % 4];
  return `<button class="live-market ${colour} ${row.market === dashboardMarket ? 'selected' : ''}" data-dashboard-market="${esc(row.market)}"><b>${esc(pretty(row.market))}</b><div class="market-side-grid"><span>OPEN PLAY <strong>${money(row.open_play)}</strong></span><span>OPEN WIN <strong>${money(row.open_win)}</strong></span><span>CLOSE PLAY <strong>${money(row.close_play)}</strong></span><span>CLOSE WIN <strong>${money(row.close_win)}</strong></span></div><small>${row.messages} messages · total ${money(row.play)}</small></button>`;
}
function marketBreakdown(label, detail) {
  const info = detail || {};
  const line = (name, key, value) => {
    const wins = info.winning_numbers?.[key] || [];
    const exact = wins.length ? wins.map(item => `<i>${esc(item.number)} = ${money(item.stake)}</i>`).join('') : '<i>No win</i>';
    return `<span><em>${name}</em><b>Play ${money(value?.play)}</b><strong>Win ${money(value?.win)}</strong><small>${exact}</small></span>`;
  };
  return `<article class="market-breakdown"><header><b>${label}</b><span>PLAY<strong>${money(info.play)}</strong></span><span>WIN<strong>${money(info.win)}</strong></span></header><div>${line('ANK', 'ank', info.ank)}${line('PANNA', 'panna', info.panna)}${line('JODI', 'jodi', info.jodi)}</div></article>`;
}
function renderDashboardNumbers(values) {
  const rows = Object.entries(values || {});
  return rows.length ? rows.map(([number, amount]) => `<div><span>${esc(number)}</span><b>${money(amount)}</b></div>`).join('') + `<footer>TOTAL <b>${money(rows.reduce((sum, [, amount]) => sum + Number(amount || 0), 0))}</b></footer>` : '<p class="empty-data">No accepted number for this market yet.</p>';
}
async function loadFinalOptions() {
  if (finalOptionsLoaded || !window.cobo.finalOptions) return;
  const select = $('#finalOutputGroup');
  try {
    const data = await window.cobo.finalOptions();
    select.innerHTML = '<option value="">Select output group</option>' + (data.output_groups || []).map(group => `<option value="${esc(group)}">${esc(group)}</option>`).join('');
    finalOptionsLoaded = true;
  } catch (_) { select.innerHTML = '<option value="">Output groups unavailable</option>'; }
}
async function runFinalSettlement() {
  const select = $('#finalOutputGroup'); const output_group = select.value;
  if (!output_group) { alert('Select output group first.'); return; }
  if (!window.confirm(`Run final settlement for ${output_group}? Output replies and linked input-group totals will be sent.`)) return;
  const button = $('#runFinal'); button.disabled = true; button.textContent = 'Queueing…';
  try {
    const result = await window.cobo.runFinal({ output_group });
    alert(`Final queued: ${result.queued || 0} output replies, ${result.input_group_totals_queued || 0} input-group totals.`);
  } catch (error) { alert(error.message); }
  finally { button.disabled = false; button.textContent = 'Run Final'; }
}
async function loadDashboard() {
  if (!window.cobo.dashboard) return;
  if (dashboardLoading) return;
  if ($('#botState')?.textContent !== 'Running') {
    $('#dashboardTotalPlay').textContent = '₹0'; $('#dashboardTotalWin').textContent = '₹0';
    $('#metricCards').innerHTML = '<div class="metric"><small>Live status</small><strong>Stopped</strong><span>Start Service to load live records.</span></div>';
    $('#contactCount').textContent = '0 groups'; $('#marketCount').textContent = '0 markets';
    $('#customerList').innerHTML = '<div class="empty-data">Start Service to load live Play, Win and messages.</div>';
    $('#marketList').innerHTML = '<div class="empty-data">No market activity yet.</div>';
    $('#dashboardMarketSelect').innerHTML = '<option value="">No active market</option>';
    $('#dashboardTableTitle').textContent = 'Select market'; $('#dashboardNumbers').innerHTML = '';
    return;
  }
  dashboardLoading = true;
  try {
    const data = (await window.cobo.dashboard({ date: todayBusinessDate(), market: dashboardMarket, contact: dashboardContact })) || {};
    dashboardMarket = data.selected_market || '';
    $('#dashboardTotalPlay').textContent = money(data.total_play);
    $('#dashboardTotalWin').textContent = money(data.total_win);
    $('#metricCards').innerHTML = (data.customers || []).map((row, index) => `<button class="metric live-customer metric-${index % 4} ${row.contact === dashboardContact ? 'selected' : ''}" data-dashboard-contact="${esc(row.contact)}"><small>${esc(row.name)}</small><div class="live-progress"><i style="width:${Math.min(100, Number(row.play || 0) ? 62 : 0)}%"></i></div><div class="live-totals"><span>PLAY <b>${money(row.play)}</b></span><span>WIN <b>${money(row.win)}</b></span></div></button>`).join('') || '<div class="metric"><small>Today Play</small><strong>₹0</strong><span>No accepted message yet</span></div>';
    $('#contactCount').textContent = `${data.customers?.length || 0} groups`;
    $('#marketCount').textContent = `${data.markets?.length || 0} markets${dashboardContact ? ' · selected customer' : ''}`;
    $('#customerList').innerHTML = (data.messages || []).map(liveMessageCard).join('') || '<div class="empty-data">No accepted play yet.</div>';
    $('#marketList').innerHTML = (data.markets || []).map(liveMarketCard).join('') || '<div class="empty-data">No market activity yet.</div>';
    const select = $('#dashboardMarketSelect');
    select.innerHTML = (data.markets || []).map(row => `<option value="${esc(row.market)}" ${row.market === dashboardMarket ? 'selected' : ''}>${esc(pretty(row.market))}</option>`).join('') || '<option value="">No active market</option>';
    $('#dashboardTableTitle').textContent = dashboardMarket ? pretty(dashboardMarket) : 'Select market';
    $('#dashboardNumbers').innerHTML = marketBreakdown('OPEN', data.breakdown?.OP) + marketBreakdown('CLOSE', data.breakdown?.CL) + '<div class="number-table-title">Number-wise Play</div>' + renderDashboardNumbers(data.number_table);
    loadFinalOptions();
  } catch (error) { $('#customerList').innerHTML = `<div class="empty-data">${esc(error.message)}</div>`; }
  finally { dashboardLoading = false; }
}
async function rejectLiveMessage(card) {
  if (!window.confirm('Reject this message? It will be removed from play, win and final settlement.')) return;
  const button = card.querySelector('[data-action="reject-live"]'); button.disabled = true; button.textContent = 'Removing…';
  try { await window.cobo.rejectTransaction({ date: todayBusinessDate(), record_id: card.dataset.recordId }); await loadDashboard(); }
  catch (error) { button.disabled = false; button.textContent = 'Reject'; alert(error.message); }
}

async function mutate(change) {
  try {
    const next = cloneConfig();
    change(next);
    const result = await window.cobo.saveConfig(JSON.stringify(next));
    render(result);
    setMessage(result.restarted ? 'Saved · service restarted' : 'Saved');
  } catch (error) { setMessage(error.message); }
}
function render(next) {
  summary = next || summary;
  const client = summary?.clientName || 'vijay';
  $('#clientName').textContent = client;
  $('#configOverviewGroupCount').textContent = `${summary?.contactCount || 0} active`;
  $('#configOverviewMarketCount').textContent = `${summary?.marketCount || 0} timings`;
  $('#configOverviewMetrics').innerHTML = [
    ['Input Groups', summary?.contactCount || 0, 'Configured customer groups'],
    ['Market Timings', summary?.marketCount || 0, 'Open and close rules'],
    ['Service Status', $('#botState')?.textContent || 'Stopped', 'Local service'],
    ['Today Play', '₹0', 'No live play yet']
  ].map((x,i) => `<div class="metric metric-${i}"><small>${x[0]}</small><strong>${esc(x[1])}</strong><span>${x[2]}</span></div>`).join('');
  $('#configOverviewGroups').innerHTML = contacts().map(([name, item]) => `<div class="crm-customer-row"><b>${esc(name)}</b><span>${esc(item.LD ?? 100)}%</span><span>₹${esc(item.Limit ?? 0)}</span><span>${item.instant_cutting ? 'Instant' : 'Scheduled'}</span></div>`).join('') || '<p class="muted">No input group configured.</p>';
  $('#configOverviewMarkets').innerHTML = timingRows().slice(0,8).map(([name, row]) => `<div class="crm-market-row"><div><b>${esc(pretty(name))}</b><small>${phase(name)} · ${hm(row, 0)} – ${hm(row, 2)}</small></div><span>● Active</span></div>`).join('');
  renderTimingTable();
  renderGroups();
}
function renderTimingTable() {
  const root = $('#marketRows'); const editor = $('#marketEditor');
  if (!root || !editor) return;
  const data = timingRows();
  if (!selectedMarketKey || !data.some(([key]) => key === selectedMarketKey)) selectedMarketKey = data[0]?.[0] || '';
  root.innerHTML = data.map(([key,row]) => `<button class="timing-line ${key === selectedMarketKey ? 'selected' : ''}" data-market-key="${esc(key)}">
    <span>${esc(pretty(key))}</span><span class="phase-chip ${key.endsWith('_CL') ? 'close' : ''}">${phase(key)}</span>
    <span class="time-chip">${hm(row,0)}</span><span class="time-chip">${hm(row,2)}</span>
    <span class="day-dots">${esc(row?.[1] ?? 0)} days</span><span class="status-ok">● Active</span><span class="row-actions">▣ &nbsp;⌫</span>
  </button>`).join('');
  const current = getConfig().fixed_market_time?.[selectedMarketKey];
  if (!current) { editor.innerHTML = ''; return; }
  const selectedDays = daysFor(selectedMarketKey, current);
  selectedMarketDays = new Set(selectedDays);
  editor.innerHTML = `<div class="edit-head"><div class="edit-icon">＋</div><div><h2>Add / Edit Market</h2><p>Create or update market timings</p></div></div>
    <label>Market Name<input value="${esc(pretty(selectedMarketKey))}" disabled></label>
    <label>Phase</label><div class="phase-toggle"><button data-phase="OP" class="${selectedMarketKey.endsWith('_OP') ? 'on' : ''}">Open</button><button data-phase="CL" class="${selectedMarketKey.endsWith('_CL') ? 'on' : ''}">Close</button></div>
    <div class="editor-time-grid"><label>Start Time<div><input data-edit="startHour" type="number" min="0" max="23" value="${esc(current[0]?.hour ?? 0)}"><input data-edit="startMinute" type="number" min="0" max="59" value="${esc(current[0]?.minute ?? 0)}"></div></label><label>End Time<div><input data-edit="endHour" type="number" min="0" max="23" value="${esc(current[2]?.hour ?? 0)}"><input data-edit="endMinute" type="number" min="0" max="59" value="${esc(current[2]?.minute ?? 0)}"></div></label></div>
    <label>Active Days</label><div class="weekday-row">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day,index)=>`<button type="button" data-day="${index}" class="${selectedDays.includes(index) ? 'checked' : ''}">${day}</button>`).join('')}</div><p class="editor-note" id="activeDaysNote">${selectedDays.length} day${selectedDays.length === 1 ? '' : 's'} selected</p>
    <button class="primary editor-save" data-action="save-market">▣ &nbsp; Save Market</button>`;
}
function renderGroups() {
  const markup = contacts().map(([name, group]) => {
    const director = group.Director || {};
    const overrides = director.market_overrides || {};
    const reply = group.reply_settings || {};
    const overflow = group.overflow_limits || {};
    const overflowEnabled = Number(group.LD ?? 100) === 100;
    return `<article class="group-card" data-group="${esc(name)}">
      <div class="group-head"><div><small>CUSTOMER GROUP</small><input class="group-name" value="${esc(name)}"></div><div class="active-group">● Active</div><button class="secondary group-save" data-action="save-group">Save Changes</button><button class="icon danger" data-action="delete-group">⌫</button></div>
      <div class="customer-fields"><label>LD %<input data-field="LD" type="text" inputmode="decimal" value="${esc(group.LD ?? 100)}"></label><label>Limit (₹)<input data-field="Limit" type="text" inputmode="numeric" value="${esc(group.Limit ?? 0)}"></label><label class="cutting-label">⚡ Instant Cutting<input data-field="instant_cutting" type="checkbox" ${group.instant_cutting ? 'checked' : ''}></label><label>All Table${destinationInput('table', director.all_table || '', 'data-director="all_table"')}</label><label>All Forward${destinationInput('fast_forward', director.all_fast_forward || '', 'data-director="all_fast_forward"')}</label></div>
      <div class="reply-box"><div class="mini-title">Bot replies</div><p>Choose acknowledgement types for this input group.</p><label><input data-reply="normal_ok" type="checkbox" ${reply.normal_ok !== false ? 'checked' : ''}> Normal OK</label><label><input data-reply="fast_forward_ok" type="checkbox" ${reply.fast_forward_ok !== false ? 'checked' : ''}> Fast-forward OK</label><label><input data-reply="total_ok" type="checkbox" ${reply.total_ok !== false ? 'checked' : ''}> Missing / wrong total OK</label></div>
      <div class="overflow-box ${overflowEnabled ? '' : 'disabled'}"><div><div class="mini-title">100% LD category overflow</div><p>${overflowEnabled ? 'For each game line, only the amount above its category limit is sent instantly.' : 'Available only when LD is exactly 100%.'}</p></div>${overflowEnabled ? `<label>Overflow output${destinationInput('table', overflow.output_group || '', 'data-overflow="output_group"')}</label><div class="overflow-limits">${[['ank','ANK'],['jodi','JODI'],['sp','SP'],['dp','DP'],['tp','TP']].map(([key,label])=>`<label>${label} limit<input data-overflow="${key}" type="text" inputmode="numeric" value="${esc(overflow[key] ?? 0)}"></label>`).join('')}</div>` : ''}</div>
      <div class="group-lower"><div class="override-box"><div class="mini-title">⌄ Market-wise destinations <button data-action="add-override">＋ Add</button></div>${Object.entries(overrides).map(([market,route])=>`<div class="override-row" data-market="${esc(market)}"><b>${esc(market)}</b>${destinationInput('table', route.table || '', 'data-route="table"')}${destinationInput('fast_forward', route.fast_forward || '', 'data-route="fast_forward"')}<button class="icon danger" data-action="delete-override">−</button></div>`).join('') || '<p class="muted">All markets use default destinations.</p>'}</div>
      <div class="rates-box"><div class="mini-title">Win Rate</div><div class="rate-grid">${['ANK','Jodi','SP','DP','TP','FS','HS','Commission'].map(key=>`<label>${key}<input data-rate="${key}" type="text" inputmode="decimal" value="${esc(group.win_rate?.[key] ?? '')}"></label>`).join('')}</div></div></div>
    </article>`;
  }).join('') || '<div class="empty-groups"><b>No input groups yet</b><span>Use Add Input Group to create the first customer rule.</span></div>';
  ['#groupManager','#groupManagerSecondary'].forEach(id => { const node=$(id); if(node) node.innerHTML=markup; });
}
function groupChange(event) {
  const card = event.target.closest('.group-card'); if (!card) return;
  markGroupDirty(card);
}
function markGroupDirty(card) {
  card.classList.add('dirty');
  const button = card.querySelector('[data-action="save-group"]');
  if (button) button.textContent = 'Save Changes ●';
}
function saveGroup(card) {
  const oldName = card.dataset.group;
  const nextName = card.querySelector('.group-name').value.trim();
  if (!nextName) return;
  const routes = [
    card.querySelector('[data-director="all_table"]').value.trim(),
    card.querySelector('[data-director="all_fast_forward"]').value.trim(),
    ...[...card.querySelectorAll('.override-row')].flatMap(row => [row.querySelector('[data-route="table"]').value.trim(), row.querySelector('[data-route="fast_forward"]').value.trim()]),
  ].filter(Boolean);
  const overflowTarget = card.querySelector('[data-overflow="output_group"]')?.value.trim();
  if (overflowTarget) routes.push(overflowTarget);
  const inputNames = new Set(contacts().map(([name]) => name.toLocaleLowerCase()));
  const invalid = routes.find(value => inputNames.has(value.toLocaleLowerCase()));
  if (invalid) { alert(`“${invalid}” is an input group, not an output destination. Select its output group or paste its @g.us JID.`); return; }
  mutate(next => {
    const group = next.in_contacts?.[oldName]; if (!group) return;
    if (nextName !== oldName) { next.in_contacts[nextName] = group; delete next.in_contacts[oldName]; }
    group.LD = Number(card.querySelector('[data-field="LD"]').value || 0);
    group.Limit = Number(card.querySelector('[data-field="Limit"]').value || 0);
    group.instant_cutting = card.querySelector('[data-field="instant_cutting"]').checked;
    group.Director ||= {}; group.Director.market_overrides ||= {};
    group.Director.all_table = card.querySelector('[data-director="all_table"]').value.trim();
    group.Director.all_fast_forward = card.querySelector('[data-director="all_fast_forward"]').value.trim();
    group.reply_settings ||= {};
    card.querySelectorAll('[data-reply]').forEach(input => { group.reply_settings[input.dataset.reply] = input.checked; });
    if (group.LD === 100) {
      group.overflow_limits ||= {};
      card.querySelectorAll('[data-overflow]').forEach(input => { group.overflow_limits[input.dataset.overflow] = input.dataset.overflow === 'output_group' ? input.value.trim() : Number(input.value || 0); });
    }
    card.querySelectorAll('.override-row').forEach(row => {
      const market = row.dataset.market;
      group.Director.market_overrides[market] = {
        table: row.querySelector('[data-route="table"]').value,
        fast_forward: row.querySelector('[data-route="fast_forward"]').value
      };
    });
    group.win_rate ||= {};
    card.querySelectorAll('[data-rate]').forEach(input => { group.win_rate[input.dataset.rate] = Number(input.value || 0); });
  });
}
function groupClick(event) {
  const card=event.target.closest('.group-card'); if(!card) return; const name=card.dataset.group;
  if(event.target.dataset.action==='save-group'){saveGroup(card);return;}
  if(event.target.dataset.action==='delete-group') mutate(next=>delete next.in_contacts[name]);
  if(event.target.dataset.action==='add-override'){overrideTargetGroup=name;prepareOverrideDialog();$('#overrideDialog').showModal();}
  if(event.target.dataset.action==='delete-override'){const row=event.target.closest('.override-row');mutate(next=>delete next.in_contacts[name].Director.market_overrides[row.dataset.market]);}
}
function prepareOverrideDialog() {
  const markets = Object.keys(getConfig().fixed_market_time || {}).map(pretty)
    .filter((value, index, all) => all.indexOf(value) === index).sort();
  $('#overrideMarket').innerHTML = '<option value="" selected>Select market</option>' + markets.map(value => `<option value="${esc(value.replaceAll(' ', '_'))}">${esc(value)}</option>`).join('');
  const optionMarkup = kind => destinationNames(kind).map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
  $('#overrideTable').innerHTML = '<option value="">Select table group</option>' + optionMarkup('table');
  $('#overrideForward').innerHTML = '<option value="">Select forward group</option>' + optionMarkup('fast_forward');
}
function resultCard(row, index) {
  const jodi = row.open && row.close ? `${row.open} - ${row.close}` : '—';
  const colour = ['red','violet','blue','green'][index % 4];
  return `<article class="result-card ${colour}" data-market="${esc(row.market)}"><div class="result-card-head"><b>${esc(pretty(row.market))}</b><span>● Result</span></div><div class="result-values"><label>Open Panna<input data-result="open_panna" type="text" value="${esc(row.open_panna)}"></label><label>Jodi<div class="jodi-value">${esc(jodi)}</div></label><label>Close Panna<input data-result="close_panna" type="text" value="${esc(row.close_panna)}"></label></div><div class="result-values compact"><label>Open Ank<input data-result="open" type="text" value="${esc(row.open)}"></label><label>Open Time<input data-result="open_time" type="text" placeholder="HH:MM:SS" value="${esc(row.open_time)}"></label><label>Close Ank<input data-result="close" type="text" value="${esc(row.close)}"></label><label>Close Time<input data-result="close_time" type="text" placeholder="HH:MM:SS" value="${esc(row.close_time)}"></label></div><div class="result-card-footer"><span class="result-save-note">Edit values, then save</span><button class="secondary" data-action="save-result">Save Result</button></div></article>`;
}
async function loadResults() {
  const date = $('#resultDate')?.value?.trim();
  if (!validBusinessDate(date)) { $('#resultStatus').textContent = 'Use date format YY-MM-DD.'; return; }
  $('#resultStatus').textContent = 'Loading results…';
  try { const data = await window.cobo.results(date); $('#resultCards').innerHTML = data.markets.map(resultCard).join('') || '<div class="empty-data">No configured market result found for this date.</div>'; $('#resultStatus').textContent = `${data.markets.length} market result${data.markets.length === 1 ? '' : 's'} loaded for ${date}.`; }
  catch (error) { $('#resultCards').innerHTML = ''; $('#resultStatus').textContent = error.message; }
}
async function saveResult(card) {
  const payload = { date: $('#resultDate').value.trim(), market: card.dataset.market };
  card.querySelectorAll('[data-result]').forEach(input => { payload[input.dataset.result] = input.value.trim(); });
  const note = card.querySelector('.result-save-note'); note.textContent = 'Saving…';
  try { await window.cobo.saveResult(payload); note.textContent = 'Saved'; } catch (error) { note.textContent = error.message; }
}
function transactionState(row) { return row.settled ? 'settled' : row.result_ready ? 'ready' : 'pending'; }
function transactionBase(market) { return String(market || '').replace(/_(OP|CL)$/, ''); }
function transactionMarketCards(rows) {
  const markets = {};
  rows.forEach(row => {
    const base = transactionBase(row.market) || 'UNKNOWN';
    const item = markets[base] ||= { market: base, play: 0, win: 0, open_play: 0, open_win: 0, close_play: 0, close_win: 0, messages: 0 };
    const side = String(row.market || '').endsWith('_OP') ? 'open' : String(row.market || '').endsWith('_CL') ? 'close' : '';
    item.play += Number(row.total || 0); item.win += Number(row.win || 0); item.messages += 1;
    if (side) { item[`${side}_play`] += Number(row.total || 0); item[`${side}_win`] += Number(row.win || 0); }
  });
  return Object.values(markets).sort((a,b) => b.play - a.play);
}
function oldMarketCard(item) {
  const selected = ($('#transactionMarket')?.value || '') === item.market;
  return `<button class="old-market-card ${selected ? 'selected' : ''}" data-transaction-market="${esc(item.market)}"><b>${esc(pretty(item.market))}</b><div><span>OPEN<br><strong>${money(item.open_play)} / ${money(item.open_win)}</strong></span><span>CLOSE<br><strong>${money(item.close_play)} / ${money(item.close_win)}</strong></span></div><footer>PLAY <strong>${money(item.play)}</strong><em>WIN ${money(item.win)}</em><small>${item.messages} records</small></footer></button>`;
}
function transactionCustomerCards(rows) {
  const customers = {};
  rows.forEach(row => {
    const contact = String(row.contact || '');
    const item = customers[contact] ||= { contact, name: row.contact_name || contact || 'Unknown customer', play: 0, win: 0, messages: 0 };
    item.play += Number(row.total || 0); item.win += Number(row.win || 0); item.messages += 1;
  });
  return Object.values(customers).sort((a,b) => b.play - a.play);
}
function oldCustomerCard(item, index) {
  const percent = item.play ? Math.min(100, Math.max(10, (item.win / item.play) * 45 + 25)) : 0;
  return `<button class="old-customer-card shade-${index % 4}" data-transaction-contact="${esc(item.contact)}"><span class="customer-initial">${esc(item.name.charAt(0).toUpperCase())}</span><div><b>${esc(item.name)}</b><small>${item.messages} records</small></div><i style="width:${percent}%"></i><footer><span>PLAY<strong>${money(item.play)}</strong></span><span>WIN<strong>${money(item.win)}</strong></span></footer></button>`;
}
function transactionMarketDetail(market, detail) {
  if (!detail) return '<div class="empty-data">No number-wise data for this market.</div>';
  return `<article class="transaction-detail"><div class="panel-title"><div><p class="eyebrow">${esc(pretty(market))}</p><h3>Play &amp; Win detail</h3></div></div>${marketBreakdown('OPEN', detail.breakdown?.OP)}${marketBreakdown('CLOSE', detail.breakdown?.CL)}<div class="number-table-title">Number-wise Play</div><div class="transaction-number-table">${renderDashboardNumbers(detail.number_table)}</div></article>`;
}
function renderTransactions() {
  const market = $('#transactionMarket')?.value || '';
  const state = $('#transactionState')?.value || '';
  const filtered = loadedTransactions.filter(row => (!state || transactionState(row) === state));
  const selectedCustomer = Boolean($('#transactionContact')?.value);
  $('#transactionBack').hidden = !selectedCustomer;
  if (!selectedCustomer) {
    const customers = transactionCustomerCards(filtered);
    $('#transactionCount').textContent = String(customers.length);
    $('#transactionPlay').textContent = money(filtered.reduce((total, row) => total + Number(row.total || 0), 0));
    $('#transactionWin').textContent = money(filtered.reduce((total, row) => total + Number(row.win || 0), 0));
    $('#transactionMarketSummary').innerHTML = customers.map(oldCustomerCard).join('') || '<div class="empty-data">No customer record for this date.</div>';
    $('#transactionList').innerHTML = '';
    return;
  }
  const rows = filtered.filter(row => (!market || transactionBase(row.market) === market));
  const markets = transactionMarketCards(filtered);
  $('#transactionCount').textContent = String(markets.length);
  $('#transactionPlay').textContent = `₹${rows.reduce((total, row) => total + Number(row.total || 0), 0)}`;
  $('#transactionWin').textContent = money(rows.reduce((total, row) => total + Number(row.win || 0), 0));
  $('#transactionMarketSummary').innerHTML = markets.map(oldMarketCard).join('') || '<div class="empty-data">No market record matches these filters.</div>';
  $('#transactionList').innerHTML = market ? transactionMarketDetail(market, loadedTransactionDetails[market]) : '';
}
async function loadTransactions() {
  const date = $('#transactionDate')?.value?.trim();
  if (!validBusinessDate(date)) { $('#transactionStatus').textContent = 'Use date format YY-MM-DD.'; return; }
  const contact = $('#transactionContact').value;
  $('#transactionStatus').textContent = 'Loading customer history…';
  try {
    const data = await window.cobo.transactions({ date, contact }); loadedTransactions = data.transactions; loadedTransactionDetails = data.market_details || {};
    const select = $('#transactionContact'); const previous = select.value;
    select.innerHTML = '<option value="">All customers</option>' + data.contacts.map(item => `<option value="${esc(item.value)}">${esc(item.name)}</option>`).join('');
    select.value = data.contacts.some(item => item.value === previous) ? previous : '';
    const marketSelect = $('#transactionMarket'); const previousMarket = marketSelect.value;
    const markets = [...new Set(data.transactions.map(item => transactionBase(item.market)).filter(Boolean))].sort();
    marketSelect.innerHTML = '<option value="">All markets</option>' + markets.map(item => `<option value="${esc(item)}">${esc(pretty(item))}</option>`).join('');
    marketSelect.value = markets.includes(previousMarket) ? previousMarket : '';
    renderTransactions();
    $('#transactionStatus').textContent = `${data.transactions.length} message record${data.transactions.length === 1 ? '' : 's'} loaded for ${date}.`;
  } catch (error) { $('#transactionList').innerHTML = ''; $('#transactionStatus').textContent = error.message; }
}
async function saveTransaction(row) {
  const button = row.querySelector('[data-action="save-transaction"]'); button.textContent = 'Saving…';
  try { await window.cobo.saveTransaction({ date: $('#transactionDate').value.trim(), record_id: row.dataset.recordId, message: row.querySelector('[data-transaction="message"]').value, total: Number(row.querySelector('[data-transaction="total"]').value || 0) }); button.textContent = 'Saved'; }
  catch (error) { button.textContent = 'Save'; $('#transactionStatus').textContent = error.message; }
}
function log(value){const clean=String(value).split('\n').map(line=>line.length>420?`${line.slice(0,420)}…`:line).join('\n');['#logs','#configLogs'].forEach(id=>{const out=$(id);if(!out)return;out.textContent=(out.textContent+'\n'+clean).trim().slice(-12000);out.scrollTop=out.scrollHeight;});}
function setService(status){const state=status.running?'Running':status.starting?'Starting…':'Stopped';$('#botState').textContent=state;$('#botDot').classList.toggle('running',Boolean(status.running));const workspaceState=$('#workspaceLogState');if(workspaceState)workspaceState.textContent=state;if(status.running&&$('#dashboard')?.classList.contains('active'))setTimeout(loadDashboard,600);if(status.running)log('Service running — waiting for input/output activity.');if(status.code!==undefined)log('Service stopped with code '+status.code);}

nav.forEach(button=>button.addEventListener('click',()=>goto(button.dataset.page)));
document.querySelectorAll('[data-open-config]').forEach(button=>button.addEventListener('click',()=>showConfigDetail(button.dataset.openTab || 'timings')));
$('#configBack').addEventListener('click',showConfigHome);
document.querySelectorAll('[data-goto]').forEach(button=>button.addEventListener('click',()=>{goto(button.dataset.goto);if(button.dataset.gotoTab)gotoTab(button.dataset.gotoTab);}));
tabs.forEach(button=>button.addEventListener('click',()=>gotoTab(button.dataset.tab)));
document.querySelectorAll('[data-tab-target]').forEach(button=>button.addEventListener('click',()=>gotoTab(button.dataset.tabTarget)));
$('#marketRows').addEventListener('click',event=>{const item=event.target.closest('[data-market-key]');if(item){selectedMarketKey=item.dataset.marketKey;renderTimingTable();}});
$('#marketEditor').addEventListener('click',event=>{
  const phaseButton=event.target.closest('[data-phase]');
  if(phaseButton){const key=selectedMarketKey.replace(/_(OP|CL)$/, `_${phaseButton.dataset.phase}`);if(getConfig().fixed_market_time?.[key]){selectedMarketKey=key;renderTimingTable();}return;}
  const dayButton=event.target.closest('[data-day]');
  if(dayButton){const day=Number(dayButton.dataset.day);selectedMarketDays.has(day)?selectedMarketDays.delete(day):selectedMarketDays.add(day);dayButton.classList.toggle('checked',selectedMarketDays.has(day));const note=$('#activeDaysNote');if(note)note.textContent=`${selectedMarketDays.size} day${selectedMarketDays.size === 1 ? '' : 's'} selected — Save Market to apply`;return;}
  if(event.target.dataset.action!=='save-market')return;const edit=$('#marketEditor');const val=k=>Number(edit.querySelector('[data-edit="'+k+'"]').value||0);mutate(next=>{const row=next.fixed_market_time[selectedMarketKey];const days=[...selectedMarketDays].sort((a,b)=>a-b);next.market_days ||= {};next.market_days[selectedMarketKey]=days;row[1]=days.length;row[0]={hour:val('startHour'),minute:val('startMinute'),second:0};row[2]={hour:val('endHour'),minute:val('endMinute'),second:0};});
});
['#groupManager','#groupManagerSecondary'].forEach(id=>{const node=$(id);if(node){node.addEventListener('change',groupChange);node.addEventListener('click',groupClick);}});
['#addGroup','#addGroupSecondary'].forEach(id=>{const node=$(id);if(node)node.addEventListener('click',()=>{prepareGroupDialog();$('#groupDialog').showModal();});});
$('#addMarket').addEventListener('click',()=>$('#marketDialog').showModal());
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$('#'+button.dataset.close).close()));
$('#groupForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const name=String(d.get('name')).trim();if(!name)return;mutate(next=>{next.in_contacts ||= {};next.in_contacts[name]={LD:Number(d.get('ld')||100),Limit:Number(d.get('limit')||0),instant_cutting:d.get('instant')==='on',reply_settings:{normal_ok:true,fast_forward_ok:true,total_ok:true},overflow_limits:{output_group:'',ank:0,jodi:0,sp:0,dp:0,tp:0},Director:{all_table:String(d.get('allTable')||'').trim(),all_fast_forward:String(d.get('allForward')||'').trim(),market_overrides:{}},win_rate:{ANK:Number(d.get('ank')||0),Jodi:Number(d.get('jodi')||0),SP:Number(d.get('sp')||0),DP:Number(d.get('dp')||0),TP:Number(d.get('tp')||0),FS:Number(d.get('fs')||0),HS:Number(d.get('hs')||0),Commission:Number(d.get('commission')||0)}};});event.currentTarget.reset();$('#groupDialog').close();});
$('#overrideForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const market=String(d.get('market')).trim();if(!market||!overrideTargetGroup)return;mutate(next=>{const group=next.in_contacts[overrideTargetGroup];group.Director ||= {};group.Director.market_overrides ||= {};group.Director.market_overrides[market]={table:String(d.get('table')||'').trim(),fast_forward:String(d.get('forward')||'').trim()};});event.currentTarget.reset();$('#overrideDialog').close();overrideTargetGroup='';});
$('#marketForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const name=String(d.get('name')).trim();if(!name)return;mutate(next=>{next.fixed_market_time ||= {};next.fixed_market_time[name]=[{hour:Number(d.get('startHour')||0),minute:Number(d.get('startMinute')||0),second:0},Number(d.get('days')||0),{hour:Number(d.get('endHour')||0),minute:Number(d.get('endMinute')||0),second:0}];selectedMarketKey=name;});event.currentTarget.reset();$('#marketDialog').close();});
async function chooseWorkspace(){try{const state=await window.cobo.chooseBotDirectory();log(state.botDirectory?'Project folder: '+state.botDirectory:'Project folder unchanged.');}catch(error){alert(error.message);}}
async function startService(){try{await window.cobo.startBot();log('Service started.');setTimeout(loadOutputGroups,1200);}catch(error){alert(error.message);}}
$('#chooseBot').addEventListener('click',chooseWorkspace);$('#launchService').addEventListener('click',startService);$('#stopBot').addEventListener('click',()=>window.cobo.stopBot());
$('#dashboardStart').addEventListener('click',startService);
$('#refreshDashboard').addEventListener('click',loadDashboard);
$('#runFinal').addEventListener('click',runFinalSettlement);
setInterval(()=>{if($('#dashboard')?.classList.contains('active')&&$('#botState')?.textContent==='Running')loadDashboard();},8000);
$('#dashboardMarketSelect').addEventListener('change',event=>{dashboardMarket=event.target.value;loadDashboard();});
$('#metricCards').addEventListener('click',event=>{const card=event.target.closest('[data-dashboard-contact]');if(card){dashboardContact=dashboardContact===card.dataset.dashboardContact?'':card.dataset.dashboardContact;dashboardMarket='';loadDashboard();}});
$('#marketList').addEventListener('click',event=>{const button=event.target.closest('[data-dashboard-market]');if(button){dashboardMarket=button.dataset.dashboardMarket;loadDashboard();}});
$('#customerList').addEventListener('click',event=>{const button=event.target.closest('[data-action="reject-live"]');if(button)rejectLiveMessage(button.closest('.live-message'));});
$('#refreshResults').addEventListener('click',loadResults);
$('#resultCards').addEventListener('click',event=>{const button=event.target.closest('[data-action="save-result"]');if(button)saveResult(button.closest('.result-card'));});
$('#refreshTransactions').addEventListener('click',loadTransactions);
$('#transactionContact').addEventListener('change',loadTransactions);
$('#transactionBack').addEventListener('click',()=>{ $('#transactionContact').value=''; $('#transactionMarket').value=''; loadTransactions(); });
$('#transactionDate').addEventListener('change',loadTransactions);
['#transactionMarket','#transactionState'].forEach(id => $(id)?.addEventListener('change',renderTransactions));
$('#transactionMarketSummary').addEventListener('click',event=>{const customer=event.target.closest('[data-transaction-contact]');if(customer){const select=$('#transactionContact');select.value=customer.dataset.transactionContact;$('#transactionMarket').value='';loadTransactions();return;}const card=event.target.closest('[data-transaction-market]');if(card){const select=$('#transactionMarket');select.value=select.value===card.dataset.transactionMarket?'':card.dataset.transactionMarket;renderTransactions();}});
$('#transactionList').addEventListener('click',event=>{const button=event.target.closest('[data-action="save-transaction"]');if(button)saveTransaction(button.closest('.transaction-row'));});
window.cobo.onLog(log);window.cobo.onStatus(setService);
(async()=>{const date=todayBusinessDate();$('#resultDate').value=date;$('#transactionDate').value=date;const state=await window.cobo.state();render(state.summary);setService(state);loadOutputGroups();})();
