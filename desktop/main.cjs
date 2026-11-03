const { app, BrowserWindow, dialog, shell, Menu } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const http = require('node:http');
let backend, win, splash, quitting = false, backendEnded = false;
const dataDir = process.env.DREAMGOODS_DESKTOP_DATA_DIR || path.join(app.getPath('appData'), 'DreamGoodsDesktop');
fs.mkdirSync(path.join(dataDir, 'window'), { recursive: true });
app.setPath('userData', path.join(dataDir, 'window'));
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (win) { win.restore(); win.show(); win.focus(); } });
  app.whenReady().then(start).catch(fail);
}
function status(text) {
  if (!splash || splash.isDestroyed()) {
    splash = new BrowserWindow({ width: 550, height: 260, resizable: false, autoHideMenuBar: true,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  }
  splash.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>DreamGoods</title><body style="background:#15191f;color:#eee;font:17px system-ui;padding:36px"><h1>DreamGoods</h1><p>${text}</p></body>`));
}
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
    { label: 'Файл', submenu: [{ label: 'Открыть папку данных', click: () => shell.openPath(dataDir) }, { role: 'quit', label: 'Выход' }] },
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
  const origin = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 180000;
  while (!await health(`${origin}/api/health`)) {
    if (backendEnded || quitting) return;
    if (Date.now() > deadline) throw new Error('Сервер не запустился за 3 минуты. Подробности в desktop.log.');
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  if (quitting) return;
  win = new BrowserWindow({ width: 1440, height: 960, minWidth: 900, minHeight: 640, show: false, autoHideMenuBar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  win.webContents.setWindowOpenHandler(({ url }) => {
    const u = new URL(url);
    if (u.origin === origin) {
      // Downloads and asset previews remain in the same authenticated session.
      win.webContents.downloadURL(url);
    } else if (['https:', 'http:'].includes(u.protocol)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const u = new URL(url);
    if (u.origin !== origin) { event.preventDefault(); if (['https:', 'http:'].includes(u.protocol)) void shell.openExternal(url); }
  });
  win.webContents.on('will-attach-webview', event => event.preventDefault());
  win.once('ready-to-show', () => { if (splash && !splash.isDestroyed()) splash.destroy(); win.show(); });
  await win.loadURL(`${origin}/studio`);
  // CI verifies an actual packaged window, HTTP API and isolated renderer; no paid calls.
  if (process.env.DREAMGOODS_DESKTOP_SMOKE === '1') {
    const result = await win.webContents.executeJavaScript(`(async () => {
      for(let i=0; i<300 && document.body.innerText.length < 30; i++) await new Promise(r => setTimeout(r,100));
      return {title:document.title, node:typeof require, body:document.body.innerText.length, origin:location.origin};
    })()`);
    fs.appendFileSync(path.join(dataDir, 'desktop.log'), '[desktop smoke] ' + JSON.stringify(result) + '\n');
    if (result.node !== 'undefined' || result.body < 10 || result.origin !== origin) throw new Error('Проверка окна не прошла');
    const project = await win.webContents.executeJavaScript(`(async () => {
      const login = await fetch('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'admin',password:'admin'})});
      if (!login.ok) throw new Error('Local login failed: ' + login.status + ' ' + await login.text());
      const r = await fetch('/api/projects');
      if (!r.ok) throw new Error('Projects API failed: ' + r.status + ' ' + await r.text());
      const body = await r.json();
      const project = body.projects[0];
      if (!project) throw new Error('Default project missing');
      return {id:project.id, name:project.name};
    })()`);
    const marker = path.join(dataDir, 'smoke-project.json');
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
