(() => {
  'use strict';
  const editor = document.querySelector('[data-checklist-editor]');
  if (!editor) return;
  const source = editor.querySelector('textarea');
  const enabled = editor.querySelector('input[type="checkbox"]');
  const rows = editor.querySelector('[data-checklist-rows]');
  const preview = editor.querySelector('[data-checklist-preview]');
  const add = editor.querySelector('[data-checklist-add]');
  const status = editor.querySelector('[data-checklist-status]');
  let items = source.value.split(/\r?\n/).filter(value => value.trim());
  const sync = () => {
    source.value = items.join('\n');
    preview.replaceChildren();
    if (enabled.checked) items.filter(value => value.trim()).forEach(value => {
      const li = document.createElement('li');
      li.textContent = `☐ ${value}`;
      preview.append(li);
    });
    editor.querySelector('[data-checklist-disabled]').hidden = enabled.checked;
    add.disabled = items.length >= 20;
    status.textContent = `${items.length}/20 itens · até 100 caracteres por item.`;
  };
  const render = (focusIndex = null) => {
    rows.replaceChildren();
    items.forEach((title, index) => {
      const li = document.createElement('li');
      li.className = 'planner-checklist-row';
      const label = document.createElement('label');
      const input = document.createElement('input');
      label.textContent = `Item ${index + 1}`;
      input.type = 'text';
      input.maxLength = 100;
      input.value = title;
      input.required = enabled.checked;
      input.addEventListener('input', () => { items[index] = input.value; sync(); });
      label.append(input);
      li.append(label);
      const actions = document.createElement('div');
      actions.className = 'field-actions';
      [['↑', 'Mover item para cima', -1], ['↓', 'Mover item para baixo', 1], ['Remover', 'Remover item', 0]].forEach(([text, aria, direction]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button button-quiet';
        button.textContent = text;
        button.setAttribute('aria-label', `${aria} ${index + 1}`);
        button.disabled = direction < 0 ? index === 0 : direction > 0 && index === items.length - 1;
        button.addEventListener('click', () => {
          if (direction) {
            const next = index + direction;
            [items[index], items[next]] = [items[next], items[index]];
            render(next);
          } else { items.splice(index, 1); render(Math.min(index, items.length - 1)); }
        });
        actions.append(button);
      });
      li.append(actions);
      rows.append(li);
    });
    sync();
    if (focusIndex !== null) rows.children[focusIndex]?.querySelector('input').focus();
  };
  add.addEventListener('click', () => { if (items.length < 20) { items.push(''); render(items.length - 1); } });
  enabled.addEventListener('change', () => render());
  // Keep the original textarea available without JavaScript and on validation errors.
  editor.querySelector('[data-checklist-source]').hidden = true;
  editor.querySelector('[data-checklist-controls]').hidden = false;
  render();
})();
