/* Read-only task chat. Only the last seen message ID is persisted. */
(function () {
  'use strict';
  function unread(ids, last) {
    if (!ids.length) return {count: 0, uncertain: false};
    if (!last) return {count: ids.length, uncertain: false};
    const index = ids.indexOf(last);
    return index < 0 ? {count: null, uncertain: true} : {count: ids.length - index - 1, uncertain: false};
  }
  function createReader(user, getStorage) {
    const memory = new Map();
    const pendingWrites = new Set();
    let persistent = true;
    const key = ticket => `cmais:observations:v1:${user}:${ticket}`;
    return {
      get(ticket) {
        if (pendingWrites.has(ticket)) return memory.get(ticket) || null;
        try {return getStorage().getItem(key(ticket)) || memory.get(ticket) || null;}
        catch (_) {persistent = false; return memory.get(ticket) || null;}
      },
      mark(ticket, id) {
        memory.set(ticket, id);
        try {getStorage().setItem(key(ticket), id); pendingWrites.delete(ticket);}
        catch (_) {persistent = false; pendingWrites.add(ticket);}
      },
      persistent: () => persistent,
    };
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {unread, createReader};
    return;
  }
  const root = document.querySelector('[data-observations-root]');
  if (!root) return;
  const reader = createReader(root.dataset.observationsUser, () => window.localStorage);
  const snapshots = new Map();
  const panel = document.querySelector('[data-observation-panel]');
  const badges = () => [...document.querySelectorAll('[data-observation-ticket]')];
  const ids = () => [...new Set(badges().map(b => b.dataset.observationTicket))];
  const status = panel?.querySelector('[data-observation-status]');
  let loading = false;
  let timer;
  let detailLoading = false;
  let detailLoaded = false;
  let renderedIds = [];
  let detailComplete = false;
  let lastDetailCheck = 0;

  function paint() {
    badges().forEach(badge => {
      const state = snapshots.get(badge.dataset.observationTicket);
      if (!state) return;
      // An empty failed response must not clear a previously visible alert.
      if (!state.complete && !state.ids.length) return;
      const result = unread(state.ids, reader.get(badge.dataset.observationTicket));
      badge.hidden = !result.uncertain && result.count === 0;
      const label = result.uncertain ? 'Há observações. Abra para atualizar a leitura.' :
        `${result.count} ${result.count === 1 ? 'observação não lida' : 'observações não lidas'}`;
      badge.title = label;
      badge.setAttribute('aria-label', label);
      badge.querySelector('[data-observation-count]').textContent = result.uncertain ? '' : String(result.count);
    });
    if (panel) panel.querySelector('[data-observation-storage]').hidden = reader.persistent();
  }
  function visible() {
    if (!panel?.open || document.hidden) return false;
    const box = panel.getBoundingClientRect();
    // Require the start of the actual message content to be on screen.
    const content = panel.querySelector('[data-observation-content]').getBoundingClientRect();
    return box.bottom > 0 && content.top >= 0 && content.top < window.innerHeight - 40;
  }
  function markSeen() {
    if (!detailComplete || !renderedIds.length || !visible()) return;
    reader.mark(panel.dataset.ticket, renderedIds.at(-1));
    paint();
  }
  function render(data) {
    const content = panel.querySelector('[data-observation-content]');
    content.replaceChildren();
    data.messages.forEach(message => {
      const article = document.createElement('article');
      article.className = 'support-observation';
      const head = document.createElement('div');
      head.className = 'support-observation-meta';
      const author = document.createElement('strong');
      author.textContent = message.author;
      const date = document.createElement('time');
      date.dateTime = message.created_at;
      date.textContent = new Date(message.created_at).toLocaleString('pt-BR', {dateStyle: 'short', timeStyle: 'short'});
      const text = document.createElement('p');
      text.className = 'support-observation-text';
      text.textContent = message.content;
      head.append(author, date);
      article.append(head, text);
      content.append(article);
    });
    if (!data.messages.length && data.complete) {
      const empty = document.createElement('p');
      empty.className = 'helptext';
      empty.textContent = 'Ainda não há observações do suporte neste chamado.';
      content.append(empty);
    }
    renderedIds = data.messages.map(m => m.id);
    detailComplete = data.complete;
    snapshots.set(panel.dataset.ticket, {ids: renderedIds, complete: data.complete});
    status.textContent = data.complete ? 'Atualizado. As observações são apenas para leitura.' :
      'Não foi possível atualizar as observações. Tentaremos novamente em instantes.';
    panel.querySelector('[data-observation-loading]').hidden = true;
    paint();
    requestAnimationFrame(markSeen);
  }
  async function json(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store',
        headers: {Accept: 'application/json'}, signal: controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('unavailable');
      return await response.json();
    } finally {clearTimeout(timeout);}
  }
  async function detail(force = false) {
    if (!panel?.open || document.hidden || detailLoading) return;
    if (!force && Date.now() - lastDetailCheck < 120000) return;
    detailLoading = true;
    lastDetailCheck = Date.now();
    try {
      const data = await json(panel.dataset.url);
      detailLoaded = true;
      render(data);
    } catch (_) {
      detailComplete = false;
      status.textContent = 'Observações temporariamente indisponíveis. Tentaremos novamente em instantes.';
      panel.querySelector('[data-observation-loading]').hidden = true;
    } finally {detailLoading = false;}
  }
  async function poll() {
    clearTimeout(timer);
    if (loading) return;
    let delay = 120000;
    if (!document.hidden && ids().length) {
      loading = true;
      try {
        const query = new URLSearchParams({ids: ids().slice(0, 20).join(',')});
        const data = await json(root.dataset.observationsSummaryUrl + '?' + query);
        for (const [ticket, state] of Object.entries(data.tickets)) {
          if (state.complete || state.ids.length) snapshots.set(ticket, state);
        }
        paint();
        // Progressive cache warmup: one task per request, no 20-task Graph burst.
        if (data.pending) delay = 5000;
        const state = panel && data.tickets[panel.dataset.ticket];
        const changed = state?.complete && JSON.stringify(state.ids) !== JSON.stringify(renderedIds);
        await detail(Boolean(changed));
      } catch (_) {await detail();}
      finally {loading = false;}
    }
    timer = setTimeout(poll, delay);
  }
  panel?.addEventListener('toggle', () => {
    if (panel.open) {detail(!detailLoaded); markSeen();}
  });
  window.addEventListener('storage', () => {paint();});
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {poll(); markSeen();}
  });
  document.addEventListener('htmx:afterSwap', poll);
  window.addEventListener('scroll', markSeen, {passive: true});
  window.addEventListener('resize', markSeen, {passive: true});
  poll();
})();
