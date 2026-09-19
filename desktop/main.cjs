const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

let windowRef;
let botProcess;

const statePath = () => path.join(app.getPath('userData'), 'cobo-state.json');
const configDir = () => path.join(app.getPath('userData'), 'configs');

function readState() {
  try { return JSON.parse(fs.readFileSync(statePath(), 'utf8')); }
  catch { return { botDirectory: '', configPath: '' }; }
}

function saveState(next) {
  fs.mkdirSync(path.dirname(statePath()), { recursive: true });
  fs.writeFileSync(statePath(), JSON.stringify(next, null, 2));
}

function emit(channel, payload) { windowRef?.webContents.send(channel, payload); }

function normaliseConfig(value) {
  const config = Array.isArray(value) ? value[0] : value;
  if (!config || typeof config !== 'object') throw new Error('JSON object or one-item JSON array is required.');
  if (!config.client_name) throw new Error('client_name is required.');
  if (!Array.isArray(config.sessions)) throw new Error('sessions array is required.');
  return config;
}

function loadConfig(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  return { raw, config: normaliseConfig(JSON.parse(raw)) };
}

function configSummary(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return null;
  const { config } = loadConfig(filePath);
  const sessions = config.sessions || [];
  const contacts = sessions.flatMap(item => Object.keys(item.in_contacts || {}));
  return {
    filePath,
    clientName: config.client_name,
    sessionNames: sessions.map(item => item.session_name || 'Session'),
    contactCount: contacts.length,
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

ipcMain.handle('app:state', () => ({ ...readState(), running: Boolean(botProcess), summary: configSummary(readState().configPath) }));

ipcMain.handle('config:choose', async () => {
  const picked = await dialog.showOpenDialog(windowRef, { properties: ['openFile'], filters: [{ name: 'JSON config', extensions: ['json'] }] });
  if (picked.canceled || !picked.filePaths[0]) return null;
  const source = picked.filePaths[0];
  const { raw } = loadConfig(source);
  fs.mkdirSync(configDir(), { recursive: true });
  const target = path.join(configDir(), path.basename(source));
  fs.writeFileSync(target, raw);
  const next = { ...readState(), configPath: target };
  saveState(next);
  return configSummary(target);
});

ipcMain.handle('config:load', () => {
  const { configPath } = readState();
  if (!configPath || !fs.existsSync(configPath)) return { raw: '', summary: null };
  const { raw } = loadConfig(configPath);
  return { raw, summary: configSummary(configPath) };
});

ipcMain.handle('config:save', (_event, raw) => {
  const state = readState();
  if (!state.configPath) throw new Error('Import a JSON config first.');
  const parsed = JSON.parse(raw);
  normaliseConfig(parsed);
  fs.writeFileSync(state.configPath, JSON.stringify(parsed, null, 2));
  return configSummary(state.configPath);
});

ipcMain.handle('bot:choose-directory', async () => {
  const picked = await dialog.showOpenDialog(windowRef, { properties: ['openDirectory'] });
  if (picked.canceled || !picked.filePaths[0]) return readState();
  const botDirectory = picked.filePaths[0];
  if (!fs.existsSync(path.join(botDirectory, 'package.json'))) throw new Error('Selected folder must contain package.json.');
  const next = { ...readState(), botDirectory };
  saveState(next);
  return next;
});

ipcMain.handle('bot:start', () => {
  const state = readState();
  if (botProcess) return { running: true };
  if (!state.configPath || !fs.existsSync(state.configPath)) throw new Error('Import and save a JSON config first.');
  if (!state.botDirectory || !fs.existsSync(path.join(state.botDirectory, 'package.json'))) throw new Error('Choose the npm bot folder first.');
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  botProcess = spawn(npm, ['start'], {
    cwd: state.botDirectory,
    env: { ...process.env, COBO_CONFIG_PATH: state.configPath, COBO_CONFIG_FORMAT: 'json' },
    windowsHide: true
  });
  botProcess.stdout.on('data', data => emit('bot-log', data.toString()));
  botProcess.stderr.on('data', data => emit('bot-log', data.toString()));
  botProcess.on('close', code => { botProcess = undefined; emit('bot-status', { running: false, code }); });
  emit('bot-status', { running: true });
  return { running: true };
});

ipcMain.handle('bot:stop', () => { stopBot(); return { running: false }; });
