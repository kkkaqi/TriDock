/* System instances share the existing isolated runner API and visual vocabulary. */
const systemLabels = { android: 'Android', ios: 'iOS', openharmony: 'OpenHarmony' };
const systemExtensions = { android: '.apk', ios: '.ipa', openharmony: '.hap' };
let systemData = { instances: [], packages: [] };
let activeSystem = null;
let systemBusy = false;
let systemRefresh = 0;
let systemCatalog = [];
let inspection = null;
let inspectionFingerprint = '';
let wizardRequest = 0;
let wizardBusy = false;
let archiveBusy = false;
let archiveSource = null;
const wizardFields = ['platform', 'name', 'home', 'target', 'tool', 'work', 'memory', 'cpus'];

function wizardValues() {
  return Object.fromEntries(wizardFields.map(key => [key, byId(`system-${key}`).value]));
}

function syncWizard() {
  const valid = inspection?.canCreate && inspectionFingerprint === JSON.stringify(wizardValues());
  byId('system-save').disabled = systemBusy || wizardBusy || archiveBusy || !valid;
  byId('system-save').textContent = valid ? '创建实例，随后可试启动' : '检查通过后创建实例';
}

function invalidateInspection() {
  wizardRequest++;
  inspection = null;
  inspectionFingerprint = '';
  byId('system-check-hint').textContent = '配置已变更，请检查环境后再创建。';
  syncWizard();
}

function showInspection(report) {
  byId('system-inspection').hidden = false;
  byId('system-inspection-summary').textContent = `${systemLabels[report.platform]} · ${report.architecture} · ${report.version} · ${report.canCreate ? '文件与电脑条件检查通过，系统引导尚未验证' : '存在需要处理的问题'}`;
  const makeRow = check => {
    const row = document.createElement('li');
    row.className = `check-${check.level}`;
    row.textContent = `${{ pass: '通过', warning: '提示', error: '需处理' }[check.level]} · ${check.title}：${check.message}`;
    return row;
  };
  const storage = document.createElement('li');
  storage.textContent = `磁盘可用 ${report.freeBytes == null ? '未知' : (report.freeBytes / 1024 ** 3).toFixed(1) + ' GB'} · 首次实例数据预留至少 ${(report.requiredBytes / 1024 ** 3).toFixed(2)} GB，后续应用与数据另计。`;
  const passed = report.checks.filter(check => check.level === 'pass');
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = `${passed.length} 项检查通过 · 展开详情`;
  const rows = document.createElement('ul');
  rows.className = 'system-checks';
  rows.append(...passed.map(makeRow));
  details.append(summary, rows);
  const holder = document.createElement('li');
  holder.append(details);
  byId('system-checks').replaceChildren(storage, ...report.checks.filter(check => check.level !== 'pass').map(makeRow), holder);
}

async function inspectWizard() {
  if (wizardBusy || archiveBusy) return;
  wizardBusy = true;
  const request = ++wizardRequest;
  byId('system-inspect').disabled = true;
  byId('system-inspect').textContent = '正在检查本地文件与电脑条件…';
  syncWizard();
  try {
    let report = await api.inspectSystem(wizardValues());
    if (request !== wizardRequest) return;
    if (report.platform !== byId('system-platform').value) {
      byId('system-platform').value = report.platform;
      // The backend requires matching platform confirmation; inspect again with the detected value.
      report = await api.inspectSystem(wizardValues());
      if (request !== wizardRequest) return;
    }
    for (const key of ['home', 'target', 'tool', 'work']) {
      if (report.values[key]) byId(`system-${key}`).value = report.values[key];
    }
    byId('system-target-row').hidden = report.platform !== 'android';
    byId('system-tool-row').hidden = report.platform !== 'openharmony';
    byId('system-work-row').hidden = report.platform !== 'ios';
    byId('system-resources').hidden = report.platform === 'ios';
    const options = report.devices.map(device => new Option(`${device.name} · ${device.version} · ${device.architecture}`, device.name));
    byId('system-avd-choice').replaceChildren(...(options.length ? options : [new Option('未找到 AVD，请先创建后重新检查', '')]));
    byId('system-avd-choice').disabled = !options.length;
    byId('system-avd-choice').value = report.values.target || '';
    if (!byId('system-name').value.trim()) byId('system-name').value = `${systemLabels[report.platform]} 测试机`;
    inspection = report;
    inspectionFingerprint = JSON.stringify(wizardValues());
    byId('system-check-hint').textContent = report.canCreate ? '检查完成。创建不会下载系统，也不会启动系统。' : '按上方提示补齐环境后重新检查。';
    showInspection(report);
    byId('system-inspection').scrollIntoView({ block: 'nearest' });
  } catch (error) {
    inspection = null;
    byId('system-inspection').hidden = false;
    byId('system-inspection-summary').textContent = error.message;
    byId('system-checks').replaceChildren();
    notify(error.message, true);
  } finally {
    wizardBusy = false;
    byId('system-inspect').disabled = false;
    byId('system-inspect').textContent = '检查环境并自动配置';
    syncWizard();
  }
}

function openSystems() {
  view(false);
  byId('library-view').hidden = true;
  byId('systems-view').hidden = false;
  byId('library-nav').removeAttribute('aria-current');
  byId('systems-nav').setAttribute('aria-current', 'page');
  void refreshSystems().catch(error => notify(error.message, true));
}

function systemPlatformChanged() {
  invalidateInspection();
  const platform = byId('system-platform').value;
  byId('system-target-row').hidden = platform !== 'android';
  byId('system-target').required = false;
  byId('system-tool-row').hidden = platform !== 'openharmony';
  byId('system-tool').required = false;
  byId('system-work-row').hidden = platform !== 'ios';
  byId('system-resources').hidden = platform === 'ios';
  byId('system-help').textContent = {
    android: '先在 Android Studio 中下载系统镜像并创建 AVD。这里选择 Android SDK 根目录，需包含 Emulator、Platform-Tools 和 Build-Tools。',
    ios: '选择已部署的 ASoftware iOS 16 目录，需包含 Start-iOS.cmd。IPA 需要兼容的 ARM64 应用。CPU 与内存使用该运行环境自己的设置。',
    openharmony: '下载并解压 Oniro x86_64 镜像，选择包含 run.bat、run.sh、bzImage 和 system.img 的目录。需预先安装 QEMU、Git Bash 及 OpenHarmony SDK。',
  }[platform];
  const profile = systemCatalog.find(item => item.id === platform);
  if (profile) {
    byId('system-help').textContent = profile.instructions;
    byId('system-compatibility').textContent = profile.compatibility;
  }
}

async function refreshSystems() {
  const request = ++systemRefresh;
  const data = await api.systems();
  if (request !== systemRefresh) return;
  systemData = data;
  if (!systemData.instances.some(item => item.id === activeSystem)) activeSystem = systemData.instances[0]?.id || null;
  renderSystems();
  byId('systems-view').dataset.ready = 'true';
}

function renderSystems() {
  const container = byId('system-list');
  const rows = systemData.instances.map(item => {
    const button = document.createElement('button');
    button.className = 'system-row';
    button.type = 'button';
    button.setAttribute('aria-pressed', String(item.id === activeSystem));
    const title = document.createElement('strong');
    title.textContent = item.name;
    const info = document.createElement('span');
    info.textContent = `${systemLabels[item.platform]} · ${item.state}`;
    button.append(title, info);
    button.addEventListener('click', () => { if (!systemBusy) { activeSystem = item.id; renderSystems(); } });
    return button;
  });
  container.replaceChildren(...rows);
  byId('system-message').hidden = rows.length > 0;
  byId('system-message').textContent = '尚未添加系统。点击“添加系统”，查看下载说明并导入你准备的运行环境。';
  const item = systemData.instances.find(x => x.id === activeSystem);
  byId('system-detail').hidden = !item;
  if (!item) return;
  byId('system-detail-name').textContent = item.name;
  byId('system-detail-info').textContent = `${systemLabels[item.platform]} · ${item.state} · ${item.platform === 'ios' ? '资源由运行环境管理' : `${item.memory} MB / ${item.cpus} 核`}`;
  byId('system-path').textContent = `运行目录：${item.home}${item.device ? ` · 设备：${item.device}` : ''}${item.freeBytes != null ? ` · 所在磁盘可用 ${(item.freeBytes / 1024 ** 3).toFixed(1)} GB` : ''}`;
  byId('system-start').disabled = systemBusy || item.state === '运行中';
  byId('system-stop').disabled = item.state !== '运行中';
  byId('system-probe').disabled = systemBusy || item.state !== '运行中';
  byId('system-remove').disabled = systemBusy || item.state === '运行中';
  const packages = systemData.packages.filter(x => x.instance === item.id);
  byId('system-apps-empty').textContent = packages.length ? '' : `拖入 ${systemExtensions[item.platform]} 文件，或点击“导入应用”。安装与启动会自动打开系统并等待其就绪。`;
  byId('system-packages').replaceChildren(...packages.map(app => {
    const row = document.createElement('div');
    row.className = 'system-package';
    const text = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = app.name;
    const detail = document.createElement('p');
    detail.className = 'caption';
    detail.textContent = `${app.bundleId} · ${app.state}${app.detail ? ` · ${app.detail}` : ''}`;
    text.append(title, detail);
    const button = document.createElement('button');
    button.className = 'button secondary';
    button.textContent = item.platform === 'ios' ? '提交安装 / 打开系统' : '安装并启动';
    button.disabled = systemBusy;
    button.addEventListener('click', () => void systemTask(async () => {
      byId('system-operation').textContent = '正在启动系统、等待就绪并安装应用，首次引导可能需要几分钟…';
      return api.installPackage(app.id, true);
    }));
    row.append(text, button);
    if (item.platform !== 'ios') {
      const shortcut = document.createElement('button');
      shortcut.className = 'link';
      shortcut.textContent = '桌面快捷方式';
      shortcut.disabled = systemBusy;
      shortcut.addEventListener('click', () => void systemTask(() => api.systemShortcut(app.id)));
      row.append(shortcut);
    }
    return row;
  }));
}

async function systemTask(task) {
  if (systemBusy) return;
  systemBusy = true;
  for (const id of ['system-save', 'new-system', 'system-import']) byId(id).disabled = true;
  renderSystems();
  try {
    const message = await task();
    if (typeof message === 'string') {
      byId('system-operation').textContent = message;
      notify(message);
    }
  } catch (error) {
    byId('system-operation').textContent = error.message;
    notify(error.message, true);
  } finally {
    systemBusy = false;
    for (const id of ['system-save', 'new-system', 'system-import']) byId(id).disabled = false;
    syncWizard();
    await refreshSystems().catch(error => notify(error.message, true));
  }
}

async function importSystemPackage(file) {
  if (!activeSystem) { notify('请先添加并选择系统实例。', true); return; }
  await systemTask(async () => {
    const app = await api.importPackage(activeSystem, file);
    return app ? `已导入 ${app.name}，点击“安装并启动”继续。` : null;
  });
}

byId('systems-nav').addEventListener('click', openSystems);
byId('new-system').addEventListener('click', () => { byId('system-form').hidden = false; byId('system-name').focus(); });
byId('system-cancel').addEventListener('click', () => { byId('system-form').hidden = true; });
byId('system-platform').addEventListener('change', systemPlatformChanged);
for (const key of wizardFields) byId(`system-${key}`).addEventListener('input', () => {
  invalidateInspection();
  if (key === 'home') {
    byId('system-target').value = '';
    byId('system-work').value = '';
    byId('system-tool').value = '';
    byId('system-avd-choice').replaceChildren(new Option('检查目录后自动列出 AVD', ''));
    byId('system-avd-choice').disabled = true;
  }
});
byId('system-avd-choice').addEventListener('change', () => {
  byId('system-target').value = byId('system-avd-choice').value;
  invalidateInspection();
});
byId('system-inspect').addEventListener('click', () => void inspectWizard());
byId('system-zip').addEventListener('click', async () => {
  try {
    const path = await api.browseSystem('archive');
    if (!path) return;
    invalidateInspection();
    archiveSource = await api.inspectArchive(path);
    byId('system-archive-panel').hidden = false;
    byId('system-archive-info').textContent = `${path} · 识别：${systemLabels[archiveSource.platform] || '未知'} · 展开约 ${(archiveSource.unpackedBytes / 1024 ** 3).toFixed(2)} GB。尚未解压或执行脚本。`;
  } catch (error) { archiveSource = null; byId('system-archive-panel').hidden = true; notify(error.message, true); }
});
byId('system-extract').addEventListener('click', async () => {
  if (!archiveSource || wizardBusy || archiveBusy) return;
  const source = archiveSource;
  try {
    const destination = await api.browseSystem('destination');
    if (!destination) return;
    archiveBusy = true;
    syncWizard();
    byId('system-form').querySelector('fieldset').disabled = true;
    byId('system-inspect').disabled = true;
    byId('system-cancel').disabled = true;
    byId('system-extract').disabled = true;
    byId('system-zip').disabled = true;
    byId('system-extract').textContent = '正在解压，请稍候…';
    const home = await api.extractSystem(source.path, destination);
    byId('system-home').value = home;
    byId('system-home').dispatchEvent(new Event('input'));
    if (systemLabels[source.platform]) byId('system-platform').value = source.platform;
    systemPlatformChanged();
    byId('system-archive-panel').hidden = true;
    notify('已解压到新的子目录，正在检查环境。');
    archiveBusy = false;
    await inspectWizard();
  } catch (error) { notify(error.message, true); }
  finally {
    archiveBusy = false;
    byId('system-form').querySelector('fieldset').disabled = false;
    byId('system-inspect').disabled = false;
    byId('system-cancel').disabled = false;
    byId('system-extract').disabled = false;
    byId('system-zip').disabled = false;
    byId('system-extract').textContent = '选择存放目录并解压';
    syncWizard();
  }
});
byId('system-download').addEventListener('click', () => {
  const platform = byId('system-platform').value;
  void api.download(platform === 'ios' ? 'asoftware' : platform).catch(error => notify(error.message, true));
});
for (const button of document.querySelectorAll('[data-system-browse]')) {
  button.addEventListener('click', async () => {
    try {
      const key = button.dataset.systemBrowse;
      const value = await api.browseSystem(key);
      if (value) {
        byId(`system-${key}`).value = value;
        byId(`system-${key}`).dispatchEvent(new Event('input'));
        if (key === 'home') await inspectWizard();
      }
    } catch (error) { notify(error.message, true); }
  });
}
byId('system-form').addEventListener('submit', event => {
  event.preventDefault();
  const values = wizardValues();
  if (!inspection?.canCreate || inspectionFingerprint !== JSON.stringify(values)) {
    notify('请先检查环境，配置变更后需要重新检查。', true);
    return;
  }
  void systemTask(async () => {
    const item = await api.createSystem({ ...values, guided: true });
    activeSystem = item.id;
    byId('system-form').hidden = true;
    return '实例已添加，镜像保留在原目录。';
  });
});
byId('system-start').addEventListener('click', () => void systemTask(async () => {
  await api.startSystem(activeSystem);
  return (await api.probeSystem(activeSystem)).message;
}));
byId('system-probe').addEventListener('click', () => void systemTask(async () => (await api.probeSystem(activeSystem)).message));
// Stop remains available while install waits for boot; it uses its own IPC request.
byId('system-stop').addEventListener('click', async () => {
  byId('system-stop').disabled = true;
  try { await api.stopSystem(activeSystem); notify('系统已关闭。'); }
  catch (error) { notify(error.message, true); }
  finally { await refreshSystems().catch(error => notify(error.message, true)); }
});
byId('system-log').addEventListener('click', () => void api.systemLog(activeSystem).catch(error => notify(error.message, true)));
byId('system-remove').addEventListener('click', () => void systemTask(async () => {
  await api.removeSystem(activeSystem);
  return '管理记录已移除。原镜像、应用包和用户数据已保留。';
}));
byId('system-import').addEventListener('click', () => void importSystemPackage());
document.addEventListener('drop', event => {
  if (byId('systems-view').hidden) return;
  event.preventDefault();
  byId('drop-overlay').hidden = true;
  const files = event.dataTransfer?.files;
  if (files?.length === 1) void importSystemPackage(files[0]);
  else notify('请一次拖入一个应用包。', true);
});
systemPlatformChanged();
void api.systemCatalog().then(catalog => {
  systemCatalog = catalog;
  const profile = catalog.find(item => item.id === byId('system-platform').value);
  if (profile) {
    byId('system-help').textContent = profile.instructions;
    byId('system-compatibility').textContent = profile.compatibility;
  }
}).catch(error => notify(error.message, true));
openSystems();
setInterval(() => {
  if (!byId('systems-view').hidden) void refreshSystems().catch(() => {});
}, 5000);
