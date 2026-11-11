/** Exercise the real Django views against pytest's disposable live server.
 * All non-localhost requests are blocked; never connect to a real deployment.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.env.STATUS_UI_URL;
assert.ok(/^http:\/\/localhost:\d+$/.test(base), 'Only disposable localhost server allowed');
const output = path.join(root, '.tmp/ticket-status-ui');
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
const ticket = process.env.STATUS_UI_TICKET;
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
  throw new Error(`Condition not reached: ${expression}`);
}
async function navigate(url) {
  await call('Page.navigate', {url: base + url});
  await until(`document.readyState === 'complete' && location.pathname === ${JSON.stringify(url)}`);
}
const set = (selector, value) => evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); e.value=${JSON.stringify(value)}; e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
async function screenshot(name) {
  const previousScroll = await evaluate('window.scrollY');
  await evaluate('window.scrollTo(0,0)');
  await delay(100);
  const {data} = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(output, name + '.png'), Buffer.from(data, 'base64'));
  await evaluate(`window.scrollTo(0,${previousScroll})`);
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
      const url = new URL(request.url);
      if (url.origin !== base) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      if (url.pathname.includes('/sincronizar/')) {
        return call('Fetch.fulfillRequest', {requestId, responseCode:503,
          responseHeaders:[{name:'Content-Type',value:'text/html'}, {name:'X-Planner-Feedback',value:'error'}],
          body:Buffer.from('<p>Consulta temporariamente indisponível. Tente novamente.</p>').toString('base64')});
      }
      if (!url.pathname.startsWith('/static/')) return call('Fetch.continueRequest', {requestId});
      const directory = path.join(root, 'static');
      const filename = path.resolve(directory, url.pathname.slice('/static/'.length));
      if (!filename.startsWith(directory + path.sep)) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      const body = await readFile(filename);
      const mime = {'.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon'}[path.extname(filename)] || 'application/octet-stream';
      return call('Fetch.fulfillRequest', {requestId, responseCode:200, responseHeaders:[{name:'Content-Type', value:mime}], body:body.toString('base64')});
    })().catch(error => errors.push(String(error)));
  };
  await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
  await call('Fetch.enable', {patterns:[{urlPattern:'*'}]});
  await call('Network.setCookie', {name:process.env.STATUS_UI_COOKIE_NAME, value:process.env.STATUS_UI_SESSION, url:base, httpOnly:true, sameSite:'Lax'});
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await navigate('/chamados/' + ticket + '/');
  for (const width of [1440, 390, 320]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height:900, deviceScaleFactor:1, mobile:width < 600});
    await delay(100);
    const layout = await evaluate(`(() => {
      const button = document.querySelector('#planner-status button');
      const status = document.querySelector('#ticket-status-label');
      const b = button.getBoundingClientRect(), s = status.getBoundingClientRect();
      return {height:b.height, left:b.left, right:b.right, gap:b.top-s.bottom,
        primary:button.classList.contains('button-primary'),
        icon:button.querySelector('use').getAttribute('href'),
        overflow:document.documentElement.scrollWidth > innerWidth};
    })()`);
    assert.ok(layout.height >= 44 && layout.left >= 0 && layout.right <= width);
    assert.ok(layout.gap < 55, 'Refresh must remain near status');
    assert.ok(layout.primary && layout.icon.endsWith('#refresh'));
    assert.equal(layout.overflow, false, 'Page must fit narrow screens');
    await screenshot('detail-' + width);
  }
  await click('#planner-status button');
  await until(`document.querySelector('#planner-feedback').textContent.includes('temporariamente indisponível')`);
  await until(`!document.querySelector('#planner-status button').disabled`);
  assert.ok(await evaluate(`document.querySelector('#ticket-status-label').textContent.length > 0`));
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log('Status UI passed: 1440/390/320px, primary action, refresh icon, nearby status, no overflow, API error feedback.');
} finally {
  socket?.close(); browser.kill();
}
