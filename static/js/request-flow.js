/* Keep the live form nodes (including FileLists) when revisiting wizard steps.
 * No draft is written to storage, cookies or the server. */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-request-review]").forEach((form) => {
    const fields = form.querySelector("[data-request-fields]");
    const actions = form.querySelector("[data-request-actions]");
    const panel = form.querySelector("[data-context-panel]");
    if (!fields || !actions || !panel) return;
    const content = panel.querySelector("[data-context-content]");
    const next = panel.querySelector("[data-context-next]");
    const back = panel.querySelector("[data-context-back]");
    const error = panel.querySelector("[data-context-error]");
    const company = fields.querySelector('[name="company"]');
    const sector = fields.querySelector('[name="sector"]');
    if (!company || !sector) return;
    let stage = 4;
    let navigating = false;
    const groups = [fields.querySelector(".field-company"), fields.querySelector(".field-sector")];
    const slots = groups.map((group) => {
      const slot = document.createComment("Original field position");
      group?.before(slot);
      return slot;
    });
    const restore = () => groups.forEach((group, i) => { if (group) slots[i].after(group); });
    const progress = () => document.querySelectorAll(".intake-progress li").forEach((step, index) => {
      if (index + 1 === stage) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
    });
    const summary = () => {
      const companyText = document.querySelector("[data-summary-company]");
      const sectorText = document.querySelector("[data-summary-sector]");
      if (companyText) companyText.textContent = company.selectedOptions[0]?.textContent || "Aguardando seleção";
      if (sectorText) sectorText.textContent = sector.selectedOptions[0]?.textContent || "Aguardando seleção";
    };
    const show = async (target) => {
      if (navigating || form.dataset.busy) return;
      stage = target;
      delete form.dataset.reviewing;
      const reviewPanel = form.querySelector("[data-review-panel]");
      const reviewActions = form.querySelector("[data-review-actions]");
      if (reviewPanel) reviewPanel.hidden = true;
      if (reviewActions) reviewActions.hidden = true;
      restore(); content.replaceChildren(); error.textContent = "";
      progress(); summary();
      fields.hidden = stage !== 4; actions.hidden = stage !== 4; panel.hidden = stage === 4;
      if (stage === 4) { fields.querySelector("input:not([type=hidden]), select, textarea")?.focus(); return; }
      panel.querySelector("#context-title").textContent = stage === 1 ? "Para qual empresa é a solicitação?" : stage === 2 ? "Qual é o seu departamento?" : "Sobre o que você precisa de ajuda?";
      panel.querySelector("[data-context-help]").textContent = "Os dados e os anexos já preenchidos continuam nesta página.";
      back.hidden = stage === 1;
      if (stage < 3) {
        if (groups[stage - 1]) content.append(groups[stage - 1]);
      } else {
        navigating = true; next.disabled = true; panel.setAttribute("aria-busy", "true");
        error.textContent = "Carregando os formulários disponíveis…";
        try {
          const query = new URLSearchParams({company: company.value, sector: sector.value});
          const response = await fetch(`${form.dataset.chooseUrl}?${query}`, {credentials: "same-origin"});
          if (!response.ok) throw new Error("Unavailable forms");
          const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
          const choices = documentCopy.querySelector(".request-cards");
          if (!choices) throw new Error("No choices");
          content.append(document.importNode(choices, true));
          content.querySelectorAll("a.request-card").forEach((link) => {
            const url = new URL(link.href, location.href);
            if (url.pathname === location.pathname) {
              link.classList.add("is-selected");
              link.setAttribute("aria-current", "true");
            }
            link.addEventListener("click", (event) => {
              if (url.pathname === location.pathname) { event.preventDefault(); show(4); }
              else if (!window.confirm("Escolher outro formulário abre perguntas diferentes. Os dados e anexos deste formulário não serão transferidos. Deseja continuar?")) event.preventDefault();
            });
          });
          error.textContent = "";
        } catch {
          error.textContent = "Não foi possível consultar os formulários agora. Você pode voltar às informações e tentar novamente depois.";
        } finally {
          navigating = false; next.disabled = false; panel.removeAttribute("aria-busy");
        }
      }
      next.textContent = stage === 3 ? "Manter formulário e continuar →" : "Continuar →";
      panel.focus();
    };
    document.querySelectorAll("[data-wizard-back]").forEach((button) => {
      button.hidden = false;
      button.addEventListener("click", (event) => { event.preventDefault(); show(3); });
    });
    next.addEventListener("click", () => {
      const control = stage === 1 ? company : stage === 2 ? sector : null;
      if (control && !control.reportValidity()) return;
      show(Math.min(4, stage + 1));
    });
    back.addEventListener("click", () => show(Math.max(1, stage - 1)));
    company.addEventListener("change", summary); sector.addEventListener("change", summary);
    form.addEventListener("invalid", (event) => { if (stage < 4 && !panel.contains(event.target)) show(4); }, true);
    summary();
  });
});
