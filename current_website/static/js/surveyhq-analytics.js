(() => {
  const root = document.querySelector("[data-survey-analytics]");
  const payloadNode = document.getElementById("surveyhq-analytics-data");
  if (!root || !payloadNode) return;

  const palette = ["#b88420", "#173b68", "#547ca8", "#d5ad5d", "#6e7f91", "#8b6b32", "#2e5d83"];
  const charts = new Map();
  let analytics;
  try {
    analytics = JSON.parse(payloadNode.textContent);
  } catch (_error) {
    return;
  }

  const displayValue = (value) => {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
    return String(value);
  };

  const chartOptions = (question) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 250 },
    indexAxis: ["choice", "multiple_choice", "numeric", "date"].includes(question.kind) ? "y" : "x",
    plugins: {
      legend: { display: question.chart.datasets.length > 1, position: "bottom" },
      tooltip: { enabled: true },
    },
    scales: {
      x: { beginAtZero: true, stacked: Boolean(question.chart.stacked), ticks: { precision: 0 } },
      y: { beginAtZero: true, stacked: Boolean(question.chart.stacked), ticks: { precision: 0 } },
    },
  });

  const renderChart = (question) => {
    if (!question.chart || typeof window.Chart === "undefined") return;
    const canvas = root.querySelector(`[data-question-chart="${question.id}"]`);
    if (!canvas) return;
    const existing = charts.get(question.id);
    if (existing) existing.destroy();
    const datasets = question.chart.datasets.map((dataset, index) => ({
      ...dataset,
      backgroundColor: palette[index % palette.length],
      borderColor: palette[index % palette.length],
      borderWidth: 1,
      borderRadius: 3,
    }));
    charts.set(question.id, new window.Chart(canvas, {
      type: question.chart.type,
      data: { labels: question.chart.labels, datasets },
      options: chartOptions(question),
    }));
  };

  const addCell = (row, value, header = false) => {
    const cell = document.createElement(header ? "th" : "td");
    cell.textContent = displayValue(value);
    row.appendChild(cell);
    return cell;
  };

  const renderTable = (question, card) => {
    const body = card.querySelector("[data-analytics-table]");
    if (!body || question.kind === "text") return;
    body.replaceChildren();
    if (question.kind === "matrix") {
      question.matrix_rows.forEach((item) => {
        const row = document.createElement("tr");
        addCell(row, item.label, true);
        addCell(row, item.response_count);
        addCell(row, item.missing_count);
        addCell(row, item.weighted_mean);
        addCell(row, item.distribution.map((option) => `${option.label}: ${option.count} (${option.percentage}%)`).join(" · "));
        body.appendChild(row);
      });
      return;
    }
    if (question.kind === "ranking") {
      question.rows.forEach((item) => {
        const row = document.createElement("tr");
        addCell(row, item.label, true);
        addCell(row, item.average_rank);
        addCell(row, item.first_choice_count);
        addCell(row, item.distribution.map((rank) => `${rank.rank}: ${rank.count}`).join(" · "));
        body.appendChild(row);
      });
      return;
    }
    if (!question.rows.length) {
      const row = document.createElement("tr");
      const cell = addCell(row, "No submitted values.");
      cell.colSpan = 3;
      cell.className = "svhq-empty";
      body.appendChild(row);
      return;
    }
    question.rows.forEach((item) => {
      const row = document.createElement("tr");
      addCell(row, item.label, true);
      addCell(row, item.count);
      addCell(row, `${item.percentage}%`);
      body.appendChild(row);
    });
  };

  const renderQuestion = (question) => {
    const card = root.querySelector(`[data-question-id="${question.id}"]`);
    if (!card) return;
    ["total_responses", "response_count", "missing_count"].forEach((key) => {
      const node = card.querySelector(`[data-question-metric="${key}"]`);
      if (node) node.textContent = displayValue(question[key]);
    });
    Object.entries(question.statistics || {}).forEach(([key, value]) => {
      const node = card.querySelector(`[data-stat-key="${key}"]`);
      if (node) node.textContent = displayValue(value);
    });
    renderTable(question, card);
    renderChart(question);
  };

  const render = (data) => {
    Object.entries(data.summary).forEach(([key, value]) => {
      const node = root.querySelector(`[data-summary-key="${key}"]`);
      if (node) node.textContent = displayValue(value);
    });
    data.questions.forEach(renderQuestion);
    const refreshed = root.querySelector("[data-last-refresh]");
    if (refreshed) refreshed.textContent = `Current as of ${new Date(data.generated_at).toLocaleString()}`;
  };

  render(analytics);

  let polling = false;
  const poll = async () => {
    if (document.hidden || polling) return;
    polling = true;
    try {
      const response = await fetch(root.dataset.pollUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      if (data.analytics) render(data.analytics);
    } catch (_error) {
      // Preserve the last successfully rendered analytics and retry on the next interval.
    } finally {
      polling = false;
    }
  };

  const interval = window.setInterval(poll, 20000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });
  window.addEventListener("pagehide", () => window.clearInterval(interval), { once: true });
})();
