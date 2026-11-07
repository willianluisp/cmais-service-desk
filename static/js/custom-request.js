document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-required-choice]").forEach((group) => {
    const boxes = [...group.querySelectorAll('input[type="checkbox"]')];
    if (!boxes.length) return;
    const validate = () => boxes[0].setCustomValidity(boxes.some((box) => box.checked) ? "" : "Selecione pelo menos uma opção.");
    boxes.forEach((box) => box.addEventListener("change", validate));
    validate();
  });
});
