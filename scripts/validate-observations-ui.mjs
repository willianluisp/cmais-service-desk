/** Exercise the real Django views against pytest's disposable live server.
 * All non-localhost requests are blocked; never connect to a real deployment.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.env.OBS_UI_URL;
assert.ok(/^http:\/\/localhost:\d+$/.test(base), 'Only disposable localhost server allowed');
const output = path.join(root, '.tmp/observations-ui');
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
let stage = 1;
const ticket = process.env.OBS_UI_TICKET;
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
      if (url.pathname.includes('/observacoes/')) {
        const ids = stage === 0 ? [] : Array.from({length: stage}, (_, i) => 'm' + (i+1));
        const payload = url.pathname.endsWith('/resumos/') ? {tickets: {[ticket]: {ids, complete: true}}, pending: false} :
          {complete:true, available:true, messages: ids.map((id,i) => ({id, author:'Equipe TI fictícia', created_at:'2026-11-10T10:00:00Z', content: i === 0 ? 'Mensagem sem prefixo. <script>window.attacked=true</script>' : 'Nova observação do suporte.'}))};
        if (stage === -1) return call('Fetch.fulfillRequest', {requestId, responseCode:503, body:''});
        return call('Fetch.fulfillRequest', {requestId, responseCode:200, responseHeaders:[{name:'Content-Type',value:'application/json'}], body:Buffer.from(JSON.stringify(payload)).toString('base64')});
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
  await call('Network.setCookie', {name:process.env.OBS_UI_COOKIE_NAME, value:process.env.OBS_UI_SESSION, url:base, httpOnly:true, sameSite:'Lax'});
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await call('Page.addScriptToEvaluateOnNewDocument', {source: `(() => {const original = window.setTimeout; window.setTimeout = (fn, ms, ...args) => original(fn, ms === 120000 ? 250 : ms, ...args);const now = Date.now; const start = now(); Date.now = () => start + (now() - start) * 1000;})()`});
  await navigate('/chamados/');
  await until(`!document.querySelector('[data-observation-ticket]').hidden`);
  assert.equal(await evaluate('localStorage.length'), 0, 'Listing must not mark read');
  await screenshot('list-unread-desktop');
  await navigate('/');
  await until(`!document.querySelector('[data-observation-ticket]').hidden`);
  assert.equal(await evaluate('localStorage.length'), 0, 'Dashboard must not mark read');
  await navigate('/chamados/' + ticket + '/');
  await until(`!document.querySelector('[data-observation-ticket]').hidden`);
  await evaluate(`document.querySelector('[data-observation-panel]').scrollIntoView({block:'start'})`);
  await click('[data-observation-panel] > summary');
  await until(`document.querySelectorAll('.support-observation').length === 1 && document.querySelector('[data-observation-ticket]').hidden`);
  assert.equal(await evaluate('window.attacked'), undefined);
  assert.ok(await evaluate(`document.querySelector('.support-observation-text').textContent.includes('<script>')`));
  assert.deepEqual(await evaluate('Object.values(localStorage)'), ['m1']);
  await screenshot('detail-read-desktop');
  await navigate('/chamados/' + ticket + '/');
  await until(`document.querySelector('[data-observation-ticket]').hidden`);
  stage = 2;
  await until(`!document.querySelector('[data-observation-ticket]').hidden && document.querySelector('[data-observation-count]').textContent === '1'`);
  await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await evaluate(`document.querySelector('[data-observation-panel]').scrollIntoView({block:'start'})`);
  await screenshot('detail-unread-mobile');
  await click('[data-observation-panel] > summary');
  await until(`document.querySelectorAll('.support-observation').length === 2 && document.querySelector('[data-observation-ticket]').hidden`);
  assert.deepEqual(await evaluate('Object.values(localStorage)'), ['m2']);
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow');
  await screenshot('detail-read-mobile');
  await evaluate(`Storage.prototype.setItem = function () {throw new DOMException('quota','QuotaExceededError');}`);
  stage = 3;
  await until(`document.querySelectorAll('.support-observation').length === 3 && document.querySelector('[data-observation-ticket]').hidden && !document.querySelector('[data-observation-storage]').hidden`);
  assert.deepEqual(await evaluate('Object.values(localStorage)'), ['m2'], 'Quota failure preserves the old stored marker but uses the new in-memory one');
  // The feature recovers from a transient HTTP failure without breaking the page.
  stage = -1;
  await delay(650);
  await until(`document.querySelector('[data-observation-status]').textContent.includes('indisponíveis')`);
  stage = 0;
  await until(`document.querySelector('[data-observation-content]').textContent.includes('Ainda não há observações')`);
  await call('Page.addScriptToEvaluateOnNewDocument', {source: `Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('blocked','SecurityError');}});`});
  stage = 1;
  await navigate('/chamados/' + ticket + '/');
  await evaluate(`document.querySelector('[data-observation-panel]').scrollIntoView({block:'start'})`);
  await click('[data-observation-panel] > summary');
  await until(`!document.querySelector('[data-observation-storage]').hidden && document.querySelector('[data-observation-ticket]').hidden`);
  await screenshot('storage-fallback-mobile');
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log('Observations UI passed: list, dashboard, read persistence, new messages, mobile, safe text, empty, failure, blocked storage.');
} finally {
  socket?.close(); browser.kill();
}
