document.addEventListener("DOMContentLoaded", () => {
  const search = document.querySelector("#searchbar");
  if (search && !search.placeholder) search.placeholder = "Digite para buscar";
  const table = document.querySelector("#result_list");
  if (!table) return;
  const headings = [...table.querySelectorAll("thead th")].map((heading) => heading.textContent.trim());
  table.querySelectorAll("tbody tr").forEach((row) => {
    [...row.children].forEach((cell, index) => {
      if (headings[index] && !cell.classList.contains("action-checkbox")) cell.dataset.label = headings[index];
    });
  });
});
