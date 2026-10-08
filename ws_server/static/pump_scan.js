/* Вкладка «Памп-скан»: карточки + график 70/30 как «Поиск пампов». */

const PUMP_CHECKS = [
  ["liquidations_faded", "Ликвидации шортов затихли"],
  ["oi_drop", "OI падает"],
  ["volume_faded", "Объём спал"],
  ["cvd_divergence", "Дивергенция CVD"],
  ["taker_sellers", "Продавцы в контроле"],
];

const pumpState = {
  board: [],
  selected: null,
  detail: null,
  interval: "15",
  chart: null,
  prefetch: null,
};

const PUMP_CHART = {
  listWrap: "pump-scan-list-wrap",
  workspace: "pump-scan-workspace",
  tfRow: "pump-scan-tf-row",
  chart: "pump-scan-candle-chart",
  info: "pump-scan-info-pane",
  book: "pump-scan-book-pane",
};

function initPumpScanTab() {
  if (window.__pumpScanBound) return;
  window.__pumpScanBound = true;
  if (!pumpState.chart) pumpState.chart = window.boardChart.createRuntime();
  if (!pumpState.prefetch) pumpState.prefetch = window.boardChart.createPrefetchStore();

  window.boardChart.bindInfoPane(PUMP_CHART.info, closePumpScanChart, (board, symbol) => {
    void dismissBoardWatch(board, symbol);
  });

  document.getElementById("pump-columns")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(".dismiss-watch")) return;
    const card = target?.closest(".pump-card");
    if (card?.dataset.symbol) togglePumpScanSymbol(card.dataset.symbol);
  });
}

function togglePumpScanSymbol(symbol) {
  if (pumpState.selected === symbol) {
    closePumpScanChart();
    return;
  }
  pumpState.selected = symbol;
  pumpState.detail = null;
  pumpState.chart.chartGen += 1;
  window.boardChart.resetChartSession(pumpState.chart, symbol);
  openPumpScanChart();
  renderPumpBoard();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_pump_scan", symbol }));
  }
  window.boardChart.scheduleAssetsPrefetch([symbol], {
    intervals: [pumpState.interval, "15", "60"],
    book: true,
    liq: true,
    priority: "high",
  });
  void refreshPumpScanChart(true);
}

function openPumpScanChart() {
  window.boardChart.bindInfoPane(PUMP_CHART.info, closePumpScanChart, (board, symbol) => {
    void dismissBoardWatch(board, symbol);
  });
  window.boardChart.bindTfRow(
    PUMP_CHART.tfRow,
    () => pumpState.interval,
    setPumpInterval,
  );
  document.getElementById(PUMP_CHART.listWrap)?.setAttribute("hidden", "");
  document.getElementById(PUMP_CHART.workspace)?.removeAttribute("hidden");
  window.boardChart.mount(pumpState.chart, PUMP_CHART.chart);
  window.boardChart.syncTfButtons(() => pumpState.interval, PUMP_CHART.tfRow);
  renderPumpScanInfo(true);
}

function closePumpScanChart() {
  pumpState.selected = null;
  pumpState.detail = null;
  document.getElementById(PUMP_CHART.workspace)?.setAttribute("hidden", "");
  document.getElementById(PUMP_CHART.listWrap)?.removeAttribute("hidden");
  renderPumpBoard();
}

function setPumpInterval(interval) {
  if (!interval || pumpState.interval === interval) return;
  pumpState.interval = interval;
  pumpState.chart.chartGen += 1;
  window.boardChart.syncTfButtons(() => pumpState.interval, PUMP_CHART.tfRow);
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "pump_scan_interval", interval }));
  }
  void refreshPumpScanChart(true);
}

async function dismissBoardWatch(board, symbol) {
  try {
    await fetch("/api/watch/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board, symbol }),
    });
    pumpState.selected = null;
    pumpState.detail = null;
    closePumpScanChart();
    renderPumpBoard();
  } catch (_e) {
    /* ignore */
  }
}

function onPumpScanBoard(data) {
  pumpState.board = data || [];
  renderPumpBoard();
  schedulePumpScanPrefetch();
}

function onPumpScanSnapshot(board, detail) {
  pumpState.board = board || [];
  if (detail?.signal && pumpState.selected === detail.signal.symbol) {
    mergePumpLiveDetail(detail);
  }
  renderPumpBoard();
  if (pumpState.selected) {
    openPumpScanChart();
    void refreshPumpScanChart(false);
  }
  schedulePumpScanPrefetch();
}

function mergePumpLiveDetail(data) {
  if (!data) return;
  const prev = pumpState.detail || {};
  pumpState.detail = {
    ...prev,
    ...data,
    signal: data.signal ?? prev.signal,
    book: data.book ?? prev.book,
    liquidations: data.liquidations ?? prev.liquidations,
    funding_rate: data.funding_rate ?? prev.funding_rate,
    taker_ratio: data.taker_ratio ?? prev.taker_ratio,
  };
  if (pumpState.selected && pumpState.chart?._lastBars?.length) {
    window.boardChart.setChartLiquidations(pumpState.chart, pumpState.detail.liquidations);
  }
}

function onPumpScanDetail(symbol, data) {
  if (!pumpState.selected || pumpState.selected !== symbol) return;
  mergePumpLiveDetail(data);
  window.boardChart.setChartLiquidations(pumpState.chart, pumpState.detail?.liquidations);
  void refreshPumpScanChart(false);
}

function schedulePumpScanPrefetch() {
  const symbols = [];
  for (const column of pumpState.board) {
    for (const row of column.signals || []) {
      if (row.symbol) symbols.push(row.symbol);
    }
  }
  window.boardChart.schedulePrefetch(pumpState.prefetch, symbols, ["15", "60"]);
}

async function refreshPumpScanChart(resetScale) {
  const symbol = pumpState.selected;
  if (!symbol) return;
  if (!pumpState.chart.series) window.boardChart.mount(pumpState.chart, PUMP_CHART.chart);
  if (!pumpState.chart.series) return;
  const BC = window.boardChart;
  if (!resetScale) {
    updatePumpScanLive();
    const now = Date.now();
    if (pumpState._chartPullAt && now - pumpState._chartPullAt < 15_000) return;
    pumpState._chartPullAt = now;
  }
  const gen = ++pumpState.chart.chartGen;
  const interval = pumpState.interval;
  BC.scheduleAssetsPrefetch([symbol], { intervals: [interval], book: true, liq: true, priority: "high" });
  BC.paintCandlesFromCache(pumpState.chart, symbol, interval, resetScale, PUMP_CHART.chart);
  const candles = await BC.ensureCandles(null, symbol, interval, pumpState.detail, { refreshFallback: resetScale });
  if (gen !== pumpState.chart.chartGen) return;
  if (pumpState.detail) {
    pumpState.detail.candles = candles;
    pumpState.detail.interval = interval;
  }
  const live = findPumpRow(symbol)?.last_price ?? pumpState.detail?.last_price;
  window.boardChart.drawCandles(pumpState.chart, candles, interval, resetScale, PUMP_CHART.chart, live);
  window.boardChart.setChartLiquidations(pumpState.chart, pumpState.detail?.liquidations);
  if (resetScale) renderPumpScanInfo(true);
  else updatePumpScanLive();
}

function updatePumpScanLive() {
  const row = findPumpRow(pumpState.selected);
  if (!row) return;
  const priceEl = document.querySelector(`#${PUMP_CHART.info} [data-live='price']`);
  if (priceEl) priceEl.textContent = fmtPrice(row.last_price);
  window.boardChart.renderBookPane(PUMP_CHART.book, pumpState.detail?.book, row?.last_price, row?.symbol);
}

function renderPumpScanInfo(full) {
  const pane = document.getElementById(PUMP_CHART.info);
  if (!pane) return;
  const row = findPumpRow(pumpState.selected);
  const detail = pumpState.detail;
  if (!pumpState.selected || !row) {
    pane.innerHTML = '<p class="empty">Выберите карточку.</p>';
    return;
  }
  if (!full) {
    updatePumpScanLive();
    return;
  }
  const BC = window.boardChart;
  const { h1, h4 } = BC.resolveOi1h4h(row, detail);
  const oi1 = BC.formatOiChange(h1);
  const oi4 = BC.formatOiChange(h4);
  const funding = BC.fundingFrom(row, detail);
  const taker =
    detail?.taker_ratio != null
      ? Number(detail.taker_ratio).toFixed(2)
      : row.taker_ratio != null
        ? Number(row.taker_ratio).toFixed(2)
        : "—";
  const checks = PUMP_CHECKS.map(([key, label]) => {
    let on = false;
    if (key === "taker_sellers") on = row.taker_ratio != null && row.taker_ratio < 1;
    else on = !!row[key];
    return `<li class="${on ? "ok" : ""}">${label}</li>`;
  }).join("");

  pane.innerHTML = `
    <div class="psc-info-meta">
      <header class="psc-info-head">
        <h2>${row.symbol}</h2>
        <span class="tag">${row.status} ${row.label}</span>
        <button type="button" class="psc-close-chart">Закрыть график</button>
        <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${row.symbol}" target="_blank" rel="noopener">Bybit</a>
      </header>
      <div class="psc-growth psc-growth-side">+${fmt(row.price_24h_pct)}%</div>
      <p class="quiet psc-sub">рост за 24 часа · ослабление ${row.weaken_score ?? 0}/7</p>
      <dl class="psc-info-fields">
        <div class="psc-row"><dt>EMA (глубина)</dt><dd>${row.ema_depth ?? 0} / 3</dd></div>
        <div class="psc-row"><dt>Открытый интерес · 1 ч</dt><dd class="${oi1.cls}">${oi1.text}</dd></div>
        <div class="psc-row"><dt>Открытый интерес · 4 ч</dt><dd class="${oi4.cls}">${oi4.text}</dd></div>
        <div class="psc-row"><dt>Объём × к MA</dt><dd>${row.volume_ratio != null ? Number(row.volume_ratio).toFixed(1) : "—"}</dd></div>
        <div class="psc-row"><dt>Цена</dt><dd data-live="price">${fmtPrice(row.last_price)}</dd></div>
        <div class="psc-row"><dt>Финансирование</dt><dd>${funding}</dd></div>
        <div class="psc-row"><dt>Тейкеры buy/sell</dt><dd>${taker}</dd></div>
      </dl>
      <h3 class="psc-info-subhead">Признаки ослабления</h3>
      <ul class="checklist psc-checklist">${checks}</ul>
      <h3 class="psc-info-subhead">EMA 50 / 100 / 200</h3>
      <div class="psc-ema-block">${renderEmaBlock(row.ema_by_tf)}</div>
    </div>
    ${window.boardChart.bookSectionHtml("pump-scan-book-pane")}
    <footer class="psc-info-foot">
      <button type="button" class="dismiss-watch" data-dismiss-board="pump_scan" data-symbol="${row.symbol}">Снять с отслеживания</button>
      <p class="quiet psc-info-hint">Таймфрейм: ${window.boardChart.tfLabel(pumpState.interval)}</p>
    </footer>`;
  window.boardChart.renderBookPane(PUMP_CHART.book, detail?.book, row.last_price, row.symbol);
}

function renderPumpBoard() {
  const root = document.getElementById("pump-columns");
  if (!root) return;
  root.innerHTML = pumpState.board
    .map((column) => {
      const cards = (column.signals || [])
        .map((row) => pumpCardHtml(row, column.color, row.symbol === pumpState.selected))
        .join("");
      return `<section class="column ${column.color}">
        <h2>${column.status} ${column.label}</h2>
        ${cards || '<p class="quiet">нет монет</p>'}
      </section>`;
    })
    .join("");
  root.querySelectorAll("canvas.mini").forEach(drawPumpMini);
}

function pumpCardHtml(row, color, active) {
  const BC = window.boardChart;
  const { h1, h4 } = BC.resolveOi1h4h(row, null);
  const oi1 = BC.formatOiChange(h1);
  const oi4 = BC.formatOiChange(h4);
  const pending = row.pending_stage ? `ожидает колонку ${row.pending_stage}` : "—";
  const emaLine = emaHintText(row.ema_by_tf);
  return `<article class="card pump-card board-rich-card ${color}${active ? " active" : ""}" data-symbol="${row.symbol}">
    <header class="psc-head">
      <h3 class="psc-symbol">${row.symbol.replace("USDT", "")}</h3>
      <span class="psc-kind">${row.status || ""} ${row.label || ""}</span>
    </header>
    <div class="psc-growth">+${fmt(row.price_24h_pct)}%</div>
    <p class="quiet psc-sub">рост за 24 часа</p>
    <dl class="psc-fields">
      <div class="psc-row"><dt>Ослабление пампа</dt><dd>${row.weaken_score ?? 0} из 7</dd></div>
      <div class="psc-row"><dt>EMA (глубина)</dt><dd>${row.ema_depth ?? 0} / 3</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 1 ч</dt><dd class="${oi1.cls}">${oi1.text}</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 4 ч</dt><dd class="${oi4.cls}">${oi4.text}</dd></div>
      <div class="psc-row"><dt>Смена колонки</dt><dd>${pending}</dd></div>
      <div class="psc-row"><dt>EMA по ТФ</dt><dd class="psc-muted psc-ema-dd">${emaLine}</dd></div>
    </dl>
    <canvas class="mini mini-strategy" width="280" height="48" data-symbol="${row.symbol}"></canvas>
  </article>`;
}

function emaHintText(map) {
  if (!map || !Object.keys(map).length) return "EMA: ждём свечи 15m–4H";
  return Object.entries(map)
    .map(([tf, info]) => `${tf}: ${info.summary}`)
    .slice(0, 2)
    .join(" · ");
}

function renderEmaBlock(map) {
  if (!map || !Object.keys(map).length) {
    return '<p class="quiet">Нужны закрытые свечи 15m–4H.</p>';
  }
  const rows = Object.entries(map)
    .map(
      ([tf, info]) =>
        `<tr><td>${tf}</td><td>${info.summary}</td><td>${info.depth}/3</td></tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table class="ema-table"><thead><tr><th>TF</th><th>Состояние</th><th>Глубина</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function drawPumpMini(canvas) {
  const symbol = canvas.dataset.symbol;
  const row = findPumpRow(symbol);
  const closes = row?.mini;
  if (!closes?.length) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  ctx.strokeStyle = "#5dade2";
  ctx.beginPath();
  closes.forEach((price, index) => {
    const x = (index / (closes.length - 1 || 1)) * (w - 2) + 1;
    const y = h - 1 - ((price - min) / span) * (h - 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function findPumpRow(symbol) {
  for (const column of pumpState.board) {
    for (const row of column.signals || []) {
      if (row.symbol === symbol) return row;
    }
  }
  return null;
}

function fmtPrice(n) {
  const x = Number(n);
  if (Number.isNaN(x) || !x) return "—";
  if (x >= 100) return x.toFixed(2);
  if (x >= 1) return x.toFixed(4);
  return x.toPrecision(4);
}

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(1);
}

function resizePumpScanChart() {
  const container = document.getElementById(PUMP_CHART.chart);
  if (!container || !pumpState.chart?.chart || container.clientWidth <= 0) return;
  pumpState.chart.chart.resize(container.clientWidth, container.clientHeight || 420);
}

window.pumpScan = {
  initPumpScanTab,
  onPumpScanBoard,
  onPumpScanSnapshot,
  onPumpScanDetail,
  resizeChart: resizePumpScanChart,
};
