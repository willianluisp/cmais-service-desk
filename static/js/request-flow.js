/* Keep the live form nodes (including FileLists) when revisiting wizard steps.
 * No draft is written to storage, cookies or the server. */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('form[data-selection-advance]').forEach((selection) => {
    const reset = () => {
      delete selection.dataset.navigating;
      selection.removeAttribute('aria-busy');
      selection.querySelector('[data-selection-status]').textContent = '';
    };
    selection.addEventListener('submit', (event) => {
      if (selection.dataset.navigating) { event.preventDefault(); return; }
      selection.dataset.navigating = 'true';
      selection.setAttribute('aria-busy', 'true');
      selection.querySelectorAll('button.choice').forEach(button => {
        button.classList.toggle('selected', button === event.submitter);
        button.setAttribute('aria-pressed', String(button === event.submitter));
      });
      // Keep the submitter enabled: its name/value is required in the native GET.
      selection.querySelector('[data-selection-status]').textContent = 'Carregando a próxima etapa…';
    });
    window.addEventListener('pageshow', reset);
  });
  const choices = document.querySelector('.request-cards');
  choices?.addEventListener('click', (event) => {
    const link = event.target.closest('a.request-card');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    if (choices.dataset.navigating) { event.preventDefault(); return; }
    choices.dataset.navigating = 'true';
    choices.setAttribute('aria-busy', 'true');
    link.classList.add('is-selected');
    link.setAttribute('aria-current', 'true');
  });
  window.addEventListener('pageshow', () => {
    if (choices) { delete choices.dataset.navigating; choices.removeAttribute('aria-busy'); }
  });
  document.querySelectorAll("form[data-request-review]").forEach((form) => {
    const fields = form.querySelector("[data-request-fields]");
    const actions = form.querySelector("[data-request-actions]");
    const panel = form.querySelector("[data-context-panel]");
    if (!fields || !actions || !panel) return;
    const content = panel.querySelector("[data-context-content]");
    const back = panel.querySelector("[data-context-back]");
    const error = panel.querySelector("[data-context-error]");
    const company = fields.querySelector('[name="company"]');
    const sector = fields.querySelector('[name="sector"]');
    if (!company || !sector) return;
    let stage = 4;
    let navigating = false;
    let generation = 0;
    let controller;
    const groups = [fields.querySelector(".field-company"), fields.querySelector(".field-sector")];
    const slots = groups.map((group) => {
      const slot = document.createComment("Original field position");
      group?.before(slot);
      return slot;
    });
    const restore = () => groups.forEach((group, i) => { if (group) { group.hidden = false; slots[i].after(group); } });
    const progress = () => document.querySelectorAll(".intake-progress li").forEach((step, index) => {
      if (index + 1 === stage) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
    });
    const summary = () => {
      const companyText = document.querySelector("[data-summary-company]");
      const sectorText = document.querySelector("[data-summary-sector]");
      if (companyText) companyText.textContent = company.selectedOptions[0]?.textContent || "Aguardando seleção";
      if (sectorText) sectorText.textContent = sector.selectedOptions[0]?.textContent || "Aguardando seleção";
    };
    const state = () => ({...history.state, cmaisRequest: {path: location.pathname, stage, company: company.value, sector: sector.value}});
    history.replaceState(state(), '');
    const show = async (target, fromHistory = false) => {
      if ((navigating && !fromHistory) || form.dataset.busy) return;
      controller?.abort();
      const currentGeneration = ++generation;
      navigating = false;
      panel.removeAttribute('aria-busy');
      const changed = stage !== target;
      stage = target;
      if (changed && !fromHistory) {
        const url = new URL(location.href);
        url.searchParams.set('company', company.value); url.searchParams.set('sector', sector.value);
        history.pushState(state(), '', url);
      }
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
      panel.querySelector("[data-context-help]").textContent = "Selecione uma opção para avançar. Os dados e os anexos já preenchidos continuam nesta página.";
      back.hidden = stage === 1;
      if (stage < 3) {
        if (groups[stage - 1]) { content.append(groups[stage - 1]); groups[stage - 1].hidden = true; }
        const control = stage === 1 ? company : sector;
        const choiceStage = stage;
        const grid = document.createElement('div'); grid.className = 'choice-grid';
        [...control.options].filter(option => option.value && !option.disabled).forEach(option => {
          const button = document.createElement('button'); button.type = 'button';
          button.className = 'choice'; button.value = option.value;
          button.dataset.contextOption = stage === 1 ? 'company' : 'sector';
          button.classList.toggle('selected', control.value === option.value);
          button.setAttribute('aria-pressed', String(control.value === option.value));
          button.textContent = option.textContent;
          button.addEventListener('click', (event) => {
            if (navigating || stage !== choiceStage || event.detail > 1) return;
            control.value = option.value; summary(); show(stage + 1);
          });
          grid.append(button);
        });
        content.append(grid);
      } else {
        navigating = true; panel.setAttribute("aria-busy", "true");
        controller = new AbortController();
        error.textContent = "Carregando os formulários disponíveis…";
        try {
          const query = new URLSearchParams({company: company.value, sector: sector.value});
          const response = await fetch(`${form.dataset.chooseUrl}?${query}`, {credentials: "same-origin", signal: controller.signal});
          if (!response.ok) throw new Error("Unavailable forms");
          const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
          if (currentGeneration !== generation) return;
          const choices = documentCopy.querySelector(".request-cards");
          if (!choices) throw new Error("No choices");
          content.append(document.importNode(choices, true));
          let choosingForm = false;
          content.querySelectorAll("a.request-card").forEach((link) => {
            const url = new URL(link.href, location.href);
            if (url.pathname === location.pathname) {
              link.classList.add("is-selected");
              link.setAttribute("aria-current", "true");
            }
            link.addEventListener("click", (event) => {
              if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
              if (choosingForm) { event.preventDefault(); return; }
              if (url.pathname === location.pathname) { event.preventDefault(); show(4); }
              else if (!window.confirm("Escolher outro formulário abre perguntas diferentes. Os dados e anexos deste formulário não serão transferidos. Deseja continuar?")) event.preventDefault();
              else { choosingForm = true; link.setAttribute('aria-current', 'true'); }
            });
          });
          error.textContent = "";
        } catch (errorResponse) {
          if (errorResponse.name === 'AbortError' || currentGeneration !== generation) return;
          error.textContent = "Não foi possível consultar os formulários agora. Você pode voltar às informações e tentar novamente depois.";
          const returnButton = document.createElement('button'); returnButton.type = 'button';
          returnButton.className = 'button button-quiet'; returnButton.textContent = 'Voltar às informações';
          returnButton.addEventListener('click', () => show(4)); content.append(returnButton);
        } finally {
          if (currentGeneration === generation) { navigating = false; panel.removeAttribute("aria-busy"); }
        }
      }
      if (currentGeneration !== generation) return;
      panel.focus();
    };
    document.querySelectorAll("[data-wizard-back]").forEach((button) => {
      button.hidden = false;
      button.addEventListener("click", (event) => { event.preventDefault(); show(3); });
    });
    back.addEventListener("click", () => show(Math.max(1, stage - 1)));
    company.addEventListener("change", summary); sector.addEventListener("change", summary);
    window.addEventListener('popstate', (event) => {
      const previous = event.state?.cmaisRequest;
      if (previous?.path !== location.pathname || ![1, 2, 3, 4].includes(previous.stage)) return;
      for (const control of [company, sector]) {
        if ([...control.options].some(option => option.value === previous[control.name])) control.value = previous[control.name];
      }
      show(previous.stage, true);
    });
    form.addEventListener("invalid", (event) => { if (stage < 4 && !panel.contains(event.target)) show(4); }, true);
    summary();
  });
});
