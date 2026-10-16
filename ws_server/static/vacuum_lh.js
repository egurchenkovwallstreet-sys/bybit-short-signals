/* Пылесос LH: 1H lower highs → список монет, график 15m с отметками вершин. */

const vacuumLhState = {
  signals: [],
  selected: null,
  detail: null,
  chart: null,
};

const VAC_CHART = {
  listWrap: "vacuum-lh-list-wrap",
  workspace: "vacuum-lh-workspace",
  chart: "vacuum-lh-candle-chart",
  info: "vacuum-lh-info-pane",
};

const PEAK_COLORS = ["#e9c46a", "#f4a261", "#e76f51", "#d62828", "#9d0208"];

function initVacuumLhTab() {
  if (window.__vacuumLhBound) return;
  window.__vacuumLhBound = true;
  vacuumLhState.chart = window.boardChart.createRuntime();
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
  window.boardChart.scheduleAssetsPrefetch([symbol], { intervals: ["15", "60"], book: true, liq: false, priority: "high" });
  void refreshVacuumLhChart(true);
}

function openVacuumLhChart() {
  document.getElementById(VAC_CHART.listWrap)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.workspace)?.removeAttribute("hidden");
  window.boardChart.mount(vacuumLhState.chart, VAC_CHART.chart);
  renderVacuumLhInfo();
}

function closeVacuumLhChart() {
  vacuumLhState.selected = null;
  vacuumLhState.detail = null;
  clearVacuumPeakOverlays(vacuumLhState.chart);
  document.getElementById(VAC_CHART.workspace)?.setAttribute("hidden", "");
  document.getElementById(VAC_CHART.listWrap)?.removeAttribute("hidden");
  renderVacuumLhBoard();
}

function onVacuumLhBoard(data) {
  vacuumLhState.signals = Array.isArray(data) ? data : [];
  renderVacuumLhBoard();
  if (vacuumLhState.selected) {
    void refreshVacuumLhChart(false);
  }
}

function onVacuumLhSnapshot(board, detail) {
  onVacuumLhBoard(board);
  if (detail?.signal && vacuumLhState.selected === detail.signal.symbol) {
    vacuumLhState.detail = detail;
    renderVacuumLhInfo();
    drawVacuumPeakOverlays(vacuumLhState.chart, detail.signal.peaks || []);
  }
}

function onVacuumLhDetail(symbol, data) {
  if (!vacuumLhState.selected || vacuumLhState.selected !== symbol) return;
  vacuumLhState.detail = data;
  renderVacuumLhInfo();
  if (vacuumLhState.chart?.series) {
    drawVacuumPeakOverlays(vacuumLhState.chart, data?.signal?.peaks || []);
  }
}

function renderVacuumLhBoard() {
  const grid = document.getElementById("vacuum-lh-grid");
  if (!grid) return;
  if (!vacuumLhState.signals.length) {
    grid.innerHTML = '<p class="quiet">Нет монет: нужны 5 LH на 1H и цена ниже всех вершин, оборот &gt; $300k.</p>';
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
  const list = peaks
    .map(
      (p) =>
        `<li>LH${p.index}: <strong>${p.price}</strong> (1H ${new Date(p.time_ms).toLocaleString("ru-RU")})</li>`,
    )
    .join("");
  pane.innerHTML = `
    <div class="psc-info-head">
      <h3>${sym}</h3>
      <button type="button" class="paper-btn vacuum-lh-close">Закрыть</button>
    </div>
    <p>График <strong>15m</strong>. Линии — пять последних вершин 1H (понижающиеся). Цена ниже всех.</p>
    <p>Цена: <strong>${row.last_price ?? "—"}</strong></p>
    <ul class="vacuum-lh-peaks">${list || "<li>—</li>"}</ul>`;
}

function clearVacuumPeakOverlays(runtime) {
  if (!runtime?.series || !runtime._vacuumPeakLines?.length) return;
  for (const line of runtime._vacuumPeakLines) {
    try {
      runtime.series.removePriceLine(line);
    } catch (_e) {
      /* ignore */
    }
  }
  runtime._vacuumPeakLines = [];
  try {
    runtime.series.setMarkers([]);
  } catch (_e) {
    /* ignore */
  }
}

function drawVacuumPeakOverlays(runtime, peaks) {
  if (!runtime?.series) return;
  clearVacuumPeakOverlays(runtime);
  runtime._vacuumPeakLines = [];
  const markers = [];
  const tzOffset = new Date().getTimezoneOffset() * 60;
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
    if (p.time_15m_ms) {
      markers.push({
        time: Math.floor(p.time_15m_ms / 1000) - tzOffset,
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

async function refreshVacuumLhChart(resetScale) {
  const symbol = vacuumLhState.selected;
  if (!symbol) return;
  const BC = window.boardChart;
  if (!vacuumLhState.chart.series) BC.mount(vacuumLhState.chart, VAC_CHART.chart);
  if (!vacuumLhState.chart.series) return;
  const interval = "15";
  BC.scheduleAssetsPrefetch([symbol], { intervals: [interval], book: true, priority: "high" });
  BC.paintCandlesFromCache(vacuumLhState.chart, symbol, interval, resetScale, VAC_CHART.chart);
  const candles = await BC.ensureCandles(null, symbol, interval, vacuumLhState.detail, { refreshFallback: resetScale });
  if (vacuumLhState.detail) {
    vacuumLhState.detail.candles = candles;
    vacuumLhState.detail.interval = interval;
  }
  const live = findVacuumRow(symbol)?.last_price ?? vacuumLhState.detail?.signal?.last_price;
  BC.drawCandles(vacuumLhState.chart, candles, interval, resetScale, VAC_CHART.chart, live);
  const peaks = vacuumLhState.detail?.signal?.peaks || findVacuumRow(symbol)?.peaks || [];
  drawVacuumPeakOverlays(vacuumLhState.chart, peaks);
  if (resetScale) renderVacuumLhInfo();
}

function resizeVacuumLhChart() {
  vacuumLhState.chart?.chart?.resize?.();
}

window.vacuumLh = {
  initVacuumLhTab,
  onVacuumLhBoard,
  onVacuumLhSnapshot,
  onVacuumLhDetail,
  resizeChart: resizeVacuumLhChart,
};
