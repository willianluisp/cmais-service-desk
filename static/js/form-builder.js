/* Visual schema editor. User text is assigned through value/textContent only. */
document.addEventListener("DOMContentLoaded", () => {
  const editor = document.querySelector("[data-form-builder]");
  if (!editor) return;
  const types = JSON.parse(document.getElementById("builder-types").textContent);
  let fields = JSON.parse(document.getElementById("builder-schema").textContent);
  const list = editor.querySelector("[data-fields-list]");
  const hidden = editor.querySelector('[name="fields"]');
  const status = editor.querySelector("[data-builder-status]");
  const template = document.getElementById("builder-field-template");
  let dirty = false;
  let dragging = null;
  let leavingForSave = false;
  const announce = (message) => { status.textContent = message; };
  const sync = () => { hidden.value = JSON.stringify(fields); dirty = true; };
  const lines = (value) => value.split("\n").map((v) => v.trim()).filter(Boolean);
  function move(id, destination) {
    const index = fields.findIndex((field) => field.id === id);
    if (index < 0 || destination < 0 || destination >= fields.length || index === destination) return;
    const [field] = fields.splice(index, 1);
    fields.splice(destination, 0, field);
    sync(); render();
    list.querySelector(`[data-field-id="${CSS.escape(id)}"] .field-drag`)?.focus();
    announce(`Campo movido para a posição ${destination + 1}.`);
  }
  function render() {
    list.replaceChildren();
    editor.querySelector("[data-builder-empty]").hidden = fields.length > 0;
    fields.forEach((field, index) => {
      const fragment = template.content.cloneNode(true);
      const card = fragment.querySelector("article");
      card.dataset.fieldId = field.id;
      card.querySelector(".field-number").textContent = String(index + 1).padStart(2, "0");
      const heading = card.querySelector(".field-heading");
      heading.textContent = field.label || "Nova pergunta";
      const typeSelect = card.querySelector('[data-property="type"]');
      Object.entries(types).forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value; option.textContent = label; typeSelect.append(option);
      });
      const choice = ["select", "multiple"].includes(field.type);
      card.querySelector("[data-options-row]").hidden = !choice;
      card.querySelector("[data-multi-default-row]").hidden = field.type !== "multiple";
      card.querySelector("[data-check-default-row]").hidden = field.type !== "checkbox";
      card.querySelector("[data-default-row]").hidden = ["multiple", "checkbox", "attachment", "sector"].includes(field.type);
      card.querySelector("[data-placeholder-row]").hidden = !["short_text", "long_text", "number"].includes(field.type);
      let defaultInput = card.querySelector('[data-property="default"]');
      if (field.type === "long_text") {
        const multiline = document.createElement("textarea");
        multiline.dataset.property = "default"; multiline.rows = 3;
        defaultInput.replaceWith(multiline); defaultInput = multiline;
      } else defaultInput.type = field.type === "date" ? "date" : field.type === "datetime" ? "datetime-local" : ["number", "integer"].includes(field.type) ? "number" : "text";
      if (field.type === "number") defaultInput.step = "0.0001";
      if (field.type === "integer") { defaultInput.step = "1"; defaultInput.min = "1"; }
      defaultInput.maxLength = field.type === "long_text" ? 10000 : 255;
      card.querySelectorAll("[data-property]").forEach((input) => {
        const property = input.dataset.property;
        // Stable IDs associate labels and controls without making schema keys model fields.
        input.id = `editor-${field.id}-${property}`;
        input.closest("label")?.setAttribute("for", input.id);
        if (property === "required") input.checked = Boolean(field.required);
        else if (property === "checkbox_default") input.checked = field.default === true;
        else if (property === "multiple_default") input.value = Array.isArray(field.default) ? field.default.join("\n") : "";
        else if (property === "options") input.value = Array.isArray(field.options) ? field.options.join("\n") : "";
        else input.value = typeof field[property] === "string" ? field[property] : "";
        if (input.closest("label").hidden) input.disabled = true;
        const update = () => {
          if (property === "type") {
            field.type = input.value;
            field.options = ["select", "multiple"].includes(field.type) ? ["Opção 1", "Opção 2"] : [];
            field.default = field.type === "checkbox" ? false : field.type === "multiple" ? [] : "";
            field.placeholder = "";
            sync(); render(); return;
          }
          if (property === "required") field.required = input.checked;
          else if (property === "checkbox_default") field.default = input.checked;
          else if (property === "multiple_default") field.default = lines(input.value);
          else if (property === "options") field.options = lines(input.value);
          else field[property] = input.value;
          if (property === "label") heading.textContent = input.value || "Nova pergunta";
          sync();
        };
        input.addEventListener(input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input", update);
      });
      card.querySelectorAll("[data-move]").forEach((button) => {
        const delta = Number(button.dataset.move);
        button.disabled = index + delta < 0 || index + delta >= fields.length;
        button.addEventListener("click", () => move(field.id, index + delta));
      });
      card.querySelector("[data-remove-field]").addEventListener("click", () => {
        fields = fields.filter((item) => item !== field); sync(); render();
        announce(`Campo ${field.label || index + 1} removido do rascunho.`);
      });
      const duplicate = document.createElement('button');
      duplicate.type = 'button'; duplicate.className = 'button button-quiet';
      duplicate.textContent = 'Duplicar'; duplicate.dataset.duplicateField = '';
      duplicate.addEventListener('click', () => {
        if (fields.length >= 40) { announce('Limite de 40 campos atingido.'); return; }
        if (field.type === 'attachment' && fields.filter(f => f.type === 'attachment').length >= 5) {
          announce('Use no máximo cinco campos de anexo.'); return;
        }
        const copy = structuredClone(field); copy.id = crypto.randomUUID(); copy.label = `${field.label.slice(0,150)} (cópia)`;
        fields.splice(index + 1, 0, copy); sync(); render(); announce('Campo duplicado no rascunho.');
      });
      card.querySelector('.field-actions').prepend(duplicate);
      card.querySelector(".field-drag").addEventListener("dragstart", (event) => {
        dragging = field.id; event.dataTransfer.setData("text/plain", field.id);
        event.dataTransfer.effectAllowed = "move"; card.classList.add("is-dragging");
      });
      card.addEventListener("dragend", () => { dragging = null; card.classList.remove("is-dragging"); });
      card.addEventListener("dragover", (event) => { if (dragging) event.preventDefault(); });
      card.addEventListener("drop", (event) => {
        event.preventDefault(); if (dragging) move(dragging, index); dragging = null;
      });
      list.append(fragment);
    });
    hidden.value = JSON.stringify(fields);
  }
  editor.querySelectorAll("[data-add-field]").forEach((button) => button.addEventListener("click", () => {
    if (fields.length >= 40) { announce("Limite de 40 campos atingido."); return; }
    const kind = button.dataset.addField;
    if (kind === "attachment" && fields.filter((f) => f.type === kind).length >= 5) {
      announce("Use no máximo cinco campos de anexo."); return;
    }
    fields.push({id: crypto.randomUUID(), type: kind, label: "Nova pergunta", required: false,
      help_text: "", placeholder: "", options: ["select", "multiple"].includes(kind) ? ["Opção 1", "Opção 2"] : [],
      default: kind === "checkbox" ? false : kind === "multiple" ? [] : ""});
    sync(); render();
    const input = list.lastElementChild.querySelector('[data-property="label"]');
    input.focus(); input.select(); announce(`${types[kind]} adicionado. ${fields.length} campos no rascunho.`);
  }));
  editor.addEventListener("input", () => { dirty = true; });
  editor.addEventListener("change", () => { dirty = true; });
  editor.addEventListener("submit", (event) => {
    hidden.value = JSON.stringify(fields);
    leavingForSave = event.submitter?.value !== "preview";
  });
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !leavingForSave) { event.preventDefault(); event.returnValue = ""; }
  });
  render();
});
