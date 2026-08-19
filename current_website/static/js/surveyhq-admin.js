(() => {
  const root = document.querySelector(".surveyhq-admin");
  if (!root) return;

  root.querySelectorAll("[data-copy-value]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyValue || "");
        const previous = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(() => { button.textContent = previous; }, 1400);
      } catch (_error) {
        button.textContent = "Copy unavailable";
      }
    });
  });

  const client = root.querySelector("[data-surveyhq-client]");
  const project = root.querySelector("[data-surveyhq-project]");
  if (client && project) {
    client.addEventListener("change", async () => {
      const selected = client.value;
      project.innerHTML = '<option value="">---------</option>';
      if (!selected) return;
      const url = new URL(root.dataset.projectOptionsUrl, window.location.origin);
      url.searchParams.set("client", selected);
      const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const payload = await response.json();
      payload.projects.forEach((item) => project.add(new Option(item.label, item.id)));
    });
  }

  const type = root.querySelector("[data-question-type]");
  if (type) {
    const groups = {
      placeholder: ["short_text", "long_text", "email"],
      max_length: ["short_text", "long_text"],
      minimum: ["number", "rating", "linear_scale"],
      maximum: ["number", "rating", "linear_scale"],
      step: ["number", "rating", "linear_scale"],
      low_anchor: ["number", "rating", "linear_scale"],
      high_anchor: ["number", "rating", "linear_scale"],
      likert_preset: ["likert"],
    };
    const update = () => {
      Object.entries(groups).forEach(([name, types]) => {
        const field = root.querySelector(`[data-config-field="${name}"]`);
        if (field) field.hidden = !types.includes(type.value);
      });
      const required = root.querySelector('[data-config-field="required"]');
      if (required) required.hidden = ["heading", "description", "page_break"].includes(type.value);
    };
    type.addEventListener("change", update);
    update();
  }
})();
