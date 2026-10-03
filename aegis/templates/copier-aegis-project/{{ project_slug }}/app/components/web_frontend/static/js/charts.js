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

// The same units as format_bytes in app/core/formatting.py.
function bytes(value) {
  if (value < 1024) return `${Math.trunc(value)} B`;
  let size = value;
  for (const unit of ['KB', 'MB', 'GB', 'TB']) {
    size /= 1024;
    if (size < 1024 || unit === 'TB') return `${size.toFixed(1)} ${unit}`;
  }
  return `${size.toFixed(1)} TB`;
}

// Axis ticks and tooltips: plain numbers unless the data says how to read
// them (``"format": "money" | "percent" | "bytes" | "seconds"``), so a generic chart
// never reads as dollars.
function formatValue(value, format) {
  if (format === 'money') return money(value);
  if (format === 'percent') return `${Number(value).toFixed(1)}%`;
  if (format === 'bytes') return bytes(value);
  if (format === 'seconds') return value < 10 ? `${Number(value).toFixed(1)} s` : `${Math.round(value)} s`;
  return Number(value).toLocaleString();
}

// ``"x": "time"``: the labels are epoch ms, shown on the viewer's clock,
// and each point is plotted at its own time ({x, y}), so a live chart can
// slide along as points come and go (see refresh).
// The tooltip reads the second; an axis tick, only the minute.
function clock(ms, seconds = true) {
  const parts = { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) };
  return new Date(ms).toLocaleTimeString([], parts);
}

// A time axis ticks on the clock: the first of these steps that gives at
// most six ticks, at its whole multiples (11:39, 11:42, ... for 15 minutes).
const TIME_STEPS = [60e3, 120e3, 180e3, 300e3, 600e3, 900e3, 1800e3, 3600e3];
function timeTicks(min, max) {
  const step = TIME_STEPS.find((s) => (max - min) / s <= 6) || TIME_STEPS[TIME_STEPS.length - 1];
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) ticks.push(t);
  return ticks;
}

// A byte axis steps in round amounts of one unit (5 GB, 50 MB), not
// whatever decimal step the raw byte count suggests.
function byteStep(max) {
  if (!(max > 0)) return undefined;
  const unit = 1024 ** Math.min(Math.floor(Math.log(max) / Math.log(1024)), 4);
  const step = [1, 2, 5, 10, 20, 50, 100, 200, 500].find((s) => max / unit / s <= 6) || 1000;
  return step * unit;
}
function highest(data) {
  return Math.max(0, ...data.series.flatMap((series) => series.values.filter((v) => v !== null)));
}
function timed(data) {
  return data.x === 'time';
}
// A time axis spans the data's ``window`` (from then to now) when it has
// one, its own first and last points otherwise.
function span(data) {
  return data.window || [data.labels[0], data.labels[data.labels.length - 1]];
}

// ``chart_panel(empty=...)``: said over the chart while its data has no
// ``points`` (counted by ``series.chart``).
function showEmpty(canvas, data) {
  canvas.parentElement?.querySelector('[data-chart-empty]')?.classList.toggle('hidden', data.points > 0);
}
function values(data, series) {
  return timed(data) ? series.values.map((y, i) => ({ x: data.labels[i], y })) : series.values;
}

// One line is the theme's teal over a soft fill; several are the ramp,
// unfilled, with a legend to tell them apart.
function datasets(kind, data) {
  const tail = token('--n'); // "Other" reads as tail, never as a category
  const many = data.series.length > 1;
  const line = (i) => (many ? rampColor(i) : token('--p'));
  // ``"style": "events"`` (see series.chart): dots, no line.
  const events = data.style === 'events';
  return data.series.map((series, i) => (series.points || events ? markers(data, series, events ? line(i) : token('--er')) : {
    label: series.label,
    data: values(data, series),
    backgroundColor:
      kind === 'doughnut'
        ? data.labels.map((label, j) => (label === 'Other' ? tail : rampColor(j)))
        : kind === 'line'
          ? (many ? line(i) : token('--p', 0.15))
          : rampColor(i),
    borderColor: kind === 'line' ? line(i) : undefined,
    borderWidth: kind === 'doughnut' ? 0 : 2,
    fill: kind === 'line' && !many,
    tension: 0.3,
    pointRadius: 0,
    // Hovering anywhere over the chart lands on the nearest time (see the
    // interaction option in build); the point there grows to show it.
    pointHoverRadius: 5,
    pointHoverBorderWidth: 2,
    pointHoverBackgroundColor: token('--b2'),
    pointHoverBorderColor: line(i),
  }));
}

// Dots where something happened, no line: a marker series
// (``{"points": true}``, the overdue days on a balance projection, in the
// error colour) or a chart of events (``"style": "events"``, in its own).
function markers(data, series, color) {
  return {
    label: series.label,
    data: values(data, series),
    showLine: false,
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBackgroundColor: color,
    pointBorderColor: color,
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
  showEmpty(canvas, data);
  const muted = token('--n');
  const grid = token('--b3');
  const axes = {
    // Times on a real time axis, read flat and spaced out however many
    // points there are; anything else by its labels.
    x: timed(data)
      ? {
        type: 'linear',
        min: span(data)[0],
        max: span(data)[1],
        ticks: { color: muted, maxRotation: 0, callback: (ms) => clock(ms, false) },
        afterBuildTicks: (axis) => { axis.ticks = timeTicks(axis.min, axis.max).map((value) => ({ value })); },
        grid: { color: grid },
      }
      : { ticks: { color: muted }, grid: { color: grid } },
    // A time chart measures from zero, so a small change reads as small.
    y: {
      beginAtZero: timed(data),
      ticks: {
        color: muted,
        callback: (v) => formatValue(v, data.format),
        stepSize: data.format === 'bytes' ? byteStep(highest(data)) : undefined,
      },
      grid: { color: grid },
    },
  };
  new Chart(canvas, {
    type: kind,
    data: { labels: timed(data) ? undefined : data.labels, datasets: datasets(kind, data) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // Every value at the hovered spot, from anywhere over the chart, not
      // only on a line's exact pixel.
      interaction: kind === 'doughnut' ? { mode: 'nearest' } : { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: kind !== 'line' || data.series.length > 1,
          position: kind === 'doughnut' ? 'right' : 'top',
          labels: { color: muted, boxWidth: 10 },
        },
        tooltip: {
          backgroundColor: token('--b2'),
          borderColor: token('--b3'),
          borderWidth: 1,
          titleColor: muted,
          bodyColor: token('--bc'),
          bodyFont: { weight: '600' },
          padding: 10,
          boxPadding: 4,
          callbacks: {
            title: (items) => (items.length && timed(data) ? clock(items[0].parsed.x) : items[0]?.label ?? ''),
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

// A time series moving on: the points older than the new window leave from
// the front and the new ones join at the back, on the same array, so every
// other point (and a hovered tooltip) stays where it was.
function slide(dataset, points) {
  const live = dataset.data;
  const from = points.length ? points[0].x : Infinity;
  while (live.length && live[0].x < from) live.shift();
  const last = live[live.length - 1];
  // A long window's newest bucket fills as the tick goes on: it moves.
  const same = last && points.find((point) => point.x === last.x);
  if (same) last.y = same.y;
  const after = last ? last.x : -Infinity;
  points.filter((point) => point.x > after).forEach((point) => live.push(point));
}

// A live chart's data script swapped in again (``chart_panel(live=...)``):
// the drawn chart takes the new data in place, without animation: a tick
// moves a time chart's line under a pixel, and an animated new point swoops
// in from the axis so the line's end redraws itself every tick. A change in
// how many series there are rebuilds them.
function refresh(Chart, script) {
  const canvas = document.querySelector(`canvas[data-chart-data="${script.id}"]`);
  const chart = canvas && Chart.getChart(canvas);
  if (!chart) return false;
  const data = JSON.parse(script.textContent);
  showEmpty(canvas, data);
  if (chart.data.datasets.length !== data.series.length) {
    chart.data.datasets = datasets(canvas.dataset.chart, data);
  } else if (timed(data)) {
    data.series.forEach((series, i) => slide(chart.data.datasets[i], values(data, series)));
  } else {
    data.series.forEach((series, i) => {
      Object.assign(chart.data.datasets[i], { label: series.label, data: series.values });
    });
  }
  if (timed(data)) {
    const [min, max] = span(data);
    Object.assign(chart.options.scales.x, { min, max });
  } else {
    chart.data.labels = data.labels;
  }
  if (data.format === 'bytes') chart.options.scales.y.ticks.stepSize = byteStep(highest(data));
  chart.update('none');
  return true;
}

function mount(root) {
  if (!root.querySelectorAll) return;
  const canvases = [...root.querySelectorAll('canvas[data-chart]')];
  const drawn = new Set(canvases.map((canvas) => canvas.dataset.chartData));
  const fresh = [...root.querySelectorAll('script[type="application/json"][id^="chart-"]')]
    .filter((script) => !drawn.has(script.id));
  if (!canvases.length && !fresh.length) return;
  ensureChartJs().then((Chart) => {
    canvases.forEach((canvas) => build(Chart, canvas));
    fresh.forEach((script) => refresh(Chart, script));
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => mount(document));
  document.body.addEventListener('htmx:afterSettle', (event) => mount(event.detail.elt));
  document.addEventListener('theme-changed', () => mount(document));
}

if (typeof module !== 'undefined') module.exports = { formatValue, refresh, timeTicks, byteStep };
