/* Вкладка «2× откат»: карточки + график 70/30. */

const x2State = {
  board: [],
  selected: null,
  detail: null,
  interval: "60",
  chart: null,
  prefetch: null,
};

const X2_CHART = {
  workspace: "x2-workspace",
  tfRow: "x2-tf-row",
  chart: "x2-candle-chart",
  info: "x2-info-pane",
  book: "x2-book-pane",
  walls: "x2-walls",
};

function initX2RetraceTab() {
  if (window.__x2RetraceBound) return;
  window.__x2RetraceBound = true;
  if (!x2State.chart) x2State.chart = window.boardChart.createRuntime();
  if (!x2State.prefetch) x2State.prefetch = window.boardChart.createPrefetchStore();

  window.boardChart.bindInfoPane(X2_CHART.info, closeX2Chart, (board, symbol) => {
    void dismissX2Watch(board, symbol);
  });

  document.getElementById("x2-columns")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(".dismiss-watch")) return;
    const card = target?.closest(".x2-card");
    if (card?.dataset.symbol) toggleX2Symbol(card.dataset.symbol);
  });
}

function toggleX2Symbol(symbol) {
  if (x2State.selected === symbol) {
    closeX2Chart();
    return;
  }
  x2State.selected = symbol;
  x2State.detail = null;
  openX2Chart();
  renderX2Board();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_x2_retrace", symbol }));
  }
  void refreshX2Chart(true);
}

function openX2Chart() {
  window.boardChart.bindInfoPane(X2_CHART.info, closeX2Chart, (board, symbol) => {
    void dismissX2Watch(board, symbol);
  });
  window.boardChart.bindTfRow(X2_CHART.tfRow, () => x2State.interval, setX2Interval);
  document.getElementById("x2-list-wrap")?.setAttribute("hidden", "");
  document.getElementById(X2_CHART.workspace)?.removeAttribute("hidden");
  window.boardChart.mount(x2State.chart, X2_CHART.chart);
  window.boardChart.syncTfButtons(() => x2State.interval, X2_CHART.tfRow);
  renderX2Info(true);
}

function closeX2Chart() {
  x2State.selected = null;
  x2State.detail = null;
  document.getElementById(X2_CHART.workspace)?.setAttribute("hidden", "");
  document.getElementById("x2-list-wrap")?.removeAttribute("hidden");
  renderX2Board();
}

function setX2Interval(interval) {
  if (!interval || x2State.interval === interval) return;
  x2State.interval = interval;
  x2State.chart.chartGen += 1;
  window.boardChart.syncTfButtons(() => x2State.interval, X2_CHART.tfRow);
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "x2_retrace_interval", interval }));
  }
  void refreshX2Chart(true);
}

async function dismissX2Watch(board, symbol) {
  try {
    await fetch("/api/watch/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board, symbol }),
    });
    x2State.selected = null;
    x2State.detail = null;
    closeX2Chart();
    renderX2Board();
  } catch (_e) {
    /* ignore */
  }
}

function onX2Board(data) {
  x2State.board = data || [];
  renderX2Board();
  scheduleX2Prefetch();
}

function onX2Snapshot(board, detail) {
  x2State.board = board || [];
  if (detail?.signal && x2State.selected === detail.signal.symbol) {
    mergeX2LiveDetail(detail);
  }
  renderX2Board();
  if (x2State.selected) {
    openX2Chart();
    void refreshX2Chart(false);
  }
  scheduleX2Prefetch();
}

function mergeX2LiveDetail(data) {
  if (!data) return;
  const prev = x2State.detail || {};
  x2State.detail = {
    ...prev,
    ...data,
    signal: data.signal ?? prev.signal,
    book: data.book ?? prev.book,
    funding_rate: data.funding_rate ?? prev.funding_rate,
  };
}

function onX2Detail(symbol, data) {
  if (!x2State.selected || x2State.selected !== symbol) return;
  mergeX2LiveDetail(data);
  void refreshX2Chart(false);
}

function scheduleX2Prefetch() {
  const symbols = [];
  for (const column of x2State.board) {
    for (const row of column.signals || []) {
      if (row.symbol) symbols.push(row.symbol);
    }
  }
  window.boardChart.schedulePrefetch(x2State.prefetch, symbols, ["60", "240"]);
}

async function refreshX2Chart(resetScale) {
  const symbol = x2State.selected;
  if (!symbol || !x2State.chart.series) return;
  const gen = ++x2State.chart.chartGen;
  const interval = x2State.interval;
  const candles = await window.boardChart.ensureCandles(
    x2State.prefetch,
    symbol,
    interval,
    x2State.detail,
  );
  if (gen !== x2State.chart.chartGen) return;
  if (x2State.detail) {
    x2State.detail.candles = candles;
    x2State.detail.interval = interval;
  }
  window.boardChart.drawCandles(x2State.chart, candles, interval, resetScale, X2_CHART.chart);
  if (resetScale) renderX2Info(true);
  else updateX2Live();
}

function updateX2Live() {
  const s = x2State.detail?.signal;
  if (!s) return;
  const priceEl = document.querySelector(`#${X2_CHART.info} [data-live='price']`);
  if (priceEl) priceEl.textContent = fmtPrice(s.last_price);
  window.boardChart.renderBookPane(X2_CHART.book, x2State.detail?.book, s.last_price);
  window.boardChart.renderWalls(X2_CHART.walls, x2State.detail?.book);
}

function renderX2Info(full) {
  const pane = document.getElementById(X2_CHART.info);
  if (!pane) return;
  const s = x2State.detail?.signal || findX2Row(x2State.selected);
  if (!x2State.selected || !s) {
    pane.innerHTML = '<p class="empty">Выберите карточку.</p>';
    return;
  }
  if (!full) {
    updateX2Live();
    return;
  }
  const detail = x2State.detail;
  const BC = window.boardChart;
  const { h1, h4 } = BC.resolveOi1h4h(s, detail);
  const oi1 = BC.formatOiChange(h1);
  const oi4 = BC.formatOiChange(h4);
  const funding = BC.fundingFrom(s, detail);
  const mult = s.peak_mult != null ? Number(s.peak_mult).toFixed(2) : fmt(s.multiplier);
  pane.innerHTML = `
    <header class="psc-info-head">
      <h2>${s.symbol}</h2>
      <span class="tag">${s.status} ${s.label}</span>
      <button type="button" class="psc-close-chart">Закрыть график</button>
      <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${s.symbol}" target="_blank" rel="noopener">Bybit</a>
    </header>
    <div class="psc-growth psc-growth-side">×${mult}</div>
    <p class="quiet psc-sub">рост от минимума за 21 д</p>
    <dl class="psc-info-fields">
      <div class="psc-row"><dt>Min low</dt><dd>${s.min_low_5d ?? "—"}</dd></div>
      <div class="psc-row"><dt>Откат от max 1H</dt><dd>${s.pullback_pct != null ? s.pullback_pct + "%" : "—"}</dd></div>
      <div class="psc-row"><dt>LH · 1H / 4H</dt><dd>${s.lh_1h ?? 0} / ${s.lh_4h ?? 0}</dd></div>
      <div class="psc-row"><dt>Две вершины</dt><dd>${formatTwoPeak(s)}</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 1 ч</dt><dd class="${oi1.cls}">${oi1.text}</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 4 ч</dt><dd class="${oi4.cls}">${oi4.text}</dd></div>
      <div class="psc-row"><dt>Рост 24 ч</dt><dd>${s.price_24h_pct != null ? "+" + fmt(s.price_24h_pct) + "%" : "—"}</dd></div>
      <div class="psc-row"><dt>EMA (глубина)</dt><dd>${s.ema_depth ?? 0} / 3</dd></div>
      <div class="psc-row"><dt>Цена</dt><dd data-live="price">${fmtPrice(s.last_price)}</dd></div>
      <div class="psc-row"><dt>Финансирование</dt><dd>${funding}</dd></div>
    </dl>
    <h3 class="psc-info-subhead">EMA 50 / 100 / 200</h3>
    <div class="psc-ema-block">${renderX2EmaBlock(s.ema_by_tf)}</div>
    <h3 class="psc-info-subhead">Стакан (±10% от цены)</h3>
    <div class="psc-book-pane" id="x2-book-pane"></div>
    <h3 class="psc-info-subhead">Крупные стены</h3>
    <div class="psc-walls" id="x2-walls"></div>
    <button type="button" class="dismiss-watch" data-dismiss-board="x2_retrace" data-symbol="${s.symbol}">Снять с отслеживания</button>
    <p class="quiet psc-info-hint">Таймфрейм: ${window.boardChart.tfLabel(x2State.interval)}</p>`;
  window.boardChart.renderBookPane(X2_CHART.book, detail?.book, s.last_price);
  window.boardChart.renderWalls(X2_CHART.walls, detail?.book);
}

function renderX2Board() {
  const root = document.getElementById("x2-columns");
  if (!root) return;
  root.innerHTML = x2State.board
    .map((column) => {
      const cards = (column.signals || [])
        .map((row) => x2CardHtml(row, column.color, row.symbol === x2State.selected))
        .join("");
      return `<section class="column ${column.color}">
        <h2>${column.status} ${column.label}</h2>
        ${cards || '<p class="quiet">нет монет</p>'}
      </section>`;
    })
    .join("");
  root.querySelectorAll("canvas.mini").forEach(drawX2Mini);
}

function x2CardHtml(row, color, active) {
  const peak = row.peak_mult != null ? Number(row.peak_mult).toFixed(2) : null;
  const multNum = peak || (row.multiplier != null ? Number(row.multiplier).toFixed(2) : null);
  const multLabel = multNum ? `×${multNum}` : "×2+";
  const peakHint =
    row.two_peak_kind === "double_top"
      ? `двойная вершина ${row.two_peak_tf || ""}`
      : row.two_peak_kind === "marginal_hh"
        ? `2-я вершина чуть выше (${row.two_peak_tf || ""})`
        : row.two_peak_kind === "lower_high"
          ? `LH ${row.two_peak_tf || ""}, ${row.two_peak_bars_between ?? "?"} св.`
          : "—";
  const BC = window.boardChart;
  const { h1, h4 } = BC.resolveOi1h4h(row, null);
  const oi1 = BC.formatOiChange(h1);
  const oi4 = BC.formatOiChange(h4);
  const pending = row.pending_stage ? `ожидает колонку ${row.pending_stage}` : "—";
  const pct24 =
    row.price_24h_pct != null ? `${Number(row.price_24h_pct) >= 0 ? "+" : ""}${fmt(row.price_24h_pct)}%` : "—";
  return `<article class="card x2-card board-rich-card ${color}${active ? " active" : ""}" data-symbol="${row.symbol}">
    <header class="psc-head">
      <h3 class="psc-symbol">${row.symbol.replace("USDT", "")}</h3>
      <span class="psc-kind">${row.status || ""} ${row.label || ""}</span>
    </header>
    <div class="psc-growth">${multLabel}</div>
    <p class="quiet psc-sub">рост от минимума за 21 д</p>
    <dl class="psc-fields">
      <div class="psc-row"><dt>Две вершины</dt><dd>${peakHint}</dd></div>
      <div class="psc-row"><dt>LH · 1H / 4H</dt><dd>${row.lh_1h ?? 0} / ${row.lh_4h ?? 0}</dd></div>
      <div class="psc-row"><dt>Откат от пика 1H</dt><dd>${row.pullback_pct != null ? row.pullback_pct + "%" : "—"}</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 1 ч</dt><dd class="${oi1.cls}">${oi1.text}</dd></div>
      <div class="psc-row"><dt>Открытый интерес · 4 ч</dt><dd class="${oi4.cls}">${oi4.text}</dd></div>
      <div class="psc-row"><dt>Рост 24 ч</dt><dd>${pct24}</dd></div>
      <div class="psc-row"><dt>EMA (глубина)</dt><dd>${row.ema_depth ?? 0} / 3</dd></div>
      <div class="psc-row"><dt>Смена колонки</dt><dd>${pending}</dd></div>
    </dl>
    <canvas class="mini mini-strategy" width="280" height="48" data-symbol="${row.symbol}"></canvas>
  </article>`;
}

function renderX2EmaBlock(map) {
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

function drawX2Mini(canvas) {
  const symbol = canvas.dataset.symbol;
  const row = findX2Row(symbol);
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

function findX2Row(symbol) {
  for (const column of x2State.board) {
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
  return Number(n).toFixed(2);
}

function formatTwoPeak(s) {
  if (!s.two_peak_kind) return "—";
  const label =
    s.two_peak_kind === "double_top"
      ? "double top"
      : s.two_peak_kind === "marginal_hh"
        ? "2 вершины (2-я чуть выше)"
        : "LH";
  return `${label} · ${s.two_peak_tf || "?"} · между ${s.two_peak_bars_between ?? "?"} св.`;
}

function resizeX2Chart() {
  const container = document.getElementById(X2_CHART.chart);
  if (!container || !x2State.chart?.chart || container.clientWidth <= 0) return;
  x2State.chart.chart.resize(container.clientWidth, container.clientHeight || 420);
}

window.x2Retrace = {
  initX2RetraceTab,
  onX2Board,
  onX2Snapshot,
  onX2Detail,
  resizeChart: resizeX2Chart,
};
