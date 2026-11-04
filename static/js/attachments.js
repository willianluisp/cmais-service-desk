document.addEventListener("DOMContentLoaded", () => {
  const input = document.querySelector('input[name="attachments"]');
  const list = document.querySelector("#attachment-preview");
  const status = document.querySelector("#attachment-status");
  const dialog = document.querySelector("#attachment-dialog");
  if (!input || !list || !status) return;
  let selected = [];
  let urls = [];
  let previewTrigger = null;
  const release = () => { urls.forEach((url) => URL.revokeObjectURL(url)); urls = []; };
  const render = () => {
    release();
    const error = selected.length > 5 ? "Selecione no máximo cinco arquivos." :
      selected.some((file) => file.size === 0 || file.size > 2 * 1024 * 1024) ? "Cada arquivo deve ter entre 1 byte e 2 MB." :
      selected.some((file) => !["application/pdf", "image/png", "image/jpeg"].includes(file.type)) ? "Use somente PDF, PNG ou JPEG." : "";
    input.setCustomValidity(error);
    status.textContent = error || (selected.length ? `${selected.length} de 5 arquivos selecionados. Confira antes de enviar.` : "Nenhum arquivo selecionado.");
    status.classList.toggle("field-errors", Boolean(error));
    list.replaceChildren(...selected.map((file, index) => {
      const item = document.createElement("li");
      const meta = document.createElement("span");
      meta.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB · ${file.type === "application/pdf" ? "PDF" : "Imagem"}`;
      if (["image/png", "image/jpeg"].includes(file.type) && file.size <= 2 * 1024 * 1024) {
        const url = URL.createObjectURL(file);
        urls.push(url);
        const open = document.createElement("button");
        open.type = "button";
        open.className = "attachment-thumbnail";
        open.setAttribute("aria-label", `Ampliar imagem ${file.name}`);
        const image = document.createElement("img");
        image.src = url;
        image.alt = "";
        open.append(image);
        open.addEventListener("click", () => {
          if (!dialog) return;
          previewTrigger = open;
          dialog.querySelector("img").src = url;
          dialog.querySelector("img").alt = `Pré-visualização de ${file.name}`;
          dialog.showModal();
        });
        item.append(open);
      }
      item.append(meta);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button button-quiet";
      remove.textContent = "Remover";
      remove.setAttribute("aria-label", `Remover ${file.name}`);
      remove.addEventListener("click", () => {
        selected.splice(index, 1);
        const transfer = new DataTransfer();
        selected.forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
        render();
        input.focus();
      });
      item.append(remove);
      return item;
    }));
  };
  input.addEventListener("change", () => { selected = Array.from(input.files); render(); });
  dialog?.querySelector("[data-close-preview]").addEventListener("click", () => dialog.close());
  dialog?.addEventListener("close", () => previewTrigger?.focus());
  window.addEventListener("pagehide", release);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) { selected = Array.from(input.files); render(); }
  });
});
