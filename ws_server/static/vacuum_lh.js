/* Пылесос LH: список 15m/30m/1H/4H, 3 колонки; график TF 5m–4H. */

const VACUUM_LIST_TF = [
  ["15", "15m"],
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
];

const VACUUM_STRUCTURE_COLUMNS = [
  {
    id: "down",
    color: "vacuum-col-down",
    title: "Снижаются",
    hint: "3 вершины ↓ и 3 минимума ↓ · колонка по 4H",
  },
  {
    id: "mixed",
    color: "vacuum-col-mixed",
    title: "Вразрез",
    hint: "вершины и минимумы не в одну сторону · колонка по 4H",
  },
  {
    id: "up",
    color: "vacuum-col-up",
    title: "Растут",
    hint: "3 вершины ↑ и 3 минимума ↑ · колонка по 4H",
  },
];

const VACUUM_CHART_TF = [
  ["5", "5m"],
  ["15", "15m"],
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
];

const VACUUM_BUFFER_TF = VACUUM_CHART_TF.map(([c]) => c);
const VACUUM_MIN_BARS = 8;
const VACUUM_SERIES_BARS = 300;
const VACUUM_LOAD_CONCURRENCY = 2;

const VACUUM_DESK = [
  ["scan", "Сканер"],
  ["pyl", "БАБЛОСОС"],
  ["pyl1", "БАБЛОСОС 1"],
  ["pylbtc", "БАБЛОСОС+BTC"],
  ["vps5", "Пылесос 5"],
  ["vps15", "Пылесос 15"],
];

const VACUUM_TRADE_VARIANTS = ["pyl", "pyl1", "pylbtc", "vps5", "vps15"];

function vacuumIsDeskMode(mode = vacuumLhState.mode) {
  return mode === "pyl" || mode === "pyl1" || mode === "pylbtc" || mode === "vps5" || mode === "vps15";
}

function vacuumDeskChartInterval(mode = vacuumLhState.mode) {
  if (mode === "vps15") return "15";
  if (mode === "pyl" || mode === "pyl1" || mode === "pylbtc" || mode === "vps5") return "5";
  return vacuumLhState.lhInterval;
}

const vacuumLhState = {
  mode: "scan",
  paper: null,
  closed: [],
  closedMap: { pyl: [], pyl1: [], pylbtc: [], vps5: [], vps15: [] },
  symbolClosed: {},
  series: new Map(),
  scanPivots: {},
  _vq: [],
  _vActive: 0,
  _vInflight: new Set(),
  _vPromises: new Map(),
  _symbolClosedSeq: 0,
  closedReady: false,
  closedVariant: "",
  _lastOpenCount: null,
  lhInterval: "15",
  chartInterval: "15",
  byInterval: {},
  updatedAt: 0,
  loading: false,
  loaded: false,
  signals: [],
  selected: null,
  detail: null,
  chart: null,
  bufferSymbol: null,
  bufferLoading: false,
  _loadSeq: 0,
  _warmThrottleAt: 0,
  _warmDefer: 0,
  _closedFetchAt: 0,
  _analyticsKey: "",
  _analyticsHtml: "",
};

const VAC_CHART = {
  listWrap: "vacuum-lh-list-wrap",
  workspace: "vacuum-lh-workspace",
  chart: "vacuum-lh-candle-chart",
  info: "vacuum-lh-info-pane",
  listTfRow: "vacuum-lh-tf-row",
  chartTfRow: "vacuum-lh-chart-tf-row",
  status: "vacuum-lh-status",
};

const PEAK_COLORS = ["#e9c46a", "#f4a261", "#e76f51", "#d62828", "#9d0208"];
const TROUGH_COLORS = ["#4cc9f0", "#4895ef", "#4361ee", "#3a0ca3", "#560bad"];
const PEAK_CONFLUENCE_COLOR = "#ffe566";
const PEAK_CONFLUENCE_STRONG = "#ffffff";
const TROUGH_CONFLUENCE_COLOR = "#7df9ff";
const TROUGH_CONFLUENCE_STRONG = "#e0ffff";

function vacuumUiActive() {
  const view = document.getElementById("view-vacuum-lh");
  return !!(view && !view.hidden);
}

function vacuumDeskVisible() {
  return vacuumLhState.mode !== "scan" && !vacuumLhState.selected;
}

function vacuumPivotMatchCount(p) {
  const n = Number(p?.tf_match_count);
  if (n >= 1) return n;
  return p?.confluence ? 2 : 1;
}

function vacuumLeftStrength(p) {
  const ls = Number(p?.left_strength);
  if (ls >= 15 && ls <= 30) return ls;
  return 15;
}

function vacuumPivotLineStyle(p, fallbackColor, kind) {
  const n = vacuumPivotMatchCount(p);
  const ls = vacuumLeftStrength(p);
  const amp = Math.min(1, Math.max(0, (ls - 15) / 15));
  const strong = kind === "trough" ? TROUGH_CONFLUENCE_STRONG : PEAK_CONFLUENCE_STRONG;
  const mid = kind === "trough" ? TROUGH_CONFLUENCE_COLOR : PEAK_CONFLUENCE_COLOR;
  if (n >= 3) {
    return { color: strong, lineWidth: 3, lineStyle: 0, amp: 1 };
  }
  if (n >= 2) {
    return { color: mid, lineWidth: 2, lineStyle: 0, amp: 0.85 + amp * 0.15 };
  }
  const lw = 1 + Math.round(amp * 2);
  return { color: fallbackColor, lineWidth: lw, lineStyle: 0, amp };
}

function formatVacuumPivotPrice(p, kind) {
  const price = Number(p.price);
  const n = vacuumPivotMatchCount(p);
  const x3 = kind === "trough" ? "vacuum-lh-trough-x3" : "vacuum-lh-peak-x3";
  const x2 = kind === "trough" ? "vacuum-lh-trough-x2" : "vacuum-lh-peak-x2";
  const cls = n >= 3 ? x3 : n >= 2 ? x2 : "";
  const tag = n >= 2 ? `<sup class="vacuum-lh-peak-tag">×${n} TF</sup>` : "";
  return `<span class="vacuum-lh-pivot${cls ? ` ${cls}` : ""}">${price}${tag}</span>`;
}

function formatVacuumInfoPivot(p, prefix, lhTf) {
  const n = vacuumPivotMatchCount(p);
  const isTrough = prefix === "HL";
  const cls =
    n >= 3
      ? isTrough
        ? "vacuum-lh-trough-li-x3"
        : "vacuum-lh-peak-li-x3"
      : n >= 2
        ? isTrough
          ? "vacuum-lh-trough-li-x2"
          : "vacuum-lh-peak-li-x2"
        : "";
  const tfNote =
    n >= 2 && p.tf_matches?.length
      ? ` · <span class="vacuum-lh-peak-tag">${p.tf_matches.map(labelTf).join(", ")}</span>`
      : "";
  const str =
    p.left_strength >= 16
      ? ` <span class="vacuum-lh-peak-tag" title="Свечей слева не перебили">L${p.left_strength}</span>`
      : "";
  return `<li class="${cls}">${prefix}${p.index}: <strong>${p.price}</strong>${str}${n >= 2 ? ` <span class="vacuum-lh-peak-tag">×${n} TF</span>` : ""} (${lhTf} ${new Date(p.time_ms).toLocaleString("ru-RU")})${tfNote}</li>`;
}

function labelTf(code) {
  return (
    VACUUM_CHART_TF.find(([c]) => c === code)?.[1] ||
    VACUUM_LIST_TF.find(([c]) => c === code)?.[1] ||
    code
  );
}

function destroyVacuumChartRuntime() {
  const rt = vacuumLhState.chart;
  if (rt?.chart) {
    try {
      rt.chart.remove();
    } catch (_e) {
      /* ignore */
    }
  }
  vacuumLhState.chart = window.boardChart?.createRuntime?.() || null;
}

function normalizeVacuumChartDom() {
  const pane = document.querySelector(`#${VAC_CHART.workspace} .psc-chart-pane`);
  if (!pane) return;
  const needRebuild =
    pane.querySelector(".vacuum-lh-extra-charts") ||
    pane.querySelector(".vacuum-lh-chart-stack") ||
    !document.getElementById(VAC_CHART.chart);
  if (needRebuild) {
    destroyVacuumChartRuntime();
    pane.innerHTML = `
      <div class="psc-tf-row vacuum-lh-chart-tf-row" id="${VAC_CHART.chartTfRow}"></div>
      <div class="psc-chart-wrap vacuum-lh-chart-wrap">
        <div id="${VAC_CHART.chart}" class="psc-candle-chart"></div>
        <div id="vacuum-trade-overlay" class="vacuum-trade-overlay" aria-hidden="true"></div>
      </div>`;
  } else if (!document.getElementById(VAC_CHART.chartTfRow)) {
    const row = document.createElement("div");
    row.className = "psc-tf-row vacuum-lh-chart-tf-row";
    row.id = VAC_CHART.chartTfRow;
    pane.insertBefore(row, pane.firstChild);
  }
  ensureVacuumTradeOverlayEl();
}

function setVacuumDetailOpen(open) {
  document.getElementById("view-vacuum-lh")?.classList.toggle("vacuum-lh-detail-open", open);
}

function vacuumClickTarget(event) {
  const t = event.target;
  if (t instanceof Element) return t;
  return t?.parentElement instanceof Element ? t.parentElement : null;
}

function bindVacuumLhCloseControls() {
  const runClose = (event) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    closeVacuumLhChart();
  };
  for (const btn of document.querySelectorAll(
    "#view-vacuum-lh .psc-close-chart, #vacuum-lh-back-btn",
  )) {
    btn.onclick = runClose;
  }
}

function bindVacuumLhInfoPane() {
  if (window.__vacuumLhInfoBound) return;
  window.__vacuumLhInfoBound = true;
  window.boardChart?.bindInfoPane?.(VAC_CHART.info, closeVacuumLhChart, () => {});
}

function initVacuumLhTab() {
  if (!window.__vacuumLhDomReady) {
    normalizeVacuumChartDom();
    window.__vacuumLhDomReady = true;
  }
  bindVacuumLhInfoPane();
  if (!window.__vacuumLhBound) {
    window.__vacuumLhBound = true;
    if (window.boardChart?.createRuntime) {
      vacuumLhState.chart = window.boardChart.createRuntime();
    }
    ensureVacuumTradeClock();
    ensureVacuumTradeWarm();
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !vacuumLhState.selected) return;
      const view = document.getElementById("view-vacuum-lh");
      if (!view || view.hidden) return;
      event.preventDefault();
      closeVacuumLhChart();
    });
    const root = document.getElementById("view-vacuum-lh");
    root?.addEventListener("click", (event) => {
      const target = vacuumClickTarget(event);
      if (!target) return;
      if (target.closest(".psc-close-chart") || target.closest("#vacuum-lh-back-btn")) {
        event.preventDefault();
        event.stopPropagation();
        closeVacuumLhChart();
        return;
      }
      const tfBtn = target.closest("[data-vac-tf]");
      if (tfBtn?.dataset.vacTf) {
        event.preventDefault();
        void switchVacuumChartTf(tfBtn.dataset.vacTf);
        return;
      }
      const modeBtn = target.closest("[data-vac-mode]");
      if (modeBtn?.dataset.vacMode) {
        event.preventDefault();
        setVacuumMode(modeBtn.dataset.vacMode);
        return;
      }
      const listTf = target.closest("[data-vac-list-tf]");
      if (listTf?.dataset.vacListTf) {
        event.preventDefault();
        setVacuumListTf(listTf.dataset.vacListTf);
        return;
      }
      const closeBtn = target.closest("[data-vac-paper-close]");
      if (closeBtn?.dataset.vacPaperClose) {
        event.preventDefault();
        event.stopPropagation();
        void vacuumManualCloseTrade(Number(closeBtn.dataset.vacPaperClose));
        return;
      }
      const deskRow = target.closest("[data-vac-desk-symbol]");
      if (deskRow?.dataset.vacDeskSymbol) {
        event.preventDefault();
        void toggleVacuumLhSymbol(deskRow.dataset.vacDeskSymbol);
        return;
      }
      const card = target.closest(".vacuum-lh-card");
      if (card?.dataset.symbol) toggleVacuumLhSymbol(card.dataset.symbol);
    });
  }
  renderVacuumModes();
  renderVacuumTfControls();
  if (!vacuumLhState.loaded && !vacuumLhState.loading) {
    void fetchVacuumLhBoard();
  }
  applyVacuumInterval(vacuumLhState.lhInterval);
  if (vacuumLhState.selected) {
    openVacuumLhChart();
    if (vacuumLhState.chart?._lastBars?.length) {
      patchVacuumLivePrice();
      drawVacuumTradeOverlay(vacuumLhState.chart);
      requestAnimationFrame(resizeVacuumChartNow);
    } else {
      void loadVacuumChartDisplay(true);
    }
  }
  renderVacuumLhBoard();
  if (!vacuumLhState.selected && vacuumDeskVisible()) {
    renderVacuumDesk();
  }
}

function chartTfButtonsHtml(activeCode) {
  return VACUUM_CHART_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf psc-tf${code === activeCode ? " active" : ""}" data-vac-tf="${code}">${label}</button>`,
  ).join("");
}

function listTfButtonsHtml() {
  return VACUUM_LIST_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf psc-tf${code === vacuumLhState.lhInterval ? " active" : ""}" data-vac-list-tf="${code}">${label}</button>`,
  ).join("");
}

function renderVacuumModes() {
  const row = document.getElementById("vacuum-mode-row");
  if (!row) return;
  row.innerHTML = VACUUM_DESK.map(
    ([id, label]) =>
      `<button type="button" class="tf psc-tf${id === vacuumLhState.mode ? " active" : ""}" data-vac-mode="${id}">${label}</button>`,
  ).join("");
}

function setVacuumMode(mode) {
  if (!VACUUM_DESK.some(([id]) => id === mode)) return;
  const prevInterval = vacuumLhState.chartInterval;
  vacuumLhState.mode = mode;
  if (vacuumIsDeskMode(mode)) {
    vacuumLhState.chartInterval = vacuumDeskChartInterval(mode);
    void ensureVacuumPaper().then(() => {
      void fetchVacuumDeskClosed(true);
      renderVacuumDesk();
    });
  }
  renderVacuumModes();
  renderVacuumTfControls();
  renderVacuumLhBoard();
  if (!vacuumLhState.selected) return;
  if (vacuumLhState.chartInterval !== prevInterval) {
    void loadVacuumChartDisplay(true);
  } else if (vacuumLhState.chart?._lastBars?.length) {
    drawVacuumTradeOverlay(vacuumLhState.chart);
  }
}

async function ensureVacuumPaper() {
  if (vacuumLhState.paper) return;
  await fetchVacuumPaperSnapshot();
}

async function fetchVacuumPaperSnapshot() {
  try {
    const res = await fetch("/api/paper/snapshot");
    if (res.ok) {
      vacuumLhState.paper = await res.json();
      onVacuumPaper(vacuumLhState.paper);
    }
  } catch (_err) {
    /* ignore */
  }
}

function renderVacuumTfControls() {
  const toolbar = document.querySelector(".vacuum-lh-toolbar");
  const listRow = document.getElementById(VAC_CHART.listTfRow);
  const chartRow = document.getElementById(VAC_CHART.chartTfRow);
  const detailOpen = !!vacuumLhState.selected;
  const desk = vacuumLhState.mode !== "scan";
  toolbar?.classList.toggle("vacuum-lh-toolbar-list-only", detailOpen || desk);
  if (listRow && !detailOpen && !desk) {
    listRow.innerHTML = `<span class="vacuum-tf-label">Список</span>${listTfButtonsHtml()}`;
  } else if (listRow) {
    listRow.innerHTML = "";
  }
  if (chartRow) {
    if (!detailOpen) {
      chartRow.innerHTML = "";
      chartRow.hidden = true;
      return;
    }
    chartRow.hidden = false;
    chartRow.innerHTML = `<button type="button" id="vacuum-lh-back-btn" class="psc-close-chart vacuum-lh-back">← Список</button><span class="vacuum-tf-label">TF</span>${chartTfButtonsHtml(
      vacuumLhState.chartInterval,
    )}`;
    bindVacuumLhCloseControls();
  }
}

function vacuumPivotKey(p) {
  return `${p.time_ms}:${p.price}`;
}

function vacuumSeriesKey(symbol, interval) {
  return `${symbol}|${interval}`;
}

function vacuumSeriesEntry(symbol, interval) {
  return vacuumLhState.series.get(vacuumSeriesKey(symbol, interval)) || null;
}

function vacuumScanRow(symbol, interval) {
  const rows = vacuumLhState.byInterval[interval];
  if (Array.isArray(rows)) {
    const hit = rows.find((row) => row && row.symbol === symbol);
    if (hit) return hit;
  }
  return vacuumLhState.scanPivots?.[interval]?.[symbol] || null;
}

function vacuumDetailList(field) {
  const detail = vacuumLhState.detail;
  if (!detail || String(detail.interval) !== String(vacuumLhState.chartInterval)) return null;
  return Array.isArray(detail[field]) ? detail[field] : null;
}

function vacuumUnionPivots(lists) {
  const map = new Map();
  for (const list of lists) {
    for (const point of list || []) {
      if (!point || point.price == null) continue;
      const key = vacuumPivotKey(point);
      const prev = map.get(key);
      if (!prev) {
        map.set(key, { ...point });
        continue;
      }
      const next = { ...prev, ...point };
      next.left_strength = Math.max(Number(prev.left_strength) || 0, Number(point.left_strength) || 0);
      if ((Number(prev.tf_match_count) || 0) > (Number(point.tf_match_count) || 0)) {
        next.tf_match_count = prev.tf_match_count;
        next.tf_matches = prev.tf_matches;
        next.confluence = prev.confluence;
        if (prev.index) next.index = prev.index;
      }
      map.set(key, next);
    }
  }
  return [...map.values()].sort((a, b) => Number(a.time_ms || a.time || 0) - Number(b.time_ms || b.time || 0));
}

function vacuumApplyChain(anchors, chain) {
  if (!chain?.length) return anchors;
  const byKey = new Map(chain.map((point) => [vacuumPivotKey(point), point]));
  return anchors.map((point) => {
    const hit = byKey.get(vacuumPivotKey(point));
    if (!hit) return point;
    return {
      ...point,
      index: hit.index || point.index,
      tf_match_count: hit.tf_match_count ?? point.tf_match_count,
      tf_matches: hit.tf_matches || point.tf_matches,
      confluence: hit.confluence ?? point.confluence,
      left_strength: hit.left_strength || point.left_strength,
    };
  });
}

function vacuumChainPoints(symbol, interval, field) {
  const row = vacuumScanRow(symbol, interval);
  if (Array.isArray(row?.[field]) && row[field].length) return row[field];
  const series = vacuumSeriesEntry(symbol, interval);
  const fromSeries = field === "troughs" ? series?.chainTroughs : series?.chainPeaks;
  if (fromSeries?.length) return fromSeries;
  const detail = vacuumLhState.detail;
  if (detail && String(detail.interval) === String(interval) && Array.isArray(detail[field]) && detail[field].length) {
    return detail[field];
  }
  if (detail?.signal && String(detail.signal.lh_interval) === String(interval) && Array.isArray(detail.signal[field])) {
    return detail.signal[field];
  }
  return [];
}

function vacuumChartAnchors(symbol, interval, kind) {
  const series = vacuumSeriesEntry(symbol, interval);
  const row = vacuumScanRow(symbol, interval);
  const fromSeries = kind === "trough" ? series?.anchorTroughs : series?.anchorPeaks;
  const fromScan = kind === "trough" ? row?.all_troughs : row?.all_peaks;
  const fromDetail = vacuumDetailList(kind === "trough" ? "anchor_troughs" : "anchor_peaks");
  const ready = !!(series?.pivotsReady || Array.isArray(fromScan) || Array.isArray(fromDetail));
  const chainField = kind === "trough" ? "troughs" : "peaks";
  const anchors = vacuumUnionPivots([fromSeries, fromScan, fromDetail]);
  if (anchors.length || ready) return vacuumApplyChain(anchors, vacuumChainPoints(symbol, interval, chainField));
  return vacuumChainPoints(symbol, interval, chainField);
}

function getVacuumChainPeaks() {
  const sym = vacuumLhState.selected;
  if (!sym) return [];
  return vacuumChainPoints(sym, vacuumLhState.chartInterval, "peaks");
}

function getVacuumChainTroughs() {
  const sym = vacuumLhState.selected;
  if (!sym) return [];
  return vacuumChainPoints(sym, vacuumLhState.chartInterval, "troughs");
}

function getVacuumChartPeaks() {
  const sym = vacuumLhState.selected;
  if (!sym) return [];
  return vacuumChartAnchors(sym, vacuumLhState.chartInterval, "peak");
}

function getVacuumChartTroughs() {
  const sym = vacuumLhState.selected;
  if (!sym) return [];
  return vacuumChartAnchors(sym, vacuumLhState.chartInterval, "trough");
}

function requestVacuumChartAnchors(interval) {
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(
      JSON.stringify({ type: "vacuum_lh_chart_interval", interval }),
    );
  }
}

function mountVacuumChart() {
  const BC = window.boardChart;
  if (!BC?.mount) return false;
  const container = document.getElementById(VAC_CHART.chart);
  if (!container) return false;
  if (!vacuumLhState.chart) vacuumLhState.chart = BC.createRuntime();
  BC.mount(vacuumLhState.chart, VAC_CHART.chart);
  return !!vacuumLhState.chart?.series;
}

function resizeVacuumChartNow() {
  const container = document.getElementById(VAC_CHART.chart);
  const rt = vacuumLhState.chart;
  if (!container || !rt?.chart) return;
  const h = container.clientHeight || container.parentElement?.clientHeight || 420;
  const w = container.clientWidth || 640;
  if (w > 0) rt.chart.resize(w, Math.max(h, 280));
}

function setVacuumChartPlaceholder(text) {
  const wrap = document.querySelector(".vacuum-lh-chart-wrap");
  if (!wrap) return;
  let el = document.getElementById("vacuum-lh-chart-ph");
  if (!text) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement("p");
    el.id = "vacuum-lh-chart-ph";
    el.className = "quiet vacuum-lh-chart-ph";
    wrap.appendChild(el);
  }
  el.textContent = text;
}

function focusVacuumTradeWindow(runtime) {
  const bars = runtime?._lastBars;
  if (!runtime?.chart || !bars?.length) return;
  const show = Math.min(bars.length, 180);
  runtime._programmaticChartView = true;
  try {
    runtime.chart.timeScale().applyOptions({ barSpacing: 7, rightOffset: 10 });
    runtime.chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, bars.length - show),
      to: bars.length + 10,
    });
  } catch (_e) {
    /* ignore */
  }
  queueMicrotask(() => {
    runtime._programmaticChartView = false;
  });
}

function drawVacuumCandles(candles, resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol || !candles?.length || !mountVacuumChart()) return false;
  const BC = window.boardChart;
  const interval = vacuumLhState.chartInterval;
  const runtime = vacuumLhState.chart;
  let keptRange = null;
  if (!resetScale && runtime?.chart) {
    try {
      keptRange = runtime.chart.timeScale().getVisibleLogicalRange();
    } catch (_e) {
      keptRange = null;
    }
  }
  const live = findVacuumRow(symbol)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  BC.drawCandles(runtime, candles, interval, resetScale, VAC_CHART.chart, live);
  if (resetScale) focusVacuumTradeWindow(runtime);
  else if (keptRange) {
    try {
      runtime.chart.timeScale().setVisibleLogicalRange(keptRange);
    } catch (_e) {
      /* ignore */
    }
  }
  ensureVacuumLhMarkerHooks(runtime);
  drawVacuumLhOverlays(runtime, getVacuumChartPeaks(), getVacuumChartTroughs(), interval);
  requestAnimationFrame(resizeVacuumChartNow);
  setVacuumChartPlaceholder("");
  return true;
}

function vacuumNeedBars(_interval) {
  return VACUUM_SERIES_BARS;
}

function vacuumTailFresh(candles, interval) {
  if (!candles?.length) return false;
  const last = Number(candles[candles.length - 1].timestamp ?? candles[candles.length - 1].time ?? 0);
  const ms = last > 1e12 ? last : last * 1000;
  const step = (window.boardChart?.INTERVAL_SEC?.[interval] || 300) * 1000;
  if (!ms || !step) return false;
  return ms >= Math.floor(Date.now() / step) * step;
}

function vacuumSeriesSkipFetch(symbol, interval) {
  const entry = vacuumSeriesEntry(symbol, interval);
  if (!entry?.pivotsReady || !entry.candles?.length) return false;
  if (!vacuumTailFresh(entry.candles, interval)) return false;
  return !!(entry.historyComplete || entry.candles.length >= vacuumNeedBars(interval));
}

function vacuumCandlesForChart(symbol, interval) {
  const entry = vacuumSeriesEntry(symbol, interval);
  if (entry?.candles?.length >= VACUUM_MIN_BARS) return entry.candles;
  return window.boardChart?.getCachedCandles?.(symbol, interval) || [];
}

function paintVacuumChartFromBuffer(resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol) return false;
  const candles = vacuumCandlesForChart(symbol, vacuumLhState.chartInterval);
  if (candles.length < VACUUM_MIN_BARS) return false;
  return drawVacuumCandles(candles, resetScale);
}

function vacuumLoadStillValid(seq, symbol) {
  return vacuumLhState._loadSeq === seq && vacuumLhState.selected === symbol;
}

async function loadVacuumChartDisplay(resetScale) {
  const symbol = vacuumLhState.selected;
  const interval = vacuumLhState.chartInterval;
  if (!symbol) return;
  if (paintVacuumChartFromBuffer(resetScale)) {
    if (!vacuumSeriesSkipFetch(symbol, interval)) void refreshVacuumVisibleChart();
    scheduleVacuumSeriesWarm();
    return;
  }
  if (!mountVacuumChart()) {
    setVacuumChartPlaceholder("График недоступен (нет lightweight-charts)");
    return;
  }
  const seq = ++vacuumLhState._loadSeq;
  const payload = await vacuumFetchShared(symbol, interval, false);
  if (!vacuumLoadStillValid(seq, symbol)) {
    if (payload?.candles?.length) vacuumStoreSeries(symbol, interval, payload);
    return;
  }
  if (!payload?.candles?.length) {
    setVacuumChartPlaceholder("Нет данных свечей для этого TF — попробуйте 15m или 1H");
    return;
  }
  vacuumApplySeries(symbol, interval, payload);
  scheduleVacuumSeriesWarm();
}

function vacuumStoreSeries(symbol, interval, payload) {
  if (!symbol || !interval || !payload?.candles?.length) return;
  const prev = vacuumSeriesEntry(symbol, interval);
  vacuumLhState.series.set(vacuumSeriesKey(symbol, interval), {
    candles: payload.candles,
    anchorPeaks: payload.anchor_peaks || [],
    anchorTroughs: payload.anchor_troughs || [],
    chainPeaks: payload.peaks || [],
    chainTroughs: payload.troughs || [],
    at: Date.now(),
    historyComplete: !!(payload.history_complete || prev?.historyComplete),
    pivotsReady: Array.isArray(payload.anchor_peaks) && Array.isArray(payload.anchor_troughs),
  });
  const bucket = window.boardChart?.getAssetBucket?.(symbol);
  if (bucket?.intervals) {
    bucket.intervals.set(interval, payload.candles);
    bucket.intervalAt.set(interval, Date.now());
  }
}

function vacuumApplySeries(symbol, interval, payload) {
  vacuumStoreSeries(symbol, interval, payload);
  if (vacuumLhState.selected !== symbol || vacuumLhState.chartInterval !== interval) return;
  const candles = payload.candles || [];
  if (!candles.length || !mountVacuumChart()) return;
  const runtime = vacuumLhState.chart;
  if (!runtime?._lastBars?.length) {
    drawVacuumCandles(candles, true);
    return;
  }
  const BC = window.boardChart;
  const prev = runtime._lastBars[runtime._lastBars.length - 1];
  const next = candles[candles.length - 1];
  const nextTime = BC.candleTime(next.timestamp ?? next.time, interval);
  const same =
    candles.length === runtime._lastBars.length &&
    BC.barTimeToSec(nextTime) === BC.barTimeToSec(prev.time) &&
    Number(next.close) === Number(prev.close);
  if (!same) drawVacuumCandles(candles, false);
  else drawVacuumLhOverlays(runtime, getVacuumChartPeaks(), getVacuumChartTroughs(), interval);
}

async function vacuumFetchSeries(symbol, interval, tail) {
  const q = new URLSearchParams({
    interval,
    bars: String(VACUUM_SERIES_BARS),
    pivots: "1",
  });
  if (tail) q.set("tail", "1");
  const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
  if (!res.ok) return null;
  return await res.json();
}

function vacuumFetchShared(symbol, interval, tail) {
  const key = vacuumSeriesKey(symbol, interval);
  const pending = vacuumLhState._vPromises.get(key);
  if (pending) return pending;
  const job = vacuumFetchSeries(symbol, interval, tail).finally(() => {
    if (vacuumLhState._vPromises.get(key) === job) vacuumLhState._vPromises.delete(key);
  });
  vacuumLhState._vPromises.set(key, job);
  return job;
}

function vacuumEnqueue(symbol, interval, rank) {
  if (!symbol || !interval || vacuumSeriesSkipFetch(symbol, interval)) return;
  const key = vacuumSeriesKey(symbol, interval);
  if (vacuumLhState._vInflight.has(key)) return;
  const existing = vacuumLhState._vq.find((job) => job.key === key);
  if (existing) {
    existing.rank = Math.min(existing.rank, rank);
    return;
  }
  vacuumLhState._vq.push({ key, symbol, interval, rank });
}

function scheduleVacuumSeriesWarmThrottled(minMs = 12_000) {
  if (!vacuumUiActive()) return;
  const now = Date.now();
  const last = vacuumLhState._warmThrottleAt || 0;
  if (now - last < minMs) {
    if (!vacuumLhState._warmDefer) {
      const wait = minMs - (now - last);
      vacuumLhState._warmDefer = setTimeout(() => {
        vacuumLhState._warmDefer = 0;
        vacuumLhState._warmThrottleAt = Date.now();
        scheduleVacuumSeriesWarm();
      }, wait);
    }
    return;
  }
  vacuumLhState._warmThrottleAt = now;
  scheduleVacuumSeriesWarm();
}

function scheduleVacuumSeriesWarm() {
  const seen = new Set();
  const selected = vacuumLhState.selected;
  const tfOrder = ["5", "15", "30", "60", "240"];
  if (selected) {
    vacuumEnqueue(selected, vacuumLhState.chartInterval, 0);
    for (const interval of tfOrder) {
      if (interval !== vacuumLhState.chartInterval) vacuumEnqueue(selected, interval, 1);
    }
    seen.add(selected);
  }
  const opens = ((vacuumLhState.paper || {}).open_trades || []).filter((trade) =>
    VACUUM_TRADE_VARIANTS.includes(trade.variant),
  );
  let rank = 10;
  for (const trade of opens) {
    const symbol = trade.symbol;
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    vacuumEnqueue(symbol, trade.variant === "vps15" ? "15" : "5", rank);
    rank += 1;
  }
  vacuumDrain();
}

function vacuumDrain() {
  vacuumLhState._vq.sort((a, b) => a.rank - b.rank);
  while (vacuumLhState._vActive < VACUUM_LOAD_CONCURRENCY && vacuumLhState._vq.length) {
    const job = vacuumLhState._vq.shift();
    if (!job || vacuumSeriesSkipFetch(job.symbol, job.interval)) continue;
    vacuumLhState._vActive += 1;
    vacuumLhState._vInflight.add(job.key);
    void vacuumRunJob(job)
      .catch(() => {})
      .finally(() => {
        vacuumLhState._vInflight.delete(job.key);
        vacuumLhState._vActive -= 1;
        vacuumDrain();
      });
  }
}

async function vacuumRunJob(job) {
  const entry = vacuumSeriesEntry(job.symbol, job.interval);
  const tail = !!(entry?.historyComplete || (entry?.candles?.length || 0) >= 48);
  const payload = await vacuumFetchShared(job.symbol, job.interval, tail);
  if (payload?.candles?.length) vacuumApplySeries(job.symbol, job.interval, payload);
}

function ensureVacuumBuffers() {
  scheduleVacuumSeriesWarm();
}

function scheduleVacuumTradeCharts() {
  if (!vacuumUiActive()) return;
  if (vacuumLhState._warmSoon) return;
  vacuumLhState._warmSoon = setTimeout(() => {
    vacuumLhState._warmSoon = 0;
    scheduleVacuumSeriesWarmThrottled();
  }, 400);
}

function ensureVacuumTradeWarm() {
  if (!vacuumUiActive()) return;
  if (vacuumLhState._warmTimer) return;
  void fetchVacuumDeskClosed(false).then(() => scheduleVacuumSeriesWarmThrottled(0));
  vacuumLhState._warmTimer = setInterval(() => {
    if (!vacuumUiActive()) return;
    scheduleVacuumSeriesWarmThrottled();
    void refreshVacuumVisibleChart();
  }, 15_000);
}

async function refreshVacuumVisibleChart() {
  const symbol = vacuumLhState.selected;
  const interval = vacuumLhState.chartInterval;
  if (!symbol || !interval || vacuumSeriesSkipFetch(symbol, interval)) return;
  const entry = vacuumSeriesEntry(symbol, interval);
  const tail = !!(entry?.historyComplete || (entry?.candles?.length || 0) >= 48);
  const payload = await vacuumFetchShared(symbol, interval, tail);
  if (!payload?.candles?.length) return;
  vacuumApplySeries(symbol, interval, payload);
}

async function switchVacuumChartTf(interval) {
  if (!vacuumLhState.selected || vacuumLhState.chartInterval === interval) return;
  vacuumLhState.chartInterval = interval;
  requestVacuumChartAnchors(interval);
  if (VACUUM_LIST_TF.some(([c]) => c === interval) && vacuumLhState.lhInterval !== interval) {
    vacuumLhState.lhInterval = interval;
    applyVacuumInterval(interval);
    if (window.signalSocket?.readyState === WebSocket.OPEN) {
      window.signalSocket.send(JSON.stringify({ type: "vacuum_lh_interval", interval }));
    }
    if (!vacuumLhState.byInterval[interval]) {
      void fetchVacuumLhBoard(interval);
    } else {
      renderVacuumLhBoard();
    }
  }
  renderVacuumTfControls();
  renderVacuumLhInfo();
  if (paintVacuumChartFromBuffer(true)) {
    ensureVacuumBuffers(vacuumLhState.selected);
    void refreshVacuumVisibleChart();
    return;
  }
  await loadVacuumChartDisplay(true);
}

function setVacuumListTf(interval) {
  if (vacuumLhState.lhInterval === interval) return;
  vacuumLhState.lhInterval = interval;
  applyVacuumInterval(interval);
  renderVacuumTfControls();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "vacuum_lh_interval", interval }));
  }
  if (!vacuumLhState.byInterval[interval]) {
    void fetchVacuumLhBoard(interval);
  }
  renderVacuumLhBoard();
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
      ingestVacuumScanPivots(data);
      redrawVacuumOpenChart();
    }
  } catch (_e) {
    setVacuumStatus("Не удалось загрузить список");
  } finally {
    vacuumLhState.loading = false;
    setVacuumStatus(
      vacuumLhState.updatedAt
        ? `Обновлено: ${new Date(vacuumLhState.updatedAt).toLocaleTimeString("ru-RU")} · список ${labelTf(vacuumLhState.lhInterval)}`
        : "",
    );
    renderVacuumLhBoard();
  }
}

function vacuumRememberScan(interval, symbol, row) {
  if (!interval || !symbol || !row) return;
  if (!vacuumLhState.scanPivots[interval]) vacuumLhState.scanPivots[interval] = {};
  vacuumLhState.scanPivots[interval][symbol] = row;
}

function ingestVacuumScanPivots(data) {
  if (!data || typeof data !== "object") return;
  const intervals = data.intervals;
  if (intervals && typeof intervals === "object" && !Array.isArray(intervals)) {
    for (const [iv, rows] of Object.entries(intervals)) {
      if (!Array.isArray(rows)) continue;
      for (const row of rows) {
        if (row?.symbol) vacuumRememberScan(iv, row.symbol, row);
      }
    }
  }
  if (Array.isArray(data.signals) && data.interval) {
    for (const row of data.signals) {
      if (row?.symbol) vacuumRememberScan(String(data.interval), row.symbol, row);
    }
  }
  const charts = data.chart_pivots;
  if (charts && typeof charts === "object" && !Array.isArray(charts)) {
    for (const [iv, bySym] of Object.entries(charts)) {
      if (!bySym || typeof bySym !== "object" || Array.isArray(bySym)) continue;
      for (const [sym, row] of Object.entries(bySym)) vacuumRememberScan(iv, sym, row);
    }
  }
}

function redrawVacuumOpenChart() {
  const rt = vacuumLhState.chart;
  if (!vacuumLhState.selected || !rt?._lastBars?.length) return;
  drawVacuumLhOverlays(rt, getVacuumChartPeaks(), getVacuumChartTroughs(), vacuumLhState.chartInterval);
}

function ingestVacuumPayload(data) {
  if (!data) return;
  if (data.intervals && typeof data.intervals === "object" && !Array.isArray(data.intervals)) {
    for (const [iv, rows] of Object.entries(data.intervals)) {
      if (!Array.isArray(rows)) continue;
      vacuumLhState.byInterval[iv] = rows;
    }
    vacuumLhState.updatedAt = data.updated_at || vacuumLhState.updatedAt;
    vacuumLhState.loaded = true;
    const def = data.default_interval;
    if (def && VACUUM_LIST_TF.some(([c]) => c === def) && !vacuumLhState.selected) {
      vacuumLhState.lhInterval = def;
      if (vacuumLhState.chartInterval === "15" || vacuumLhState.chartInterval === "60") {
        vacuumLhState.chartInterval = def;
      }
    }
    applyVacuumInterval(vacuumLhState.lhInterval);
    ingestVacuumScanPivots(data);
  } else if (Array.isArray(data)) {
    vacuumLhState.byInterval[vacuumLhState.lhInterval] = data;
    applyVacuumInterval(vacuumLhState.lhInterval);
  } else if (data.signals) {
    const iv = data.interval || vacuumLhState.lhInterval;
    vacuumLhState.byInterval[iv] = data.signals;
    vacuumLhState.updatedAt = data.updated_at || vacuumLhState.updatedAt;
    applyVacuumInterval(vacuumLhState.lhInterval);
    ingestVacuumScanPivots(data);
  }
  if (!vacuumUiActive()) return;
  setVacuumStatus(
    vacuumLhState.updatedAt
      ? `Обновлено: ${new Date(vacuumLhState.updatedAt).toLocaleTimeString("ru-RU")} · список ${labelTf(vacuumLhState.lhInterval)}`
      : "",
  );
  renderVacuumLhBoard();
}

function findVacuumRow(symbol) {
  const inList = vacuumLhState.signals.find((s) => s.symbol === symbol);
  if (inList) return inList;
  for (const rows of Object.values(vacuumLhState.byInterval)) {
    const hit = (Array.isArray(rows) ? rows : []).find((s) => s.symbol === symbol);
    if (hit) return hit;
  }
  return undefined;
}

async function toggleVacuumLhSymbol(symbol) {
  if (vacuumLhState.selected === symbol) {
    closeVacuumLhChart();
    return;
  }
  vacuumLhState.selected = symbol;
  vacuumLhState.detail = null;
  vacuumLhState.chartInterval = vacuumIsDeskMode()
    ? vacuumDeskChartInterval()
    : vacuumLhState.lhInterval;
  openVacuumLhChart();
  renderVacuumLhBoard();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_vacuum_lh", symbol }));
    requestVacuumChartAnchors(vacuumLhState.chartInterval);
  }
  void loadVacuumChartDisplay(true);
  void ensureVacuumPaper();
  void fetchVacuumDeskClosed(false);
  void fetchVacuumSymbolClosed(symbol);
  scheduleVacuumTradeCharts();
}

function openVacuumLhChart() {
  normalizeVacuumChartDom();
  renderVacuumTfControls();
  document.getElementById(VAC_CHART.listWrap)?.setAttribute("hidden", "");
  document.getElementById("vacuum-desk")?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.workspace)?.removeAttribute("hidden");
  setVacuumDetailOpen(true);
  mountVacuumChart();
  renderVacuumLhInfo();
  requestAnimationFrame(resizeVacuumChartNow);
}

function closeVacuumLhChart() {
  vacuumLhState._loadSeq += 1;
  vacuumLhState.selected = null;
  vacuumLhState.detail = null;
  vacuumLhState.bufferSymbol = null;
  setVacuumChartPlaceholder("");
  clearVacuumLhOverlays(vacuumLhState.chart);
  document.getElementById(VAC_CHART.workspace)?.setAttribute("hidden", "");
  setVacuumDetailOpen(false);
  renderVacuumTfControls();
  renderVacuumLhBoard();
}

function patchVacuumLivePrice() {
  const sym = vacuumLhState.selected;
  const rt = vacuumLhState.chart;
  if (!sym || !rt?.series || !rt._lastBars?.length) return;
  const live =
    vacuumPaperLastPrice(sym) ||
    findVacuumRow(sym)?.last_price ||
    vacuumLhState.detail?.signal?.last_price;
  if (live == null || !(Number(live) > 0)) return;
  const BC = window.boardChart;
  const bars = rt._lastBars.map((b) => ({ ...b }));
  BC.patchLiveLastBar(bars, live);
  const last = bars[bars.length - 1];
  try {
    rt.series.update(last);
    if (rt.volumeSeries) {
      rt.volumeSeries.update({
        time: last.time,
        value: last.volume ?? 0,
        color:
          last.close >= last.open ? "rgba(61, 214, 140, 0.45)" : "rgba(255, 93, 115, 0.45)",
      });
    }
  } catch (_e) {
    return;
  }
  rt._lastBars = bars;
  scheduleVacuumLhMarkerRedraw();
  const priceEl = document.querySelector(`#${VAC_CHART.info} [data-vac-live='price']`);
  if (priceEl) priceEl.textContent = String(live);
}

function mergeVacuumDetail(data) {
  if (!data) return;
  const prev = vacuumLhState.detail || {};
  const prevSignal = prev.signal;
  vacuumLhState.detail = {
    ...prev,
    ...data,
    signal: data.signal || prevSignal,
    anchor_peaks: data.anchor_peaks ?? prev.anchor_peaks,
    anchor_troughs: data.anchor_troughs ?? prev.anchor_troughs,
    peaks: data.peaks ?? prev.peaks,
    troughs: data.troughs ?? prev.troughs,
  };
}

function onVacuumLhBoard(data) {
  ingestVacuumPayload(data);
  if (!vacuumUiActive() || !vacuumLhState.selected) return;
  patchVacuumLivePrice();
  redrawVacuumOpenChart();
}

function onVacuumLhSnapshot(board, detail) {
  ingestVacuumPayload(board);
  if (!vacuumUiActive()) return;
  if (detail?.signal && vacuumLhState.selected === detail.signal.symbol) {
    mergeVacuumDetail(detail);
    renderVacuumLhInfo();
    if (vacuumLhState.chart?._lastBars?.length) {
      drawVacuumLhOverlays(
        vacuumLhState.chart,
        getVacuumChartPeaks(),
        getVacuumChartTroughs(),
        vacuumLhState.chartInterval,
      );
    }
  }
}

function vacuumListColumn(row) {
  const lc = row?.live_column;
  if (lc === "down" || lc === "up") return lc;
  return vacuumStructureTrend(row);
}

function vacuumStructureTrend(row) {
  const key = row?.structure_trend;
  if (key === "down" || key === "up" || key === "mixed") return key;
  const row4h = (vacuumLhState.byInterval["240"] || []).find((s) => s.symbol === row?.symbol);
  const source = row4h || row;
  const peaks = source?.peaks || [];
  const troughs = source?.troughs || [];
  if (peaks.length < 3 || troughs.length < 3) return "mixed";
  const pp = peaks.slice(-3).map((p) => Number(p.price));
  const tt = troughs.slice(-3).map((p) => Number(p.price));
  const down = (arr) => arr[0] > arr[1] && arr[1] > arr[2];
  const up = (arr) => arr[0] < arr[1] && arr[1] < arr[2];
  if (down(pp) && down(tt)) return "down";
  if (up(pp) && up(tt)) return "up";
  return "mixed";
}

function vacuumLhCardHtml(row) {
  const sel = row.symbol === vacuumLhState.selected ? " selected" : "";
  const hiUntil = Number(row.live_highlight_until_ms) || 0;
  const fresh = hiUntil > Date.now() ? " vacuum-lh-card--live-new" : "";
  const peaks = (row.peaks || []).map((p) => formatVacuumPivotPrice(p, "peak")).join(" · ");
  const troughs = (row.troughs || []).map((p) => formatVacuumPivotPrice(p, "trough")).join(" · ");
  return `<article class="vacuum-lh-card pump-strategy-card${sel}${fresh}" data-symbol="${row.symbol}">
    <strong>${row.symbol}</strong>
    <span class="quiet">${Number(row.last_price).toFixed(4)}</span>
    <span class="quiet">${vacuumTurnoverText(row)}</span>
    <span class="quiet">${vacuumHourRangeText(row)}</span>
    <span class="quiet peaks-line">LH: ${peaks || "—"}</span>
    <span class="quiet troughs-line">HL: ${troughs || "—"}</span>
  </article>`;
}

function onVacuumLhDetail(symbol, data) {
  if (!vacuumLhState.selected || vacuumLhState.selected !== symbol) return;
  mergeVacuumDetail(data);
  renderVacuumLhInfo();
  if (vacuumLhState.chart?._lastBars?.length) {
    drawVacuumLhOverlays(
      vacuumLhState.chart,
      getVacuumChartPeaks(),
      getVacuumChartTroughs(),
      vacuumLhState.chartInterval,
    );
  }
}

function vacuumTurnoverText(row) {
  const n = Number(row.turnover_24h_usdt);
  if (!Number.isFinite(n) || n <= 0) return "оборот —";
  if (n >= 1_000_000) return `оборот ${(n / 1_000_000).toFixed(1)} млн`;
  return `оборот ${Math.round(n / 1000)} тыс`;
}

function vacuumHourRangeText(row) {
  const n = Number(row.hour_range_pct);
  if (!Number.isFinite(n)) return "час —";
  return `час ${n.toFixed(1)}%`;
}

function renderVacuumLhBoard() {
  const desk = document.getElementById("vacuum-desk");
  const list = document.getElementById(VAC_CHART.listWrap);
  const deskMode = vacuumLhState.mode !== "scan" && !vacuumLhState.selected;
  document.getElementById("view-vacuum-lh")?.classList.toggle("vacuum-desk-open", deskMode);
  if (desk) desk.hidden = !deskMode;
  if (list) list.hidden = deskMode || !!vacuumLhState.selected;
  if (deskMode) {
    renderVacuumDesk();
    return;
  }
  if (vacuumLhState.selected) {
    return;
  }
  const root = document.getElementById("vacuum-lh-columns");
  if (!root) return;
  if (vacuumLhState.loading) {
    root.innerHTML = '<p class="quiet pump-strategy-empty">Загрузка монет…</p>';
    return;
  }
  const tfLabel = labelTf(vacuumLhState.lhInterval);
  if (!vacuumLhState.signals.length) {
    root.innerHTML = `<p class="quiet pump-strategy-empty">На ${tfLabel}: нет монет с оборотом от 1 млн и размахом за час от 2%. Список обновляется каждые ~45 с.</p>`;
    return;
  }
  const buckets = { down: [], mixed: [], up: [] };
  for (const row of vacuumLhState.signals) {
    const key = vacuumListColumn(row);
    buckets[key].push(row);
  }
  const pinSort = (a, b) =>
    Number(b.live_pin_seq || 0) - Number(a.live_pin_seq || 0) ||
    Number(b.turnover_24h_usdt || 0) - Number(a.turnover_24h_usdt || 0) ||
    String(a.symbol).localeCompare(String(b.symbol));
  for (const id of ["down", "mixed", "up"]) {
    buckets[id].sort(pinSort);
  }
  root.innerHTML = VACUUM_STRUCTURE_COLUMNS.map((col) => {
    const cards = (buckets[col.id] || []).map((row) => vacuumLhCardHtml(row)).join("");
    return `<section class="column ${col.color}">
      <h2>${col.title}</h2>
      <p class="quiet vacuum-lh-col-hint">${col.hint} · карточки ${tfLabel}</p>
      ${cards || '<p class="quiet">нет монет</p>'}
    </section>`;
  }).join("");
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
  const detail = vacuumLhState.detail;
  const chartTf = labelTf(vacuumLhState.chartInterval);
  const peaks =
    detail && String(detail.interval) === String(vacuumLhState.chartInterval) && detail.peaks?.length
      ? detail.peaks
      : row.peaks || [];
  const troughs =
    detail && String(detail.interval) === String(vacuumLhState.chartInterval) && detail.troughs?.length
      ? detail.troughs
      : row.troughs || [];
  const lhTf = chartTf;
  const peakList = peaks
    .map((p) => formatVacuumInfoPivot(p, "LH", lhTf))
    .join("");
  const troughList = troughs
    .map((p) => formatVacuumInfoPivot(p, "HL", lhTf))
    .join("");
  pane.innerHTML = `
    <div class="psc-info-head">
      <h3>${sym}</h3>
      <button type="button" class="psc-close-chart">Закрыть</button>
    </div>
    <p>График <strong>${chartTf}</strong> (ось <strong>MSK</strong>): маркеры экстремумов (слева 15–30, справа 2, разнос ≥30). Список ${lhTf}.</p>
    <p>Цена: <strong data-vac-live="price">${vacuumPaperLastPrice(sym) || row.last_price || "—"}</strong></p>
    <p class="vacuum-lh-info-sub">Вершины LH</p>
    <ul class="vacuum-lh-peaks">${peakList || "<li>—</li>"}</ul>
    <p class="vacuum-lh-info-sub">Минимумы HL</p>
    <ul class="vacuum-lh-troughs">${troughList || "<li>—</li>"}</ul>`;
  bindVacuumLhCloseControls();
}

function clearVacuumLhOverlays(runtime) {
  if (!runtime?.series) return;
  runtime._vacuumPeakLines = [];
  runtime._vacuumTroughLines = [];
  try {
    runtime.series.setMarkers([]);
  } catch (_e) {
    /* ignore */
  }
  const ov = document.getElementById("vacuum-trade-overlay");
  if (ov) ov.innerHTML = "";
}

function scheduleVacuumLhMarkerRedraw() {
  const rt = vacuumLhState.chart;
  if (!rt?.series || !vacuumLhState.selected) return;
  if (rt._vacMarkerRedrawTimer) clearTimeout(rt._vacMarkerRedrawTimer);
  rt._vacMarkerRedrawTimer = setTimeout(() => {
    rt._vacMarkerRedrawTimer = 0;
    if (!rt._lastBars?.length) return;
    drawVacuumLhOverlays(rt, getVacuumChartPeaks(), getVacuumChartTroughs(), vacuumLhState.chartInterval);
  }, 40);
}

function ensureVacuumLhMarkerHooks(runtime) {
  if (!runtime?.chart || runtime._vacLhMarkerHooks) return;
  runtime._vacLhMarkerHooks = true;
  const redraw = () => scheduleVacuumLhMarkerRedraw();
  runtime.chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
  if (typeof runtime.chart.timeScale().subscribeVisibleTimeRangeChange === "function") {
    runtime.chart.timeScale().subscribeVisibleTimeRangeChange(redraw);
  }
}

function vacuumMarkerBarTime(runtime, p, iv) {
  const BC = window.boardChart;
  const tMs = p.time_chart_ms ?? p.time_ms ?? p.time_15m_ms;
  if (!tMs || !BC?.candleTime) return null;
  const wantSec = BC.barTimeToSec(BC.candleTime(tMs, iv));
  const step = BC.INTERVAL_SEC?.[iv] || 900;
  const bars = runtime._lastBars || [];
  let best = null;
  let bestDist = step + 1;
  for (const b of bars) {
    const bs = BC.barTimeToSec(b.time);
    const d = Math.abs(bs - wantSec);
    if (d < bestDist) {
      bestDist = d;
      best = b.time;
    }
  }
  if (best != null && bestDist <= step) return best;
  return null;
}

function vacuumMarkerTimeKey(time) {
  const BC = window.boardChart;
  return BC?.barTimeKey ? BC.barTimeKey(time) : String(time);
}

function vacuumLhPivotMarkers(runtime, points, chartInterval, kind, chainKeys) {
  const markers = [];
  const iv = chartInterval || vacuumLhState.chartInterval || "60";
  const colors = kind === "trough" ? TROUGH_COLORS : PEAK_COLORS;
  const prefix = kind === "trough" ? "HL" : "LH";
  const position = kind === "trough" ? "belowBar" : "aboveBar";
  points.forEach((p, i) => {
    const price = Number(p.price);
    if (!price) return;
    const inChain = chainKeys?.has(vacuumPivotKey(p));
    const baseColor = colors[i % colors.length];
    const n = vacuumPivotMatchCount(p);
    const ls = vacuumLeftStrength(p);
    let style = inChain
      ? vacuumPivotLineStyle(p, baseColor, kind)
      : vacuumPivotLineStyle(p, baseColor, kind);
    if (!inChain) {
      const a = style.amp ?? 0.5;
      style = {
        ...style,
        color: kind === "trough" ? `rgba(76,201,240,${0.45 + a * 0.45})` : `rgba(233,196,106,${0.45 + a * 0.45})`,
      };
    }
    const lsTag = ls >= 16 ? `L${ls}` : "";
    const label = inChain
      ? n >= 2
        ? `${prefix}${p.index || i + 1}·${n}TF${lsTag ? ` ${lsTag}` : ""}`
        : `${prefix}${p.index || i + 1}${lsTag ? ` ${lsTag}` : ""}`
      : lsTag || (kind === "trough" ? "L" : "H");
    const barTime = vacuumMarkerBarTime(runtime, p, iv);
    if (!barTime) return;
    const rank = (inChain ? 1000 : 0) + ls * 10 + n;
    markers.push({
      time: barTime,
      position,
      color: style.color,
      shape: n >= 2 || ls >= 22 ? "square" : "circle",
      text: label,
      _rank: rank,
    });
  });
  return markers;
}

function drawVacuumLhOverlays(runtime, peaks, troughs, chartInterval) {
  if (!runtime?.series) return;
  clearVacuumLhOverlays(runtime);
  runtime._vacuumPeakLines = [];
  runtime._vacuumTroughLines = [];
  const chainPeakKeys = new Set(getVacuumChainPeaks().map(vacuumPivotKey));
  const chainTroughKeys = new Set(getVacuumChainTroughs().map(vacuumPivotKey));
  const raw = [
    ...vacuumLhPivotMarkers(runtime, peaks || [], chartInterval, "peak", chainPeakKeys),
    ...vacuumLhPivotMarkers(runtime, troughs || [], chartInterval, "trough", chainTroughKeys),
  ];
  const byTime = new Map();
  for (const m of raw) {
    const k = vacuumMarkerTimeKey(m.time);
    const prev = byTime.get(k);
    if (!prev || (m._rank || 0) > (prev._rank || 0)) byTime.set(k, m);
  }
  const markers = [...byTime.values()]
    .map(({ _rank, ...rest }) => rest)
    .sort((a, b) => {
      const ta = window.boardChart.barTimeToSec(a.time);
      const tb = window.boardChart.barTimeToSec(b.time);
      return ta - tb;
    });
  if (markers.length) {
    try {
      runtime.series.setMarkers(markers);
    } catch (_e) {
      /* ignore */
    }
  }
  drawVacuumTradeOverlay(runtime);
}

function resizeVacuumLhChart() {
  if (!vacuumLhState.selected) return;
  resizeVacuumChartNow();
}

function vacuumChartTradeVariants() {
  return vacuumLhState.mode === "scan" ? VACUUM_TRADE_VARIANTS : [vacuumDeskVariant()];
}

function vacuumClosedForSymbol(symbol) {
  const variants = vacuumChartTradeVariants();
  const bag = vacuumLhState.symbolClosed[symbol];
  if (bag) return variants.flatMap((v) => bag[v] || []);
  return variants
    .flatMap((v) => vacuumLhState.closedMap[v] || [])
    .filter((t) => t.symbol === symbol);
}

function vacuumSymbolTrades(symbol) {
  if (!symbol) return [];
  const variants = new Set(vacuumChartTradeVariants());
  const opens = ((vacuumLhState.paper || {}).open_trades || []).filter(
    (t) => t.symbol === symbol && variants.has(t.variant),
  );
  const seen = new Set(opens.map((t) => t.id));
  const closed = vacuumClosedForSymbol(symbol).filter((t) => t.id == null || !seen.has(t.id));
  return [
    ...opens.map((t) => ({ ...t, _open: true })),
    ...closed.map((t) => ({ ...t, _open: false })),
  ];
}

function vacuumTradeSide(trade) {
  const entry = trade.entry || trade.entry_json || {};
  const metrics = entry.metrics || {};
  const side = trade.side || entry.side || metrics.side || metrics.pump?.side;
  return side === "long" || side === "short" ? side : "";
}

function vacuumSideLabel(side) {
  if (side === "long") return '<span class="vacuum-side-tag long" aria-label="лонг">▲ лонг</span>';
  if (side === "short") return '<span class="vacuum-side-tag short" aria-label="шорт">▼ шорт</span>';
  return "—";
}

function vacuumPaperLastPrice(symbol) {
  const opens = (vacuumLhState.paper || {}).open_trades || [];
  for (const t of opens) {
    if (t.symbol !== symbol) continue;
    const p = Number(t.last_price);
    if (p > 0) return p;
  }
  return 0;
}

function vacuumChartLivePrice(runtime, symbol) {
  const fromPaper = vacuumPaperLastPrice(symbol);
  if (fromPaper > 0) return fromPaper;
  const last = runtime?._lastBars?.[runtime._lastBars.length - 1];
  const fromBar = Number(last?.close);
  if (fromBar > 0) return fromBar;
  const row = findVacuumRow(symbol)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  const n = Number(row);
  return n > 0 ? n : 0;
}

function vacuumOpenMoney(trade) {
  const px = Number(trade.last_price);
  if (!(px > 0)) {
    return { roe: Number(trade.roe_pct), pnl: Number(trade.pnl_usd) };
  }
  return vacuumTradePnl({ ...trade, _open: true }, px);
}

function vacuumTradeCurrentPrice(trade, live) {
  if (!trade._open) {
    const exitPx = Number(trade.exit_price || trade.last_price);
    return exitPx > 0 ? exitPx : 0;
  }
  const liveN = Number(live);
  if (liveN > 0) return liveN;
  const last = Number(trade.last_price);
  return last > 0 ? last : 0;
}

function vacuumTradeWorstPrice(trade) {
  const stored = Number(trade.worst_price);
  return stored > 0 ? stored : 0;
}

function vacuumTradePnl(trade, price) {
  if (!trade._open) {
    return { roe: Number(trade.roe_pct), pnl: Number(trade.pnl_usd) };
  }
  const entry = Number(trade.entry_price);
  const qty = Number(trade.qty);
  const margin = Number(trade.margin);
  const px = Number(price);
  const entryFee = Number(trade.entry_fee) || 0;
  const funding = Number(trade.funding_paid) || 0;
  const rawFee = Number((vacuumLhState.paper || {}).summary?.fee_rate);
  const fee = Number.isFinite(rawFee) ? rawFee : 0.00055;
  if (!(entry > 0) || !(qty > 0) || !(margin > 0) || !(px > 0)) {
    return { roe: Number(trade.roe_pct), pnl: Number(trade.pnl_usd) };
  }
  const gross = vacuumTradeSide(trade) === "long" ? (px - entry) * qty : (entry - px) * qty;
  const pnl = gross - entryFee - qty * px * fee + funding;
  return { roe: (pnl / margin) * 100, pnl };
}

function ensureVacuumTradeOverlayEl() {
  const wrap = document.querySelector(`#${VAC_CHART.workspace} .vacuum-lh-chart-wrap`);
  if (!wrap) return null;
  let el = document.getElementById("vacuum-trade-overlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "vacuum-trade-overlay";
    el.className = "vacuum-trade-overlay";
    el.setAttribute("aria-hidden", "true");
    wrap.appendChild(el);
  }
  return el;
}

function vacuumTimeToX(runtime, ms) {
  const BC = window.boardChart;
  const bars = runtime?._lastBars;
  if (!runtime?.chart || !bars?.length || !ms || !BC?.barTimeToSec) return null;
  const target = Number(ms) / 1000;
  if (!Number.isFinite(target)) return null;
  const scale = runtime.chart.timeScale();
  const secs = bars.map((b) => BC.barTimeToSec(b.time));
  const xAt = (idx) => {
    const x = scale.timeToCoordinate(bars[idx].time);
    return x == null || Number.isNaN(x) ? null : x;
  };
  const pxPerSec = (i0, i1) => {
    const x0 = xAt(i0);
    const x1 = xAt(i1);
    const span = secs[i1] - secs[i0];
    if (x0 == null || x1 == null || !(span > 0)) return null;
    return { x0, sec0: secs[i0], px: (x1 - x0) / span };
  };
  const last = secs.length - 1;
  if (target <= secs[0]) {
    if (last < 1) return xAt(0);
    const step = pxPerSec(0, 1);
    return step ? step.x0 + (target - step.sec0) * step.px : xAt(0);
  }
  if (target >= secs[last]) {
    if (last < 1) return xAt(last);
    const step = pxPerSec(last - 1, last);
    if (!step) return xAt(last);
    const xLast = xAt(last);
    return xLast == null ? null : xLast + (target - secs[last]) * step.px;
  }
  let lo = 0;
  let hi = last;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (secs[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const step = pxPerSec(lo - 1, lo);
  return step ? step.x0 + (target - step.sec0) * step.px : xAt(lo);
}

function vacuumMarkOnScreen(x, hostW) {
  if (x == null || Number.isNaN(x)) return false;
  if (hostW > 0 && (x < -8 || x > hostW + 8)) return false;
  return true;
}

function vacuumTradePlus(money) {
  return (Number.isFinite(money.roe) ? money.roe : Number(money.pnl)) >= 0;
}

function vacuumEntryArrow(runtime, trade, hostW) {
  const side = vacuumTradeSide(trade);
  if (side !== "long" && side !== "short") return "";
  const entry = Number(trade.entry_price);
  const long = side === "long";
  const x = vacuumTimeToX(runtime, trade.opened_at);
  const y = runtime.series.priceToCoordinate(entry);
  if (!vacuumMarkOnScreen(x, hostW) || y == null || Number.isNaN(y)) return "";
  const shift = long ? "translate(-50%, 2px)" : "translate(-50%, calc(-100% - 2px))";
  return `<div class="vacuum-trade-arrow ${long ? "long" : "short"}" style="left:${Math.round(x)}px;top:${Math.round(y)}px;transform:${shift}" title="${long ? "Лонг" : "Шорт"}">${long ? "▲" : "▼"}</div>`;
}

function vacuumExitMark(runtime, trade, hostW) {
  if (!trade.closed_at) return "";
  const exitPx = Number(trade.exit_price || trade.last_price);
  const x = vacuumTimeToX(runtime, trade.closed_at);
  const y = exitPx > 0 ? runtime.series.priceToCoordinate(exitPx) : null;
  if (!vacuumMarkOnScreen(x, hostW) || y == null || Number.isNaN(y)) return "";
  const plus = vacuumTradePlus(vacuumTradePnl(trade, exitPx));
  return `<div class="vacuum-trade-mark ${plus ? "plus" : "minus"}" style="left:${Math.round(x)}px;top:${Math.round(y)}px;transform:translate(-50%,-50%)">${plus ? "✓" : "✕"}</div>`;
}

function vacuumTradeHudCard(trade, money) {
  const name = VACUUM_DESK.find(([id]) => id === trade.variant)?.[1] || trade.variant || "";
  const tone = vacuumTradePlus(money) ? "plus" : "minus";
  const dollars = Number.isFinite(money.pnl)
    ? `${money.pnl >= 0 ? "+" : "−"}$${Math.abs(money.pnl).toFixed(2)}`
    : "—";
  const closeBtn =
    trade._open && trade.id
      ? `<br><button type="button" class="paper-btn vac-paper-close-btn" data-vac-paper-close="${trade.id}">Закрыть</button>`
      : "";
  return `<div class="vacuum-trade-pnl ${tone}"><span class="vacuum-trade-hud-name">${name}</span><br>${vacuumFmtSigned(money.roe, 1, "%")}<br>${dollars}${closeBtn}</div>`;
}

function vacuumFmtSigned(n, digits, suffix) {
  if (!Number.isFinite(n)) return "—";
  const sign = n >= 0 ? "+" : "−";
  return `${sign}${Math.abs(n).toFixed(digits)}${suffix || ""}`;
}

function drawVacuumTradeOverlay(runtime) {
  const el = ensureVacuumTradeOverlayEl();
  const symbol = vacuumLhState.selected;
  if (!el) return;
  if (!runtime?.chart || !runtime.series || !symbol) {
    el.innerHTML = "";
    return;
  }
  const live = vacuumChartLivePrice(runtime, symbol);
  const trades = vacuumSymbolTrades(symbol);
  if (!trades.length) {
    el.innerHTML = "";
    return;
  }
  const hostW = el.clientWidth || 0;
  const nowMs = Date.now();
  const parts = [];
  const hud = [];
  for (const trade of trades) {
    const entry = Number(trade.entry_price);
    if (!(entry > 0) || !trade.opened_at) continue;
    const arrow = vacuumEntryArrow(runtime, trade, hostW);
    if (arrow) parts.push(arrow);
    if (!trade._open) {
      const mark = vacuumExitMark(runtime, trade, hostW);
      if (mark) parts.push(mark);
      continue;
    }
    const current = vacuumTradeCurrentPrice(trade, live);
    const money = vacuumTradePnl(trade, current);
    hud.push(vacuumTradeHudCard(trade, money));
    const left = vacuumTimeToX(runtime, trade.opened_at);
    const right = vacuumTimeToX(runtime, nowMs);
    const worst = vacuumTradeWorstPrice(trade);
    if (left == null || right == null || !(current > 0) || !(worst > 0)) continue;
    const xL = Math.min(left, right);
    const xR = Math.max(left, right);
    if (hostW > 0 && (xR < -8 || xL > hostW + 8)) continue;
    const yTop = runtime.series.priceToCoordinate(Math.max(current, worst));
    const yBot = runtime.series.priceToCoordinate(Math.min(current, worst));
    if (yTop == null || yBot == null || Number.isNaN(yTop) || Number.isNaN(yBot)) continue;
    const tone = vacuumTradePlus(money) ? "plus" : "minus";
    parts.push(
      `<div class="vacuum-trade-box ${tone}" style="left:${Math.round(xL)}px;top:${Math.round(Math.min(yTop, yBot))}px;width:${Math.round(Math.max(2, xR - xL))}px;height:${Math.round(Math.max(2, Math.abs(yBot - yTop)))}px"></div>`,
    );
  }
  if (hud.length) parts.push(`<div class="vacuum-trade-hud">${hud.join("")}</div>`);
  el.innerHTML = parts.join("");
}

function ensureVacuumTradeClock() {
  if (vacuumLhState._tradeClock) return;
  vacuumLhState._tradeClock = setInterval(() => {
    const rt = vacuumLhState.chart;
    if (!vacuumLhState.selected || !rt?._lastBars?.length) return;
    if (!vacuumSymbolTrades(vacuumLhState.selected).some((t) => t._open)) return;
    drawVacuumTradeOverlay(rt);
  }, 1000);
}

async function fetchVacuumSymbolClosed(symbol) {
  if (!symbol) return;
  const seq = ++vacuumLhState._symbolClosedSeq;
  try {
    const pairs = await Promise.all(
      VACUUM_TRADE_VARIANTS.map(async (variant) => {
        const q = new URLSearchParams({
          status: "closed",
          limit: "2000",
          variant,
          symbol,
        });
        const res = await fetch(`/api/paper/trades?${q}`);
        if (!res.ok) return [variant, []];
        const body = await res.json();
        return [variant, body.rows || []];
      }),
    );
    if (seq !== vacuumLhState._symbolClosedSeq) return;
    const bag = {};
    for (const [variant, rows] of pairs) bag[variant] = rows;
    vacuumLhState.symbolClosed[symbol] = bag;
    if (vacuumLhState.selected === symbol && vacuumLhState.chart?._lastBars?.length) {
      drawVacuumTradeOverlay(vacuumLhState.chart);
    }
  } catch (_err) {
    /* ignore */
  }
}

function vacuumMoney(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  const sign = x > 0 ? "+" : "";
  return `${sign}${x.toFixed(2)}`;
}

function vacuumPnlClass(n) {
  const x = Number(n);
  if (!Number.isFinite(x) || x === 0) return "";
  return x > 0 ? "pnl-plus" : "pnl-minus";
}

function vacuumPnlTd(n, text) {
  const cls = vacuumPnlClass(n);
  const body = text == null ? vacuumMoney(n) : text;
  return `<td class="${cls}">${body}</td>`;
}

function vacuumTimeMsk(ms) {
  const t = Number(ms);
  if (!t) return "—";
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function vacuumDur(min) {
  if (!Number.isFinite(min) || min < 0) return "—";
  if (min < 90) return `${Math.round(min)} мин`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

function vacuumExitLabel(reason) {
  if (reason === "trailing_stop") return "стоп";
  if (reason === "liquidation") return "ликвидация";
  if (reason === "opposite_pivot") return "противоположный";
  if (reason === "manual") return "вручную";
  return reason || "—";
}

async function vacuumManualCloseTrade(tradeId) {
  if (!Number.isFinite(tradeId) || tradeId < 1) return;
  if (!window.confirm("Закрыть сделку по текущей цене?")) return;
  try {
    const res = await fetch(`/api/paper/trades/${tradeId}/close`, { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      window.alert(body.detail || "Не удалось закрыть");
      return;
    }
    await fetchVacuumPaperSnapshot();
    void fetchVacuumDeskClosed(true);
    if (vacuumDeskVisible()) renderVacuumDesk();
  } catch (_err) {
    window.alert("Ошибка сети");
  }
}

function vacuumClosedStats(rows) {
  const list = rows || [];
  const pnls = list.map((t) => Number(t.pnl_usd) || 0);
  const wins = pnls.filter((p) => p > 0);
  const losses = pnls.filter((p) => p <= 0);
  const grossWin = wins.reduce((a, b) => a + b, 0);
  const grossLoss = -losses.reduce((a, b) => a + b, 0);
  const roes = list.map((t) => Number(t.roe_pct) || 0);
  const durs = list
    .map((t) => (t.closed_at && t.opened_at ? (Number(t.closed_at) - Number(t.opened_at)) / 60000 : null))
    .filter((x) => x != null && x >= 0);
  let running = 1000;
  let peak = 1000;
  let maxDd = 0;
  list
    .slice()
    .sort((a, b) => (Number(a.closed_at) || 0) - (Number(b.closed_at) || 0))
    .forEach((t) => {
      running += Number(t.pnl_usd) || 0;
      if (running > peak) peak = running;
      if (peak > 0) maxDd = Math.max(maxDd, ((peak - running) / peak) * 100);
    });
  const n = list.length;
  return {
    n,
    wins: wins.length,
    losses: losses.length,
    winRate: n ? (wins.length / n) * 100 : null,
    net: pnls.reduce((a, b) => a + b, 0),
    avgWin: wins.length ? grossWin / wins.length : 0,
    avgLoss: losses.length ? grossLoss / losses.length : 0,
    pf: grossLoss > 0 ? grossWin / grossLoss : wins.length ? Infinity : null,
    best: n ? Math.max(...pnls) : 0,
    worst: n ? Math.min(...pnls) : 0,
    avgRoe: n ? roes.reduce((a, b) => a + b, 0) / n : 0,
    avgMin: durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : 0,
    dd: maxDd,
    fees: list.reduce((a, t) => a + (Number(t.entry_fee) || 0) + (Number(t.exit_fee) || 0), 0),
  };
}

function vacuumDeskVariant() {
  if (vacuumLhState.mode === "vps5") return "vps5";
  if (vacuumLhState.mode === "vps15") return "vps15";
  if (vacuumLhState.mode === "pyl1") return "pyl1";
  if (vacuumLhState.mode === "pylbtc") return "pylbtc";
  return "pyl";
}

function vacuumRateText(stats) {
  if (!stats.n || stats.winRate == null) return "—";
  return `${stats.winRate.toFixed(1)}%`;
}

function vacuumAnalyticsCacheKey() {
  const opensAll = (vacuumLhState.paper || {}).open_trades || [];
  const openSig = opensAll
    .filter((t) => VACUUM_TRADE_VARIANTS.includes(t.variant))
    .map((t) => `${t.id}:${t.last_price}:${t.pnl_usd}`)
    .join("|");
  const closedSig = VACUUM_TRADE_VARIANTS
    .map((v) => {
      const rows = vacuumLhState.closedMap[v] || [];
      const tail = rows[0];
      return `${v}:${rows.length}:${tail?.id || 0}:${tail?.closed_at || 0}`;
    })
    .join(";");
  return `${openSig};${closedSig}`;
}

function vacuumAnalyticsTable() {
  const cacheKey = vacuumAnalyticsCacheKey();
  if (vacuumLhState._analyticsHtml && vacuumLhState._analyticsKey === cacheKey) {
    return vacuumLhState._analyticsHtml;
  }
  const opensAll = (vacuumLhState.paper || {}).open_trades || [];
  const cols = [
    ["pyl", "БАБЛОСОС"],
    ["pyl1", "БАБЛОСОС 1"],
    ["vps5", "Пылесос 5"],
    ["vps15", "Пылесос 15"],
  ].map(([variant, label]) => {
    const rows = vacuumLhState.closedMap[variant] || [];
    const stats = vacuumClosedStats(rows);
    const longs = vacuumClosedStats(rows.filter((t) => vacuumTradeSide(t) === "long"));
    const shorts = vacuumClosedStats(rows.filter((t) => vacuumTradeSide(t) === "short"));
    const openRows = opensAll.filter((t) => t.variant === variant);
    const openPnl = openRows.reduce((sum, t) => sum + (vacuumOpenMoney(t).pnl || 0), 0);
    const current = variant === vacuumDeskVariant();
    const plain = (html) => `<td class="${current ? "current" : ""}">${html}</td>`;
    const pnl = (n, text) => {
      const cls = [vacuumPnlClass(n), current ? "current" : ""].filter(Boolean).join(" ");
      const body = text == null ? vacuumMoney(n) : text;
      return `<td class="${cls}">${body}</td>`;
    };
    const pf = stats.pf == null ? "—" : stats.pf === Infinity ? "∞" : stats.pf.toFixed(2);
    return {
      label,
      current,
      cells: {
        open: plain(String(openRows.length)),
        openPnl: openRows.length ? pnl(openPnl) : plain("—"),
        closed: plain(String(stats.n)),
        split: plain(stats.n ? `${stats.wins} / ${stats.losses}` : "—"),
        wr: plain(vacuumRateText(stats)),
        net: stats.n ? pnl(stats.net) : plain("—"),
        avgWin: stats.wins ? pnl(stats.avgWin) : plain("—"),
        avgLoss: stats.losses ? pnl(-Math.abs(stats.avgLoss)) : plain("—"),
        pf: plain(pf),
        best: stats.n ? pnl(stats.best) : plain("—"),
        worst: stats.n ? pnl(stats.worst) : plain("—"),
        roe: stats.n
          ? pnl(stats.avgRoe, `${stats.avgRoe >= 0 ? "+" : ""}${stats.avgRoe.toFixed(1)}%`)
          : plain("—"),
        dur: plain(stats.n ? vacuumDur(stats.avgMin) : "—"),
        dd: plain(stats.n ? `${stats.dd.toFixed(1)}%` : "—"),
        fees: stats.n ? pnl(-stats.fees) : plain("—"),
        longWr: plain(longs.n ? `${vacuumRateText(longs)} · ${longs.n}` : "—"),
        longNet: longs.n ? pnl(longs.net) : plain("—"),
        shortWr: plain(shorts.n ? `${vacuumRateText(shorts)} · ${shorts.n}` : "—"),
        shortNet: shorts.n ? pnl(shorts.net) : plain("—"),
      },
    };
  });
  const head = cols.map((col) => `<th class="${col.current ? "current" : ""}">${col.label}</th>`).join("");
  const line = (name, key) => `<tr><td>${name}</td>${cols.map((col) => col.cells[key]).join("")}</tr>`;
  const html = `<thead><tr><th>Показатель</th>${head}</tr></thead><tbody>
    ${line("Открыто сейчас", "open")}
    ${line("Плавающий P&L", "openPnl")}
    ${line("Закрыто", "closed")}
    ${line("В плюсе / в минусе", "split")}
    ${line("Винрейт", "wr")}
    ${line("Итог", "net")}
    ${line("Средний плюс", "avgWin")}
    ${line("Средний минус", "avgLoss")}
    ${line("Profit factor", "pf")}
    ${line("Лучшая сделка", "best")}
    ${line("Худшая сделка", "worst")}
    ${line("Средний ROE", "roe")}
    ${line("Среднее время", "dur")}
    ${line("Макс. просадка", "dd")}
    ${line("Комиссии", "fees")}
    ${line("Лонги, винрейт", "longWr")}
    ${line("Лонги, итог", "longNet")}
    ${line("Шорты, винрейт", "shortWr")}
    ${line("Шорты, итог", "shortNet")}
  </tbody>`;
  vacuumLhState._analyticsKey = cacheKey;
  vacuumLhState._analyticsHtml = html;
  return html;
}

function vacuumDeskAccount() {
  const data = vacuumLhState.paper || window.paperTest?.data || {};
  return (((data.summary || {}).accounts || {})[vacuumDeskVariant()]) || {};
}

function vacuumDeskWatch() {
  const data = vacuumLhState.paper || {};
  if (vacuumLhState.mode === "vps5") return data.vps5_watch || [];
  if (vacuumLhState.mode === "vps15") return data.vps15_watch || [];
  if (vacuumLhState.mode === "pyl1") return data.pyl1_watch || [];
  if (vacuumLhState.mode === "pylbtc") return data.pylbtc_watch || [];
  return data.pyl_watch || [];
}

function onVacuumPaper(data) {
  if (!data) return;
  vacuumLhState.paper = data;
  vacuumLhState._analyticsKey = "";
  if (!vacuumUiActive()) return;
  const opens = (data.open_trades || []).filter((t) => VACUUM_TRADE_VARIANTS.includes(t.variant));
  if (vacuumLhState._lastOpenCount != null && opens.length < vacuumLhState._lastOpenCount) {
    void fetchVacuumDeskClosed(true);
    if (vacuumLhState.selected) void fetchVacuumSymbolClosed(vacuumLhState.selected);
  }
  vacuumLhState._lastOpenCount = opens.length;
  if (vacuumDeskVisible()) renderVacuumDesk();
  if (vacuumLhState.selected && vacuumLhState.chart?._lastBars?.length) {
    patchVacuumLivePrice();
    drawVacuumTradeOverlay(vacuumLhState.chart);
  }
  ensureVacuumTradeWarm();
  scheduleVacuumTradeCharts();
}

async function fetchVacuumDeskClosed(force) {
  const now = Date.now();
  if (force && vacuumLhState.closedReady && now - (vacuumLhState._closedFetchAt || 0) < 30_000) {
    force = false;
  }
  if (!force && vacuumLhState.closedReady) {
    vacuumLhState.closed = vacuumLhState.closedMap[vacuumDeskVariant()] || [];
    vacuumLhState.closedVariant = vacuumDeskVariant();
    return;
  }
  try {
    const pairs = await Promise.all(
      VACUUM_TRADE_VARIANTS.map(async (variant) => {
        const res = await fetch(`/api/paper/trades?status=closed&limit=2000&variant=${encodeURIComponent(variant)}`);
        if (!res.ok) return [variant, []];
        const body = await res.json();
        return [variant, body.rows || []];
      }),
    );
    for (const [variant, rows] of pairs) {
      vacuumLhState.closedMap[variant] = rows;
    }
    vacuumLhState.closedReady = true;
    vacuumLhState._closedFetchAt = Date.now();
    vacuumLhState._analyticsKey = "";
    vacuumLhState.closed = vacuumLhState.closedMap[vacuumDeskVariant()] || [];
    vacuumLhState.closedVariant = vacuumDeskVariant();
    if (vacuumDeskVisible()) renderVacuumDesk();
    if (vacuumLhState.selected && vacuumLhState.chart?._lastBars?.length) {
      drawVacuumTradeOverlay(vacuumLhState.chart);
    }
    scheduleVacuumTradeCharts();
  } catch (_err) {
    /* ignore */
  }
}

function renderVacuumDesk() {
  const acc = vacuumDeskAccount();
  const summary = document.getElementById("vacuum-desk-summary");
  if (summary) {
    const deskLabel =
      vacuumLhState.mode === "vps5"
        ? "Пылесос 5"
        : vacuumLhState.mode === "vps15"
          ? "Пылесос 15"
          : vacuumLhState.mode === "pyl1"
            ? "БАБЛОСОС 1"
            : vacuumLhState.mode === "pylbtc"
              ? "БАБЛОСОС+BTC"
              : "БАБЛОСОС";
    const rule =
      vacuumLhState.mode === "vps5"
        ? "LH/HL L15–L30, вход на 3-й 5m (max L слева). Закрытие: противоп. pivot после 2-й 5m справа. Стоп −15%, с +3% +0.5%, с +7% трейл − 20."
        : vacuumLhState.mode === "vps15"
          ? "15m pivot L15–L30: вход и выход через 1 закрытую 15m справа (окно 10 с). После выхода — сразу вход в обратную сторону. Стоп −15%, с +3% +0.5%, с +7% трейл − 20."
          : vacuumLhState.mode === "pyl1"
            ? "Как БАБЛОСОС + размах ≥2% за час. Запрет при расширении (high↑ и low↓). Лонг: min выше prev; шорт: max ниже prev. Стоп ±5% от пивота."
            : vacuumLhState.mode === "pylbtc"
              ? "Как БАБЛОСОС + BTC за 5 мин в сторону сделки (лонг — рост, шорт — падение). Стоп ±5% ROE от pivot."
              : "LH/HL L15–L30, вход на 3-й 5m (max L слева). Выход: лонг — новый LH после входа (2-я 5m справа закрыта); шорт — новый HL. Не каждый маркер на графике. Стоп ±5% ROE от pivot.";
    summary.innerHTML = `
      <div class="paper-card"><span class="label">Баланс</span><div class="value">${vacuumMoney(acc.balance ?? 1000)}</div><div class="sub">свободно ${vacuumMoney(acc.free_margin ?? 0)}</div></div>
      <div class="paper-card"><span class="label">Капитал</span><div class="value">${vacuumMoney(acc.equity ?? acc.balance ?? 1000)}</div><div class="sub">в сделках ${acc.open_trades || 0}</div></div>
      <div class="paper-card"><span class="label">Правило</span><div class="value">${deskLabel}</div><div class="sub">${rule}</div></div>`;
  }
  const statsTable = document.getElementById("vacuum-desk-stats");
  if (statsTable) statsTable.innerHTML = vacuumAnalyticsTable();
  const opens = ((vacuumLhState.paper || {}).open_trades || []).filter((t) => t.variant === vacuumDeskVariant());
  const openTable = document.getElementById("vacuum-desk-open");
  if (openTable) {
    openTable.innerHTML = opens.length
      ? `<thead><tr><th>Монета</th><th>Сторона</th><th>Вход</th><th>Цена</th><th>Стоп</th><th>ROE</th><th>P&L</th><th></th></tr></thead><tbody>${opens
          .map((t) => {
            const m = vacuumOpenMoney(t);
            const roeText = Number.isFinite(m.roe) ? `${m.roe >= 0 ? "+" : ""}${m.roe.toFixed(1)}%` : "—";
            return `<tr class="clickable" data-vac-desk-symbol="${t.symbol}">
          <td><b>${t.symbol}</b></td>
          <td>${vacuumSideLabel(vacuumTradeSide(t))}</td>
          <td>${t.entry_price}</td>
          <td>${t.last_price}</td>
          <td>${t.stop_price}</td>
          ${vacuumPnlTd(m.roe, roeText)}
          ${vacuumPnlTd(m.pnl)}
          <td><button type="button" class="paper-btn vac-paper-close-btn" data-vac-paper-close="${t.id}">Закрыть</button></td>
        </tr>`;
          })
          .join("")}</tbody>`
      : `<tbody><tr><td class="quiet">Нет открытых сделок</td></tr></tbody>`;
  }
  const watch = vacuumDeskWatch();
  const watchTable = document.getElementById("vacuum-desk-watch");
  if (watchTable) {
    watchTable.innerHTML = watch.length
      ? `<thead><tr><th>Монета</th><th>Сторона</th><th>Готово</th></tr></thead><tbody>${watch
          .slice(0, 40)
          .map((r) => {
            const vk = vacuumDeskVariant();
            const ev = (r.eval && r.eval[vk]) || {};
            const side = r.side || (ev.metrics || {}).side || ev.side;
            return `<tr class="clickable" data-vac-desk-symbol="${r.symbol}">
          <td><b>${r.symbol}</b></td>
          <td>${vacuumSideLabel(side)}</td>
          <td>${r.ready ? "да" : "нет"}</td>
        </tr>`;
          })
          .join("")}</tbody>`
      : `<tbody><tr><td class="quiet">Ждём новый экстремум на ${vacuumLhState.mode === "vps15" ? "15" : "5"} мин</td></tr></tbody>`;
  }
  const closed = vacuumLhState.closed || [];
  const closedTable = document.getElementById("vacuum-desk-closed");
  if (closedTable) {
    closedTable.innerHTML = closed.length
      ? `<thead><tr><th>Закрыта</th><th>Монета</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>ROE</th><th>P&L</th><th>Время</th><th>Причина</th></tr></thead><tbody>${closed
          .slice(0, 200)
          .map((t) => {
            const side = vacuumTradeSide(t);
            const mins = t.closed_at && t.opened_at ? (Number(t.closed_at) - Number(t.opened_at)) / 60000 : null;
            const roe = Number(t.roe_pct);
            const roeText = Number.isFinite(roe) ? `${roe >= 0 ? "+" : ""}${roe.toFixed(1)}%` : "—";
            return `<tr class="clickable" data-vac-desk-symbol="${t.symbol}">
          <td>${vacuumTimeMsk(t.closed_at)}</td>
          <td><b>${t.symbol}</b></td>
          <td>${vacuumSideLabel(side)}</td>
          <td>${t.entry_price ?? "—"}</td>
          <td>${t.exit_price ?? "—"}</td>
          ${vacuumPnlTd(roe, roeText)}
          ${vacuumPnlTd(t.pnl_usd)}
          <td>${vacuumDur(mins)}</td>
          <td>${vacuumExitLabel(t.exit_reason)}</td>
        </tr>`;
          })
          .join("")}</tbody>`
      : `<tbody><tr><td class="quiet">Нет закрытых сделок. Винрейт появится после первых выходов.</td></tr></tbody>`;
  }
}

window.vacuumLh = {
  initVacuumLhTab,
  onVacuumLhBoard,
  onVacuumLhSnapshot,
  onVacuumLhDetail,
  onPaper: onVacuumPaper,
  resizeChart: resizeVacuumLhChart,
  closeChart: closeVacuumLhChart,
};
