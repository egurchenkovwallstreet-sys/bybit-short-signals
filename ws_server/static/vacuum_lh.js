/* Пылесос LH: lower highs на 30m / 1H / 4H, график того же TF. */

const VACUUM_TF = [
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
];

const vacuumLhState = {
  lhInterval: "60",
  byInterval: {},
  updatedAt: 0,
  loading: false,
  loaded: false,
  signals: [],
  selected: null,
  detail: null,
  chart: null,
  chart5: null,
  chart15: null,
  tfBound: false,
};

const VAC_CHART = {
  listWrap: "vacuum-lh-list-wrap",
  workspace: "vacuum-lh-workspace",
  chart: "vacuum-lh-candle-chart",
  chart5: "vacuum-lh-candle-chart-5",
  chart15: "vacuum-lh-candle-chart-15",
  mainLabel: "vacuum-lh-main-label",
  info: "vacuum-lh-info-pane",
  tfRow: "vacuum-lh-tf-row",
  status: "vacuum-lh-status",
};

const VACUUM_CHART_PANELS = [
  { stateKey: "chart", elId: VAC_CHART.chart, intervalKey: "lh" },
  { stateKey: "chart5", elId: VAC_CHART.chart5, interval: "5" },
  { stateKey: "chart15", elId: VAC_CHART.chart15, interval: "15" },
];

const PEAK_COLORS = ["#e9c46a", "#f4a261", "#e76f51", "#d62828", "#9d0208"];

function initVacuumLhTab() {
  if (!window.__vacuumLhBound) {
    window.__vacuumLhBound = true;
    if (window.boardChart?.createRuntime) {
      vacuumLhState.chart = window.boardChart.createRuntime();
      vacuumLhState.chart5 = window.boardChart.createRuntime();
      vacuumLhState.chart15 = window.boardChart.createRuntime();
    }
    document.getElementById("vacuum-lh-grid")?.addEventListener("click", (event) => {
      const card = event.target instanceof Element ? event.target.closest(".vacuum-lh-card") : null;
      if (card?.dataset.symbol) toggleVacuumLhSymbol(card.dataset.symbol);
    });
    document.getElementById(VAC_CHART.info)?.addEventListener("click", (event) => {
      if (event.target instanceof Element && event.target.closest(".vacuum-lh-close")) {
        closeVacuumLhChart();
      }
    });
  }
  bindVacuumTfRow();
  if (!vacuumLhState.loaded && !vacuumLhState.loading) {
    void fetchVacuumLhBoard();
  }
  applyVacuumInterval(vacuumLhState.lhInterval);
  renderVacuumLhBoard();
}

function bindVacuumTfRow() {
  if (vacuumLhState.tfBound) return;
  const row = document.getElementById(VAC_CHART.tfRow);
  if (!row) return;
  vacuumLhState.tfBound = true;
  row.innerHTML = VACUUM_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf psc-tf${code === vacuumLhState.lhInterval ? " active" : ""}" data-vac-interval="${code}">${label}</button>`,
  ).join("");
  row.addEventListener("click", (event) => {
    const btn = event.target instanceof Element ? event.target.closest("[data-vac-interval]") : null;
    if (!btn?.dataset.vacInterval) return;
    setVacuumLhInterval(btn.dataset.vacInterval);
  });
}

function setVacuumLhInterval(interval) {
  if (vacuumLhState.lhInterval === interval) return;
  vacuumLhState.lhInterval = interval;
  document.querySelectorAll("#vacuum-lh-tf-row .psc-tf").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.vacInterval === interval);
  });
  applyVacuumInterval(interval);
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "vacuum_lh_interval", interval }));
  }
  if (!vacuumLhState.byInterval[interval]) {
    void fetchVacuumLhBoard(interval);
  }
  renderVacuumLhBoard();
  if (vacuumLhState.selected) {
    vacuumLhState.detail = null;
    void refreshVacuumLhChart(true);
  }
}

function applyVacuumInterval(interval) {
  vacuumLhState.signals = vacuumLhState.byInterval[interval] || [];
}

function setVacuumStatus(text) {
  const el = document.getElementById(VAC_CHART.status);
  if (el) el.textContent = text;
}

async function fetchVacuumLhBoard(interval) {
  const iv = interval || vacuumLhState.lhInterval;
  vacuumLhState.loading = true;
  setVacuumStatus("Загрузка списка…");
  renderVacuumLhBoard();
  try {
    const res = await fetch(`/api/vacuum-lh/board?interval=${encodeURIComponent(iv)}`);
    if (res.ok) {
      const data = await res.json();
      vacuumLhState.byInterval[iv] = data.signals || [];
      vacuumLhState.updatedAt = data.updated_at || vacuumLhState.updatedAt;
      vacuumLhState.loaded = true;
      applyVacuumInterval(vacuumLhState.lhInterval);
    }
  } catch (_e) {
    setVacuumStatus("Не удалось загрузить список");
  } finally {
    vacuumLhState.loading = false;
    setVacuumStatus(
      vacuumLhState.updatedAt
        ? `Обновлено: ${new Date(vacuumLhState.updatedAt).toLocaleTimeString("ru-RU")} · TF ${labelTf(vacuumLhState.lhInterval)}`
        : "",
    );
    renderVacuumLhBoard();
  }
}

function labelTf(code) {
  return VACUUM_TF.find(([c]) => c === code)?.[1] || code;
}

function ingestVacuumPayload(data) {
  if (!data) return;
  if (data.intervals && typeof data.intervals === "object") {
    for (const [iv, rows] of Object.entries(data.intervals)) {
      vacuumLhState.byInterval[iv] = rows || [];
    }
    vacuumLhState.updatedAt = data.updated_at || vacuumLhState.updatedAt;
    vacuumLhState.loaded = true;
    applyVacuumInterval(vacuumLhState.lhInterval);
  } else if (Array.isArray(data)) {
    vacuumLhState.byInterval[vacuumLhState.lhInterval] = data;
    applyVacuumInterval(vacuumLhState.lhInterval);
  } else if (data.signals) {
    const iv = data.interval || vacuumLhState.lhInterval;
    vacuumLhState.byInterval[iv] = data.signals;
    vacuumLhState.updatedAt = data.updated_at || vacuumLhState.updatedAt;
    applyVacuumInterval(vacuumLhState.lhInterval);
  }
  setVacuumStatus(
    vacuumLhState.updatedAt
      ? `Обновлено: ${new Date(vacuumLhState.updatedAt).toLocaleTimeString("ru-RU")} · TF ${labelTf(vacuumLhState.lhInterval)}`
      : "",
  );
  renderVacuumLhBoard();
}

function findVacuumRow(symbol) {
  return vacuumLhState.signals.find((s) => s.symbol === symbol);
}

function toggleVacuumLhSymbol(symbol) {
  if (vacuumLhState.selected === symbol) {
    closeVacuumLhChart();
    return;
  }
  vacuumLhState.selected = symbol;
  vacuumLhState.detail = null;
  openVacuumLhChart();
  renderVacuumLhBoard();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_vacuum_lh", symbol }));
  }
  const iv = vacuumLhState.lhInterval;
  window.boardChart.scheduleAssetsPrefetch([symbol], {
    intervals: [iv, "5", "15"],
    book: true,
    liq: false,
    priority: "high",
  });
  void refreshVacuumLhChart(true);
}

function vacuumChartRuntime(stateKey) {
  return vacuumLhState[stateKey];
}

function panelInterval(panel) {
  return panel.intervalKey === "lh" ? vacuumLhState.lhInterval : panel.interval;
}

function ensureVacuumRuntimes() {
  const BC = window.boardChart;
  if (!BC?.createRuntime) return;
  for (const panel of VACUUM_CHART_PANELS) {
    if (!vacuumLhState[panel.stateKey]) {
      vacuumLhState[panel.stateKey] = BC.createRuntime();
    }
  }
}

function mountVacuumCharts() {
  const BC = window.boardChart;
  if (!BC?.mount) return;
  ensureVacuumRuntimes();
  for (const panel of VACUUM_CHART_PANELS) {
    const rt = vacuumChartRuntime(panel.stateKey);
    if (rt && !rt.series) BC.mount(rt, panel.elId);
  }
  updateVacuumMainChartLabel();
}

function updateVacuumMainChartLabel() {
  const el = document.getElementById(VAC_CHART.mainLabel);
  if (el) el.textContent = `LH · ${labelTf(vacuumLhState.lhInterval)}`;
}

function openVacuumLhChart() {
  document.getElementById(VAC_CHART.listWrap)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.workspace)?.removeAttribute("hidden");
  mountVacuumCharts();
  renderVacuumLhInfo();
}

function closeVacuumLhChart() {
  vacuumLhState.selected = null;
  vacuumLhState.detail = null;
  for (const panel of VACUUM_CHART_PANELS) {
    clearVacuumPeakOverlays(vacuumChartRuntime(panel.stateKey));
  }
  document.getElementById(VAC_CHART.workspace)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.listWrap)?.removeAttribute("hidden");
  renderVacuumLhBoard();
}

function onVacuumLhBoard(data) {
  ingestVacuumPayload(data);
  if (vacuumLhState.selected) void refreshVacuumLhChart(false);
}

function onVacuumLhSnapshot(board, detail) {
  ingestVacuumPayload(board);
  if (detail?.signal && vacuumLhState.selected === detail.signal.symbol) {
    vacuumLhState.detail = detail;
    renderVacuumLhInfo();
    redrawVacuumLhPeakOverlays(detail.signal.peaks || []);
  }
}

function onVacuumLhDetail(symbol, data) {
  if (!vacuumLhState.selected || vacuumLhState.selected !== symbol) return;
  vacuumLhState.detail = data;
  renderVacuumLhInfo();
  redrawVacuumLhPeakOverlays(data?.signal?.peaks || []);
}

function redrawVacuumLhPeakOverlays(peaks) {
  for (const panel of VACUUM_CHART_PANELS) {
    const rt = vacuumChartRuntime(panel.stateKey);
    if (rt?.series) drawVacuumPeakOverlays(rt, peaks, panelInterval(panel));
  }
}

function renderVacuumLhBoard() {
  const grid = document.getElementById("vacuum-lh-grid");
  if (!grid) return;
  if (vacuumLhState.loading) {
    grid.innerHTML = '<p class="quiet pump-strategy-empty">Загрузка монет…</p>';
    return;
  }
  if (!vacuumLhState.signals.length) {
    grid.innerHTML = `<p class="quiet pump-strategy-empty">На ${labelTf(vacuumLhState.lhInterval)}: нет монет с ≥3 LH и ценой ниже 3 последних вершин (оборот &gt; $300k). Список обновляется каждые ~45 с.</p>`;
    return;
  }
  grid.innerHTML = vacuumLhState.signals
    .map((row) => {
      const sel = row.symbol === vacuumLhState.selected ? " selected" : "";
      const peaks = (row.peaks || []).map((p) => p.price).join(" · ");
      return `<article class="vacuum-lh-card pump-strategy-card${sel}" data-symbol="${row.symbol}">
        <strong>${row.symbol}</strong>
        <span class="quiet">${Number(row.last_price).toFixed(4)}</span>
        <span class="quiet">−${row.gap_to_nearest_pct}% до LH</span>
        <span class="quiet peaks-line">${peaks}</span>
      </article>`;
    })
    .join("");
}

function renderVacuumLhInfo() {
  const pane = document.getElementById(VAC_CHART.info);
  if (!pane) return;
  const sym = vacuumLhState.selected;
  if (!sym) {
    pane.innerHTML = "";
    return;
  }
  const row = vacuumLhState.detail?.signal || findVacuumRow(sym) || {};
  const peaks = row.peaks || [];
  const tf = labelTf(vacuumLhState.lhInterval);
  const list = peaks
    .map(
      (p) =>
        `<li>LH${p.index}: <strong>${p.price}</strong> (${tf} ${new Date(p.time_ms).toLocaleString("ru-RU")})</li>`,
    )
    .join("");
  pane.innerHTML = `
    <div class="psc-info-head">
      <h3>${sym}</h3>
      <button type="button" class="paper-btn vacuum-lh-close">Закрыть</button>
    </div>
    <p>LH на <strong>${tf}</strong> + графики <strong>5m</strong> и <strong>15m</strong>. Линии LH — с TF скана.</p>
    <p>Цена: <strong>${row.last_price ?? "—"}</strong></p>
    <ul class="vacuum-lh-peaks">${list || "<li>—</li>"}</ul>`;
}

function clearVacuumPeakOverlays(runtime) {
  if (!runtime?.series) return;
  if (runtime._vacuumPeakLines?.length) {
    for (const line of runtime._vacuumPeakLines) {
      try {
        runtime.series.removePriceLine(line);
      } catch (_e) {
        /* ignore */
      }
    }
  }
  runtime._vacuumPeakLines = [];
  try {
    runtime.series.setMarkers([]);
  } catch (_e) {
    /* ignore */
  }
}

function drawVacuumPeakOverlays(runtime, peaks, chartInterval) {
  if (!runtime?.series) return;
  clearVacuumPeakOverlays(runtime);
  runtime._vacuumPeakLines = [];
  const markers = [];
  const BC = window.boardChart;
  const iv = chartInterval || vacuumLhState.lhInterval || "60";
  peaks.forEach((p, i) => {
    const price = Number(p.price);
    if (!price) return;
    const color = PEAK_COLORS[i % PEAK_COLORS.length];
    runtime._vacuumPeakLines.push(
      runtime.series.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: `LH${p.index || i + 1}`,
      }),
    );
    const tMs = p.time_ms ?? p.time_chart_ms ?? p.time_15m_ms;
    const barTime = BC?.candleTime?.(tMs, iv);
    if (barTime) {
      markers.push({
        time: barTime,
        position: "aboveBar",
        color,
        shape: "circle",
        text: `LH${p.index || i + 1}`,
      });
    }
  });
  if (markers.length) {
    try {
      runtime.series.setMarkers(markers);
    } catch (_e) {
      /* ignore */
    }
  }
}

async function refreshVacuumPanel(panel, symbol, resetScale, live, peaks) {
  const BC = window.boardChart;
  if (!BC?.mount) return;
  const interval = panelInterval(panel);
  const rt = vacuumChartRuntime(panel.stateKey);
  if (!rt) return;
  if (!rt.series) BC.mount(rt, panel.elId);
  if (!rt.series) return;
  BC.paintCandlesFromCache(rt, symbol, interval, resetScale, panel.elId);
  const detailForFetch =
    panel.intervalKey === "lh" && vacuumLhState.detail ? vacuumLhState.detail : null;
  const candles = await BC.ensureCandles(null, symbol, interval, detailForFetch, {
    refreshFallback: resetScale,
  });
  if (panel.intervalKey === "lh" && vacuumLhState.detail) {
    vacuumLhState.detail.candles = candles;
    vacuumLhState.detail.interval = interval;
  }
  BC.drawCandles(rt, candles, interval, resetScale, panel.elId, live);
  drawVacuumPeakOverlays(rt, peaks, interval);
}

async function refreshVacuumLhChart(resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol) return;
  const BC = window.boardChart;
  if (!BC?.mount) return;
  mountVacuumCharts();
  const lhInterval = vacuumLhState.lhInterval;
  BC.scheduleAssetsPrefetch([symbol], { intervals: [lhInterval, "5", "15"], book: true, priority: "high" });
  const live = findVacuumRow(symbol)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  const peaks = vacuumLhState.detail?.signal?.peaks || findVacuumRow(symbol)?.peaks || [];
  await Promise.all(
    VACUUM_CHART_PANELS.map((panel) => refreshVacuumPanel(panel, symbol, resetScale, live, peaks)),
  );
  if (resetScale) {
    updateVacuumMainChartLabel();
    renderVacuumLhInfo();
  }
}

function resizeVacuumLhChart() {
  for (const panel of VACUUM_CHART_PANELS) {
    vacuumChartRuntime(panel.stateKey)?.chart?.resize?.();
  }
}

window.vacuumLh = {
  initVacuumLhTab,
  onVacuumLhBoard,
  onVacuumLhSnapshot,
  onVacuumLhDetail,
  resizeChart: resizeVacuumLhChart,
};
