document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#user_form");
  if (!form) return;
  const username = form.querySelector("#id_username");
  const first = form.querySelector("#id_first_name");
  const last = form.querySelector("#id_last_name");
  const creating = Boolean(form.querySelector("#id_temporary_password"));
  let manual = Boolean(username?.value);
  const normalize = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().trim().replace(/\s+/g, ".").replace(/[^a-z0-9.]/g, "")
    .replace(/\.+/g, ".").replace(/^\.|\.$/g, "");
  username?.addEventListener("input", () => { manual = true; });
  const suggest = () => {
    if (!creating || manual || !username) return;
    const parts = [normalize(first?.value || ""), normalize(last?.value || "")];
    username.value = parts.every(Boolean) ? parts.join(".").slice(0, username.maxLength) : "";
  };
  first?.addEventListener("input", suggest);
  last?.addEventListener("input", suggest);
  const snapshot = () => JSON.stringify(Array.from(new FormData(form).entries())
    .filter(([name]) => name !== "csrfmiddlewaretoken"));
  const initial = snapshot();
  let submitting = false;
  form.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("pageshow", () => { submitting = false; });
  window.addEventListener("beforeunload", (event) => {
    if (!submitting && snapshot() !== initial) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
});
