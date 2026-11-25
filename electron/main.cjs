const { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } = require('electron');
const { execFile } = require('node:child_process');
const { writeFile } = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const project = path.resolve(__dirname, '..');
const backend = app.isPackaged ? path.join(process.resourcesPath, 'python') : project;
const python = app.isPackaged ? path.join(backend, 'python.exe') : 'python.exe';
const renderer = path.join(__dirname, 'renderer');
const url = 'ipa-runner://desktop/index.html';
const pages = new Set(['/index.html', '/app.js', '/systems.js', '/app.css', '/icon.png']);
const smoke = process.argv.includes('--smoke');
const minimum = { width: 660, height: 500 };
const downloads = {
  touchhle: 'https://github.com/touchHLE/touchHLE/releases',
  asoftware: 'https://github.com/alpersamur3/asoft-ios/releases',
  android: 'https://developer.android.com/studio/run/managing-avds',
  openharmony: 'https://docs.oniroproject.org/device-development/developer-boards/emulator/',
};

app.setName('TriDock（三栖）');
// Keep the existing Electron profile and Python library across the product rename.
app.setPath('userData', path.join(app.getPath('appData'), 'IPA Runner'));
protocol.registerSchemesAsPrivileged([{ scheme: 'ipa-runner', privileges: { standard: true, secure: true } }]);

function bridge(action, payload = {}) {
  return new Promise((resolve, reject) => {
    const args = ['-X', 'utf8', path.join(backend, 'desktop_bridge.py')];
    if (smoke && process.env.IPA_RUNNER_SMOKE_DATA) args.push('--data-dir', process.env.IPA_RUNNER_SMOKE_DATA);
    args.push(action);
    const child = execFile(python, args, {
      cwd: backend,
      windowsHide: true,
      encoding: 'utf8',
      timeout: action === 'system-extract' ? 0 : 10 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error) {
        const missingPython = app.isPackaged ? '找不到内置 Python，请重新安装 TriDock（三栖）。' : '找不到 Python。请安装 Python 3.10 或更高版本。';
        const message = error.code === 'ENOENT' ? missingPython : stderr.trim() || '后台进程未完成操作。';
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
  for (const action of ['snapshot', 'create', 'remove', 'start', 'stop', 'install', 'catalog', 'inspect', 'archive', 'extract', 'probe']) {
    handle(`system-${action}`, (_event, payload) => bridge(`system-${action}`, payload));
  }
  handle('system-log', async (_event, id) => {
    const file = await bridge('system-log', { id });
    const error = await shell.openPath(file);
    if (error) throw new Error('尚无日志，请先启动系统。');
  });
  handle('system-shortcut', async (_event, id) => {
    const data = await bridge('system-snapshot');
    const entry = data.packages.find(item => item.id === id);
    if (!entry || !/^[a-f0-9]{64}$/.test(id)) throw new Error('找不到该应用记录。');
    const instance = data.instances.find(item => item.id === entry.instance);
    if (instance?.platform === 'ios') throw new Error('现代 iOS 应用请从系统桌面打开。');
    const name = entry.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[. ]+$/g, '').slice(0, 60) || 'App';
    const folder = smoke && process.env.IPA_RUNNER_SMOKE_DATA ? process.env.IPA_RUNNER_SMOKE_DATA : app.getPath('desktop');
    const file = path.join(folder, `${name} (Runner ${id.slice(0, 8)}).lnk`);
    const details = { target: process.execPath, cwd: app.isPackaged ? path.dirname(process.execPath) : project, icon: process.execPath, iconIndex: 0,
      args: `${app.isPackaged ? '' : `"${project}" `}--system-package=${id}`,
      description: `通过 ${instance.name} 打开 ${entry.name}` };
    if (!shell.writeShortcutLink(file, 'create', details)) throw new Error('无法创建桌面快捷方式。');
    if (smoke && shell.readShortcutLink(file).args !== details.args) throw new Error('快捷方式参数校验失败。');
    return '桌面快捷方式已创建。';
  });
  handle('system-browse', async (event, kind) => {
    if (!['home', 'work', 'tool', 'archive', 'destination'].includes(kind)) throw new Error('未知目录类型。');
    const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
      title: { tool: '选择 hdc.exe', archive: '选择完整运行环境 ZIP', destination: '选择解压存放目录（将新建子目录）' }[kind] || '选择已准备的运行环境或数据目录',
      properties: [['tool', 'archive'].includes(kind) ? 'openFile' : 'openDirectory'],
      ...(['tool', 'archive'].includes(kind) ? { filters: [{ name: kind === 'tool' ? 'HDC' : 'ZIP', extensions: [kind === 'tool' ? 'exe' : 'zip'] }] } : {}),
    });
    return canceled ? null : filePaths[0];
  });
  handle('system-import', async (event, values) => {
    if (!values || typeof values.id !== 'string') throw new Error('请选择系统实例。');
    let file = values.path;
    if (!file) {
      const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
        title: '选择应用安装包', properties: ['openFile'],
        filters: [{ name: '应用安装包', extensions: ['apk', 'ipa', 'hap'] }],
      });
      if (canceled) return null;
      file = filePaths[0];
    }
    return bridge('system-import', { id: values.id, path: file });
  });
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
    document.querySelector('#notice').textContent = '';
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
    title: 'TriDock（三栖）',
    backgroundColor: '#f7f8fc',
    icon: path.join(renderer, 'icon.png'),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#f7f8fc', symbolColor: '#383a52', height: 42 },
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: !smoke },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  await window.loadURL(url);
  if (smoke) {
    const checks = await window.webContents.executeJavaScript(`(async () => {
      const deadline = Date.now() + 10000;
      while ((document.body.dataset.ready !== 'true' || document.querySelector('#systems-view').dataset.ready !== 'true') && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 30));
      }
      const search = document.querySelector('#search');
      document.querySelector('#systems-nav').click();
      const systems = !document.querySelector('#systems-view').hidden;
      document.querySelector('#new-system').click();
      const form = !document.querySelector('#system-form').hidden;
      const platform = document.querySelector('#system-platform');
      platform.value = 'ios';
      platform.dispatchEvent(new Event('change'));
      const iosForm = document.querySelector('#system-resources').hidden && !document.querySelector('#system-work-row').hidden;
      platform.value = 'openharmony';
      platform.dispatchEvent(new Event('change'));
      const harmonyForm = !document.querySelector('#system-tool-row').hidden && document.querySelector('#system-target-row').hidden;
      platform.value = 'android';
      platform.dispatchEvent(new Event('change'));
      const androidForm = !document.querySelector('#system-target-row').hidden;
      document.querySelector('#system-cancel').click();
      document.querySelector('#library-nav').click();
      const count = document.querySelectorAll('.app-row').length;
      search.value = '__no_match_ipa__';
      search.dispatchEvent(new Event('input'));
      const filters = !document.querySelector('.app-row');
      search.value = '';
      search.dispatchEvent(new Event('input'));
      document.querySelector('#settings-nav').click();
      const settings = !document.querySelector('#settings-view').hidden;
      document.querySelector('#library-nav').click();
      const branding = document.title === 'TriDock（三栖）' && document.querySelector('.titlebar').textContent.includes('TriDock（三栖）');
      return { branding, ready: document.body.dataset.ready === 'true', systems, form, iosForm, harmonyForm, androidForm, count, filters, settings,
        library: !document.querySelector('#library-view').hidden };
    })()`);
    if (!checks.branding || !checks.ready || !checks.filters || !checks.settings || !checks.library || !checks.systems || !checks.form || !checks.iosForm || !checks.harmonyForm || !checks.androidForm) throw new Error(JSON.stringify(checks));
    if (process.env.IPA_RUNNER_SMOKE_SYSTEM) {
      const definition = JSON.parse(process.env.IPA_RUNNER_SMOKE_SYSTEM);
      if (!process.env.IPA_RUNNER_SMOKE_DATA) throw new Error('System smoke requires a separate data directory.');
      if (process.env.IPA_RUNNER_SMOKE_RUNTIME_ZIP) {
        const zip = process.env.IPA_RUNNER_SMOKE_RUNTIME_ZIP;
        const destination = process.env.IPA_RUNNER_SMOKE_DESTINATION;
        definition.home = await window.webContents.executeJavaScript(`(async () => {
          const info = await window.runner.inspectArchive(${JSON.stringify(zip)});
          if (info.platform !== 'openharmony' || info.files < 8) throw new Error('Archive recognition failed.');
          return window.runner.extractSystem(${JSON.stringify(zip)}, ${JSON.stringify(destination)});
        })()`);
        definition.tool = '';
      }
      const systemResult = await window.webContents.executeJavaScript(`(async () => {
        document.querySelector('#systems-nav').click();
        document.querySelector('#new-system').click();
        const values = ${JSON.stringify(definition)};
        for (const key of ['platform', 'name', 'home', 'tool']) document.querySelector('#system-' + key).value = values[key];
        for (const key of ['work', 'tool', 'target']) document.querySelector('#system-' + key).value = '__previous_environment__';
        document.querySelector('#system-home').dispatchEvent(new Event('input'));
        if (['work', 'tool', 'target'].some(key => document.querySelector('#system-' + key).value)) throw new Error('Changing source must clear previous environment paths.');
        document.querySelector('#system-tool').value = values.tool;
        document.querySelector('#system-platform').dispatchEvent(new Event('change'));
        if (!document.querySelector('#system-save').disabled) throw new Error('Create must be disabled before inspection.');
        document.querySelector('#system-inspect').click();
        const checkDeadline = Date.now() + 15000;
        while (document.querySelector('#system-save').disabled && Date.now() < checkDeadline) await new Promise(r => setTimeout(r, 50));
        if (document.querySelector('#system-save').disabled) throw new Error(document.querySelector('#system-inspection-summary').textContent + document.querySelector('#system-checks').textContent);
        const name = document.querySelector('#system-name');
        name.value += 'x';
        name.dispatchEvent(new Event('input'));
        if (!document.querySelector('#system-save').disabled) throw new Error('Editing must invalidate inspection.');
        name.value = values.name;
        name.dispatchEvent(new Event('input'));
        document.querySelector('#system-inspect').click();
        const recheckDeadline = Date.now() + 15000;
        while (document.querySelector('#system-save').disabled && Date.now() < recheckDeadline) await new Promise(r => setTimeout(r, 50));
        if (document.querySelector('#system-save').disabled) throw new Error('Recheck did not pass.');
        document.querySelector('#system-form').requestSubmit();
        const deadline = Date.now() + 10000;
        while (document.querySelector('#system-detail-name').textContent !== values.name && Date.now() < deadline) await new Promise(r => setTimeout(r, 50));
        return document.querySelector('#system-detail-name').textContent;
      })()`);
      if (systemResult !== definition.name) throw new Error(`Instance creation failed: ${systemResult}`);
      if (process.env.IPA_RUNNER_SMOKE_HAP) await verifyDrop(window.webContents, process.env.IPA_RUNNER_SMOKE_HAP);
      await window.webContents.executeJavaScript(`(async () => {
        const snapshot = await window.runner.systems();
        if (!snapshot.packages.length) throw new Error('Missing package for shortcut smoke.');
        await window.runner.systemShortcut(snapshot.packages[0].id);
      })()`);
    }
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
      if (process.env.IPA_RUNNER_SMOKE_SYSTEM) {
        await window.webContents.executeJavaScript(`(async () => {
          document.querySelector('#new-system').click();
          document.querySelector('#system-inspect').click();
          const deadline = Date.now() + 10000;
          while (document.querySelector('#system-inspect').disabled && Date.now() < deadline) await new Promise(r => setTimeout(r, 50));
          document.querySelector('#system-inspection').scrollIntoView({ block: 'start' });
        })()`);
        window.showInactive();
        await window.webContents.executeJavaScript(`new Promise(resolve => setTimeout(resolve, 500))`);
        await writeFile(process.env.IPA_RUNNER_SMOKE_PNG.replace(/\.png$/i, '-wizard.png'), (await window.webContents.capturePage()).toPNG());
        await window.webContents.executeJavaScript(`document.querySelector('#system-cancel').click()`);
      }
      await window.webContents.executeJavaScript(`document.querySelector('#systems-nav').click()`);
      window.showInactive();
      await window.webContents.executeJavaScript(`new Promise(resolve => setTimeout(resolve, 700))`);
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
    console.log(`Electron smoke passed · ${checks.count} initial app(s) · system forms, search, navigation and layout`);
    app.exit(0);
    return;
  }
  window.show();
  void launchShortcut(process.argv);
}

async function launchShortcut(args) {
  const id = args.map(value => /^--system-package=([a-f0-9]{64})$/.exec(value)?.[1]).find(Boolean);
  if (!id) return;
  try { await bridge('system-install', { id, launch: true }); }
  catch (error) { dialog.showErrorBox('应用启动失败', error.message); }
}

if (!smoke && !app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv) => {
    const window = BrowserWindow.getAllWindows()[0];
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.focus();
    void launchShortcut(argv);
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
    else dialog.showErrorBox('TriDock（三栖）', error.message);
    app.exit(1);
  });
}
