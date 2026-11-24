const api = window.runner;
const byId = id => document.getElementById(id);
const runtimeName = app => app.modern ? 'iOS 16' : 'touchHLE';
const fields = ['touchhle', 'asoftware', 'asoftwareWork'];

let library = null;
let selected = null;
let busy = false;
let toastTimer;
let statusRequest = 0;
const iconCache = new Map();
const pendingIcons = new WeakMap();
const iconObserver = new IntersectionObserver(entries => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    iconObserver.unobserve(entry.target);
    loadArt(entry.target, pendingIcons.get(entry.target));
  }
}, { root: document.querySelector('.workspace') });

function notify(text, error = false) {
  clearTimeout(toastTimer);
  const feedback = byId('feedback');
  feedback.classList.toggle('error', error);
  byId('notice').textContent = text;
  feedback.hidden = false;
  if (!error) toastTimer = setTimeout(() => { feedback.hidden = true; }, 4200);
}

function setBusy(value) {
  busy = value;
  for (const id of ['import-button', 'run-button', 'app-secondary', 'save-settings', 'display-mode']) byId(id).disabled = value;
}

async function run(task) {
  if (busy) return;
  setBusy(true);
  try {
    await task();
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(false);
  }
}

function view(settings) {
  byId('systems-view').hidden = true;
  byId('systems-nav').removeAttribute('aria-current');
  byId('settings-view').hidden = !settings;
  byId('library-view').hidden = settings;
  for (const [id, active] of [['settings-nav', settings], ['library-nav', !settings]]) {
    if (active) byId(id).setAttribute('aria-current', 'page');
    else byId(id).removeAttribute('aria-current');
  }
  document.querySelector('.workspace').scrollTop = 0;
}

function updateConnections() {
  const { runtimes } = library;
  for (const [id, ready] of [['touchhle', runtimes.touchhleReady], ['ios', runtimes.asoftwareReady]]) {
    byId(`${id}-dot`).classList.toggle('connected', ready);
    byId(`${id}-state`).textContent = ready ? '已连接' : '未连接';
  }
  for (const key of fields) byId(key).value = runtimes[key];
}

async function loadArt(element, app) {
  const key = `${app.bundleId}/${app.revision}`;
  if (!iconCache.has(key)) iconCache.set(key, api.icon(app.bundleId).catch(() => ''));
  const url = await iconCache.get(key);
  if (!url || !element.isConnected || element.dataset.art !== key) return;
  const image = new Image();
  image.alt = '';
  image.addEventListener('load', () => {
    if (element.dataset.art === key) element.replaceChildren(image);
  }, { once: true });
  image.src = url;
}

function art(element, app, lazy = false) {
  element.dataset.art = `${app.bundleId}/${app.revision}`;
  const initial = document.createElement('span');
  initial.textContent = [...app.name.trim()][0]?.toUpperCase() || 'i';
  element.replaceChildren(initial);
  if (lazy) {
    pendingIcons.set(element, app);
    iconObserver.observe(element);
  } else {
    void loadArt(element, app);
  }
}

function createRow(app) {
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'app-row';
  row.dataset.bundle = app.bundleId;
  row.setAttribute('aria-pressed', String(selected?.bundleId === app.bundleId));
  const identity = document.createElement('span');
  identity.className = 'row-identity';
  const icon = document.createElement('span');
  icon.className = 'app-art row-icon';
  icon.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'row-text';
  const name = document.createElement('span');
  name.className = 'row-name';
  name.textContent = app.name;
  const version = document.createElement('span');
  version.className = 'row-version';
  version.textContent = app.version ? `版本 ${app.version}` : app.bundleId;
  text.append(name, version);
  identity.append(icon, text);
  const runtime = document.createElement('span');
  runtime.className = 'row-runtime';
  runtime.textContent = runtimeName(app);
  row.append(identity, runtime);
  row.addEventListener('click', () => selectApp(app));
  row.addEventListener('dblclick', () => runSelected());
  art(icon, app, true);
  return row;
}

function render(preferred = selected?.bundleId) {
  const query = byId('search').value.trim().toLowerCase();
  const apps = library.apps.filter(app => [app.name, app.bundleId].some(value => value.toLowerCase().includes(query)));
  const count = library.apps.length;
  selected = apps.find(app => app.bundleId === preferred) || apps[0] || null;
  byId('app-count').textContent = query ? `找到 ${apps.length} 个应用` : `${count} 个应用`;
  byId('list-message').hidden = apps.length > 0;
  byId('list-message').textContent = count ? '没有匹配的应用。' : '导入一个 IPA 开始。';
  byId('drop-note').hidden = Boolean(query);
  iconObserver.disconnect();
  byId('app-list').replaceChildren(...apps.map(createRow));
  selectApp(selected);
}

function selectApp(app) {
  selected = app;
  for (const row of document.querySelectorAll('.app-row')) row.setAttribute('aria-pressed', String(row.dataset.bundle === app?.bundleId));
  byId('selected-details').hidden = !app;
  byId('no-selection').hidden = Boolean(app);
  if (!app) return;
  byId('app-name').textContent = app.name;
  byId('bundle-id').textContent = app.bundleId;
  byId('runtime-tag').textContent = runtimeName(app);
  byId('app-version').textContent = app.version || '未知';
  byId('app-arch').textContent = app.architectures.join(' / ');
  byId('minimum-os').textContent = app.minimumOs || '未知';
  byId('run-button').textContent = app.modern ? '提交安装' : '启动应用';
  byId('app-secondary').textContent = app.modern ? '打开 iOS 窗口' : '创建桌面快捷方式';
  byId('display-options').hidden = app.modern;
  byId('display-mode').value = app.displayMode || 'window';
  byId('fullscreen-help').hidden = app.displayMode !== 'fullscreen';
  const detailIcon = byId('detail-icon');
  if (detailIcon.dataset.art !== `${app.bundleId}/${app.revision}`) art(detailIcon, app);
  setStatus('');
  void updateStatus();
}

function setStatus(text, error = false) {
  const element = byId('app-status');
  element.textContent = text;
  element.classList.toggle('error', error);
}

async function updateStatus() {
  const app = selected;
  const request = ++statusRequest;
  if (!app) return;
  if (!app.modern) {
    setStatus(library.runtimes.touchhleReady ? '通过 touchHLE 在独立窗口中运行。' : '请在运行时设置中连接 touchHLE。');
    return;
  }
  if (!library.runtimes.asoftwareReady) {
    setStatus('请在运行时设置中连接 ASoftware iOS 16。');
    return;
  }
  try {
    const [status, detail] = await api.status(app.bundleId);
    if (selected === app && request === statusRequest) setStatus(detail ? `${status} · ${detail}` : status, status === '安装失败');
  } catch (error) {
    if (selected === app && request === statusRequest) setStatus(error.message, true);
  }
}

function runSelected() {
  const app = selected;
  if (!app) return;
  void run(async () => {
    if (app.modern) {
      const [status] = await api.enqueue(app.bundleId);
      notify(status === '已安装' ? '该版本已安装。' : '已提交。iOS 窗口运行时会处理安装。');
      await updateStatus();
    } else {
      await api.launch(app.bundleId);
      notify(`已启动 ${app.name}`);
    }
  });
}

function doImport(file) {
  void run(async () => {
    const button = byId('import-button');
    button.setAttribute('aria-busy', 'true');
    try {
      if (file && !file.name.toLowerCase().endsWith('.ipa')) throw new Error('请选择 .ipa 安装包。');
      const bundleId = await (file ? api.importFile(file) : api.pickIpa());
      if (!bundleId) return;
      library = await api.snapshot();
      updateConnections();
      byId('search').value = '';
      view(false);
      render(bundleId);
      document.body.dataset.ready = 'true';
      notify(`已导入 ${selected.name}`);
    } finally {
      button.removeAttribute('aria-busy');
    }
  });
}

byId('library-nav').addEventListener('click', () => view(false));
byId('settings-nav').addEventListener('click', () => view(true));
byId('import-button').addEventListener('click', () => doImport());
byId('search').addEventListener('input', () => { if (library) render(); });
byId('run-button').addEventListener('click', runSelected);
byId('display-mode').addEventListener('change', event => {
  const app = selected;
  if (!app || busy) return;
  const mode = event.target.value;
  void run(async () => {
    try {
      app.displayMode = await api.saveDisplayMode(app.bundleId, mode);
    } finally {
      if (selected === app) {
        byId('display-mode').value = app.displayMode;
        byId('fullscreen-help').hidden = app.displayMode !== 'fullscreen';
      }
    }
  });
});
byId('dismiss').addEventListener('click', () => { byId('feedback').hidden = true; });
byId('open-data').addEventListener('click', () => run(() => api.openData()));
byId('app-secondary').addEventListener('click', () => {
  const app = selected;
  if (!app) return;
  void run(async () => {
    if (app.modern) {
      await api.openIos();
      notify('正在打开 iOS 16。');
    } else {
      await api.shortcut(app.bundleId);
      notify('桌面快捷方式已创建。');
    }
  });
});
for (const button of document.querySelectorAll('[data-browse]')) {
  button.addEventListener('click', () => run(async () => {
    const field = button.dataset.browse;
    const value = await api.browse(field);
    if (value) byId(field).value = value;
  }));
}
for (const button of document.querySelectorAll('[data-download]')) {
  button.addEventListener('click', () => run(() => api.download(button.dataset.download)));
}
byId('settings-form').addEventListener('submit', event => {
  event.preventDefault();
  void run(async () => {
    library = await api.saveSettings(Object.fromEntries(fields.map(key => [key, byId(key).value])));
    updateConnections();
    render();
    document.body.dataset.ready = 'true';
    notify('运行时设置已保存。');
  });
});

const overlay = byId('drop-overlay');
document.addEventListener('dragover', event => {
  event.preventDefault();
  overlay.textContent = !byId('systems-view').hidden ? '松开鼠标以导入到当前系统实例' : '松开鼠标以导入 IPA';
  if (event.dataTransfer?.types.includes('Files') && !busy) overlay.hidden = false;
});
document.addEventListener('dragleave', event => {
  if (!event.relatedTarget) overlay.hidden = true;
});
document.addEventListener('drop', event => {
  if (!byId('systems-view').hidden) return;
  event.preventDefault();
  overlay.hidden = true;
  const files = event.dataTransfer?.files;
  if (files?.length === 1) doImport(files[0]);
  else if (files?.length > 1) notify('请一次拖入一个 IPA。', true);
});
document.addEventListener('keydown', event => {
  if (!event.ctrlKey || event.altKey || event.metaKey) return;
  if (event.key.toLowerCase() === 'o') {
    event.preventDefault();
    if (!byId('systems-view').hidden) byId('system-import').click();
    else doImport();
  }
  if (event.key.toLowerCase() === 'f') {
    event.preventDefault();
    view(false);
    byId('search').focus();
  }
});

void api.snapshot().then(snapshot => {
  library = snapshot;
  updateConnections();
  render();
  document.body.dataset.ready = 'true';
}).catch(error => {
  byId('app-count').textContent = '无法读取应用库';
  notify(error.message, true);
});
setInterval(() => { if (selected?.modern && !byId('library-view').hidden) void updateStatus(); }, 3500);
