const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cobo', {
  state: () => ipcRenderer.invoke('app:state'),
  loadConfig: () => ipcRenderer.invoke('config:load'),
  saveConfig: raw => ipcRenderer.invoke('config:save', raw),
  dashboard: payload => ipcRenderer.invoke('desktop:dashboard', payload),
  finalOptions: () => ipcRenderer.invoke('desktop:final-options'),
  runFinal: payload => ipcRenderer.invoke('desktop:run-final', payload),
  results: date => ipcRenderer.invoke('desktop:results', date),
  saveResult: payload => ipcRenderer.invoke('desktop:save-result', payload),
  transactions: payload => ipcRenderer.invoke('desktop:transactions', payload),
  saveTransaction: payload => ipcRenderer.invoke('desktop:save-transaction', payload),
  rejectTransaction: payload => ipcRenderer.invoke('desktop:reject-transaction', payload),
  chooseBotDirectory: () => ipcRenderer.invoke('bot:choose-directory'),
  startBot: () => ipcRenderer.invoke('bot:start'),
  stopBot: () => ipcRenderer.invoke('bot:stop'),
  onLog: handler => ipcRenderer.on('bot-log', (_event, value) => handler(value)),
  onStatus: handler => ipcRenderer.on('bot-status', (_event, value) => handler(value))
});
