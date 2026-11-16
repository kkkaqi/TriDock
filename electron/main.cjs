const { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } = require('electron');
const { execFile } = require('node:child_process');
const { writeFile } = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const project = path.resolve(__dirname, '..');
const renderer = path.join(__dirname, 'renderer');
const url = 'ipa-runner://desktop/index.html';
const pages = new Set(['/index.html', '/app.js', '/app.css']);
const smoke = process.argv.includes('--smoke');
const minimum = { width: 660, height: 500 };
const downloads = {
  touchhle: 'https://github.com/touchHLE/touchHLE/releases',
  asoftware: 'https://github.com/alpersamur3/asoft-ios/releases',
};

app.setName('IPA Runner');
protocol.registerSchemesAsPrivileged([{ scheme: 'ipa-runner', privileges: { standard: true, secure: true } }]);

function bridge(action, payload = {}) {
  return new Promise((resolve, reject) => {
    const args = [path.join(project, 'desktop_bridge.py')];
    if (smoke && process.env.IPA_RUNNER_SMOKE_DATA) args.push('--data-dir', process.env.IPA_RUNNER_SMOKE_DATA);
    args.push(action);
    const child = execFile('python.exe', args, {
      cwd: project,
      windowsHide: true,
      encoding: 'utf8',
      timeout: 10 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: '1' },
    }, (error, stdout, stderr) => {
      if (error) {
        const message = error.code === 'ENOENT' ? '找不到 Python。请安装 Python 3.10 或更高版本。' : stderr.trim() || '后台进程未完成操作。';
        reject(new Error(message));
        return;
      }
      try {
        const response = JSON.parse(stdout);
        if (response.ok) resolve(response.value);
        else reject(new Error(response.error));
      } catch (parseError) {
        reject(new Error('后台返回了无法读取的数据。', { cause: parseError }));
      }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify(payload));
  });
}

function registerHandlers() {
  function handle(channel, task) {
    ipcMain.handle(`runner:${channel}`, async (event, value) => {
      if (event.senderFrame?.url !== url || event.senderFrame !== event.sender.mainFrame) {
        throw new Error('无效的请求来源。');
      }
      try {
        return { value: await task(event, value) };
      } catch (error) {
        return { error: error.message };
      }
    });
  }

  handle('snapshot', () => bridge('snapshot'));
  handle('import', async (event, dropPath) => {
    if (dropPath) return bridge('import', { path: dropPath });
    const owner = BrowserWindow.fromWebContents(event.sender);
    const { canceled, filePaths } = await dialog.showOpenDialog(owner, {
      title: '选择 IPA 安装包', properties: ['openFile'], filters: [{ name: 'iOS 安装包', extensions: ['ipa'] }],
    });
    return canceled ? null : bridge('import', { path: filePaths[0] });
  });
  for (const action of ['icon', 'status', 'enqueue', 'shortcut', 'launch']) {
    handle(action, (_event, bundleId) => bridge(action, { bundleId }));
  }
  handle('display-mode', (_event, values) => bridge('display-mode', values));
  handle('open-ios', () => bridge('open-ios'));
  handle('save-settings', (_event, settings) => bridge('save-settings', settings));
  handle('browse', async (event, kind) => {
    const options = {
      touchhle: { title: '选择 touchHLE.exe', properties: ['openFile'], filters: [{ name: '应用程序', extensions: ['exe'] }] },
      asoftware: { title: '选择 ASoftware iOS 16 安装目录', properties: ['openDirectory'] },
      asoftwareWork: { title: '选择 iOS 16 数据目录', properties: ['openDirectory'] },
    }[kind];
    if (!options) throw new Error('未知的运行时设置。');
    const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), options);
    return canceled ? null : filePaths[0];
  });
  handle('open-data', async () => {
    const { dataDir } = await bridge('snapshot');
    const error = await shell.openPath(dataDir);
    if (error) throw new Error(error);
  });
  handle('download', (_event, kind) => {
    if (!Object.hasOwn(downloads, kind)) throw new Error('未知的下载来源。');
    return shell.openExternal(downloads[kind]);
  });
}

async function verifyDrop(contents, ipa) {
  const debuggerClient = contents.debugger;
  debuggerClient.attach('1.3');
  try {
    const { result } = await debuggerClient.sendCommand('Runtime.evaluate', { expression: `(() => {
      const input = document.createElement('input');
      input.type = 'file';
      input.hidden = true;
      document.body.append(input);
      return input;
    })()` });
    await debuggerClient.sendCommand('DOM.setFileInputFiles', { files: [ipa], objectId: result.objectId });
  } finally {
    debuggerClient.detach();
  }
  const notice = await contents.executeJavaScript(`(async () => {
    const input = document.querySelector('input[type=file]');
    const files = new DataTransfer();
    files.items.add(input.files[0]);
    document.dispatchEvent(new DragEvent('drop', { dataTransfer: files, cancelable: true }));
    input.remove();
    const deadline = Date.now() + 10000;
    const notice = document.querySelector('#notice');
    while (!notice.textContent && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
    return notice.textContent;
  })()`);
  if (!notice.startsWith('已导入 ')) throw new Error(notice || 'The drop did not report an import result.');
  console.log(notice);
}

async function createWindow() {
  const window = new BrowserWindow({
    width: 1100,
    height: 720,
    minWidth: minimum.width,
    minHeight: minimum.height,
    show: false,
    backgroundColor: '#f7f8fc',
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#f7f8fc', symbolColor: '#383a52', height: 42 },
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  await window.loadURL(url);
  if (smoke) {
    const checks = await window.webContents.executeJavaScript(`(async () => {
      const deadline = Date.now() + 10000;
      while (document.body.dataset.ready !== 'true' && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 30));
      }
      const search = document.querySelector('#search');
      const count = document.querySelectorAll('.app-row').length;
      search.value = '__no_match_ipa__';
      search.dispatchEvent(new Event('input'));
      const filters = !document.querySelector('.app-row');
      search.value = '';
      search.dispatchEvent(new Event('input'));
      document.querySelector('#settings-nav').click();
      const settings = !document.querySelector('#settings-view').hidden;
      document.querySelector('#library-nav').click();
      return { ready: document.body.dataset.ready === 'true', count, filters, settings,
        library: !document.querySelector('#library-view').hidden };
    })()`);
    if (!checks.ready || !checks.filters || !checks.settings || !checks.library) throw new Error(JSON.stringify(checks));
    const importPath = process.env.IPA_RUNNER_SMOKE_IMPORT;
    if (importPath) {
      if (!process.env.IPA_RUNNER_SMOKE_DATA) throw new Error('Set a separate smoke-test library before testing import.');
      await verifyDrop(window.webContents, importPath);
      const saved = await window.webContents.executeJavaScript(`(async () => {
        if (document.querySelector('#display-options').hidden) return true;
        const select = document.querySelector('#display-mode');
        select.value = 'fullscreen';
        select.dispatchEvent(new Event('change'));
        const deadline = Date.now() + 10000;
        while (select.disabled && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
        const { apps } = await window.runner.snapshot();
        return select.value === 'fullscreen' && apps.some(app => app.displayMode === 'fullscreen');
      })()`);
      if (!saved) throw new Error('The display mode was not saved from the launcher.');
    }
    if (process.env.IPA_RUNNER_SMOKE_PNG) {
      await window.webContents.executeJavaScript(`new Promise(resolve => setTimeout(resolve, 500))`);
      const image = await window.webContents.capturePage();
      await writeFile(process.env.IPA_RUNNER_SMOKE_PNG, image.toPNG());
    }
    window.setSize(minimum.width, minimum.height);
    const fits = await window.webContents.executeJavaScript(`new Promise(resolve => setTimeout(() => {
      const workspace = document.querySelector('.workspace');
      resolve(workspace.scrollWidth <= workspace.clientWidth);
    }, 100))`);
    if (!fits) throw new Error('The library overflows horizontally at the minimum window size.');
    const launchId = process.env.IPA_RUNNER_SMOKE_LAUNCH;
    if (launchId) {
      const launched = await window.webContents.executeJavaScript(`(async () => {
        const row = [...document.querySelectorAll('.app-row')].find(item => item.dataset.bundle === ${JSON.stringify(launchId)});
        if (!row) throw new Error('Smoke app is missing.');
        row.click();
        document.querySelector('#run-button').click();
        const deadline = Date.now() + 10000;
        const notice = document.querySelector('#notice');
        const previous = notice.textContent;
        while (notice.textContent === previous && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
        return notice.textContent;
      })()`);
      if (!launched.startsWith('已启动 ')) throw new Error(launched || 'The app did not report a launch result.');
      console.log(launched);
    }
    console.log(`Electron smoke passed · ${checks.count} initial app(s) · search, navigation and layout`);
    app.exit(0);
    return;
  }
  window.show();
}

if (!smoke && !app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const window = BrowserWindow.getAllWindows()[0];
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.focus();
  });
  app.once('window-all-closed', () => app.quit());
  app.whenReady().then(async () => {
    protocol.handle('ipa-runner', request => {
      const resource = new URL(request.url);
      if (resource.hostname !== 'desktop' || !pages.has(resource.pathname)) return new Response('', { status: 404 });
      return net.fetch(pathToFileURL(path.join(renderer, resource.pathname.slice(1))).href);
    });
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    registerHandlers();
    await createWindow();
  }).catch(error => {
    if (smoke) console.error(error);
    else dialog.showErrorBox('IPA Runner', error.message);
    app.exit(1);
  });
}
