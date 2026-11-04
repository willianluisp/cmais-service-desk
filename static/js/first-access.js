document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.querySelector("#first-access-dialog");
  if (!dialog) return;
  // With JavaScript disabled the open dialog is the entire standalone page.
  // The server gate remains authoritative in both cases.
  dialog.removeAttribute("open");
  dialog.showModal();
  dialog.addEventListener("cancel", (event) => event.preventDefault());
  dialog.addEventListener("close", () => dialog.showModal());
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = Array.from(dialog.querySelectorAll('button, input:not([type="hidden"]), a[href]'))
      .filter((element) => !element.disabled && element.getClientRects().length);
    const firstControl = controls[0];
    const lastControl = controls.at(-1);
    if (event.shiftKey && document.activeElement === firstControl) {
      event.preventDefault();
      lastControl.focus();
    } else if (!event.shiftKey && document.activeElement === lastControl) {
      event.preventDefault();
      firstControl.focus();
    }
  });
  const form = document.querySelector("#first-access-form");
  const first = form.elements.new_password1;
  const second = form.elements.new_password2;
  const feedback = document.querySelector("#password-feedback");
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      button.textContent = visible ? "Ocultar" : "Mostrar";
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute("aria-label", `${visible ? "Ocultar" : "Mostrar"} ${input.name === "new_password1" ? "nova senha" : "confirmação da nova senha"}`);
    });
  });
  const update = () => {
    const checks = {
      length: Array.from(first.value).length >= 8,
      numeric: Boolean(first.value) && !/^\d+$/.test(first.value),
      match: Boolean(second.value) && first.value === second.value,
    };
    Object.entries(checks).forEach(([rule, valid]) => {
      dialog.querySelector(`[data-rule="${rule}"]`).classList.toggle("is-met", valid);
    });
    second.setCustomValidity(second.value && !checks.match ? "As senhas não coincidem." : "");
    feedback.textContent = checks.length && checks.numeric && checks.match
      ? "Os requisitos indicados foram atendidos. Confirme para validar e salvar sua senha."
      : "";
  };
  first.addEventListener("input", update);
  second.addEventListener("input", update);
  form.addEventListener("submit", () => {
    form.setAttribute("aria-busy", "true");
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Salvando sua senha…";
  });
  window.addEventListener("pageshow", () => {
    form.removeAttribute("aria-busy");
    const button = form.querySelector('button[type="submit"]');
    button.disabled = false;
    button.textContent = "Salvar senha e entrar";
    update();
  });
  document.querySelector(".error-summary")?.focus();
});
