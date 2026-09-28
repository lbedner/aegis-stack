/* Chart island (the first of two JS islands; the other is chat).

   The server renders a <canvas data-chart="line|bar|doughnut"> next to a
   JSON block (see the chart_panel macro); this file mounts Chart.js over
   every such canvas on load and after each htmx settle. Chart.js itself
   is fetched on first use, so pages without charts pay nothing and a
   swap into a chart page still works. */

const CHART_JS = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js';
const RAMP = 8; // --aegis-chart-1 .. -8 in tailwind.config.js; cycles past that

// Colors come from the active theme's tokens, read at mount time so a
// theme switch repaints charts in the new palette.
function token(name, alpha) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return name.startsWith('--aegis-chart-')
    ? value
    : (alpha === undefined ? `oklch(${value})` : `oklch(${value} / ${alpha})`);
}
function rampColor(i) {
  return token(`--aegis-chart-${(i % RAMP) + 1}`);
}

let chartJsLoading = null;
function ensureChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (!chartJsLoading) {
    chartJsLoading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = CHART_JS;
      script.onload = () => resolve(window.Chart);
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  return chartJsLoading;
}

function money(value) {
  const abs = Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? '-' : ''}$${abs}`;
}

// Axis ticks and tooltips: plain numbers unless the data says
// ``"format": "money"``, so a generic chart never reads as dollars.
function formatValue(value, format) {
  return format === 'money' ? money(value) : Number(value).toLocaleString();
}

function datasets(kind, data) {
  const tail = token('--n'); // "Other" reads as tail, never as a category
  return data.series.map((series, i) => (series.points ? markers(series) : {
    label: series.label,
    data: series.values,
    backgroundColor:
      kind === 'doughnut'
        ? data.labels.map((label, j) => (label === 'Other' ? tail : rampColor(j)))
        : kind === 'line'
          ? token('--p', 0.15)
          : rampColor(i),
    borderColor: kind === 'line' ? token('--p') : undefined,
    borderWidth: kind === 'doughnut' ? 0 : 2,
    fill: kind === 'line',
    tension: 0.3,
    pointRadius: 0,
  }));
}

// A marker series (``{"points": true}``): dots where something happened,
// no line - the overdue days on a balance projection, say.
function markers(series) {
  return {
    label: series.label,
    data: series.values,
    showLine: false,
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBackgroundColor: token('--er'),
    pointBorderColor: token('--er'),
    spanGaps: false,
  };
}

function drilldownHandler(canvas, data) {
  const base = canvas.dataset.drilldown;
  if (!base || !data.slices) return undefined;
  return (_event, elements) => {
    if (!elements.length) return;
    const slice = data.slices[elements[0].index];
    if (!slice) return;
    const params = slice.categories.map((c) => `category=${encodeURIComponent(c)}`).join('&');
    htmx.ajax('GET', `${base}&${params}`, { target: '#dialog-body', swap: 'innerHTML' });
  };
}

function build(Chart, canvas) {
  const data = JSON.parse(document.getElementById(canvas.dataset.chartData).textContent);
  const kind = canvas.dataset.chart;
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
  const muted = token('--n');
  const grid = token('--b3');
  const axes = {
    x: { ticks: { color: muted }, grid: { color: grid } },
    y: { ticks: { color: muted, callback: (v) => formatValue(v, data.format) }, grid: { color: grid } },
  };
  new Chart(canvas, {
    type: kind,
    data: { labels: data.labels, datasets: datasets(kind, data) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: kind !== 'line',
          position: kind === 'doughnut' ? 'right' : 'top',
          labels: { color: muted, boxWidth: 10 },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value = kind === 'doughnut' ? ctx.parsed : ctx.parsed.y;
              return `${ctx.dataset.label ? `${ctx.dataset.label}: ` : ''}${formatValue(value, data.format)}`;
            },
          },
        },
      },
      scales: kind === 'doughnut' ? {} : axes,
      onClick: drilldownHandler(canvas, data),
    },
  });
}

function mount(root) {
  const canvases = root.querySelectorAll ? root.querySelectorAll('canvas[data-chart]') : [];
  if (!canvases.length) return;
  ensureChartJs().then((Chart) => {
    canvases.forEach((canvas) => {
      build(Chart, canvas);
    });
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => mount(document));
  document.body.addEventListener('htmx:afterSettle', (event) => mount(event.detail.elt));
  document.addEventListener('theme-changed', () => mount(document));
}

if (typeof module !== 'undefined') module.exports = { formatValue };
