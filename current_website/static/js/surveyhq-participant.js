(() => {
  const form = document.querySelector("[data-participant-form]");
  if (!form) return;

  form.querySelectorAll("[data-linear-scale]").forEach((control) => {
    const answer = document.getElementById(control.dataset.answerId);
    const range = control.querySelector("[data-linear-range]");
    const output = control.querySelector("[data-linear-output]");
    const clear = control.querySelector("[data-linear-clear]");
    if (!answer || !range || !output) return;
    const commit = () => {
      answer.value = range.value;
      output.value = range.value;
      output.textContent = range.value;
      control.classList.add("participant-linear-scale--answered");
    };
    range.addEventListener("input", commit);
    range.addEventListener("change", commit);
    if (clear) clear.addEventListener("click", () => {
      answer.value = "";
      output.value = "";
      output.textContent = "Not answered";
      control.classList.remove("participant-linear-scale--answered");
      range.focus();
    });
  });

  form.querySelectorAll("[data-ranking]").forEach((ranking) => {
    const fallback = ranking.querySelector("[data-ranking-fallback]");
    const enhanced = ranking.querySelector("[data-ranking-enhanced]");
    const available = ranking.querySelector("[data-ranking-available]");
    const list = ranking.querySelector("[data-ranked-list]");
    const status = ranking.querySelector("[data-ranking-status]");
    const reset = ranking.querySelector("[data-ranking-reset]");
    if (!fallback || !enhanced || !available || !list) return;
    const records = new Map();
    fallback.querySelectorAll("[data-ranking-field]").forEach((row) => {
      records.set(row.dataset.choiceKey, {
        key: row.dataset.choiceKey,
        label: row.dataset.choiceLabel,
        select: row.querySelector("select"),
        add: available.querySelector(`[data-ranking-add="${CSS.escape(row.dataset.choiceKey)}"]`),
      });
    });
    let order = Array.from(records.values())
      .filter((item) => item.select && item.select.value)
      .sort((left, right) => Number(left.select.value) - Number(right.select.value))
      .map((item) => item.key);
    let draggedKey = null;

    const announce = (message) => { if (status) status.textContent = message; };
    const sync = () => records.forEach((item) => {
      if (item.select) item.select.value = order.includes(item.key) ? String(order.indexOf(item.key) + 1) : "";
    });
    const move = (key, delta) => {
      const index = order.indexOf(key);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= order.length) return;
      [order[index], order[target]] = [order[target], order[index]];
      render();
      announce(`${records.get(key).label} moved to position ${target + 1}.`);
    };
    const remove = (key) => {
      order = order.filter((value) => value !== key);
      render();
      announce(`${records.get(key).label} returned to available choices.`);
    };
    const render = () => {
      sync();
      list.replaceChildren();
      records.forEach((item) => { if (item.add) item.add.hidden = order.includes(item.key); });
      order.forEach((key, index) => {
        const item = records.get(key);
        const row = document.createElement("li");
        row.draggable = true;
        row.dataset.rankingItem = key;
        const label = document.createElement("span");
        label.textContent = item.label;
        const actions = document.createElement("span");
        actions.className = "participant-ranking-actions";
        [["Move Up", -1], ["Move Down", 1]].forEach(([text, delta]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = text;
          button.disabled = delta < 0 ? index === 0 : index === order.length - 1;
          button.addEventListener("click", () => move(key, delta));
          actions.appendChild(button);
        });
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.textContent = "Remove";
        removeButton.addEventListener("click", () => remove(key));
        actions.appendChild(removeButton);
        row.append(label, actions);
        row.addEventListener("dragstart", () => { draggedKey = key; row.classList.add("is-dragging"); });
        row.addEventListener("dragend", () => { draggedKey = null; row.classList.remove("is-dragging"); });
        row.addEventListener("dragover", (event) => event.preventDefault());
        row.addEventListener("drop", (event) => {
          event.preventDefault();
          if (!draggedKey || draggedKey === key) return;
          order = order.filter((value) => value !== draggedKey);
          order.splice(order.indexOf(key), 0, draggedKey);
          render();
          announce(`${records.get(draggedKey).label} moved to position ${order.indexOf(draggedKey) + 1}.`);
        });
        list.appendChild(row);
      });
    };
    records.forEach((item) => {
      if (item.add) item.add.addEventListener("click", () => {
        order.push(item.key);
        render();
        announce(`${item.label} added at position ${order.length}.`);
      });
    });
    if (reset) reset.addEventListener("click", () => {
      order = [];
      render();
      announce("Ranking reset.");
    });
    fallback.hidden = true;
    enhanced.hidden = false;
    render();
  });

  const pages = Array.from(form.querySelectorAll("[data-survey-page]"));
  if (pages.length < 2) return;
  const previous = form.querySelector("[data-previous]");
  const next = form.querySelector("[data-next]");
  const submit = form.querySelector("[data-submit]");
  const progress = form.querySelector("[data-progress]");
  const label = form.querySelector("[data-progress-label]");
  const bar = form.querySelector("[data-progress-bar]");
  let current = Math.max(0, pages.findIndex((page) => page.querySelector(".errorlist")));

  const show = (index, focus = false) => {
    current = Math.max(0, Math.min(index, pages.length - 1));
    pages.forEach((page, pageIndex) => { page.hidden = pageIndex !== current; });
    previous.hidden = current === 0;
    next.hidden = current === pages.length - 1;
    submit.hidden = current !== pages.length - 1;
    progress.hidden = false;
    label.textContent = `Page ${current + 1} of ${pages.length}`;
    bar.style.width = `${((current + 1) / pages.length) * 100}%`;
    if (focus) {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      pages[current].scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
      const target = pages[current].querySelector("input:not([type=hidden]), textarea, select, button");
      if (target) target.focus({ preventScroll: true });
    }
  };

  previous.addEventListener("click", () => show(current - 1, true));
  next.addEventListener("click", () => show(current + 1, true));
  show(current);
})();
