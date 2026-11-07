/** Exercise the real Django views against pytest's disposable live server.
 * All non-localhost requests are blocked; never connect to a real deployment.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.env.FORMS_UI_URL;
assert.ok(/^http:\/\/localhost:\d+$/.test(base), 'Only disposable localhost server allowed');
const output = path.join(root, '.tmp/custom-forms-ui');
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
      const url = new URL(request.url);
      if (url.origin !== base) return call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
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
  await call('Network.setCookie', {name:process.env.FORMS_UI_COOKIE_NAME, value:process.env.FORMS_UI_SESSION, url:base, httpOnly:true, sameSite:'Lax'});
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await navigate('/administracao/setores/');
  assert.ok(await evaluate(`document.body.textContent.includes('Setor fictício da validação visual')`));
  await click('a[href$="/editar/"]');
  await until(`location.pathname.endsWith('/editar/') && document.readyState === 'complete'`);
  await set('#id_name', 'Setor oficial fictício revisado');
  await set('#id_display_order', '2');
  await click('.ticket-form button[type="submit"]');
  await until(`location.pathname === '/administracao/setores/' && document.readyState === 'complete'`);
  await screenshot('sectors-desktop');
  await navigate('/administracao/formularios/novo/');
  await until(`document.querySelector('[data-add-field]') !== null`);
  await set('#id_title', 'Solicitação fictícia de acesso');
  await set('#id_description', 'Solicite acesso aos sistemas de demonstração da C+.');
  for (const type of ['short_text', 'select', 'multiple', 'number', 'date', 'checkbox', 'attachment', 'long_text']) {
    await click(`[data-add-field="${type}"]`);
  }
  assert.equal(await evaluate('document.querySelectorAll(".builder-field").length'), 8);
  await set('.builder-field:first-child [data-property="label"]', 'Sistema de destino');
  await click('.builder-field:first-child [data-property="required"]');
  await set('.builder-field:nth-child(2) [data-property="options"]', 'Consulta\nEdição\nRelatórios');
  await set('.builder-field:nth-child(2) [data-property="default"]', 'Consulta');
  await click('.builder-field:nth-child(3) [data-property="required"]');
  await click('.builder-field:last-child [data-move="-1"]');
  await click('.builder-field:last-child [data-remove-field]');
  assert.equal(await evaluate('document.querySelectorAll(".builder-field").length'), 7);
  await click('.builder-field:first-child [data-duplicate-field]');
  assert.equal(await evaluate('document.querySelectorAll(".builder-field").length'), 8);
  await click('.builder-field:nth-child(2) [data-remove-field]');
  assert.equal(await evaluate('document.querySelectorAll(".builder-field").length'), 7);
  await screenshot('editor-desktop');
  // Publish through the browser with its real CSRF cookie/form, then verify persisted controls.
  await click('button[name="action"][value="publish"]');
  await until(`location.pathname !== '/administracao/formularios/novo/' && document.readyState === 'complete' && document.body.textContent.includes('Formulário publicado.')`);
  const editorPath = await evaluate('location.pathname');
  assert.equal(await evaluate('document.querySelectorAll(".builder-field").length'), 7);
  await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await screenshot('editor-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile editor overflows');
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await navigate('/administracao/formularios/ordenar/');
  await click('.form-order-list li:last-child [data-order-move="-1"]');
  await click('[data-card-order] button[type="submit"]');
  await until(`document.readyState === 'complete' && document.body.textContent.includes('Ordem dos cards salva.')`);
  assert.ok(await evaluate(`document.querySelector('.form-order-list li:first-child').dataset.cardKey !== 'standard'`));
  await screenshot('ordering-desktop');
  await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await screenshot('ordering-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile ordering overflows');
  await call('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await navigate('/chamados/novo/');
  assert.ok(await evaluate(`!document.querySelector('.request-card').classList.contains('request-card-standard')`));
  assert.ok(await evaluate(`document.querySelector('.request-cards').textContent.includes('Solicitação fictícia de acesso')`));
  await screenshot('cards-desktop');
  await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await screenshot('cards-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile cards overflow');
  await click('.request-card:not(.request-card-standard)');
  await until(`location.pathname.includes('/formulario/') && document.readyState === 'complete'`);
  assert.ok(await evaluate(`document.querySelector('input[required][name^="cf_"]') !== null`));
  await screenshot('request-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile request overflows');
  await set('#id_title', 'Chamado fictício pelo construtor visual');
  await evaluate(`(() => {const select=document.querySelector('#id_sector'); select.value=select.options[1].value; select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await set('#id_service_location', 'Sala fictícia da validação visual');
  await set('input[name^="cf_"][required]', 'ERP de demonstração');
  assert.equal(await evaluate(`document.querySelector('[data-required-choice] input').checkValidity()`), false);
  await click('[data-required-choice] input');
  assert.equal(await evaluate(`document.querySelector('[data-required-choice] input').checkValidity()`), true);
  await click('.custom-request button[type="submit"]');
  await until(`location.pathname.startsWith('/chamados/') && !location.pathname.includes('/novo/') && document.readyState === 'complete'`);
  assert.ok(await evaluate(`document.body.textContent.includes('ERP de demonstração')`));
  await navigate('/administracao/formularios/');
  await click('button[name="action"][value="trash"]');
  await until(`location.pathname === '/administracao/formularios/lixeira/' && document.readyState === 'complete'`);
  assert.ok(await evaluate(`document.querySelector('.form-management-list').textContent.includes('Solicitação fictícia de acesso')`));
  await screenshot('trash-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile trash overflows');
  await click('.form-management-list a.form-delete');
  await until(`location.pathname.includes('/excluir-definitivamente/') && document.readyState === 'complete'`);
  assert.ok(await evaluate(`document.querySelector('.form-permanent-delete').disabled`), 'Used form cannot be deleted');
  await navigate('/administracao/formularios/lixeira/');
  await click('button[name="action"][value="restore"]');
  await until(`location.pathname === ${JSON.stringify(editorPath)} && document.readyState === 'complete'`);
  assert.equal(await evaluate(`document.querySelector('.form-status').textContent.trim()`), 'Rascunho');
  await click('button[name="action"][value="archive"]');
  await until(`document.readyState === 'complete' && document.querySelector('.form-status')?.textContent.trim() === 'Arquivado'`);
  await click('button[name="action"][value="unarchive"]');
  await until(`document.readyState === 'complete' && document.querySelector('.form-status')?.textContent.trim() === 'Rascunho'`);
  await navigate('/chamados/novo/');
  assert.equal(await evaluate(`document.querySelectorAll('.request-card:not(.request-card-standard)').length`), 0);
  await navigate(editorPath);
  await click('button[name="action"][value="duplicate"]');
  await until(`location.pathname !== ${JSON.stringify(editorPath)} && document.readyState === 'complete' && document.querySelector('.form-lifecycle') !== null`);
  await click('button[name="action"][value="trash"]');
  await until(`location.pathname === '/administracao/formularios/lixeira/' && document.readyState === 'complete'`);
  await click('.form-management-list a.form-delete');
  await until(`location.pathname.includes('/excluir-definitivamente/') && document.readyState === 'complete'`);
  await screenshot('permanent-delete-mobile');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile confirmation overflows');
  await set('#id_confirmation_name', 'Nome incorreto');
  await click('#id_confirm');
  await click('.form-permanent-delete');
  await until(`document.readyState === 'complete' && document.querySelector('.error-summary') !== null`);
  await set('#id_confirmation_name', 'Solicitação fictícia de acesso (cópia)');
  await click('.form-permanent-delete');
  await until(`location.pathname === '/administracao/formularios/lixeira/' && document.readyState === 'complete'`);
  assert.equal(await evaluate(`document.querySelectorAll('.form-management-row').length`), 0);
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log('Builder, mobile, ticket submission, trash, draft restoration and safe permanent deletion passed.');
} finally {
  socket?.close(); browser.kill();
}
