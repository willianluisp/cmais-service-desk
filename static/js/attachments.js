document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.querySelector("#attachment-dialog");
  let previewTrigger = null;
  const inputs = [...document.querySelectorAll('.ticket-form input[type="file"]')];
  const updaters = [];
  inputs.forEach((input, fieldIndex) => {
  let list = input.name === "attachments" ? document.querySelector("#attachment-preview") : null;
  let status = input.name === "attachments" ? document.querySelector("#attachment-status") : null;
  if (!list || !status) {
    status = document.createElement("p");
    status.className = "helptext";
    status.id = `attachment-status-${fieldIndex}`;
    status.setAttribute("role", "status");
    list = document.createElement("ul");
    list.className = "attachment-preview";
    list.setAttribute("aria-label", "Arquivos selecionados");
    input.insertAdjacentElement("afterend", status);
    status.insertAdjacentElement("afterend", list);
    input.setAttribute("aria-describedby", [input.getAttribute("aria-describedby"), status.id].filter(Boolean).join(" "));
  }
  let selected = Array.from(input.files);
  let urls = [];
  const release = () => { urls.forEach((url) => URL.revokeObjectURL(url)); urls = []; };
  const render = () => {
    release();
    const total = inputs.reduce((count, field) => count + field.files.length, 0);
    const error = total > 5 ? "Selecione no máximo cinco arquivos por solicitação." :
      selected.some((file) => file.size === 0 || file.size > 2 * 1024 * 1024) ? "Cada arquivo deve ter entre 1 byte e 2 MB." :
      selected.some((file) => !["application/pdf", "image/png", "image/jpeg"].includes(file.type)) ? "Use somente PDF, PNG ou JPEG." : "";
    input.setCustomValidity(error);
    status.textContent = error || (selected.length ? `${selected.length} arquivo(s) neste campo · ${total} de 5 na solicitação. Confira antes de enviar.` : "Nenhum arquivo selecionado.");
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
        updaters.forEach((update) => update());
        input.focus();
      });
      item.append(remove);
      return item;
    }));
  };
  updaters.push(render);
  input.addEventListener("change", () => { selected = Array.from(input.files); updaters.forEach((update) => update()); });
  window.addEventListener("pagehide", release);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) { selected = Array.from(input.files); render(); }
  });
  });
  dialog?.querySelector("[data-close-preview]")?.addEventListener("click", () => dialog.close());
  dialog?.addEventListener("close", () => previewTrigger?.focus());
  updaters.forEach((update) => update());
});
