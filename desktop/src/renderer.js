const pages = [...document.querySelectorAll('.page')];
const nav = [...document.querySelectorAll('.nav')];
const tabs = [...document.querySelectorAll('.control-tab')];
let summary;
let selectedMarketKey = '';
let overrideTargetGroup = '';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const setMessage = value => { const el = $('#saveMessage'); if (el) el.textContent = value; };

function goto(page) {
  pages.forEach(item => item.classList.toggle('active', item.id === page));
  nav.forEach(item => item.classList.toggle('active', item.dataset.page === page));
}
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

async function mutate(change) {
  try {
    const next = cloneConfig();
    change(next);
    const result = await window.cobo.saveConfig(JSON.stringify(next));
    render(result);
    setMessage('Saved');
  } catch (error) { setMessage(error.message); }
}
function render(next) {
  summary = next || summary;
  const client = summary?.clientName || 'vijay';
  $('#clientName').textContent = client;
  $('#contactCount').textContent = `${summary?.contactCount || 0} active`;
  $('#marketCount').textContent = `${summary?.marketCount || 0} timings`;
  $('#metricCards').innerHTML = [
    ['Input Groups', summary?.contactCount || 0, 'Configured customer groups'],
    ['Market Timings', summary?.marketCount || 0, 'Open and close rules'],
    ['Service Status', $('#botState')?.textContent || 'Stopped', 'Local service'],
    ['Today Play', '—', 'Available while service runs']
  ].map((x,i) => `<div class="metric metric-${i}"><small>${x[0]}</small><strong>${esc(x[1])}</strong><span>${x[2]}</span></div>`).join('');
  $('#customerList').innerHTML = contacts().map(([name, item]) => `<div class="row"><b>${esc(name)}</b><span>LD ${esc(item.LD ?? 100)}% · Limit ₹${esc(item.Limit ?? 0)}</span></div>`).join('') || '<p class="muted">No input group configured.</p>';
  $('#marketList').innerHTML = timingRows().slice(0,8).map(([name]) => `<div class="market"><b>${esc(pretty(name))}</b><span>Active</span></div>`).join('');
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
  editor.innerHTML = `<div class="edit-head"><div class="edit-icon">＋</div><div><h2>Add / Edit Market</h2><p>Create or update market timings</p></div></div>
    <label>Market Name<input value="${esc(pretty(selectedMarketKey))}" disabled></label>
    <label>Phase</label><div class="phase-toggle"><button class="${selectedMarketKey.endsWith('_OP') ? 'on' : ''}">Open</button><button class="${selectedMarketKey.endsWith('_CL') ? 'on' : ''}">Close</button></div>
    <div class="editor-time-grid"><label>Start Time<div><input data-edit="startHour" type="number" min="0" max="23" value="${esc(current[0]?.hour ?? 0)}"><input data-edit="startMinute" type="number" min="0" max="59" value="${esc(current[0]?.minute ?? 0)}"></div></label><label>End Time<div><input data-edit="endHour" type="number" min="0" max="23" value="${esc(current[2]?.hour ?? 0)}"><input data-edit="endMinute" type="number" min="0" max="59" value="${esc(current[2]?.minute ?? 0)}"></div></label></div>
    <label>Active Days</label><div class="weekday-row">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day,i)=>`<span class="${i < Number(current[1] || 0) ? 'checked' : ''}">${day}</span>`).join('')}</div>
    <button class="primary editor-save" data-action="save-market">▣ &nbsp; Save Market</button>`;
}
function renderGroups() {
  const markup = contacts().map(([name, group]) => {
    const director = group.Director || {};
    const overrides = director.market_overrides || {};
    return `<article class="group-card" data-group="${esc(name)}">
      <div class="group-head"><div><small>CUSTOMER GROUP</small><input class="group-name" value="${esc(name)}"></div><div class="active-group">● Active</div><button class="icon danger" data-action="delete-group">⌫</button></div>
      <div class="customer-fields"><label>LD %<input data-field="LD" type="number" min="0" max="100" value="${esc(group.LD ?? 100)}"></label><label>Limit (₹)<input data-field="Limit" type="number" min="0" value="${esc(group.Limit ?? 0)}"></label><label class="cutting-label">⚡ Instant Cutting<input data-field="instant_cutting" type="checkbox" ${group.instant_cutting ? 'checked' : ''}></label><label>All Table<input data-director="all_table" value="${esc(director.all_table || '')}" placeholder="Group name"></label><label>All Forward<input data-director="all_fast_forward" value="${esc(director.all_fast_forward || '')}" placeholder="Group name"></label></div>
      <div class="group-lower"><div class="override-box"><div class="mini-title">⌄ Market-wise destinations <button data-action="add-override">＋ Add</button></div>${Object.entries(overrides).map(([market,route])=>`<div class="override-row" data-market="${esc(market)}"><b>${esc(market)}</b><input data-route="table" value="${esc(route.table || '')}" placeholder="Table destination"><input data-route="fast_forward" value="${esc(route.fast_forward || '')}" placeholder="Forward destination"><button class="icon danger" data-action="delete-override">−</button></div>`).join('') || '<p class="muted">All markets use default destinations.</p>'}</div>
      <div class="rates-box"><div class="mini-title">Win Rate</div><div class="rate-grid">${['ANK','Jodi','SP','DP','TP','FS','HS','Commission'].map(key=>`<label>${key}<input data-rate="${key}" type="number" value="${esc(group.win_rate?.[key] ?? '')}"></label>`).join('')}</div></div></div>
    </article>`;
  }).join('') || '<div class="empty-groups"><b>No input groups yet</b><span>Use Add Input Group to create the first customer rule.</span></div>';
  ['#groupManager','#groupManagerSecondary'].forEach(id => { const node=$(id); if(node) node.innerHTML=markup; });
}
function groupChange(event) {
  const card = event.target.closest('.group-card'); if (!card) return;
  const name = card.dataset.group; const row = event.target.closest('.override-row');
  mutate(next => {
    const group = next.in_contacts?.[name]; if (!group) return;
    if (row && event.target.dataset.route) { group.Director ||= {}; group.Director.market_overrides ||= {}; group.Director.market_overrides[row.dataset.market] ||= {}; group.Director.market_overrides[row.dataset.market][event.target.dataset.route] = event.target.value.trim(); }
    else if (event.target.classList.contains('group-name')) { const newName=event.target.value.trim(); if(newName && newName!==name){next.in_contacts[newName]=group;delete next.in_contacts[name];} }
    else if(event.target.dataset.field) group[event.target.dataset.field] = event.target.type === 'checkbox' ? event.target.checked : Number(event.target.value || 0);
    else if(event.target.dataset.director){group.Director ||= {};group.Director[event.target.dataset.director]=event.target.value.trim();}
    else if(event.target.dataset.rate){group.win_rate ||= {};group.win_rate[event.target.dataset.rate]=Number(event.target.value || 0);}
  });
}
function groupClick(event) {
  const card=event.target.closest('.group-card'); if(!card) return; const name=card.dataset.group;
  if(event.target.dataset.action==='delete-group') mutate(next=>delete next.in_contacts[name]);
  if(event.target.dataset.action==='add-override'){overrideTargetGroup=name;$('#overrideDialog').showModal();}
  if(event.target.dataset.action==='delete-override'){const row=event.target.closest('.override-row');mutate(next=>delete next.in_contacts[name].Director.market_overrides[row.dataset.market]);}
}
function log(value){const out=$('#logs');out.textContent=(out.textContent+'\n'+value).trim().slice(-12000);out.scrollTop=out.scrollHeight;}
function setService(status){$('#botState').textContent=status.running?'Running':'Stopped';$('#botDot').classList.toggle('running',Boolean(status.running));if(status.code!==undefined)log('Service stopped with code '+status.code);}

nav.forEach(button=>button.addEventListener('click',()=>goto(button.dataset.page)));
document.querySelectorAll('[data-goto]').forEach(button=>button.addEventListener('click',()=>goto(button.dataset.goto)));
tabs.forEach(button=>button.addEventListener('click',()=>gotoTab(button.dataset.tab)));
document.querySelectorAll('[data-tab-target]').forEach(button=>button.addEventListener('click',()=>gotoTab(button.dataset.tabTarget)));
$('#marketRows').addEventListener('click',event=>{const item=event.target.closest('[data-market-key]');if(item){selectedMarketKey=item.dataset.marketKey;renderTimingTable();}});
$('#marketEditor').addEventListener('click',event=>{if(event.target.dataset.action!=='save-market')return;const edit=$('#marketEditor');const val=k=>Number(edit.querySelector('[data-edit="'+k+'"]').value||0);mutate(next=>{const row=next.fixed_market_time[selectedMarketKey];row[0]={hour:val('startHour'),minute:val('startMinute'),second:0};row[2]={hour:val('endHour'),minute:val('endMinute'),second:0};});});
['#groupManager','#groupManagerSecondary'].forEach(id=>{const node=$(id);if(node){node.addEventListener('change',groupChange);node.addEventListener('click',groupClick);}});
['#addGroup','#addGroupSecondary'].forEach(id=>{const node=$(id);if(node)node.addEventListener('click',()=>$('#groupDialog').showModal());});
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$('#'+button.dataset.close).close()));
$('#groupForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const name=String(d.get('name')).trim();if(!name)return;mutate(next=>{next.in_contacts ||= {};next.in_contacts[name]={LD:Number(d.get('ld')||100),Limit:Number(d.get('limit')||0),instant_cutting:d.get('instant')==='on',Director:{all_table:String(d.get('allTable')||'').trim(),all_fast_forward:String(d.get('allForward')||'').trim(),market_overrides:{}},win_rate:{ANK:Number(d.get('ank')||0),Jodi:Number(d.get('jodi')||0),SP:Number(d.get('sp')||0),DP:Number(d.get('dp')||0),TP:Number(d.get('tp')||0),FS:Number(d.get('fs')||0),HS:Number(d.get('hs')||0),Commission:Number(d.get('commission')||0)}};});event.currentTarget.reset();$('#groupDialog').close();});
$('#overrideForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const market=String(d.get('market')).trim();if(!market||!overrideTargetGroup)return;mutate(next=>{const group=next.in_contacts[overrideTargetGroup];group.Director ||= {};group.Director.market_overrides ||= {};group.Director.market_overrides[market]={table:String(d.get('table')||'').trim(),fast_forward:String(d.get('forward')||'').trim()};});event.currentTarget.reset();$('#overrideDialog').close();overrideTargetGroup='';});
$('#marketForm').addEventListener('submit',event=>{event.preventDefault();const d=new FormData(event.currentTarget);const name=String(d.get('name')).trim();if(!name)return;mutate(next=>{next.fixed_market_time ||= {};next.fixed_market_time[name]=[{hour:Number(d.get('startHour')||0),minute:Number(d.get('startMinute')||0),second:0},Number(d.get('days')||0),{hour:Number(d.get('endHour')||0),minute:Number(d.get('endMinute')||0),second:0}];selectedMarketKey=name;});event.currentTarget.reset();$('#marketDialog').close();});
async function chooseWorkspace(){try{const state=await window.cobo.chooseBotDirectory();log(state.botDirectory?'Workspace folder: '+state.botDirectory:'Workspace folder unchanged.');}catch(error){alert(error.message);}}
async function startService(){try{await window.cobo.startBot();log('Service started.');}catch(error){alert(error.message);}}
$('#chooseBot').addEventListener('click',chooseWorkspace);$('#launchService').addEventListener('click',startService);$('#stopBot').addEventListener('click',()=>window.cobo.stopBot());
window.cobo.onLog(log);window.cobo.onStatus(setService);
(async()=>{const state=await window.cobo.state();render(state.summary);setService(state);})();