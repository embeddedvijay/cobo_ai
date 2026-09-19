const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cobo', {
  state: () => ipcRenderer.invoke('app:state'),
  chooseConfig: () => ipcRenderer.invoke('config:choose'),
  loadConfig: () => ipcRenderer.invoke('config:load'),
  saveConfig: raw => ipcRenderer.invoke('config:save', raw),
  chooseBotDirectory: () => ipcRenderer.invoke('bot:choose-directory'),
  startBot: () => ipcRenderer.invoke('bot:start'),
  stopBot: () => ipcRenderer.invoke('bot:stop'),
  onLog: handler => ipcRenderer.on('bot-log', (_event, value) => handler(value)),
  onStatus: handler => ipcRenderer.on('bot-status', (_event, value) => handler(value))
});
