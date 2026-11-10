/* Progressive enhancement only: no response, password or file is persisted. */
document.addEventListener("DOMContentLoaded", () => {
  document.body.classList.add("js-enabled");
  const navigation = document.querySelector("#portal-navigation");
  const toggle = document.querySelector("[data-navigation-toggle]");
  const scrim = document.querySelector(".navigation-scrim");
  const mobile = window.matchMedia("(max-width: 820px)");
  const workspace = document.querySelector(".workspace") || document.querySelector("#main");
  const setNavigation = (open) => {
    document.body.classList.toggle("navigation-open", mobile.matches && open);
    document.body.classList.toggle("navigation-collapsed", !mobile.matches && !open);
    toggle?.setAttribute("aria-expanded", String(open));
    if (scrim) scrim.hidden = !mobile.matches || !open;
    if (workspace) workspace.inert = mobile.matches && open;
    navigation?.removeAttribute("aria-hidden");
    if (mobile.matches && open) navigation?.querySelector("button, a")?.focus();
  };
  const closeNavigation = () => { setNavigation(false); toggle?.focus(); };
  setNavigation(!mobile.matches);
  toggle?.addEventListener("click", () => setNavigation(toggle.getAttribute("aria-expanded") !== "true"));
  document.querySelectorAll("[data-navigation-close]").forEach((button) => button.addEventListener("click", closeNavigation));
  mobile.addEventListener("change", () => setNavigation(!mobile.matches));
  document.addEventListener("keydown", (event) => {
    if (!document.body.classList.contains("navigation-open")) return;
    if (event.key === "Escape") { event.preventDefault(); closeNavigation(); }
    if (event.key === "Tab") {
      const controls = [...navigation.querySelectorAll('a[href], button:not([disabled])')].filter((element) => element.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  document.addEventListener("click", (event) => {
    document.querySelectorAll(".account-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".account-menu[open]").forEach((menu) => { menu.open = false; menu.querySelector("summary").focus(); });
  });

  // Extend Django's linked error/help descriptions to legacy hand-rendered fields.
  document.querySelectorAll(".form-field, .request-field").forEach((group, index) => {
    const errors = group.querySelector(".field-errors, .errorlist");
    if (!errors?.textContent.trim()) return;
    if (!errors.id) errors.id = `field-feedback-${index}`;
    group.querySelectorAll("input, select, textarea").forEach((field) => {
      field.setAttribute("aria-invalid", "true");
      const descriptions = new Set((field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
      descriptions.add(errors.id);
      field.setAttribute("aria-describedby", [...descriptions].join(" "));
    });
  });

  document.querySelectorAll("form[data-request-review]").forEach((form) => {
    const fields = form.querySelector("[data-request-fields]");
    const actions = form.querySelector("[data-request-actions]");
    const panel = form.querySelector("[data-review-panel]");
    const answers = form.querySelector("[data-review-content]");
    const reviewActions = form.querySelector("[data-review-actions]");
    const originalSubmit = actions?.querySelector('button[type="submit"]');
    if (!fields || !panel || !answers || !reviewActions || !originalSubmit) return;
    originalSubmit.textContent = "Revisar solicitação →";
    const dataStep = document.querySelector("[data-progress-data]");
    const reviewStep = document.querySelector("[data-progress-review]");
    const edit = () => {
      fields.hidden = false; actions.hidden = false; panel.hidden = true; reviewActions.hidden = true;
      delete form.dataset.reviewing;
      dataStep?.setAttribute("aria-current", "step"); reviewStep?.removeAttribute("aria-current");
      originalSubmit.focus();
    };
    form.querySelector("[data-review-edit]").addEventListener("click", edit);
    form.addEventListener("submit", (event) => {
      if (event.submitter?.hasAttribute("data-review-send") && form.dataset.reviewing) return;
      event.preventDefault();
      if (!form.reportValidity()) return;
      answers.replaceChildren();
      fields.querySelectorAll(".form-field, .request-field").forEach((group) => {
        const controls = [...group.querySelectorAll('input:not([type=hidden]), select, textarea')];
        if (!controls.length) return;
        const label = group.querySelector("legend, label");
        const values = controls.flatMap((control) => {
          if (control.type === "file") return [...control.files].map((file) => `${file.name} (${(file.size / 1024).toFixed(1)} KB)`);
          if (["checkbox", "radio"].includes(control.type)) return control.checked ? [control.labels?.[0]?.textContent.trim() || "Sim"] : [];
          if (control.tagName === "SELECT") return [...control.selectedOptions].filter((option) => option.value).map((option) => option.textContent.trim());
          if (control.type === "date" && control.value) return [control.value.split("-").reverse().join("/")];
          if (control.type === "datetime-local" && control.value) return [new Date(control.value).toLocaleString("pt-BR")];
          return control.value.trim() ? [control.value] : [];
        });
        const term = document.createElement("dt"), value = document.createElement("dd");
        term.textContent = label?.textContent.trim() || controls[0].name;
        value.textContent = values.join("\n") || "Não informado";
        answers.append(term, value);
      });
      fields.hidden = true; actions.hidden = true; panel.hidden = false; reviewActions.hidden = false;
      form.dataset.reviewing = "true";
      dataStep?.removeAttribute("aria-current"); reviewStep?.setAttribute("aria-current", "step");
      panel.focus();
    }, true);
    // If browser validation ever finds an invalid hidden control, reopen the data step.
    form.addEventListener("invalid", () => { if (form.dataset.reviewing) edit(); }, true);
    window.addEventListener("pageshow", () => {
      form.querySelectorAll("[data-review-send]").forEach((button) => {
        button.disabled = false;
        button.textContent = "Confirmar e enviar solicitação";
      });
    });
  });

  // Native dialog keeps focus inside confirmation and preserves the real submitter.
  const confirmation = document.querySelector("#action-confirmation");
  let pending = null;
  document.addEventListener("submit", (event) => {
    const button = event.submitter;
    const message = button?.dataset.confirm;
    if (!message || button.dataset.confirmed === "true" || !confirmation?.showModal) return;
    event.preventDefault();
    pending = {form: event.target, button};
    confirmation.querySelector("[data-confirmation-message]").textContent = message;
    confirmation.showModal();
    confirmation.querySelector("[data-confirmation-cancel]").focus();
  }, true);
  confirmation?.querySelector("[data-confirmation-cancel]").addEventListener("click", () => confirmation.close());
  confirmation?.querySelector("[data-confirmation-proceed]").addEventListener("click", () => {
    const submission = pending;
    confirmation.close();
    if (!submission) return;
    submission.button.dataset.confirmed = "true";
    submission.form.requestSubmit(submission.button);
    delete submission.button.dataset.confirmed;
  });
  confirmation?.addEventListener("close", () => {
    // A previous close event can arrive after a rapidly reopened dialog.
    if (confirmation.open) return;
    pending?.button.focus(); pending = null;
  });
});
