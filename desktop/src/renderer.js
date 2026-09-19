const pages = [...document.querySelectorAll('.page')];
const nav = [...document.querySelectorAll('.nav')];
let summary;

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
  document.querySelector('#clientName').textContent = client;
  document.querySelector('#clientEmail').textContent = summary ? `local JSON · ${summary.contactCount} groups` : 'Local desktop control';
  document.querySelector('#configState').textContent = summary ? 'Loaded' : 'Not loaded';
  document.querySelector('#contactCount').textContent = `${summary?.contactCount || 0} contacts`;
  document.querySelector('#marketCount').textContent = `${summary?.marketCount || 0} markets`;
  const data = contacts();
  document.querySelector('#metricCards').innerHTML = data.slice(0, 5).map(item =>
    `<div class="metric"><b>${item.name}</b><small>LIMIT: ${item.Limit || '—'}</small><div><span>PLAY</span><strong>0</strong><span>WIN</span><strong>0</strong></div></div>`
  ).join('') || '<div class="metric muted">Import JSON to load customers.</div>';
  document.querySelector('#customerList').innerHTML = data.map(item =>
    `<div class="row"><b>${item.name}</b><span>LD ${item.LD || '—'} · Limit ${item.Limit || '—'}</span></div>`
  ).join('') || '<p class="muted">No configured customers.</p>';
  document.querySelector('#marketList').innerHTML = markets().map(name =>
    `<div class="market"><b>${name.replaceAll('_', ' ')}</b><span>Configured</span></div>`
  ).join('') || '<p class="muted">No market timing data.</p>';
  document.querySelector('#configSummary').innerHTML = summary
    ? `<dl><dt>Client</dt><dd>${client}</dd><dt>Input groups</dt><dd>${summary.contactCount}</dd><dt>Customers</dt><dd>${summary.contactCount}</dd><dt>Markets</dt><dd>${summary.marketCount}</dd></dl>`
    : 'No JSON configuration imported.';
}

function log(line) {
  const el = document.querySelector('#logs');
  el.textContent = `${el.textContent}\n${line}`.trim().slice(-12000);
  el.scrollTop = el.scrollHeight;
}

function setBot(status) {
  document.querySelector('#botState').textContent = status.running ? 'Running' : 'Stopped';
  document.querySelector('#botDot').classList.toggle('running', Boolean(status.running));
  if (status.code !== undefined) log(`Bot stopped with code ${status.code}`);
}

nav.forEach(button => button.addEventListener('click', () => goto(button.dataset.page)));
document.querySelectorAll('[data-goto]').forEach(button => button.addEventListener('click', () => goto(button.dataset.goto)));

async function importConfig() {
  try {
    const next = await window.cobo.chooseConfig();
    if (!next) return;
    const data = await window.cobo.loadConfig();
    document.querySelector('#jsonEditor').value = data.raw;
    renderSummary(next);
    log(`Config imported: ${next.clientName}`);
  } catch (error) { alert(error.message); }
}

async function saveConfig() {
  try {
    const next = await window.cobo.saveConfig(document.querySelector('#jsonEditor').value);
    renderSummary(next);
    document.querySelector('#saveMessage').textContent = 'Saved locally.';
  } catch (error) { document.querySelector('#saveMessage').textContent = error.message; }
}

async function chooseBot() {
  try {
    const state = await window.cobo.chooseBotDirectory();
    log(state.botDirectory ? `Bot folder: ${state.botDirectory}` : 'Bot folder unchanged.');
  } catch (error) { alert(error.message); }
}

async function launch() {
  try {
    await window.cobo.startBot();
    goto('dashboard');
    log('npm start launched with COBO_CONFIG_PATH.');
  } catch (error) {
    alert(error.message);
    goto('config');
  }
}

document.querySelector('#importConfig').addEventListener('click', importConfig);
document.querySelector('#saveConfig').addEventListener('click', saveConfig);
document.querySelector('#chooseBot').addEventListener('click', chooseBot);
document.querySelector('#launchBot').addEventListener('click', launch);
document.querySelector('#dashboardLaunch').addEventListener('click', launch);
document.querySelector('#stopBot').addEventListener('click', () => window.cobo.stopBot());
window.cobo.onLog(log);
window.cobo.onStatus(setBot);

(async () => {
  const state = await window.cobo.state();
  renderSummary(state.summary);
  setBot(state);
  if (state.summary) {
    const data = await window.cobo.loadConfig();
    document.querySelector('#jsonEditor').value = data.raw;
  }
})();
