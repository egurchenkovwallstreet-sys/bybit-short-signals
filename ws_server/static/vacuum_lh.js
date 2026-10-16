/* Пылесос LH: список 30m/1H/4H; у монеты один график, TF 5m–4H, буфер свечей на каждый TF. */

const VACUUM_LIST_TF = [
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
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

const vacuumLhState = {
  lhInterval: "60",
  chartInterval: "60",
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
const PEAK_CONFLUENCE_COLOR = "#ffe566";
const PEAK_CONFLUENCE_STRONG = "#ffffff";

function vacuumPeakMatchCount(p) {
  const n = Number(p?.tf_match_count);
  if (n >= 1) return n;
  return p?.confluence ? 2 : 1;
}

function vacuumPeakLineStyle(p, fallbackColor) {
  const n = vacuumPeakMatchCount(p);
  if (n >= 3) {
    return { color: PEAK_CONFLUENCE_STRONG, lineWidth: 3, lineStyle: 0 };
  }
  if (n >= 2) {
    return { color: PEAK_CONFLUENCE_COLOR, lineWidth: 2, lineStyle: 0 };
  }
  return { color: fallbackColor, lineWidth: 1, lineStyle: 2 };
}

function formatVacuumPeakPrice(p) {
  const price = Number(p.price);
  const n = vacuumPeakMatchCount(p);
  const cls = n >= 3 ? "vacuum-lh-peak-x3" : n >= 2 ? "vacuum-lh-peak-x2" : "";
  const tag = n >= 2 ? `<sup class="vacuum-lh-peak-tag">×${n} TF</sup>` : "";
  return `<span class="vacuum-lh-peak${cls ? ` ${cls}` : ""}">${price}${tag}</span>`;
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
      </div>`;
  } else if (!document.getElementById(VAC_CHART.chartTfRow)) {
    const row = document.createElement("div");
    row.className = "psc-tf-row vacuum-lh-chart-tf-row";
    row.id = VAC_CHART.chartTfRow;
    pane.insertBefore(row, pane.firstChild);
  }
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
      const listTf = target.closest("[data-vac-list-tf]");
      if (listTf?.dataset.vacListTf) {
        event.preventDefault();
        setVacuumListTf(listTf.dataset.vacListTf);
        return;
      }
      const card = target.closest(".vacuum-lh-card");
      if (card?.dataset.symbol) toggleVacuumLhSymbol(card.dataset.symbol);
    });
  }
  renderVacuumTfControls();
  if (!vacuumLhState.loaded && !vacuumLhState.loading) {
    void fetchVacuumLhBoard();
  }
  applyVacuumInterval(vacuumLhState.lhInterval);
  renderVacuumLhBoard();
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

function renderVacuumTfControls() {
  const toolbar = document.querySelector(".vacuum-lh-toolbar");
  const listRow = document.getElementById(VAC_CHART.listTfRow);
  const chartRow = document.getElementById(VAC_CHART.chartTfRow);
  const detailOpen = !!vacuumLhState.selected;
  toolbar?.classList.toggle("vacuum-lh-toolbar-list-only", detailOpen);
  if (listRow && !detailOpen) {
    listRow.innerHTML = `<span class="vacuum-tf-label">Список LH</span>${listTfButtonsHtml()}`;
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

function getVacuumPeaks() {
  const sym = vacuumLhState.selected;
  if (!sym) return [];
  return vacuumLhState.detail?.signal?.peaks || findVacuumRow(sym)?.peaks || [];
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

function drawVacuumCandles(candles, resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol || !candles?.length || !mountVacuumChart()) return false;
  const BC = window.boardChart;
  const interval = vacuumLhState.chartInterval;
  const live = findVacuumRow(symbol)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  BC.drawCandles(vacuumLhState.chart, candles, interval, resetScale, VAC_CHART.chart, live);
  drawVacuumPeakOverlays(vacuumLhState.chart, getVacuumPeaks(), interval);
  requestAnimationFrame(resizeVacuumChartNow);
  setVacuumChartPlaceholder("");
  return true;
}

function paintVacuumChartFromBuffer(resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol) return false;
  const BC = window.boardChart;
  const interval = vacuumLhState.chartInterval;
  const candles = BC.getCachedCandles(symbol, interval);
  if (candles.length < VACUUM_MIN_BARS) return false;
  return drawVacuumCandles(candles, resetScale);
}

function vacuumLoadStillValid(seq, symbol) {
  return vacuumLhState._loadSeq === seq && vacuumLhState.selected === symbol;
}

async function loadVacuumChartDisplay(resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol) return;
  const seq = ++vacuumLhState._loadSeq;
  setVacuumChartPlaceholder("Загрузка свечей…");
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  if (!vacuumLoadStillValid(seq, symbol)) return;
  if (!mountVacuumChart()) {
    setVacuumChartPlaceholder("График недоступен (нет lightweight-charts)");
    return;
  }
  const BC = window.boardChart;
  const interval = vacuumLhState.chartInterval;
  await ensureVacuumBuffers(symbol, vacuumLhState.bufferSymbol !== symbol);
  if (!vacuumLoadStillValid(seq, symbol)) return;
  let candles = BC.getCachedCandles(symbol, interval);
  if (candles.length < VACUUM_MIN_BARS) {
    candles = await BC.ensureCandles(null, symbol, interval, null, { refreshFallback: true });
  }
  if (!vacuumLoadStillValid(seq, symbol)) return;
  if (candles.length < 1) {
    setVacuumChartPlaceholder("Нет данных свечей для этого TF — попробуйте 15m или 1H");
    return;
  }
  drawVacuumCandles(candles, resetScale);
}

async function ensureVacuumBuffers(symbol, force) {
  if (!force && vacuumLhState.bufferSymbol === symbol && !vacuumLhState.bufferLoading) {
    return VACUUM_BUFFER_TF.every(
      (iv) => window.boardChart.getCachedCandles(symbol, iv).length >= VACUUM_MIN_BARS,
    );
  }
  vacuumLhState.bufferLoading = true;
  vacuumLhState.bufferSymbol = symbol;
  const BC = window.boardChart;
  BC.scheduleAssetsPrefetch([symbol], {
    intervals: VACUUM_BUFFER_TF,
    book: false,
    liq: false,
    priority: "high",
  });
  try {
    await Promise.all(
      VACUUM_BUFFER_TF.map((iv) =>
        BC.ensureCandles(null, symbol, iv, null, { refreshFallback: true }),
      ),
    );
  } finally {
    vacuumLhState.bufferLoading = false;
  }
  return true;
}

async function switchVacuumChartTf(interval) {
  if (!vacuumLhState.selected || vacuumLhState.chartInterval === interval) return;
  vacuumLhState.chartInterval = interval;
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
  if (paintVacuumChartFromBuffer(true)) return;
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
      ? `Обновлено: ${new Date(vacuumLhState.updatedAt).toLocaleTimeString("ru-RU")} · список ${labelTf(vacuumLhState.lhInterval)}`
      : "",
  );
  renderVacuumLhBoard();
}

function findVacuumRow(symbol) {
  const inList = vacuumLhState.signals.find((s) => s.symbol === symbol);
  if (inList) return inList;
  for (const rows of Object.values(vacuumLhState.byInterval)) {
    const hit = (rows || []).find((s) => s.symbol === symbol);
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
  vacuumLhState.chartInterval = vacuumLhState.lhInterval;
  openVacuumLhChart();
  renderVacuumLhBoard();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_vacuum_lh", symbol }));
  }
  await loadVacuumChartDisplay(true);
}

function openVacuumLhChart() {
  normalizeVacuumChartDom();
  renderVacuumTfControls();
  document.getElementById(VAC_CHART.listWrap)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.workspace)?.removeAttribute("hidden");
  setVacuumDetailOpen(true);
  mountVacuumChart();
  renderVacuumLhInfo();
}

function closeVacuumLhChart() {
  vacuumLhState._loadSeq += 1;
  vacuumLhState.selected = null;
  vacuumLhState.detail = null;
  vacuumLhState.bufferSymbol = null;
  setVacuumChartPlaceholder("");
  clearVacuumPeakOverlays(vacuumLhState.chart);
  document.getElementById(VAC_CHART.workspace)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.listWrap)?.removeAttribute("hidden");
  setVacuumDetailOpen(false);
  renderVacuumTfControls();
  renderVacuumLhBoard();
}

function patchVacuumLivePrice() {
  const sym = vacuumLhState.selected;
  const rt = vacuumLhState.chart;
  if (!sym || !rt?.series || !rt._lastBars?.length) return;
  const live = findVacuumRow(sym)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  if (live == null) return;
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
  const priceEl = document.querySelector(`#${VAC_CHART.info} [data-vac-live='price']`);
  if (priceEl) priceEl.textContent = String(live);
}

function mergeVacuumDetail(data) {
  if (!data) return;
  const prevSignal = vacuumLhState.detail?.signal;
  vacuumLhState.detail = { ...data, signal: data.signal || prevSignal };
}

function onVacuumLhBoard(data) {
  ingestVacuumPayload(data);
  if (vacuumLhState.selected) patchVacuumLivePrice();
}

function onVacuumLhSnapshot(board, detail) {
  ingestVacuumPayload(board);
  if (detail?.signal && vacuumLhState.selected === detail.signal.symbol) {
    mergeVacuumDetail(detail);
    renderVacuumLhInfo();
    if (vacuumLhState.chart?._lastBars?.length) {
      drawVacuumPeakOverlays(vacuumLhState.chart, getVacuumPeaks(), vacuumLhState.chartInterval);
    }
  }
}

function onVacuumLhDetail(symbol, data) {
  if (!vacuumLhState.selected || vacuumLhState.selected !== symbol) return;
  mergeVacuumDetail(data);
  renderVacuumLhInfo();
  if (vacuumLhState.chart?._lastBars?.length) {
    drawVacuumPeakOverlays(vacuumLhState.chart, getVacuumPeaks(), vacuumLhState.chartInterval);
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
      const peaks = (row.peaks || []).map((p) => formatVacuumPeakPrice(p)).join(" · ");
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
  const lhTf = labelTf(vacuumLhState.lhInterval);
  const chartTf = labelTf(vacuumLhState.chartInterval);
  const list = peaks
    .map((p) => {
      const n = vacuumPeakMatchCount(p);
      const cls = n >= 3 ? "vacuum-lh-peak-li-x3" : n >= 2 ? "vacuum-lh-peak-li-x2" : "";
      const tfNote =
        n >= 2 && p.tf_matches?.length
          ? ` · <span class="vacuum-lh-peak-tag">${p.tf_matches.map(labelTf).join(", ")}</span>`
          : "";
      return `<li class="${cls}">LH${p.index}: <strong>${p.price}</strong>${n >= 2 ? ` <span class="vacuum-lh-peak-tag">×${n} TF</span>` : ""} (${lhTf} ${new Date(p.time_ms).toLocaleString("ru-RU")})${tfNote}</li>`;
    })
    .join("");
  pane.innerHTML = `
    <div class="psc-info-head">
      <h3>${sym}</h3>
      <button type="button" class="psc-close-chart">Закрыть</button>
    </div>
    <p>График <strong>${chartTf}</strong>. LH в списке: <strong>${lhTf}</strong>. Яркие вершины — совпадение LH на 2+ TF (5m–4H).</p>
    <p>Цена: <strong data-vac-live="price">${row.last_price ?? "—"}</strong></p>
    <ul class="vacuum-lh-peaks">${list || "<li>—</li>"}</ul>`;
  bindVacuumLhCloseControls();
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
  const iv = chartInterval || vacuumLhState.chartInterval || "60";
  peaks.forEach((p, i) => {
    const price = Number(p.price);
    if (!price) return;
    const baseColor = PEAK_COLORS[i % PEAK_COLORS.length];
    const n = vacuumPeakMatchCount(p);
    const style = vacuumPeakLineStyle(p, baseColor);
    const label =
      n >= 2 ? `LH${p.index || i + 1}·${n}TF` : `LH${p.index || i + 1}`;
    runtime._vacuumPeakLines.push(
      runtime.series.createPriceLine({
        price,
        color: style.color,
        lineWidth: style.lineWidth,
        lineStyle: style.lineStyle,
        axisLabelVisible: true,
        title: label,
      }),
    );
    const tMs = p.time_ms ?? p.time_chart_ms ?? p.time_15m_ms;
    const barTime = BC?.candleTime?.(tMs, iv);
    if (barTime) {
      markers.push({
        time: barTime,
        position: "aboveBar",
        color: style.color,
        shape: n >= 2 ? "square" : "circle",
        text: label,
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

function resizeVacuumLhChart() {
  if (!vacuumLhState.selected) return;
  resizeVacuumChartNow();
}

window.vacuumLh = {
  initVacuumLhTab,
  onVacuumLhBoard,
  onVacuumLhSnapshot,
  onVacuumLhDetail,
  resizeChart: resizeVacuumLhChart,
  closeChart: closeVacuumLhChart,
};
