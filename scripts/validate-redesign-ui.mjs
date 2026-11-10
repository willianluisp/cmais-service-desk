/** Local Edge + synthetic Django HTML. Every request is intercepted; no live portal is used.
 * Generate snapshots: REDESIGN_CAPTURE_DIR=.tmp/redesign-preview python -m pytest tests/test_redesign.py
 * Run: node scripts/validate-redesign-ui.mjs
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const captures = path.join(root, '.tmp/redesign-preview');
const output = path.join(root, '.tmp/redesign-qa');
const profile = path.join(output, `browser-${Date.now()}`);
await mkdir(profile, {recursive: true});
const browser = spawn(process.env.EDGE_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
  '--disable-component-update', '--disable-extensions', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank',
], {windowsHide: true, stdio: 'ignore'});
let socket;
let sequence = 0;
const pending = new Map();
const errors = [];
const results = [];
const blocked = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => {pending.delete(id); reject(new Error(`CDP timeout: ${method}`));}, 15000);
  pending.set(id, {resolve: value => {clearTimeout(timer); resolve(value);}, reject});
  socket.send(JSON.stringify({id, method, params}));
});
const mime = file => ({'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.webp': 'image/webp', '.avif': 'image/avif'})[path.extname(file)] || 'text/html';
async function intercept({requestId, request}) {
  try {
    const url = new URL(request.url);
    let file;
    if (url.origin === 'http://localhost:8120' && request.method === 'GET') {
      if (/^\/preview\/[a-z0-9-]+$/.test(url.pathname)) file = path.join(captures, `${url.pathname.split('/').at(-1)}.html`);
      else if (url.pathname === '/chamados/novo/') file = path.join(captures, 'choose.html');
      else if (url.pathname === '/admin/jsi18n/') file = path.join(captures, 'admin-jsi18n.js');
      else if (url.pathname.startsWith('/static/')) {
        const base = url.pathname.startsWith('/static/admin/')
          ? path.join(root, '.venv/Lib/site-packages/django/contrib/admin/static') : path.join(root, 'static');
        file = path.resolve(base, url.pathname.slice('/static/'.length));
        if (!file.startsWith(base + path.sep)) file = undefined;
      }
    }
    if (!file) {
      blocked.push(`${request.method} ${url.pathname}`);
      return await call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
    }
    const body = await readFile(file);
    await call('Fetch.fulfillRequest', {requestId, responseCode: 200,
      responseHeaders: [{name: 'Content-Type', value: `${mime(file)}; charset=utf-8`},
        {name: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'; form-action 'self'"}], body: body.toString('base64')});
  } catch (error) {errors.push(String(error)); await call('Fetch.failRequest', {requestId, errorReason: 'Failed'});}
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function navigate(name) {
  await call('Page.navigate', {url: `http://localhost:8120/preview/${name}`});
  for (let i = 0; i < 150; i++) {
    if (await evaluate(`document.readyState === 'complete' && location.pathname === '/preview/${name}'`)) {await delay(40); return;}
    await delay(30);
  }
  throw new Error(`Page did not load: ${name}`);
}
async function viewport(width) {await call('Emulation.setDeviceMetricsOverride', {width, height: 960, deviceScaleFactor: 1, mobile: width < 800});}
async function screenshot(name) {
  const result = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
  await writeFile(path.join(output, `${name}.png`), Buffer.from(result.data, 'base64'));
}
const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const fill = (selector, value) => evaluate(`(() => {const e = document.querySelector(${JSON.stringify(selector)}); e.value = ${JSON.stringify(value)}; e.dispatchEvent(new Event('input', {bubbles:true})); e.dispatchEvent(new Event('change', {bubbles:true}));})()`);

try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break;} catch {await delay(100);}
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
    } else if (message.method === 'Fetch.requestPaused') intercept(message.params).catch(error => errors.push(String(error)));
    else if (message.method === 'Runtime.exceptionThrown') errors.push(JSON.stringify(message.params.exceptionDetails));
  };
  await call('Page.enable'); await call('Runtime.enable');
  await call('Fetch.enable', {patterns: [{urlPattern: '*'}]});
  const screens = JSON.parse(await readFile(path.join(captures, 'screens.json'), 'utf8'));
  for (const width of [360, 390, 1366, 1920]) {
    await viewport(width);
    for (const name of screens) {
      await navigate(name);
      const audit = await evaluate(`(() => {
        const visible = e => e.getClientRects().length > 0;
        const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
        return {width:innerWidth, scroll:document.documentElement.scrollWidth,
          title:document.title, duplicateIds:ids.filter((id,i) => ids.indexOf(id)!==i),
          badChoices:[...document.querySelectorAll('.choice input[type=radio]')].filter(visible).filter(e=>e.getBoundingClientRect().width>24).length,
          brokenImages:[...document.images].filter(e => visible(e) && (!e.complete || e.naturalWidth===0)).map(e => e.src),
          overflow:[...document.querySelectorAll('main *, #content *')].filter(e => visible(e) && e.getBoundingClientRect().right > innerWidth+2 && !e.closest('.results, .ticket-table-wrap, .related-widget-wrapper, .selector')).slice(0,8).map(e => e.tagName+'.'+e.className)};
      })()`);
      results.push({name, width, ...audit});
      assert.ok(audit.scroll <= audit.width + 2, `${name}@${width} horizontal overflow: ${JSON.stringify(audit)}`);
      assert.deepEqual(audit.duplicateIds, [], `${name}@${width}: duplicate IDs`);
      assert.ok(!audit.title.includes('<'), `${name}@${width}: markup in title`);
      assert.equal(audit.badChoices, 0, `${name}@${width}: oversized choice controls`);
      assert.deepEqual(audit.brokenImages, [], `${name}@${width}: broken images`);
      if ([390, 1366].includes(width)) await screenshot(`${name}-${width}`);
    }
    console.log(`${width}px: ${screens.length} screens checked`);
  }

  await viewport(390); await navigate('dashboard');
  assert.equal(await evaluate(`document.querySelector('[data-navigation-toggle]').getAttribute('aria-expanded')`), 'false');
  await click('[data-navigation-toggle]');
  assert.equal(await evaluate(`document.querySelector('.workspace').inert`), true);
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape'});
  assert.equal(await evaluate(`document.querySelector('.workspace').inert`), false);
  assert.equal(await evaluate(`document.activeElement.hasAttribute('data-navigation-toggle')`), true);
  await viewport(1366); await navigate('create');
  await fill('#id_service_location', '2º andar, sala de testes');
  await fill('#id_title', '<img src=x onerror=alert(1)> Texto de teste');
  await fill('#id_description', 'Não consigo acessar o sistema. Dados fictícios para teste.');
  await evaluate(`(() => {const input=document.querySelector('input[type=file]'); const transfer=new DataTransfer(); transfer.items.add(new File(['%PDF-1.4'], 'arquivo-preservado.pdf', {type:'application/pdf'})); input.files=transfer.files; input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await click('[data-request-actions] [data-wizard-back]');
  for(let i=0;i<100;i++){if(await evaluate(`!document.querySelector('[data-context-panel]').hasAttribute('aria-busy')`))break;await delay(30);}
  await click('[data-context-back]');
  await click('[data-context-back]');
  assert.equal(await evaluate(`document.querySelector('[data-context-content] [name=company]') !== null`), true);
  await click('[data-context-next]'); await click('[data-context-next]');
  for(let i=0;i<100;i++){if(await evaluate(`!document.querySelector('[data-context-panel]').hasAttribute('aria-busy')`))break;await delay(30);}
  await click('[data-context-next]');
  assert.equal(await evaluate(`document.querySelector('#id_description').value.includes('Dados fictícios') && document.querySelector('input[type=file]').files.length===1`), true, 'Back through all steps must retain text and FileList');
  await evaluate(`window.submissions=[]; document.querySelector('[data-request-review]').addEventListener('submit', e => {if(!e.defaultPrevented) window.submissions.push([...new FormData(e.target).keys()]); e.preventDefault();});`);
  await click('[data-request-actions] button[type=submit]');
  assert.equal(await evaluate(`document.querySelector('[data-review-panel]').hidden`), false);
  assert.equal(await evaluate(`document.querySelector('[data-review-content] img') === null`), true, 'Review must treat input as text');
  assert.equal(await evaluate(`window.submissions.length`), 0, 'Review must not POST');
  assert.equal(await evaluate(`document.querySelector('[data-review-send]').disabled`), false);
  await screenshot('review-1366');
  await click('[data-review-edit]');
  assert.equal(await evaluate(`document.querySelector('#id_description').value.includes('Dados fictícios')`), true);
  await click('[data-request-actions] button[type=submit]');
  await click('[data-review-send]');
  assert.equal(await evaluate(`window.submissions.length`), 1, 'Confirmation submits once');
  assert.equal(await evaluate(`window.submissions[0].includes('company') && window.submissions[0].includes('sector') && window.submissions[0].includes('submission_key')`), true);

  await navigate('request');
  await fill('#id_service_location', 'Sala de testes');
  await fill('#id_title', 'Acesso de demonstração');
  await evaluate(`document.querySelector('input[name^="cf_"][type="text"]').value = 'Sistema de teste'; document.querySelector('input[type="checkbox"]').click();`);
  const files = await evaluate(`(() => {
    const inputs = [...document.querySelectorAll('input[type=file]')];
    inputs.forEach((e,i) => {const transfer=new DataTransfer(); transfer.items.add(new File(['%PDF-1.4'], 'evidencia-'+i+'.pdf', {type:'application/pdf'})); e.files=transfer.files; e.dispatchEvent(new Event('change',{bubbles:true}));});
    return document.querySelectorAll('.attachment-preview li').length;
  })()`);
  assert.equal(files, 2, 'Each dynamic upload needs preview/removal');
  await click('.attachment-preview .button');
  assert.equal(await evaluate(`document.querySelector('input[type=file]').files.length`), 0);
  await click('[data-request-actions] button[type=submit]');
  assert.equal(await evaluate(`document.querySelector('[data-review-panel]').hidden`), false);
  await screenshot('dynamic-review-1366');
  await click('a.form-back[data-wizard-back]');
  for(let i=0;i<100;i++){if(await evaluate(`!document.querySelector('[data-context-panel]').hasAttribute('aria-busy')`))break;await delay(30);}
  assert.equal(await evaluate(`document.querySelector('[data-review-panel]').hidden && document.querySelector('[data-review-actions]').hidden && !document.querySelector('form[data-request-review]').dataset.reviewing`), true, 'Returning to earlier steps must invalidate the previous review');
  await click('[data-context-next]');
  await evaluate(`(() => {const png=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4N8AAAAASUVORK5CYII='),c=>c.charCodeAt(0)); document.querySelectorAll('input[type=file]').forEach((e,i)=>{const t=new DataTransfer();t.items.add(new File([png],'imagem-'+i+'.png',{type:'image/png'}));e.files=t.files;e.dispatchEvent(new Event('change',{bubbles:true}));});})()`);
  await evaluate(`document.querySelectorAll('.attachment-thumbnail')[1].click()`);
  await click('[data-close-preview]'); await delay(40);
  await evaluate(`document.querySelectorAll('.attachment-thumbnail')[0].click()`);
  await click('[data-close-preview]'); await delay(40);
  assert.equal(await evaluate(`document.activeElement === document.querySelectorAll('.attachment-thumbnail')[0]`), true, 'Preview returns focus to the most recent image trigger');

  await navigate('forms');
  await evaluate(`window.actions=[]; document.querySelector('button[data-confirm]').form.addEventListener('submit', e => {if(!e.defaultPrevented) window.actions.push(e.submitter.value); e.preventDefault();});`);
  await click('button[data-confirm]');
  assert.equal(await evaluate(`document.querySelector('#action-confirmation').open`), true);
  await click('[data-confirmation-cancel]');
  assert.equal(await evaluate(`window.actions.length`), 0);
  await click('button[data-confirm]');
  await click('[data-confirmation-proceed]');
  assert.deepEqual(await evaluate(`window.actions`), ['trash'], 'Confirmation must keep the submitter action');
  await viewport(390); await navigate('editor');
  await click('[data-add-field="short_text"]');
  assert.ok(await evaluate(`document.querySelectorAll('.builder-field').length`) > 6, 'Builder still adds fields');

  assert.deepEqual(errors, [], 'Browser runtime/resource errors');
  assert.deepEqual(blocked, [], 'Unexpected network requests');
  await writeFile(path.join(output, 'results.json'), JSON.stringify({screens: screens.length, checks: results.length, results, errors, blocked, interactions: 'navigation, review, XSS-safe text, final submit, dynamic files, confirmation, builder'}, null, 2));
  const labels = {'dashboard': 'Início do colaborador', 'create': 'Abrir solicitação', 'request': 'Formulário dinâmico', 'detail': 'Detalhe do chamado', 'admin-users': 'Usuários', 'companies': 'Empresas', 'sectors': 'Departamentos', 'integrations': 'Integração Microsoft', 'editor': 'Editor de formulários', 'first-access': 'Primeiro acesso', 'login': 'Login'};
  const cards = screens.map(name => `<details><summary>${labels[name] || name}</summary><div class="pair"><a href="${name}-1366.png"><img src="${name}-1366.png" alt="${name} em desktop" loading="lazy"></a><a href="${name}-390.png"><img src="${name}-390.png" alt="${name} em celular" loading="lazy"></a></div></details>`).join('');
  await writeFile(path.join(output, 'index.html'), `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prévia do redesign C+</title><style>body{font:16px/1.6 'Segoe UI',sans-serif;background:#f5f7f8;color:#003a56;margin:0;padding:32px}main{max-width:1440px;margin:auto}h1{font-size:32px}p{max-width:80ch}details{background:white;border:1px solid #dfe7eb;border-radius:12px;padding:20px;margin:16px 0}summary{cursor:pointer;min-height:44px;font-weight:600}.pair{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,1fr);gap:20px}img{max-width:100%;height:auto;border:1px solid #dfe7eb}a{display:block}@media(max-width:720px){body{padding:16px}.pair{grid-template-columns:1fr}}</style><main><h1>Prévia do redesign C+ Service Desk</h1><p>Galeria local com dados fictícios. Abra uma tela e clique na imagem para ampliá-la. As imagens registram a área inicial de cada tela; os testes de layout verificam o documento completo.</p><p>${screens.length} telas verificadas em 360, 390, 1366 e 1920 px. Esta galeria não se conecta ao portal, ao banco ou à Microsoft.</p>${cards}<details><summary>Revisão antes do envio</summary><img src="review-1366.png" alt="Revisão da solicitação"><img src="dynamic-review-1366.png" alt="Revisão do formulário dinâmico"></details></main></html>`);
  console.log(`PASS: ${results.length} layout checks, 4 widths, interactive flows; no external requests.`);
} finally {
  socket?.close(); browser.kill();
}
