/** Exercise the real Django views against pytest's disposable live server.
 * All non-localhost requests are blocked; never connect to a real deployment.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.env.FLOW_UI_URL;
assert.ok(/^http:\/\/localhost:\d+$/.test(base), 'Only disposable localhost server allowed');
const output = path.join(root, '.tmp/request-flow-ui');
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
const requests = [];
const subject = process.env.FLOW_UI_SUBJECT;
const description = process.env.FLOW_UI_DESCRIPTION;
const ticketForm = process.env.FLOW_UI_FORM;
const company = process.env.FLOW_UI_COMPANY;
const otherCompany = process.env.FLOW_UI_OTHER_COMPANY;
const sector = process.env.FLOW_UI_SECTOR;
const otherSector = process.env.FLOW_UI_OTHER_SECTOR;
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
  throw new Error(`Condition not reached: ${expression}; state=${JSON.stringify(await evaluate(`({path:location.pathname,query:location.search,ready:document.readyState,active:document.activeElement?.outerHTML.slice(0,250),busy:document.querySelector('[data-selection-advance]')?.dataset.navigating})`))}; errors=${JSON.stringify(errors)}`);
}
async function navigate(url) {
  await call('Page.navigate', {url: base + url});
  await until(`document.readyState === 'complete' && location.pathname === ${JSON.stringify(url)}`);
}
const set = (selector, value) => evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); e.value=${JSON.stringify(value)}; e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
async function screenshot(name) {
  const scroll = await evaluate('window.scrollY');
  await evaluate('window.scrollTo(0,0)');
  await delay(100);
  const {data} = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(output, name + '.png'), Buffer.from(data, 'base64'));
  await evaluate(`window.scrollTo(0,${scroll})`);
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
      requests.push({url:request.url, method:request.method});
      const url = new URL(request.url);
      if (url.origin !== base) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      if (!url.pathname.startsWith('/static/')) return call('Fetch.continueRequest', {requestId});
      const directory = path.join(root, 'static');
      const filename = path.resolve(directory, url.pathname.slice('/static/'.length));
      if (!filename.startsWith(directory + path.sep)) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      const body = await readFile(filename);
      const mime = {'.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon'}[path.extname(filename)] || 'application/octet-stream';
      return call('Fetch.fulfillRequest', {requestId, responseCode:200, responseHeaders:[{name:'Content-Type', value:mime}], body:body.toString('base64')});
    })().catch(error => {if (!String(error).includes('Invalid InterceptionId')) errors.push(String(error));});
  };
  await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
  await call('Fetch.enable', {patterns:[{urlPattern:'*'}]});
  await call('Network.setCookie', {name:process.env.FLOW_UI_COOKIE_NAME, value:process.env.FLOW_UI_SESSION, url:base, httpOnly:true, sameSite:'Lax'});
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});

  // Subject is an explicit, optional palette field, never inserted on its own.
  await navigate('/administracao/formularios/novo/');
  assert.equal(await evaluate(`document.querySelectorAll('.builder-field').length`), 0);
  await set('#id_title', 'Formulário fictício sem assunto');
  await click('[data-add-field="subject"]');
  assert.equal(await evaluate(`document.querySelector('[data-property="label"]').value`), 'Assunto');
  assert.equal(await evaluate(`document.querySelector('[data-property="required"]').checked`), false);
  await click('[data-property="required"]');
  assert.equal(await evaluate(`JSON.parse(document.querySelector('[name="fields"]').value)[0].required`), true);
  await screenshot('subject-editor-desktop');
  await click('[data-remove-field]');
  assert.equal(await evaluate(`JSON.parse(document.querySelector('[name="fields"]').value).length`), 0);
  await click('button[name="action"][value="publish"]');
  await until(`document.querySelector('.form-status')?.textContent.trim() === 'Publicado'`);

  await navigate('/chamados/novo/');
  assert.equal(await evaluate(`document.body.textContent.includes('Continuar')`), false);
  const beforeCompany = requests.length;
  await evaluate(`document.querySelector('button[name=company][value="${company}"]').click(); document.querySelector('button[name=company][value="${company}"]').click();`);
  await until(`document.readyState === 'complete' && document.querySelector('button[name=sector]') !== null`);
  assert.equal(requests.slice(beforeCompany).filter(r => new URL(r.url).pathname === '/chamados/novo/').length, 1, 'Duplicate company navigation');
  await evaluate(`document.querySelector('button[name=sector][value="${sector}"]').focus()`);
  await call('Input.dispatchKeyEvent', {type:'keyDown', key:'Enter', code:'Enter', windowsVirtualKeyCode:13, text:'\r', unmodifiedText:'\r'});
  await call('Input.dispatchKeyEvent', {type:'keyUp', key:'Enter', code:'Enter', windowsVirtualKeyCode:13});
  await until(`document.querySelector('.request-cards') !== null`);
  await click(`a[href*="${ticketForm}"]`);
  await until(`document.querySelector('form[data-request-review]') !== null`);
  await set(`[name="cf_${subject}"]`, 'Assunto preenchido e preservado');
  await set(`[name="cf_${description}"]`, 'Descrição preservada entre etapas.');
  await evaluate(`(() => {const input=document.querySelector('input[type=file]');const transfer=new DataTransfer();transfer.items.add(new File([['%PDF-1.4','%%EOF'].join(String.fromCharCode(10))], 'preservado.pdf', {type:'application/pdf'}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const formPath = '/chamados/novo/formulario/' + ticketForm + '/';
  await click('[data-wizard-back]');
  await until(`!document.querySelector('[data-context-panel]').hasAttribute('aria-busy')`);
  await click('[data-context-back]');
  await click('[data-context-back]');
  await until(`document.querySelector('[data-context-option="company"]') !== null`);
  await evaluate(`(() => {const option=document.querySelector('[data-context-option="company"][value="${otherCompany}"]');option.click();option.click();})()`);
  await until(`document.querySelector('[data-context-option="sector"]') !== null`);
  await click(`[data-context-option="sector"][value="${otherSector}"]`);
  await until(`document.querySelector('[data-context-content] a[aria-current=true]') !== null`);
  await click('[data-context-content] a[aria-current=true]');
  await until(`!document.querySelector('[data-request-fields]').hidden`);
  assert.equal(await evaluate(`document.querySelector('[name="cf_${subject}"]').value`), 'Assunto preenchido e preservado');
  assert.equal(await evaluate(`document.querySelector('[name="cf_${description}"]').value`), 'Descrição preservada entre etapas.');
  assert.equal(await evaluate(`document.querySelector('input[type=file]').files[0].name`), 'preservado.pdf');
  assert.equal(await evaluate(`document.querySelector('[name=company]').value`), otherCompany);
  assert.equal(await evaluate(`document.querySelector('[name=sector]').value`), otherSector);
  await evaluate('history.back()');
  await until(`!document.querySelector('[data-context-panel]').hidden && !document.querySelector('[data-context-panel]').hasAttribute('aria-busy')`);
  await evaluate('history.forward()');
  await until(`!document.querySelector('[data-request-fields]').hidden`);
  assert.equal(await evaluate(`document.querySelector('input[type=file]').files.length`), 1);
  await screenshot('preserved-desktop');
  await click('[data-request-actions] button[type=submit]');
  await until(`document.querySelector('form[data-request-review]').dataset.reviewing === 'true'`);
  assert.equal(requests.filter(r=>r.method === 'POST' && new URL(r.url).pathname === formPath).length, 0, 'Review must not submit');
  await evaluate(`document.querySelector('[data-review-send]').click();document.querySelector('[data-review-send]').click();`);
  await until(`document.querySelector('[data-request-review]') === null && location.pathname.includes('/chamados/')`);
  assert.equal(requests.filter(r=>r.method === 'POST' && new URL(r.url).pathname === formPath).length, 1, 'Duplicate final POST');

  // Native touch target and blank optional subject on mobile.
  await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await call('Emulation.setTouchEmulationEnabled', {enabled:true});
  await navigate('/chamados/novo/');
  await evaluate(`document.querySelector('button[name=company][value="${company}"]').scrollIntoView({block:'center'})`);
  const touchTarget = await evaluate(`(() => {const r=document.querySelector('button[name=company][value="${company}"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  await call('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[touchTarget]});
  await call('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
  await until(`document.querySelector('button[name=sector]') !== null`);
  await click(`button[name=sector][value="${sector}"]`);
  await until(`document.querySelector('.request-cards') !== null`);
  await click(`a[href*="${ticketForm}"]`);
  await until(`document.querySelector('form[data-request-review]') !== null`);
  await set(`[name="cf_${description}"]`, 'Solicitação móvel sem assunto.');
  await screenshot('request-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow');
  await click('[data-request-actions] button[type=submit]');
  await until(`document.querySelector('form[data-request-review]').dataset.reviewing === 'true'`);
  await screenshot('review-mobile');
  await click('[data-review-send]');
  await until(`document.querySelector('[data-request-review]') === null && location.pathname.includes('/chamados/')`);
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log('Configurable subject, native single-click/keyboard/touch flow, back/history, text/files, review and no duplicate requests passed.');
} finally {socket?.close(); browser.kill();}
