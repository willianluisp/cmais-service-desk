document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-card-order]');
  if (!form) return;
  const list = form.querySelector('ol');
  const status = form.querySelector('[data-order-status]');
  let dragging = null;
  let dirty = false;
  const sync = () => {
    const rows = [...list.children];
    form.elements.items.value = JSON.stringify(rows.map(row => row.dataset.cardKey));
    rows.forEach((row, index) => row.querySelectorAll('[data-order-move]').forEach(button => {
      const target = index + Number(button.dataset.orderMove);
      button.disabled = target < 0 || target >= rows.length;
    }));
  };
  list.querySelectorAll('li').forEach(row => {
    row.querySelectorAll('[data-order-move]').forEach(button => button.addEventListener('click', () => {
      const sibling = Number(button.dataset.orderMove) < 0 ? row.previousElementSibling : row.nextElementSibling;
      if (!sibling) return;
      if (Number(button.dataset.orderMove) < 0) list.insertBefore(row, sibling);
      else list.insertBefore(sibling, row);
      dirty = true; sync(); status.textContent = 'Ordem alterada. Salve para aplicar aos cards.';
      row.querySelector('.field-drag').focus();
    }));
    row.querySelector('.field-drag').addEventListener('dragstart', event => {
      dragging = row; event.dataTransfer.setData('text/plain', row.dataset.cardKey);
    });
    row.addEventListener('dragover', event => {if (dragging) event.preventDefault();});
    row.addEventListener('drop', event => {
      event.preventDefault();
      if (dragging && dragging !== row) {list.insertBefore(dragging, row); dirty = true; sync();}
      dragging = null; status.textContent = 'Ordem alterada. Salve para aplicar aos cards.';
    });
    row.addEventListener('dragend', () => {dragging = null;});
  });
  form.addEventListener('submit', () => {sync(); dirty = false;});
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  sync();
});
