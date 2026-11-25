// Render the committed SVG at every Windows icon size; no image service or native dependencies.
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const source = await fs.readFile(path.join(root, 'electron/renderer/icon.svg'), 'utf8');
  const window = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await window.loadURL('data:text/html,<html><body></body></html>');
  const rendered = await window.webContents.executeJavaScript(`(async () => {
    const img = new Image();
    img.src = 'data:image/svg+xml;base64,' + ${JSON.stringify(Buffer.from(source).toString('base64'))};
    await img.decode();
    return [16,24,32,48,64,128,256,512,1024].map(size => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = size;
      canvas.getContext('2d').drawImage(img,0,0,size,size);
      return { size, data: canvas.toDataURL('image/png').split(',')[1] };
    });
  })()`);
  const frames = rendered.filter(item => item.size <= 256).map(item => ({ size: item.size, data: Buffer.from(item.data, 'base64') }));
  const header = Buffer.alloc(6 + frames.length * 16);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(frames.length, 4);
  let offset = header.length;
  frames.forEach((frame, i) => {
    const index = 6 + i * 16;
    header[index] = header[index + 1] = frame.size === 256 ? 0 : frame.size;
    header.writeUInt16LE(1, index + 4); header.writeUInt16LE(32, index + 6);
    header.writeUInt32LE(frame.data.length, index + 8); header.writeUInt32LE(offset, index + 12);
    offset += frame.data.length;
  });
  const folder = path.join(root, 'electron/renderer');
  await fs.writeFile(path.join(folder, 'icon.png'), Buffer.from(rendered.at(-1).data, 'base64'));
  await fs.writeFile(path.join(folder, 'icon.ico'), Buffer.concat([header, ...frames.map(frame => frame.data)]));
  console.log('TriDock icon: SVG, 1024 PNG, multi-size ICO generated.');
  app.exit(0);
}).catch(error => { console.error(error); app.exit(1); });
