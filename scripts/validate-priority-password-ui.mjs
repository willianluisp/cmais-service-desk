/** Exercise the real Django views against pytest's disposable live server.
 * All non-localhost requests are blocked; never connect to a real deployment.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.env.SEC_UI_URL;
assert.ok(/^http:\/\/localhost:\d+$/.test(base), 'Only disposable localhost server allowed');
const output = path.join(root, '.tmp/priority-password-ui');
const profile = path.join(output, `browser-${Date.now()}`);
await mkdir(profile, {recursive: true});
const browser = spawn(process.env.EDGE_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
  '--disable-component-update', '--disable-extensions', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank',
], {windowsHide: true, stdio: 'ignore'});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let sequence = 0;
const pending = new Map();
const errors = [];
let postCount = 0;
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => {pending.delete(id); reject(new Error(`CDP timeout: ${method}`));}, 15000);
  pending.set(id, {resolve: value => {clearTimeout(timer); resolve(value);}, reject});
  socket.send(JSON.stringify({id, method, params}));
});
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + JSON.stringify(result.exceptionDetails.exception));
  return result.result.value;
}
async function until(expression) {
  for (let i = 0; i < 150; i++) {if (await evaluate(expression)) return; await delay(60);}
  throw new Error(`Condition not reached: ${expression}; current path: ${await evaluate('location.pathname')}; browser exceptions: ${JSON.stringify(errors)}`);
}
async function navigate(url) {
  await call('Page.navigate', {url: base + url});
  await until(`document.readyState === 'complete' && location.pathname === ${JSON.stringify(url)}`);
}
const set = (selector, value) => evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); e.value=${JSON.stringify(value)}; e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
async function screenshot(name) {
  await evaluate('window.scrollTo(0,0)');
  await delay(100);
  const {data} = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(output, name + '.png'), Buffer.from(data, 'base64'));
}
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break;}
    catch {await delay(100);}
  }
  assert.ok(port, 'Edge did not start');
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    if (message.id) {
      const item = pending.get(message.id); pending.delete(message.id);
      if (message.error) item?.reject(new Error(JSON.stringify(message.error))); else item?.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(JSON.stringify(message.params.exceptionDetails));
    else if (message.method === 'Page.javascriptDialogOpening') call('Page.handleJavaScriptDialog', {accept: true}).catch(error => errors.push(String(error)));
    else if (message.method === 'Fetch.requestPaused') (async () => {
      const {requestId, request} = message.params;
      if(request.method === 'POST') postCount++;
      const url = new URL(request.url);
      if (url.origin !== base) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      if (!url.pathname.startsWith('/static/')) return call('Fetch.continueRequest', {requestId});
      const directory = path.join(root, 'static');
      const filename = path.resolve(directory, url.pathname.slice('/static/'.length));
      if (!filename.startsWith(directory + path.sep)) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      const body = await readFile(filename).catch(error => {
        if (error.code === 'ENOENT' && url.pathname.startsWith('/static/admin/')) {
          return readFile(path.join(process.env.SEC_UI_DJANGO_STATIC, url.pathname.slice('/static/'.length)));
        }
        throw error;
      });
      const mime = {'.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon'}[path.extname(filename)] || 'application/octet-stream';
      return call('Fetch.fulfillRequest', {requestId, responseCode:200, responseHeaders:[{name:'Content-Type', value:mime}], body:body.toString('base64')});
    })().catch(error => {if (!String(error).includes('Invalid InterceptionId')) errors.push(String(error));});
  };
  await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
  await call('Fetch.enable', {patterns:[{urlPattern:'*'}]});
  await call('Network.setCookie', {name:process.env.SEC_UI_COOKIE_NAME, value:process.env.SEC_UI_SESSION, url:base, httpOnly:true, sameSite:'Lax'});
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});

  const cookie = value => call('Network.setCookie', {name:process.env.SEC_UI_COOKIE_NAME, value, url:base, httpOnly:true, sameSite:'Lax'});
  async function checkPasswords(expected) {
    await until(`document.querySelectorAll('[data-password-toggle]').length === ${expected}`);
    const passwords = await evaluate(`Array.from(document.querySelectorAll('input[type=password]')).map(input => input.id)`);
    assert.equal(passwords.length, expected);
    const before = postCount;
    const storageBefore = await evaluate('JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])');
    for (const id of passwords) {
      const selector = '#' + id;
      await set(selector, 'Synthetic-only-482');
      const autocomplete = await evaluate(`document.querySelector(${JSON.stringify(selector)}).autocomplete`);
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
      const button = `[data-password-toggle="${id}"]`;
      await evaluate(`document.querySelector(${JSON.stringify(button)}).scrollIntoView({block:'center'});document.getElementById(${JSON.stringify(id)}).focus();document.getElementById(${JSON.stringify(id)}).setSelectionRange(2,5)`);
      const point = await evaluate(`(() => {const r=document.querySelector(${JSON.stringify(button)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
      await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
      await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
      assert.ok(await evaluate(`document.getElementById(${JSON.stringify(id)}).type === 'text' && document.getElementById(${JSON.stringify(id)}).value === 'Synthetic-only-482'`), 'Show keeps value');
      assert.ok(await evaluate(`document.activeElement === document.getElementById(${JSON.stringify(id)}) && document.activeElement.selectionStart === 2 && document.activeElement.selectionEnd === 5`), 'Pointer keeps focus and selection');
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(button)}).getAttribute('aria-pressed')`), 'true');
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(button)}).getAttribute('type')`), 'button');
      await evaluate(`document.querySelector(${JSON.stringify(button)}).focus()`);
      await call('Input.dispatchKeyEvent', {type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await call('Input.dispatchKeyEvent', {type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
      assert.ok(await evaluate(`document.getElementById(${JSON.stringify(id)}).type === 'password' && document.getElementById(${JSON.stringify(id)}).value === 'Synthetic-only-482'`), 'Hide keeps value');
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(button)}).getAttribute('aria-pressed')`), 'false');
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).autocomplete`), autocomplete);
    }
    assert.equal(postCount, before, 'Toggle cannot submit');
    assert.ok(await evaluate('JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])') === storageBefore, 'No password storage changes');
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page must fit viewport');
  }
  // Administrative configuration immediately after audience, persisted and editable.
  await navigate('/administracao/formularios/novo/');
  await set('#id_title', 'Prioridade administrativa fictícia');
  assert.ok(await evaluate(`document.querySelector('#id_audience').closest('.form-wide').nextElementSibling.contains(document.querySelector('#id_default_priority'))`));
  assert.equal(await evaluate(`document.querySelector('[data-add-field=priority]') === null`), true);
  await set('#id_default_priority', 'ALTA');
  await click('button[name=action][value=publish]');
  await until(`document.querySelector('.form-status')?.textContent.trim() === 'Publicado'`);
  assert.equal(await evaluate(`document.querySelector('#id_default_priority').value`), 'ALTA');
  await call('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});
  await set('#id_default_priority', 'CRITICA');
  await screenshot('priority-editor-mobile');
  await click('button[name=action][value=publish]');
  await until(`document.readyState === 'complete' && document.querySelector('#id_default_priority')?.value === 'CRITICA'`);

  await call('Network.clearBrowserCookies');
  await navigate('/login/');
  await checkPasswords(1);
  await screenshot('login-password-mobile');
  await cookie(process.env.SEC_UI_FIRST_SESSION);
  await navigate('/conta/senha/');
  await checkPasswords(2);
  await screenshot('first-access-password-mobile');
  await cookie(process.env.SEC_UI_SESSION);
  await navigate('/conta/senha/');
  await checkPasswords(3);
  await screenshot('change-password-mobile');
  await call('Emulation.setDeviceMetricsOverride', {width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await navigate('/admin/auth/user/add/');
  await checkPasswords(1);
  await screenshot('admin-password-desktop');
  await navigate('/admin/auth/user/' + process.env.SEC_UI_ADMIN_ID + '/password/');
  await checkPasswords(2);
  await call('Page.navigate', {url:base+process.env.SEC_UI_RESET_PATH});
  await until(`document.readyState === 'complete' && document.querySelectorAll('input[type=password]').length === 2`);
  await checkPasswords(2);
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log('Priority editor and password toggles passed: login, first access, change, admin add/reset and token reset, keyboard, mobile, no submissions or storage.');
} finally {socket?.close();browser.kill();}
