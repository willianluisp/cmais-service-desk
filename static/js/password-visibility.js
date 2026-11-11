/* Presentation only: no password storage, logging, validation or requests. */
(function () {
  'use strict';
  let sequence = 0;
  const svgNS = 'http://www.w3.org/2000/svg';
  function icon(visible) {
    const svg = document.createElementNS(svgNS, 'svg');
    for (const [key, value] of Object.entries({viewBox:'0 0 24 24', width:'20', height:'20',
      fill:'none', stroke:'currentColor', 'stroke-width':'1.8', 'stroke-linecap':'round',
      'stroke-linejoin':'round', 'aria-hidden':'true'})) svg.setAttribute(key, value);
    const outline = document.createElementNS(svgNS, 'path');
    outline.setAttribute('d', 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z');
    const pupil = document.createElementNS(svgNS, 'circle');
    pupil.setAttribute('cx', '12'); pupil.setAttribute('cy', '12'); pupil.setAttribute('r', '3');
    svg.append(outline, pupil);
    if (visible) {
      const slash = document.createElementNS(svgNS, 'path'); slash.setAttribute('d', 'M3 3 21 21');
      svg.append(slash);
    }
    return svg;
  }
  function enhance() {
    document.querySelectorAll('input[type=password]').forEach(input => {
      if (input.dataset.visibilityReady) return;
      input.dataset.visibilityReady = 'true';
      if (!input.id) input.id = `password-visibility-${++sequence}`;
      let wrapper = input.closest('.password-input-row');
      if (!wrapper) {wrapper = document.createElement('span'); input.before(wrapper); wrapper.append(input);}
      wrapper.classList.add('password-visibility');
      let button = [...wrapper.querySelectorAll('[data-password-toggle]')].find(b => b.dataset.passwordToggle === input.id);
      if (!button) {button = document.createElement('button'); wrapper.append(button);}
      button.type = 'button'; button.classList.add('password-toggle');
      button.dataset.passwordToggle = input.id;
      button.setAttribute('aria-controls', input.id);
      function paint() {
        const visible = input.type === 'text';
        const label = visible ? 'Ocultar senha' : 'Mostrar senha';
        button.setAttribute('aria-label', label); button.title = label;
        button.setAttribute('aria-pressed', String(visible));
        button.replaceChildren(icon(visible));
      }
      button.addEventListener('pointerdown', event => {
        // A pointer click keeps the text caret; keyboard activation keeps button focus.
        if (document.activeElement === input) event.preventDefault();
      });
      button.addEventListener('click', () => {
        const start = input.selectionStart, end = input.selectionEnd;
        input.type = input.type === 'password' ? 'text' : 'password';
        if (start !== null && end !== null) input.setSelectionRange(start, end);
        paint();
      });
      window.addEventListener('pageshow', () => {input.type = 'password'; paint();});
      paint();
    });
  }
  document.addEventListener('DOMContentLoaded', enhance);
  document.addEventListener('htmx:afterSwap', enhance);
})();
