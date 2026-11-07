const { app, BrowserWindow, dialog, shell, Menu, ipcMain, screen } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const http = require('node:http');
let backend, win, splash, desktopOrigin, workspaceBounds, restoreMaximized = false, windowMode = "login", quitting = false, backendEnded = false;
const dataDir = process.env.DREAMGOODS_DESKTOP_DATA_DIR || path.join(app.getPath('appData'), 'DreamGoodsDesktop');
fs.mkdirSync(path.join(dataDir, 'window'), { recursive: true });
app.setPath('userData', path.join(dataDir, 'window'));
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (win) { win.restore(); win.show(); win.focus(); } });
  app.whenReady().then(start).catch(fail);
}
function roundWindow(window) {
  // Native DWM rounding on Windows 11; a shape fallback keeps Windows 10 rounded too.
  if (process.platform !== 'win32' || Number(os.release().split('.')[2]) >= 22000) return;
  const shape = () => {
    if (window.isDestroyed()) return;
    if (window.isMaximized() || window.isFullScreen()) { window.setShape([]); return; }
    const [width, height] = window.getSize(), radius = 14;
    const rects = [{ x: 0, y: radius, width, height: height - radius * 2 }];
    for (let y = 0; y < radius; y++) {
      const inset = Math.ceil(radius - Math.sqrt(radius ** 2 - (radius - y - .5) ** 2));
      rects.push({ x: inset, y, width: width - 2 * inset, height: 1 },
        { x: inset, y: height - 1 - y, width: width - 2 * inset, height: 1 });
    }
    window.setShape(rects);
  };
  window.on('resize', shape); window.on('maximize', shape); window.on('unmaximize', shape); shape();
}
function status(text) {
  if (!splash || splash.isDestroyed()) {
    splash = new BrowserWindow({ width: 520, height: 280, resizable: false, frame: false, roundedCorners: true,
      backgroundColor: '#f8f7fc', hasShadow: true, autoHideMenuBar: true,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
    roundWindow(splash);
  }
  splash.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>DG Desktop</title><style>body{margin:0;padding:38px;font:14px/1.5 'Segoe UI',sans-serif;color:#242237;background:radial-gradient(at 0 0,#eae4ff,transparent 65%),#f8f7fc;border-radius:14px;app-region:drag}i{font-style:normal;color:#7954dc;font-size:36px}h1{font-size:24px;margin:8px 0}p{color:#777285}progress{width:100%;height:5px;accent-color:#7954dc}</style><i>✦</i><h1>DG Desktop</h1><p>${text}</p><progress></progress>`)).catch(() => {});
}
function trusted(event) {
  return win && !win.isDestroyed() && event.sender === win.webContents && event.senderFrame === win.webContents.mainFrame
    && new URL(event.senderFrame.url).origin === desktopOrigin;
}
ipcMain.handle('dg:window', (event, action) => {
  if (!trusted(event)) throw new Error('Unknown window');
  if (action === 'close') win.close();
  else if (action === 'minimize') win.minimize();
  else if (action === 'maximize' && windowMode === 'workspace') { if (win.isMaximized()) win.unmaximize(); else win.maximize(); }
});
async function dataInfo() {
  const result = await dialog.showMessageBox(win, { type: 'info', title: 'Обновление DreamGoods',
    message: `DreamGoods ${app.getVersion()}`, detail: 'Закройте приложение и запустите установщик новой версии. Удалять текущую версию перед обновлением не нужно.\n\nПроекты, фото и настройки хранятся отдельно и сохраняются также при удалении программы. Перед обновлением базы создаётся копия в backups.\n\nДля полной резервной копии закройте DreamGoods и скопируйте всю папку:\n' + dataDir,
    buttons: ['Понятно', 'Папка данных', 'Резервные копии'], defaultId: 0, cancelId: 0 });
  if (result.response === 1) await shell.openPath(dataDir);
  if (result.response === 2) { const folder = path.join(dataDir, 'backups'); fs.mkdirSync(folder, { recursive: true }); await shell.openPath(folder); }
}
ipcMain.handle('dg:data-info', async event => { if (!trusted(event)) throw new Error('Unknown window'); await dataInfo(); });
ipcMain.handle('dg:state', event => {
  if (!trusted(event)) throw new Error('Unknown window');
  return { maximized: win.isMaximized() };
});
ipcMain.handle('dg:mode', (event, mode) => {
  if (!trusted(event) || !['login','workspace'].includes(mode)) throw new Error('Unknown window mode');
  if (windowMode === mode) return;
  windowMode = mode;
  const area = screen.getDisplayMatching(win.getBounds()).workArea;
  if (mode === 'login') {
    workspaceBounds = win.getNormalBounds(); restoreMaximized = win.isMaximized();
    if (restoreMaximized) win.unmaximize();
    win.setMinimumSize(440, 540); win.setSize(Math.min(520, area.width), Math.min(620, area.height));
    win.setResizable(false); win.setMaximizable(false); win.center();
  } else {
    win.setResizable(true); win.setMaximizable(true);
    win.setMinimumSize(Math.min(1040, area.width), Math.min(720, area.height));
    const width = Math.min(workspaceBounds?.width || 1440, area.width);
    const height = Math.min(workspaceBounds?.height || 960, area.height);
    win.setBounds({ x: Math.round(area.x + (area.width - width)/2), y: Math.round(area.y + (area.height - height)/2), width, height });
    if (restoreMaximized) win.maximize();
  }
});

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer(); s.on('error', reject);
    s.listen(0, '127.0.0.1', () => { const port = s.address().port; s.close(() => resolve(port)); });
  });
}
function health(url) {
  return new Promise(resolve => {
    const req = http.get(url, res => { let data = ''; res.on('data', x => data += x); res.on('end', () => {
      try { const json = JSON.parse(data); resolve(res.statusCode === 200 && json.ok && json.version === app.getVersion()); }
      catch { resolve(false); }
    }); });
    req.setTimeout(1000, () => req.destroy()); req.on('error', () => resolve(false));
  });
}
async function start() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Файл', submenu: [{ label: 'Открыть папку данных', click: () => shell.openPath(dataDir) },
      { label: 'Открыть резервные копии', click: () => { const backups = path.join(dataDir, 'backups'); fs.mkdirSync(backups, { recursive: true }); void shell.openPath(backups); } },
      { label: 'Как обновить приложение', click: () => void dataInfo() },
      { role: 'quit', label: 'Выход' }] },
    { label: 'Правка', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: 'Вид', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] }
  ]));
  status('Первый запуск может занять несколько минут. Подготавливаю локальную базу…');
  const port = await freePort();
  const resources = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, 'dev-resources');
  const exe = path.join(resources, 'backend', 'DreamGoodsBackend.exe');
  const log = fs.openSync(path.join(dataDir, 'desktop.log'), 'a');
  backend = spawn(exe, ['--data-dir', dataDir, '--postgres-dir', path.join(resources, 'postgresql'), '--port', String(port)],
    { stdio: ['pipe', log, log], windowsHide: true, cwd: dataDir });
  fs.closeSync(log);
  backend.on('error', error => { backendEnded = true; void fail(error); });
  backend.on('exit', code => {
    backendEnded = true;
    if (quitting) app.exit(process.exitCode || 0);
    else fail(new Error(`Локальный сервер завершился (код ${code}). Журнал: ${path.join(dataDir, 'desktop.log')}`));
  });
  const origin = `http://127.0.0.1:${port}`; desktopOrigin = origin;
  const deadline = Date.now() + 180000;
  while (!await health(`${origin}/api/health`)) {
    if (backendEnded || quitting) return;
    if (Date.now() > deadline) throw new Error('Сервер не запустился за 3 минуты. Подробности в desktop.log.');
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  if (quitting) return;
  win = new BrowserWindow({ width: 520, height: 620, minWidth: 440, minHeight: 540, show: false, frame: false, roundedCorners: true,
    backgroundColor: '#f8f7fc', hasShadow: true, resizable: false, maximizable: false, autoHideMenuBar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.cjs') } });
  roundWindow(win);
  win.webContents.session.setPermissionRequestHandler((wc, permission, callback) => callback(wc === win.webContents && new URL(wc.getURL()).origin === origin && ['notifications', 'clipboard-sanitized-write'].includes(permission)));
  win.webContents.setWindowOpenHandler(({ url }) => {
    const u = new URL(url);
    if (u.origin === origin && u.pathname === '/') { void shell.openExternal(url); }
    else if (u.origin === origin) {
      // Downloads and asset previews remain in the same authenticated session.
      win.webContents.downloadURL(url);
    } else if (['https:', 'http:'].includes(u.protocol)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const u = new URL(url);
    if (u.origin === origin && !u.pathname.startsWith('/api/') && u.pathname !== '/studio') { event.preventDefault(); return; }
    if (u.origin !== origin) { event.preventDefault(); if (['https:', 'http:'].includes(u.protocol)) void shell.openExternal(url); }
  });
  win.webContents.on('will-attach-webview', event => event.preventDefault());
  win.once('ready-to-show', () => { if (splash && !splash.isDestroyed()) splash.destroy(); win.show(); });
  await win.loadURL(`${origin}/studio`);
  // CI verifies an actual packaged window, HTTP API and isolated renderer; no paid calls.
  if (process.env.DREAMGOODS_DESKTOP_SMOKE === '1') {
    const result = await win.webContents.executeJavaScript(`(async () => {
      for(let i=0; i<300 && !document.querySelector('.desktop-login,.topbar'); i++) await new Promise(r => setTimeout(r,100));
      return {title:document.title, node:typeof require, desktop:typeof window.dgDesktop === 'object', ready:!!document.querySelector('.desktop-login,.topbar'), body:document.body.innerText.length, origin:location.origin};
    })()`);
    fs.appendFileSync(path.join(dataDir, 'desktop.log'), '[desktop smoke] ' + JSON.stringify(result) + '\n');
    if (!result.desktop || !result.ready || result.node !== 'undefined' || result.body < 10 || result.origin !== origin) throw new Error('Проверка окна не прошла');
    const retention = path.join(dataDir, 'smoke-retention.json');
    const expectedProject = fs.existsSync(retention) ? JSON.parse(fs.readFileSync(retention, 'utf8')) : null;
    const project = await win.webContents.executeJavaScript(`(async () => {
      const login = await fetch('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'admin',password:'admin'})});
      if (!login.ok) throw new Error('Local login failed: ' + login.status + ' ' + await login.text());
      const r = await fetch('/api/projects');
      if (!r.ok) throw new Error('Projects API failed: ' + r.status + ' ' + await r.text());
      const body = await r.json();
      const expected = ${JSON.stringify(expectedProject)};
      const name = 'Сохранение данных — smoke';
      let project = body.projects.find(p => p.name === name);
      if (expected && (!project || project.id !== expected.id)) throw new Error('User project lost after installer operation');
      if (!project) {
        const created = await fetch('/api/projects', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client:'',name})});
        if (!created.ok) throw new Error('Retention project creation failed');
        project = {...await created.json(),name};
      }
      return {id:project.id, name:project.name};
    })()`);
    await win.webContents.executeJavaScript(`window.dgDesktop.mode('login')`);
    if (win.getSize()[0] > 600 || win.isResizable()) throw new Error('Login window is not compact');
    if (await win.webContents.executeJavaScript(`!!document.querySelector('.desktop-login')`))
      fs.writeFileSync(path.join(dataDir, 'login.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript(`window.dgDesktop.mode('workspace')`);
    if (!win.isResizable()) throw new Error('Workspace is not resizable');
    await win.webContents.executeJavaScript(`window.dgDesktop.maximize()`);
    if (!win.isMaximized()) throw new Error('Maximize button failed');
    await win.webContents.executeJavaScript(`window.dgDesktop.maximize()`);
    if (win.isMaximized()) throw new Error('Restore button failed');
    await new Promise(resolve => { win.webContents.once('did-finish-load', resolve); win.reload(); });
    await win.webContents.executeJavaScript(`(async()=>{ for(let i=0;i<200 && !document.querySelector('.topbar');i++)await new Promise(r=>setTimeout(r,100)); if(!document.querySelector('.desktop-titlebar') || !document.querySelector('.topbar')) throw new Error('Desktop workspace did not render'); })()`);
    await new Promise(resolve => setTimeout(resolve, 600));
    fs.writeFileSync(path.join(dataDir, 'workspace.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript(`document.querySelector('.assistant-launch')?.click()`);
    await new Promise(resolve => setTimeout(resolve, 500));
    fs.writeFileSync(path.join(dataDir, 'assistant.png'), (await win.webContents.capturePage()).toPNG());
    const marker = retention;
    if (fs.existsSync(marker) && JSON.parse(fs.readFileSync(marker, 'utf8')).id !== project.id) throw new Error('Project did not survive restart');
    fs.writeFileSync(marker, JSON.stringify(project));
    fs.writeFileSync(path.join(dataDir, 'smoke.json'), JSON.stringify({ ...result, project }));
    app.quit();
  }
}
async function fail(error) {
  fs.appendFileSync(path.join(dataDir, 'desktop.log'), '[desktop error] ' + (error.stack || String(error)) + '\n');
  if (quitting) return;
  if (process.env.DREAMGOODS_DESKTOP_SMOKE === '1') { console.error(error); process.exitCode = 1; app.quit(); return; }
  dialog.showErrorBox('DreamGoods: ошибка запуска', `${error.message}\n\nВаши данные сохранены. Журналы: ${dataDir}`);
  app.quit();
}
app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (!backend || backendEnded) return;
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  if (win && !win.isDestroyed()) win.hide();
  status('Завершаю текущие запросы и сохраняю базу. Дождитесь закрытия окна…');
  backend.stdin.on('error', () => {});
  backend.stdin.end('shutdown\n');
});
