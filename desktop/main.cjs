const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

let windowRef;
let botProcess;

const statePath = () => path.join(app.getPath('userData'), 'cobo-state.json');
const configDir = () => path.join(app.getPath('userData'), 'configs');
const defaultConfigPath = () => path.join(__dirname, 'config.example.json');

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
  if (state.configPath && fs.existsSync(state.configPath) && !isOldDemoWorkspace(state.configPath)) return state;
  fs.mkdirSync(configDir(), { recursive: true });
  const configPath = state.configPath || path.join(configDir(), 'workspace-config.json');
  fs.copyFileSync(defaultConfigPath(), configPath);
  const next = { ...state, configPath };
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

function runtimeConfigFromJson(value) {
  const client = normaliseConfig(value);
  const outputGroups = new Set();
  for (const detail of Object.values(client.in_contacts || {})) {
    const director = detail?.Director || {};
    if (director.all_table) outputGroups.add(String(director.all_table));
    if (director.all_fast_forward) outputGroups.add(String(director.all_fast_forward));
    const rows = director.market_overrides || director;
    for (const route of Object.values(rows)) {
      if (route?.table) outputGroups.add(String(route.table));
      if (route?.fast_forward) outputGroups.add(String(route.fast_forward));
    }
  }
  const outputs = [...outputGroups];
  return {
    whatsapp: {
      auth_dir: client.whatsapp?.auth_dir || './auth_info/desktop',
      backend_url: client.whatsapp?.backend_url || 'http://127.0.0.1:8015',
      reconnect_delay_ms: 2500, outbox_poll_ms: 500, max_parallel_jids: 1
    },
    business_day_rollover: client.business_day_rollover || '01:30',
    mongo: client.mongo || { url: 'mongodb://127.0.0.1:27017/', database: 'Market' },
    clients: [{
      client_name: client.client_name,
      fixed_market_time: 'desktop',
      dynamic_timing: client.dynamic_timing || {},
      sessions: [{
        session_name: '_runtime',
        market_timings: client.fixed_market_time || {},
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

function writeRuntimeConfig(configPath) {
  const uploaded = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const runtimePath = path.join(path.dirname(configPath), '.cobo-runtime.json');
  fs.writeFileSync(runtimePath, JSON.stringify(runtimeConfigFromJson(uploaded), null, 2));
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
  if (!botProcess) return;
  botProcess.kill('SIGTERM');
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
ipcMain.handle('config:save', (_event, raw) => {
  const state = ensureWorkspaceConfig();
  const parsed = JSON.parse(raw);
  normaliseConfig(parsed);
  fs.writeFileSync(state.configPath, JSON.stringify(parsed, null, 2));
  return configSummary(state.configPath);
});
ipcMain.handle('bot:choose-directory', async () => {
  const picked = await dialog.showOpenDialog(windowRef, { properties: ['openDirectory'] });
  if (picked.canceled || !picked.filePaths[0]) return readState();
  const botDirectory = picked.filePaths[0];
  if (!fs.existsSync(path.join(botDirectory, 'package.json'))) throw new Error('Selected workspace must contain package.json.');
  const next = { ...ensureWorkspaceConfig(), botDirectory };
  saveState(next);
  return next;
});
ipcMain.handle('bot:start', () => {
  const state = ensureWorkspaceConfig();
  if (botProcess) return { running: true };
  if (!state.botDirectory || !fs.existsSync(path.join(state.botDirectory, 'package.json'))) throw new Error('Choose the workspace folder first.');
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const runtimeConfigPath = writeRuntimeConfig(state.configPath);
  botProcess = spawn(npm, ['start'], {
    cwd: state.botDirectory,
    env: { ...process.env, COBO_CONFIG_PATH: state.configPath, COBO_RUNTIME_CONFIG_PATH: runtimeConfigPath, COBO_CONFIG_FORMAT: 'json' },
    windowsHide: true
  });
  botProcess.stdout.on('data', data => emit('bot-log', data.toString()));
  botProcess.stderr.on('data', data => emit('bot-log', data.toString()));
  botProcess.on('close', code => { botProcess = undefined; emit('bot-status', { running: false, code }); });
  emit('bot-status', { running: true });
  return { running: true };
});
ipcMain.handle('bot:stop', () => { stopBot(); return { running: false }; });
