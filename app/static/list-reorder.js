(() => {
  let dragging;
  let originalOrder;

  const itemRows = (body) => [...body.querySelectorAll("[data-item-id]")];
  const setStatus = (message) => {
    const status = document.querySelector("#reorder-status");
    if (status) status.textContent = message;
  };

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".sort-header");
    if (!button) return;
    const table = button.closest("table");
    const body = table.querySelector("tbody");
    const key = button.dataset.sortKey;
    const direction =
      body.dataset.sortKey === key && body.dataset.sortDirection === "asc" ? "desc" : "asc";
    const multiplier = direction === "asc" ? 1 : -1;
    const rows = itemRows(body);

    rows.sort((left, right) => {
      const leftValue = left.querySelector(`[data-sort-value][data-sort-key="${key}"]`);
      const rightValue = right.querySelector(`[data-sort-value][data-sort-key="${key}"]`);
      const leftSortValue = leftValue?.dataset.sortValue ?? "";
      const rightSortValue = rightValue?.dataset.sortValue ?? "";
      if (key === "quantity") return multiplier * (Number(leftSortValue) - Number(rightSortValue));
      return multiplier * leftSortValue.localeCompare(rightSortValue, undefined, {numeric: true});
    });

    rows.forEach((row) => body.append(row));
    body.dataset.sortKey = key;
    body.dataset.sortDirection = direction;
    table.querySelectorAll(".sort-header").forEach((header) => {
      header.closest("th").ariaSort =
        header === button ? (direction === "asc" ? "ascending" : "descending") : "none";
    });
    setStatus(`Items sorted by ${button.textContent} in ${direction}ending order.`);
  });

  document.addEventListener("dragstart", (event) => {
    if (!event.target.closest(".drag-handle")) return;
    const body = event.target.closest("tbody[data-reorder-url]");
    dragging = event.target.closest("[data-item-id]");
    if (!body || !dragging) return;
    originalOrder = itemRows(body).map((row) => row.dataset.itemId);
    dragging.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragging.dataset.itemId);
  });

  document.addEventListener("dragover", (event) => {
    const body = event.target.closest("tbody[data-reorder-url]");
    if (!body || !dragging) return;
    event.preventDefault();
    const target = event.target.closest("[data-item-id]");
    if (!target || target === dragging) return;
    const after = event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2;
    target.classList.add("drag-over");
    body.insertBefore(dragging, after ? target.nextSibling : target);
  });

  document.addEventListener("dragleave", (event) => {
    event.target.closest("[data-item-id]")?.classList.remove("drag-over");
  });

  document.addEventListener("dragend", async (event) => {
    if (!dragging || !event.target.closest(".drag-handle")) return;
    const body = dragging.closest("tbody[data-reorder-url]");
    dragging.classList.remove("dragging");
    itemRows(body).forEach((row) => row.classList.remove("drag-over"));
    const itemIds = itemRows(body).map((row) => row.dataset.itemId);
    const changed = itemIds.some((itemId, index) => itemId !== originalOrder[index]);
    dragging = undefined;
    if (!changed) return;

    setStatus("Saving item order…");
    try {
      const response = await fetch(body.dataset.reorderUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({item_ids: itemIds}),
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("The server rejected the new item order.");
      setStatus("Item order saved.");
    } catch (error) {
      const rows = new Map(itemRows(body).map((row) => [row.dataset.itemId, row]));
      originalOrder.forEach((itemId) => body.append(rows.get(itemId)));
      setStatus(error.message);
    }
  });
})();
