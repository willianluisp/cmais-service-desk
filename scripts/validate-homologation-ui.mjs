/** Synthetic HTML only. Requires Node 22+ and local Edge; no npm packages.
 * Capture first with PORTAL_UI_CAPTURE_DIR=.tmp/ui-preview and pytest
 * tests/test_homologation_improvements.py tests/test_employee_experience.py.
 * Every page request is intercepted; no real portal or Microsoft is contacted.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const captures = path.join(root, '.tmp/ui-preview');
const output = path.join(root, '.tmp/homologation-ui');
const profile = path.join(output, `browser-${Date.now()}`);
await mkdir(profile, {recursive: true});
const executable = process.env.EDGE_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = spawn(executable, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
  '--disable-component-update', '--disable-extensions', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank',
], {windowsHide: true, stdio: 'ignore'});
let socket;
const pending = new Map();
const errors = [];
const posts = [];
const dialogs = [];
let sequence = 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
  pending.set(id, {resolve: value => {clearTimeout(timer); resolve(value);}, reject});
  socket.send(JSON.stringify({id, method, params}));
});
const mime = filename => ({'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.ico': 'image/x-icon', '.jpg': 'image/jpeg', '.webp': 'image/webp'})[path.extname(filename)] || 'text/html';
async function intercept({requestId, request}) {
  try {
    const url = new URL(request.url);
    if (request.method !== 'GET') posts.push(url.pathname);
    let filename;
    if (url.origin === 'http://localhost:8010' && request.method === 'GET') {
      if (/^\/preview\/[a-z-]+$/.test(url.pathname)) {
        filename = path.join(captures, `${url.pathname.split('/').at(-1)}.html`);
      } else if (url.pathname === '/admin/jsi18n/') {
        filename = path.join(captures, 'admin-jsi18n.js');
      } else if (url.pathname === '/admin/auth/user/') {
        filename = path.join(captures, 'admin-list.html');
      } else if (url.pathname.startsWith('/static/')) {
        const base = url.pathname.startsWith('/static/admin/')
          ? path.join(root, '.venv/Lib/site-packages/django/contrib/admin/static')
          : path.join(root, 'static');
        filename = path.resolve(base, url.pathname.slice('/static/'.length));
        if (!filename.startsWith(base + path.sep)) filename = undefined;
      }
    }
    if (!filename) return await call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
    const body = await readFile(filename);
    await call('Fetch.fulfillRequest', {requestId, responseCode: 200,
      responseHeaders: [{name: 'Content-Type', value: `${mime(filename)}; charset=utf-8`},
        {name: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'"}],
      body: body.toString('base64')});
  } catch (error) {
    errors.push(String(error));
    await call('Fetch.failRequest', {requestId, errorReason: 'Failed'});
  }
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function navigate(name) {
  await call('Page.navigate', {url: `http://localhost:8010/preview/${name}`});
  for (let i = 0; i < 100; i++) {
    if (await evaluate(`document.readyState === 'complete' && location.pathname === '/preview/${name}'`)) return;
    await delay(50);
  }
  throw new Error(`Page did not load: ${name}`);
}
const fill = (id, value) => evaluate(`(() => {const e = document.getElementById(${JSON.stringify(id)}); e.value = ${JSON.stringify(value)}; e.dispatchEvent(new Event('input', {bubbles:true}));})()`);
const unsaved = () => evaluate(`(() => {const e = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(e); return e.defaultPrevented;})()`);
async function confirmExit() {
  const before = dialogs.length;
  await evaluate(`document.querySelector('.submit-row .closelink').click()`);
  for (let i = 0; i < 100; i++) {
    if (await evaluate(`location.pathname === '/admin/auth/user/' && document.readyState === 'complete'`)) break;
    await delay(50);
  }
  assert.equal(await evaluate('location.pathname'), '/admin/auth/user/');
  assert.ok(dialogs.slice(before).includes('beforeunload'), 'Leaving a dirty form requires confirmation');
}
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; }
    catch { await delay(100); }
  }
  assert.ok(port, 'Edge did not start');
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    if (message.id) {
      const item = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) item?.reject(new Error(JSON.stringify(message.error)));
      else item?.resolve(message.result);
    } else if (message.method === 'Fetch.requestPaused') {
      intercept(message.params).catch(error => errors.push(String(error)));
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push(JSON.stringify(message.params.exceptionDetails));
    } else if (message.method === 'Page.javascriptDialogOpening') {
      dialogs.push(message.params.type);
      call('Page.handleJavaScriptDialog', {accept: true}).catch(error => errors.push(String(error)));
    }
  };
  await call('Page.enable');
  await call('Runtime.enable');
  if (process.argv.includes('--generate-favicons')) {
    // Raster exports of the supplied symbol, preserving its proportions.
    const svg = (await readFile(path.join(root, 'static/brand/cmais-icone.svg'))).toString('base64');
    const pngs = [];
    for (const size of [16, 32, 48, 180]) {
      const encoded = await evaluate(`new Promise((resolve, reject) => {
        const image = new Image(); image.onload = () => {
          const canvas = document.createElement('canvas'); canvas.width = canvas.height = ${size};
          const context = canvas.getContext('2d');
          if (${size} === 180) {context.fillStyle = '#ffffff'; context.fillRect(0, 0, ${size}, ${size});}
          context.drawImage(image, 0, 0, ${size}, ${size}); resolve(canvas.toDataURL('image/png').split(',')[1]);
        }; image.onerror = reject; image.src = 'data:image/svg+xml;base64,${svg}';
      })`);
      const png = Buffer.from(encoded, 'base64');
      if (size === 32) await writeFile(path.join(root, 'static/brand/cmais-favicon-32.png'), png);
      if (size === 180) await writeFile(path.join(root, 'static/brand/cmais-touch-180.png'), png);
      else pngs.push({size, png});
    }
    const header = Buffer.alloc(6 + pngs.length * 16);
    header.writeUInt16LE(1, 2); header.writeUInt16LE(pngs.length, 4);
    let offset = header.length;
    pngs.forEach(({size, png}, index) => {
      const entry = 6 + index * 16;
      header[entry] = header[entry + 1] = size;
      header.writeUInt16LE(1, entry + 4); header.writeUInt16LE(32, entry + 6);
      header.writeUInt32LE(png.length, entry + 8); header.writeUInt32LE(offset, entry + 12);
      offset += png.length;
    });
    await writeFile(path.join(root, 'static/brand/cmais-favicon.ico'), Buffer.concat([header, ...pngs.map(item => item.png)]));
    console.log('Exported official C+ symbol: ICO (16/32/48), PNG (32), touch PNG (180).');
  } else {
  await call('Fetch.enable', {patterns: [{urlPattern: '*'}]});
  const screenshots = [];
  for (const [width, height] of [[1440, 1000], [390, 844]]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
    for (const name of ['guest-home', 'employee-home', 'admin-home', 'admin-add', 'admin-edit',
      'admin-list', 'admin-delete', 'integrations', 'create', 'login']) {
      await navigate(name);
      const favicons = await evaluate(`Array.from(document.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"]')).map(i => i.getAttribute('href'))`);
      assert.deepEqual(favicons, ['/static/brand/cmais-favicon.ico', '/static/brand/cmais-favicon-32.png', '/static/brand/cmais-icone.svg', '/static/brand/cmais-touch-180.png'], `Shared favicon: ${name}`);
      if (name === 'admin-add' || name === 'admin-edit') {
        assert.ok(await evaluate(`(() => {const row = document.querySelector('.submit-row'); return row.querySelectorAll('input[type="submit"]').length === 1 && row.querySelector('input[name="_save"]').value === 'Salvar' && row.querySelectorAll('a').length === 1 && row.querySelector('.closelink').textContent === 'Sair sem salvar' && !document.querySelector('[name="_continue"]');})()`), `Only Save and Exit: ${name}`);
      }
      assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), `Overflow: ${name} ${width}`);
      assert.ok(await evaluate(`Array.from(document.querySelectorAll('img[src*="cmais-logo"]')).every(i => i.complete && i.naturalWidth > 0)`), `Logo: ${name}`);
      const filename = `${name}-${width}.png`;
      const shot = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
      await writeFile(path.join(output, filename), Buffer.from(shot.data, 'base64'));
      screenshots.push(filename);
    }
    await navigate('admin-add');
    assert.ok(await evaluate(`Promise.all(Array.from(document.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"]')).map(link => new Promise(resolve => {const image = new Image(); image.onload = () => resolve(image.naturalWidth > 0); image.onerror = () => resolve(false); image.src = link.href;}))).then(results => results.every(Boolean))`), 'Browser must decode every favicon format');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('label')).color`), 'rgb(66, 93, 112)');
    assert.equal(await unsaved(), false);
    await fill('id_first_name', ' Róbson  ');
    await fill('id_last_name', ' Lémes  Silva ');
    assert.equal(await evaluate('document.querySelector("#id_username").value'), 'robson.lemes.silva');
    await fill('id_username', 'login.manual');
    await fill('id_last_name', 'Outro');
    assert.equal(await evaluate('document.querySelector("#id_username").value'), 'login.manual');
    assert.equal(await unsaved(), true);
    await evaluate(`document.querySelector('#user_form').dispatchEvent(new Event('submit', {cancelable: true}))`);
    assert.equal(await unsaved(), false);
    await navigate('admin-add');
    await fill('id_first_name', 'Novo sem salvar');
    await confirmExit();
    await navigate('admin-edit');
    assert.equal(await unsaved(), false);
    await fill('id_first_name', 'Renomeado');
    assert.equal(await evaluate('document.querySelector("#id_username").value'), 'edit.synthetic');
    assert.equal(await unsaved(), true);
    await fill('id_first_name', 'Robson');
    assert.equal(await unsaved(), false);
    await fill('id_last_name', 'Alterado sem salvar');
    await confirmExit();
    await navigate('integrations');
    assert.ok(await evaluate(`Array.from(document.querySelectorAll('main button')).every(b => b.disabled)`));
    await evaluate(`(() => {const f = document.querySelector('form[data-submit-feedback]'); f.addEventListener('submit', e => e.preventDefault()); const b = f.querySelector('button'); b.disabled = false; f.dispatchEvent(new Event('submit', {cancelable: true}));})()`);
    assert.ok(await evaluate(`document.querySelector('form[data-submit-feedback]').getAttribute('aria-busy') === 'true' && document.querySelector('form[data-submit-feedback] button').disabled`));
  }
  assert.deepEqual(posts, [], 'No POST may reach a real server');
  assert.deepEqual(errors, [], 'No runtime errors or missing assets');
  await writeFile(path.join(output, 'results.json'), JSON.stringify({screenshots, posts, errors, dialogs,
    checks: ['desktop/mobile layout', 'brand and favicon formats', 'username normalization/manual/edit', 'save/exit controls', 'unsaved changes and confirmed exit', 'integration disabled/loading']}, null, 2));
  console.log(`UI checks passed; ${screenshots.length} screenshots; no POST or external request. Output: ${output}`);
  }
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  browser.kill();
}
