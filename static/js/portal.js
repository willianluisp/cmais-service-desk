document.addEventListener("DOMContentLoaded", () => {
  document.querySelector(".error-summary")?.focus();
  document.querySelectorAll("form[data-submit-feedback]").forEach((form) => {
    let button = form.querySelector('button[type="submit"]');
    const reset = () => {
      form.removeAttribute("aria-busy");
      delete form.dataset.busy;
      if (button?.dataset.originalLabel) { button.textContent = button.dataset.originalLabel; button.disabled = false; }
    };
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      if (form.dataset.busy) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      button = event.submitter || button;
      form.dataset.busy = "true";
      form.setAttribute("aria-busy", "true");
      if (button) {
        button.dataset.originalLabel = button.textContent;
        button.textContent = button.dataset.loadingLabel || "Enviando…";
        button.disabled = true;
      }
      const status = form.querySelector("[data-submit-status]");
      if (status) status.textContent = "Enviando sua solicitação. Aguarde a confirmação nesta página.";
    });
    window.addEventListener("pageshow", reset);
  });
});
["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((name) => {
  document.addEventListener(name, (event) => {
    if (event.detail.elt?.closest("#planner-status")) {
      const feedback = document.querySelector("#planner-feedback");
      if (feedback && event.detail.xhr?.getResponseHeader("X-Planner-Feedback") !== "error") feedback.textContent = "Não foi possível consultar agora. As informações anteriores foram preservadas. Tente novamente mais tarde.";
    }
  });
});
document.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.elt?.closest("#planner-status") &&
      event.detail.xhr?.getResponseHeader("X-Planner-Feedback") === "error") {
    event.detail.shouldSwap = true;
  }
});
