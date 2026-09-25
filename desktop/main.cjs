const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

let windowRef;
let botProcess;

const statePath = () => path.join(app.getPath('userData'), 'cobo-state.json');
const configDir = () => path.join(app.getPath('userData'), 'configs');
const defaultConfigPath = () => path.join(__dirname, 'config.example.json');
const sourceProjectDirectory = () => {
  const candidate = path.resolve(__dirname, '..');
  return isProjectWorkspace(candidate) ? candidate : '';
};

function readState() {
  try { return JSON.parse(fs.readFileSync(statePath(), 'utf8')); }
  catch { return { botDirectory: '', configPath: '' }; }
}

function saveState(next) {
  fs.mkdirSync(path.dirname(statePath()), { recursive: true });
  fs.writeFileSync(statePath(), JSON.stringify(next, null, 2));
}

function isOldDemoWorkspace(filePath) {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    return Object.keys(value?.in_contacts || {}).length === 1 &&
      Boolean(value?.in_contacts?.RAJSV_DAY5) &&
      Object.keys(value?.fixed_market_time || {}).length === 2;
  } catch { return false; }
}
function ensureWorkspaceConfig() {
  const state = readState();
  const botDirectory = isProjectWorkspace(state.botDirectory) ? state.botDirectory : sourceProjectDirectory();
  if (state.configPath && fs.existsSync(state.configPath) && !isOldDemoWorkspace(state.configPath)) {
    if (botDirectory !== state.botDirectory) {
      const next = { ...state, botDirectory };
      saveState(next);
      return next;
    }
    return state;
  }
  fs.mkdirSync(configDir(), { recursive: true });
  const configPath = state.configPath || path.join(configDir(), 'workspace-config.json');
  fs.copyFileSync(defaultConfigPath(), configPath);
  const next = { ...state, botDirectory, configPath };
  saveState(next);
  return next;
}

function emit(channel, payload) { windowRef?.webContents.send(channel, payload); }

function normaliseConfig(value) {
  const source = Array.isArray(value) ? value[0] : value;
  if (!source || typeof source !== 'object') throw new Error('Workspace configuration is invalid.');
  if (!source.client_name) throw new Error('Client name is required.');
  const legacy = Array.isArray(source.sessions) ? source.sessions[0] || {} : {};
  const inContacts = source.in_contacts || legacy.in_contacts || {};
  return { ...source, in_contacts: inContacts };
}

function loadConfig(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  return { raw, config: normaliseConfig(JSON.parse(raw)) };
}

function existingAuthDir(projectDirectory, configuredAuthDir = '') {
  const hasLoggedInSession = directory => {
    try { return JSON.parse(fs.readFileSync(path.join(directory, 'creds.json'), 'utf8')).registered === true; }
    catch { return false; }
  };
  const configured = String(configuredAuthDir || '').trim();
  const absoluteConfigured = configured
    ? (path.isAbsolute(configured) ? configured : path.join(projectDirectory, configured))
    : '';
  if (absoluteConfigured && hasLoggedInSession(absoluteConfigured)) return configured;

  const authRoot = path.join(projectDirectory, 'auth_info');
  const candidates = [];
  if (hasLoggedInSession(authRoot)) candidates.push('./auth_info');
  if (fs.existsSync(authRoot)) {
    for (const entry of fs.readdirSync(authRoot, { withFileTypes: true })) {
      if (entry.isDirectory() && hasLoggedInSession(path.join(authRoot, entry.name))) {
        candidates.push(`./auth_info/${entry.name}`);
      }
    }
  }
  // A saved QR login is always preferable to creating a new desktop folder.
  return candidates.sort()[0] || configured || './auth_info/desktop';
}

function runtimeConfigFromJson(value, projectDirectory) {
  const client = normaliseConfig(value);
  const outputGroups = new Set();
  for (const detail of Object.values(client.in_contacts || {})) {
    const director = detail?.Director || {};
    const overflow = detail?.overflow_limits || {};
    if (director.all_table) outputGroups.add(String(director.all_table));
    if (director.all_fast_forward) outputGroups.add(String(director.all_fast_forward));
    if (overflow.output_group) outputGroups.add(String(overflow.output_group));
    const rows = director.market_overrides || director;
    for (const route of Object.values(rows)) {
      if (route?.table) outputGroups.add(String(route.table));
      if (route?.fast_forward) outputGroups.add(String(route.fast_forward));
    }
  }
  const outputs = [...outputGroups];
  return {
    whatsapp: {
      auth_dir: existingAuthDir(projectDirectory, client.whatsapp?.auth_dir),
      backend_url: client.whatsapp?.backend_url || 'http://127.0.0.1:8015',
      reconnect_delay_ms: 2500, outbox_poll_ms: 500, max_parallel_jids: 1
    },
    // Keep all night markets, including Main Bazar's 00:10 close result,
    // in the prior trading day until the 04:00 morning reset.
    business_day_rollover: client.business_day_rollover || '04:00',
    mongo: client.mongo || { url: 'mongodb://127.0.0.1:27017/', database: 'Market' },
    clients: [{
      client_name: client.client_name,
      fixed_market_time: 'desktop',
      dynamic_timing: client.dynamic_timing || {},
      sessions: [{
        session_name: '_runtime',
        market_timings: client.fixed_market_time || {},
        // Preserve exact weekdays from the desktop timing editor. An overnight\n        // close (for example 22:00 → 00:10) is scheduled on the next calendar\n        // day without changing its business date.\n        market_days: client.market_days || {},
        contact_rules: client.in_contacts || {},
        in_contacts: Object.entries(client.in_contacts || {}).map(([name, detail]) => `${name} ^ ${detail?.LD ?? 100}`),
        in_channels: client.in_channels || [],
        processing: { trigger_contains: 'last', quote_reply: true, max_parallel_sources: 1 },
        out_contacts: { fast_forward: { other: outputs }, table: { other: outputs } },
        scheduler: { jobs: [] }
      }]
    }]
  };
}

function writeRuntimeConfig(configPath, projectDirectory) {
  const uploaded = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const runtimePath = path.join(path.dirname(configPath), '.cobo-runtime.json');
  fs.writeFileSync(runtimePath, JSON.stringify(runtimeConfigFromJson(uploaded, projectDirectory), null, 2));
  return runtimePath;
}

function configSummary(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return null;
  const { config } = loadConfig(filePath);
  return {
    filePath,
    clientName: config.client_name,
    contactCount: Object.keys(config.in_contacts || {}).length,
    marketCount: Object.keys(config.fixed_market_time || {}).length,
    config
  };
}

function desktopBackendUrl() {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return String(config.whatsapp?.backend_url || 'http://127.0.0.1:8015').replace(/\/$/, '');
}

function isProjectWorkspace(directory) {
  return Boolean(directory) &&
    fs.existsSync(path.join(directory, 'package.json')) &&
    fs.existsSync(path.join(directory, 'start.sh')) &&
    fs.existsSync(path.join(directory, 'backend', 'app', 'main.py')) &&
    fs.existsSync(path.join(directory, 'src', 'index.mjs'));
}

const projectFolderHelp = 'Choose the project folder that contains start.sh. Do not choose its desktop subfolder.';

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function waitForLocalService(timeoutMs = 35_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${desktopBackendUrl()}/health`);
      if (response.ok) return true;
    } catch (_error) { /* backend is still booting */ }
    await wait(500);
  }
  return false;
}

async function desktopApi(path, options = {}) {
  let response;
  try {
    response = await fetch(`${desktopBackendUrl()}${path}`, {
      headers: { 'content-type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
  } catch (_error) {
    throw new Error(`Local service is not running. ${projectFolderHelp} Then press Start Service.`);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Database request failed (${response.status})`);
  return payload;
}

function createWindow() {
  windowRef = new BrowserWindow({
    width: 1480, height: 920, minWidth: 1080, minHeight: 700,
    backgroundColor: '#080d23', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false }
  });
  windowRef.loadFile(path.join(__dirname, 'src', 'index.html'));
}

app.whenReady().then(() => {
  ensureWorkspaceConfig();
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => stopBot());

function stopBot() {
  const current = botProcess;
  if (!current) return;
  // `npm start` -> start.sh -> node creates a process tree. Killing only npm
  // left the bridge alive and it kept reconnecting after the desktop said
  // Stopped. On Linux launch in its own group and terminate that whole group.
  if (process.platform === 'win32') {
    current.kill('SIGTERM');
  } else {
    try { process.kill(-current.pid, 'SIGTERM'); }
    catch (_) { current.kill('SIGTERM'); }
  }
  botProcess = undefined;
  emit('bot-status', { running: false });
}

ipcMain.handle('app:state', () => {
  const state = ensureWorkspaceConfig();
  return { ...state, running: Boolean(botProcess), summary: configSummary(state.configPath) };
});
ipcMain.handle('config:load', () => {
  const state = ensureWorkspaceConfig();
  const { raw } = loadConfig(state.configPath);
  return { raw, summary: configSummary(state.configPath) };
});
ipcMain.handle('config:save', async (_event, raw) => {
  const state = ensureWorkspaceConfig();
  const parsed = JSON.parse(raw);
  normaliseConfig(parsed);
  fs.writeFileSync(state.configPath, JSON.stringify(parsed, null, 2));
  const restarted = Boolean(botProcess);
  if (restarted) {
    const current = botProcess;
    const finished = new Promise(resolve => {
      const timeout = setTimeout(resolve, 5000);
      current.once('close', () => { clearTimeout(timeout); resolve(); });
    });
    stopBot();
    await finished;
    await startBotService();
  }
  return { ...configSummary(state.configPath), restarted };
});
ipcMain.handle('desktop:results', (_event, date) => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/results?date=${encodeURIComponent(date)}&client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime`);
});
ipcMain.handle('desktop:dashboard', (_event, { date, market = '', contact = '' }) => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/dashboard?date=${encodeURIComponent(date)}&client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime&market=${encodeURIComponent(market)}&contact=${encodeURIComponent(contact)}`);
});
ipcMain.handle('desktop:output-groups', () => {
  // The configuration screen loads before the local service is started. In
  // that state there cannot be a WhatsApp group list yet, so return an empty
  // picker instead of making Electron print an IPC handler error.
  if (!botProcess) return { groups: [] };
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/output-groups?client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime`);
});
ipcMain.handle('desktop:resolve-output-group', async (_event, name) => {
  if (!botProcess) return { status: 'unavailable' };
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  try {
    return await desktopApi(`/desktop/resolve-output-group?name=${encodeURIComponent(String(name || ''))}&client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime`);
  } catch (_) {
    // This happens briefly when Electron was updated but an older backend is
    // still alive. The renderer shows its normal "start/restart service"
    // hint instead of flooding the Electron console with IPC errors.
    return { status: 'unavailable' };
  }
});
ipcMain.handle('desktop:group-mappings', () => {
  if (!botProcess) return { mappings: [] };
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/group-mappings?client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime`);
});
ipcMain.handle('desktop:final-options', () => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/final-options?client_name=${encodeURIComponent(config.client_name || '')}&session_name=_runtime`);
});
ipcMain.handle('desktop:run-final', (_event, { output_group }) => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi('/desktop/run-final', { method: 'POST', body: JSON.stringify({ client_name: config.client_name || '', session_name: '_runtime', output_group }) });
});
ipcMain.handle('desktop:save-result', (_event, payload) => desktopApi('/desktop/results', { method: 'PUT', body: JSON.stringify(payload) }));
ipcMain.handle('desktop:transactions', (_event, { date, contact = '' }) => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/transactions?date=${encodeURIComponent(date)}&client_name=${encodeURIComponent(config.client_name || '')}&contact=${encodeURIComponent(contact)}`);
});
ipcMain.handle('desktop:hisab', (_event, { date, contact = '' }) => {
  const state = ensureWorkspaceConfig();
  const { config } = loadConfig(state.configPath);
  return desktopApi(`/desktop/hisab?date=${encodeURIComponent(date)}&client_name=${encodeURIComponent(config.client_name || '')}&contact=${encodeURIComponent(contact)}`);
});
ipcMain.handle('desktop:save-transaction', (_event, payload) => desktopApi('/desktop/transactions', { method: 'PUT', body: JSON.stringify(payload) }));
ipcMain.handle('desktop:reject-transaction', (_event, payload) => desktopApi('/desktop/transactions/reject', { method: 'POST', body: JSON.stringify(payload) }));
ipcMain.handle('bot:choose-directory', async () => {
  const picked = await dialog.showOpenDialog(windowRef, { properties: ['openDirectory'] });
  if (picked.canceled || !picked.filePaths[0]) return readState();
  const botDirectory = picked.filePaths[0];
  if (!isProjectWorkspace(botDirectory)) throw new Error(projectFolderHelp);
  const next = { ...ensureWorkspaceConfig(), botDirectory };
  saveState(next);
  return next;
});
async function startBotService() {
  const state = ensureWorkspaceConfig();
  if (botProcess) return { running: true };
  const projectDirectory = isProjectWorkspace(state.botDirectory) ? state.botDirectory : sourceProjectDirectory();
  if (!projectDirectory) throw new Error(projectFolderHelp);
  if (projectDirectory !== state.botDirectory) saveState({ ...state, botDirectory: projectDirectory });
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const runtimeConfigPath = writeRuntimeConfig(state.configPath, projectDirectory);
  botProcess = spawn(npm, ['start'], {
    cwd: projectDirectory,
    env: { ...process.env, COBO_CONFIG_PATH: state.configPath, COBO_RUNTIME_CONFIG_PATH: runtimeConfigPath, COBO_CONFIG_FORMAT: 'json' },
    detached: process.platform !== 'win32',
    windowsHide: true
  });
  botProcess.stdout.on('data', data => emit('bot-log', data.toString()));
  botProcess.stderr.on('data', data => emit('bot-log', data.toString()));
  botProcess.on('close', code => { botProcess = undefined; emit('bot-status', { running: false, code }); });
  emit('bot-status', { running: false, starting: true });
  if (!await waitForLocalService()) {
    throw new Error('Service did not become ready. Check the activity log for the startup error.');
  }
  emit('bot-status', { running: true });
  return { running: true };
}
ipcMain.handle('bot:start', startBotService);
ipcMain.handle('bot:stop', () => { stopBot(); return { running: false }; });
