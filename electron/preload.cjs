const { contextBridge, ipcRenderer, webUtils } = require('electron');

async function call(action, value) {
  const result = await ipcRenderer.invoke(`runner:${action}`, value);
  if (result.error) throw new Error(result.error);
  return result.value;
}

contextBridge.exposeInMainWorld('runner', {
  snapshot: () => call('snapshot'),
  pickIpa: () => call('import'),
  importFile: file => call('import', webUtils.getPathForFile(file)),
  icon: id => call('icon', id),
  status: id => call('status', id),
  enqueue: id => call('enqueue', id),
  shortcut: id => call('shortcut', id),
  launch: id => call('launch', id),
  saveDisplayMode: (bundleId, mode) => call('display-mode', { bundleId, mode }),
  openIos: () => call('open-ios'),
  saveSettings: settings => call('save-settings', settings),
  browse: kind => call('browse', kind),
  openData: () => call('open-data'),
  download: kind => call('download', kind),
});
