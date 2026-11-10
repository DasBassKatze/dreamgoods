const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('dgDesktop', Object.freeze({
  minimize: () => ipcRenderer.invoke('dg:window', 'minimize'),
  maximize: () => ipcRenderer.invoke('dg:window', 'maximize'),
  close: () => ipcRenderer.invoke('dg:window', 'close'),
  dataInfo: () => ipcRenderer.invoke('dg:data-info'),
  interfaceMode: (userId, mode) => ipcRenderer.invoke('dg:interface-mode', userId, mode),
  mode: mode => ipcRenderer.invoke('dg:mode', mode),
  state: () => ipcRenderer.invoke('dg:state'),
}));
