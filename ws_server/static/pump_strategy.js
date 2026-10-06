/* Вкладка «Поиск пампов»: карточки, график 70% + инфо 30%, фоновая подгрузка. */

const PSC_TF = [
  ["1", "1m"],
  ["5", "5m"],
  ["15", "15m"],
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
  ["D", "1D"],
];

const PSC_FETCH_DAYS = 14;
const PSC_PREFETCH_CONCURRENCY = 3;
const PSC_INTERVAL_SEC = { 1: 60, 5: 300, 15: 900, 30: 1800, 60: 3600, 240: 14400, D: 86400 };

const pumpStrategyState = {
  signals: [],
  selected: null,
  interval: "15",
  detail: null,
  chart: null,
  series: null,
  volumeSeries: null,
  chartGen: 0,
  priceRange: { min: 0, max: 0 },
  prefetch: new Map(),
  prefetchQueue: [],
  prefetchActive: 0,
  tfBound: false,
};

function bindPumpStrategyInfoPane() {
  if (window.__pscInfoPaneBound) return;
  window.__pscInfoPaneBound = true;
  document.getElementById("psc-info-pane")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(".psc-close-chart")) {
      event.preventDefault();
      closePumpStrategyChart();
      return;
    }
    const dismiss = target?.closest("[data-dismiss-board]");
    if (dismiss?.dataset.dismissBoard && dismiss.dataset.symbol) {
      void dismissPumpStrategy(dismiss.dataset.dismissBoard, dismiss.dataset.symbol);
    }
  });
}

function initPumpStrategyTab() {
  bindPumpStrategyInfoPane();
  if (window.__pumpStrategyBound) return;
  window.__pumpStrategyBound = true;
  bindPumpStrategyTfRow();
  document.getElementById("pump-strategy-grid")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(".dismiss-watch")) return;
    const card = target?.closest(".pump-strategy-card");
    if (card?.dataset.symbol) togglePumpStrategySymbol(card.dataset.symbol);
  });
}

function bindPumpStrategyTfRow() {
  if (pumpStrategyState.tfBound) return;
  const row = document.getElementById("psc-tf-row");
  if (!row) return;
  pumpStrategyState.tfBound = true;
  row.innerHTML = PSC_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf psc-tf${code === pumpStrategyState.interval ? " active" : ""}" data-psc-interval="${code}">${label}</button>`,
  ).join("");
  row.addEventListener("click", (event) => {
    const btn = event.target instanceof Element ? event.target.closest("[data-psc-interval]") : null;
    if (!btn?.dataset.pscInterval) return;
    setPumpStrategyInterval(btn.dataset.pscInterval);
  });
}

function togglePumpStrategySymbol(symbol) {
  if (pumpStrategyState.selected === symbol) {
    closePumpStrategyChart();
    return;
  }
  pumpStrategyState.selected = symbol;
  pumpStrategyState.detail = null;
  openPumpStrategyChart();
  renderPumpStrategyBoard();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_pump_strategy", symbol }));
  }
  void refreshPumpStrategyChart(true);
}

function closePumpStrategyChart() {
  pumpStrategyState.selected = null;
  pumpStrategyState.detail = null;
  document.getElementById("pump-strategy-workspace")?.setAttribute("hidden", "");
  document.getElementById("pump-strategy-list-wrap")?.removeAttribute("hidden");
  renderPumpStrategyBoard();
}

function openPumpStrategyChart() {
  bindPumpStrategyInfoPane();
  document.getElementById("pump-strategy-list-wrap")?.setAttribute("hidden", "");
  document.getElementById("pump-strategy-workspace")?.removeAttribute("hidden");
  bindPumpStrategyTfRow();
  syncPumpStrategyTfButtons();
  mountPumpStrategyChart();
  renderPumpStrategyInfo();
}

function syncPumpStrategyTfButtons() {
  document.querySelectorAll("[data-psc-interval]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.pscInterval === pumpStrategyState.interval);
  });
}

function setPumpStrategyInterval(interval) {
  if (!interval || pumpStrategyState.interval === interval) return;
  pumpStrategyState.interval = interval;
  pumpStrategyState.chartGen += 1;
  syncPumpStrategyTfButtons();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "pump_strategy_interval", interval }));
  }
  void refreshPumpStrategyChart(true);
}

async function dismissPumpStrategy(board, symbol) {
  try {
    await fetch("/api/watch/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board, symbol }),
    });
    pumpStrategyState.signals = pumpStrategyState.signals.filter((row) => row.symbol !== symbol);
    if (pumpStrategyState.selected === symbol) closePumpStrategyChart();
    renderPumpStrategyBoard();
  } catch (_e) {
    /* ignore */
  }
}

function onPumpStrategyBoard(data) {
  pumpStrategyState.signals = Array.isArray(data) ? data : [];
  renderPumpStrategyBoard();
  schedulePrefetchForAll();
}

function onPumpStrategySnapshot(board, detail) {
  pumpStrategyState.signals = Array.isArray(board) ? board : [];
  if (detail?.signal && pumpStrategyState.selected === detail.signal.symbol) {
    mergePumpStrategyDetail(detail);
  }
  renderPumpStrategyBoard();
  if (pumpStrategyState.selected) {
    openPumpStrategyChart();
    void refreshPumpStrategyChart(false);
  }
  schedulePrefetchForAll();
}

function onPumpStrategyDetail(symbol, data) {
  if (!pumpStrategyState.selected || pumpStrategyState.selected !== symbol) return;
  mergePumpStrategyDetail(data);
  void refreshPumpStrategyChart(false);
}

function mergePumpStrategyDetail(data) {
  if (!data) return;
  const prev = pumpStrategyState.detail || {};
  pumpStrategyState.detail = {
    ...prev,
    ...data,
    signal: data.signal ?? prev.signal,
    book: data.book ?? prev.book,
    candles:
      (data.candles && data.candles.length >= (prev.candles || []).length
        ? data.candles
        : prev.candles) || data.candles,
  };
}

function findPumpStrategyRow(symbol) {
  return pumpStrategyState.signals.find((row) => row.symbol === symbol) || null;
}

function schedulePrefetchForAll() {
  const symbols = [...new Set(pumpStrategyState.signals.map((r) => r.symbol).filter(Boolean))];
  for (const symbol of symbols) {
    enqueuePrefetch(symbol, pumpStrategyState.interval);
    enqueuePrefetch(symbol, "60");
  }
  drainPrefetchQueue();
}

function enqueuePrefetch(symbol, interval) {
  const key = `${symbol}:${interval}`;
  const bucket = pumpStrategyState.prefetch.get(symbol) || { intervals: new Map(), book: null };
  if (bucket.intervals.has(interval)) return;
  if (pumpStrategyState.prefetchQueue.some((job) => job.key === key)) return;
  pumpStrategyState.prefetchQueue.push({ symbol, interval, key });
  pumpStrategyState.prefetch.set(symbol, bucket);
}

function drainPrefetchQueue() {
  while (
    pumpStrategyState.prefetchActive < PSC_PREFETCH_CONCURRENCY &&
    pumpStrategyState.prefetchQueue.length
  ) {
    const job = pumpStrategyState.prefetchQueue.shift();
    if (!job) break;
    pumpStrategyState.prefetchActive += 1;
    void prefetchKlines(job.symbol, job.interval).finally(() => {
      pumpStrategyState.prefetchActive -= 1;
      drainPrefetchQueue();
    });
  }
}

async function prefetchKlines(symbol, interval) {
  try {
    const q = new URLSearchParams({
      interval,
      days: String(PSC_FETCH_DAYS),
      refresh: "1",
    });
    const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
    if (!res.ok) return;
    const payload = await res.json();
    const candles = payload.candles || [];
    const bucket = pumpStrategyState.prefetch.get(symbol) || { intervals: new Map(), book: null };
    bucket.intervals.set(interval, candles);
    pumpStrategyState.prefetch.set(symbol, bucket);
  } catch (_e) {
    /* ignore */
  }
}

async function ensurePumpStrategyCandles(symbol, interval) {
  const bucket = pumpStrategyState.prefetch.get(symbol);
  const cached = bucket?.intervals?.get(interval);
  if (cached && cached.length >= 20) return cached;
  await prefetchKlines(symbol, interval);
  const again = pumpStrategyState.prefetch.get(symbol)?.intervals?.get(interval);
  if (again?.length) return again;
  const detail = pumpStrategyState.detail;
  if (detail?.candles?.length && detail.interval === interval) return detail.candles;
  return [];
}

function renderPumpStrategyBoard() {
  const root = document.getElementById("pump-strategy-grid");
  if (!root) return;
  const rows = pumpStrategyState.signals;
  const sel = pumpStrategyState.selected;
  if (!rows.length) {
    root.innerHTML =
      '<p class="quiet pump-strategy-empty">Пока нет монет в списке. Условия: быстрый ≥40% за 1–12 ч; длинный ×2 за 10 д; оборот ≥300 тыс $. Если рынок активный, а список пуст — подождите 2–5 мин: движку нужны свечи с биржи по каждой паре.</p>';
    return;
  }
  const shortRows = rows.filter((r) => r.kind === "short");
  const longRows = rows.filter((r) => r.kind !== "short");
  let html = "";
  if (shortRows.length) {
    html += `<h2 class="psc-section-title">Быстрый памп (1–12 ч)</h2><div class="psc-section-grid">${shortRows.map((row) => pumpStrategyCardHtml(row, sel)).join("")}</div>`;
  }
  if (longRows.length) {
    html += `<h2 class="psc-section-title">Длинный рост (до 10 д, минимум ×2)</h2><div class="psc-section-grid">${longRows.map((row) => pumpStrategyCardHtml(row, sel)).join("")}</div>`;
  }
  root.innerHTML = html;
  root.querySelectorAll("canvas.mini-strategy").forEach(drawStrategyMini);
}

function pumpStrategyCardHtml(row, selected) {
  const oi1 = formatOiChange(row.oi_change_1h_pct);
  const oi4 = formatOiChange(row.oi_change_4h_pct);
  const active = row.symbol === selected ? " active" : "";
  return `<article class="pump-strategy-card${active}" data-symbol="${row.symbol}">
    <header class="psc-head">
      <h3 class="psc-symbol">${row.symbol.replace("USDT", "")}</h3>
      <span class="psc-kind">${row.kind_label || "Длинный рост"}</span>
    </header>
    <div class="psc-growth">+${fmt(row.growth_pct)}%</div>
    <dl class="psc-fields">
      <div class="psc-row">
        <dt>Период (дно → пик)</dt>
        <dd>${row.period_label || "—"}</dd>
      </div>
      <div class="psc-row">
        <dt>Открытый интерес · 1 ч</dt>
        <dd class="${oi1.cls}">${oi1.text}</dd>
      </div>
      <div class="psc-row">
        <dt>Открытый интерес · 4 ч</dt>
        <dd class="${oi4.cls}">${oi4.text}</dd>
      </div>
      <div class="psc-row">
        <dt>Оборот 24 ч</dt>
        <dd>${formatTurnover(row.turnover_24h_usdt)}</dd>
      </div>
    </dl>
    <canvas class="mini-strategy" width="280" height="48" data-mini="${encodeMini(row.mini)}"></canvas>
    <footer class="psc-foot">
      <button type="button" class="dismiss-watch" data-dismiss-board="pump_strategy" data-symbol="${row.symbol}">
        Снять с отслеживания
      </button>
    </footer>
  </article>`;
}

function renderPumpStrategyInfo() {
  const pane = document.getElementById("psc-info-pane");
  if (!pane) return;
  const symbol = pumpStrategyState.selected;
  const row = symbol ? findPumpStrategyRow(symbol) : null;
  const detail = pumpStrategyState.detail;
  if (!symbol || !row) {
    pane.innerHTML = '<p class="empty">Выберите карточку.</p>';
    return;
  }
  const oi1 = formatOiChange(row.oi_change_1h_pct);
  const oi4 = formatOiChange(row.oi_change_4h_pct);
  const funding =
    detail?.funding_rate != null ? `${(Number(detail.funding_rate) * 100).toFixed(4)}%` : "—";
  const taker = detail?.taker_ratio != null ? Number(detail.taker_ratio).toFixed(2) : "—";
  pane.innerHTML = `
    <header class="psc-info-head">
      <h2>${row.symbol}</h2>
      <span class="tag">${row.kind_label}</span>
      <button type="button" class="psc-close-chart">Закрыть график</button>
      <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${row.symbol}" target="_blank" rel="noopener">Bybit</a>
    </header>
    <div class="psc-growth psc-growth-side">+${fmt(row.growth_pct)}%</div>
    <dl class="psc-info-fields">
      <div class="psc-row"><dt>Период</dt><dd>${row.period_label || "—"}</dd></div>
      <div class="psc-row"><dt>Цена</dt><dd data-psc-live="price">${fmtPrice(row.last_price)}</dd></div>
      <div class="psc-row"><dt>Дно / пик (окно)</dt><dd>${fmtPrice(row.valley_price)} → ${fmtPrice(row.peak_price)}</dd></div>
      <div class="psc-row"><dt>Оборот 24 ч</dt><dd>${formatTurnover(row.turnover_24h_usdt)}</dd></div>
      <div class="psc-row"><dt>OI · 1 ч</dt><dd class="${oi1.cls}">${oi1.text}</dd></div>
      <div class="psc-row"><dt>OI · 4 ч</dt><dd class="${oi4.cls}">${oi4.text}</dd></div>
      <div class="psc-row"><dt>Финансирование</dt><dd>${funding}</dd></div>
      <div class="psc-row"><dt>Тейкеры buy/sell</dt><dd>${taker}</dd></div>
    </dl>
    <div class="psc-walls" id="psc-walls"></div>
    <button type="button" class="dismiss-watch" data-dismiss-board="pump_strategy" data-symbol="${row.symbol}">Снять с отслеживания</button>
    <p class="quiet psc-info-hint">Таймфрейм: ${PSC_TF.find(([c]) => c === pumpStrategyState.interval)?.[1] || pumpStrategyState.interval}. Данные по списку подгружаются в фоне.</p>`;
  updatePumpStrategyWalls(detail?.book);
}

function updatePumpStrategyWalls(book) {
  const walls = document.getElementById("psc-walls");
  if (!walls) return;
  const items = book?.walls || [];
  if (!items.length) {
    walls.innerHTML = '<p class="quiet">Крупные стены в стакане появятся при потоке данных.</p>';
    return;
  }
  walls.innerHTML = items
    .map((w) => {
      const kind = w.kind === "holding" ? "Holding" : w.kind === "spoof" ? "Spoof" : "Building";
      return `<span class="wall ${w.kind}">${kind} ${formatBookPrice(w.price)} · ${formatBookSize(w.size)}</span>`;
    })
    .join("");
}

function mountPumpStrategyChart() {
  if (pumpStrategyState.chart) return;
  const container = document.getElementById("psc-candle-chart");
  if (!container || !window.LightweightCharts) return;
  pumpStrategyState.chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
    grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
    timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 7 },
    rightPriceScale: { borderColor: "#2c3544" },
  });
  pumpStrategyState.series = pumpStrategyState.chart.addCandlestickSeries({
    upColor: "#3dd68c",
    downColor: "#ff5d73",
    borderVisible: true,
    wickUpColor: "#3dd68c",
    wickDownColor: "#ff5d73",
  });
  pumpStrategyState.series.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } });
  pumpStrategyState.volumeSeries = pumpStrategyState.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
  });
  pumpStrategyState.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  const resize = () => {
    if (!pumpStrategyState.chart || container.clientWidth <= 0) return;
    const h = container.clientHeight || 420;
    pumpStrategyState.chart.resize(container.clientWidth, h);
    drawPumpStrategyBookOverlay();
  };
  new ResizeObserver(resize).observe(container);
  pumpStrategyState.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    drawPumpStrategyBookOverlay();
  });
  requestAnimationFrame(resize);
}

async function refreshPumpStrategyChart(resetScale) {
  const symbol = pumpStrategyState.selected;
  if (!symbol || !pumpStrategyState.series) return;
  const gen = ++pumpStrategyState.chartGen;
  const interval = pumpStrategyState.interval;
  const candles = await ensurePumpStrategyCandles(symbol, interval);
  if (gen !== pumpStrategyState.chartGen) return;
  if (pumpStrategyState.detail) pumpStrategyState.detail.candles = candles;
  if (pumpStrategyState.detail) pumpStrategyState.detail.interval = interval;
  drawPumpStrategyCandles(candles, interval, resetScale);
  if (resetScale) renderPumpStrategyInfo();
  else updatePumpStrategyLiveFields();
  drawPumpStrategyBookOverlay();
}

function updatePumpStrategyLiveFields() {
  const row = pumpStrategyState.selected ? findPumpStrategyRow(pumpStrategyState.selected) : null;
  const detail = pumpStrategyState.detail;
  if (!row) return;
  const priceEl = document.querySelector("#psc-info-pane [data-psc-live='price']");
  if (priceEl) priceEl.textContent = fmtPrice(row.last_price);
  updatePumpStrategyWalls(detail?.book);
}

function candleTimeForPsc(raw, interval) {
  const n = Number(raw);
  if (!n || Number.isNaN(n)) return 0;
  const sec = n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
  if (interval === "D") {
    const d = new Date(sec * 1000);
    return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
  }
  return sec;
}

function drawPumpStrategyCandles(candles, interval, resetScale) {
  if (!pumpStrategyState.series) return;
  const byTime = new Map();
  for (const candle of candles || []) {
    const time = candleTimeForPsc(candle.timestamp ?? candle.time, interval);
    if (!time) continue;
    const close = Number(candle.close);
    if (Number.isNaN(close)) continue;
    byTime.set(typeof time === "object" ? JSON.stringify(time) : String(time), {
      time,
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close,
      volume: Number(candle.volume ?? 0),
    });
  }
  const bars = [...byTime.values()].sort((a, b) => {
    const ta = typeof a.time === "object" ? Date.UTC(a.time.year, a.time.month - 1, a.time.day) : a.time;
    const tb = typeof b.time === "object" ? Date.UTC(b.time.year, b.time.month - 1, b.time.day) : b.time;
    return ta - tb;
  });
  pumpStrategyState.series.setData(bars);
  if (pumpStrategyState.volumeSeries) {
    pumpStrategyState.volumeSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(61, 214, 140, 0.45)" : "rgba(255, 93, 115, 0.45)",
      })),
    );
  }
  if (bars.length) {
    pumpStrategyState.priceRange = {
      min: Math.min(...bars.map((b) => b.low)),
      max: Math.max(...bars.map((b) => b.high)),
    };
  }
  const container = document.getElementById("psc-candle-chart");
  if (container && pumpStrategyState.chart && container.clientWidth > 0) {
    pumpStrategyState.chart.resize(container.clientWidth, container.clientHeight || 420);
  }
  if (resetScale && bars.length && pumpStrategyState.chart) {
    const step = PSC_INTERVAL_SEC[interval] || 3600;
    const to =
      typeof bars[bars.length - 1].time === "object"
        ? bars[bars.length - 1].time
        : bars[bars.length - 1].time + step;
    pumpStrategyState.chart.timeScale().setVisibleRange({ from: bars[0].time, to });
  }
}

function drawPumpStrategyBookOverlay() {
  const canvas = document.getElementById("psc-book-overlay");
  const chartEl = document.getElementById("psc-candle-chart");
  if (!canvas || !chartEl || !pumpStrategyState.series) return;
  const book = pumpStrategyState.detail?.book;
  const ratio = window.devicePixelRatio || 1;
  const width = chartEl.clientWidth;
  const height = chartEl.clientHeight;
  if (width <= 0 || height <= 0) return;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  let pMin = pumpStrategyState.priceRange.min;
  let pMax = pumpStrategyState.priceRange.max;
  if (pumpStrategyState.chart && pumpStrategyState.series) {
    try {
      const y1 = pumpStrategyState.series.priceToCoordinate(pMax);
      const y2 = pumpStrategyState.series.priceToCoordinate(pMin);
      if (y1 != null && y2 != null) {
        /* диапазон совпадает с шкалой графика */
      }
    } catch (_e) {
      /* ignore */
    }
  }
  const span = pMax - pMin || 1;

  const normalizeSide = (side) => {
    if (!side) return [];
    if (Array.isArray(side) && side.length && Array.isArray(side[0])) return side;
    if (typeof side === "object" && !Array.isArray(side)) {
      return Object.entries(side).map(([p, s]) => [Number(p), Number(s)]);
    }
    return [];
  };

  const bids = normalizeSide(book?.bids);
  const asks = normalizeSide(book?.asks);
  const rows = [
    ...bids.map(([price, size]) => ({ price: Number(price), size: Number(size), bid: true })),
    ...asks.map(([price, size]) => ({ price: Number(price), size: Number(size), bid: false })),
  ].filter((r) => r.price > 0 && r.size > 0);

  if (!rows.length) {
    ctx.fillStyle = "rgba(142, 154, 171, 0.7)";
    ctx.font = "12px Segoe UI, sans-serif";
    ctx.fillText("Стакан…", width - 72, 20);
    return;
  }

  const inRange = rows.filter((r) => r.price >= pMin - span * 0.02 && r.price <= pMax + span * 0.02);
  const list = inRange.length ? inRange : rows;
  const maxSize = Math.max(...list.map((r) => r.size), 1);
  const bandW = Math.min(120, width * 0.22);

  list.forEach((row) => {
    let y;
    if (pumpStrategyState.series) {
      y = pumpStrategyState.series.priceToCoordinate(row.price);
    }
    if (y == null || Number.isNaN(y)) {
      y = height - 12 - ((row.price - pMin) / span) * (height - 24);
    }
    const barLen = 8 + (row.size / maxSize) * (bandW - 8);
    ctx.fillStyle = row.bid ? "rgba(61, 214, 140, 0.35)" : "rgba(255, 93, 115, 0.35)";
    ctx.fillRect(width - barLen - 4, y - 5, barLen, 10);
    ctx.fillStyle = row.bid ? "rgba(200, 255, 220, 0.85)" : "rgba(255, 200, 210, 0.85)";
    ctx.font = "10px Segoe UI, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(formatBookSize(row.size), width - barLen - 8, y + 3);
    ctx.fillStyle = "rgba(200, 210, 220, 0.75)";
    ctx.fillText(formatBookPrice(row.price), width - 6, y + 3);
  });
}

function formatOiChange(pct) {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct))) {
    return { text: "нет данных", cls: "psc-muted" };
  }
  const n = Number(pct);
  const sign = n > 0 ? "+" : "";
  const cls = n > 0 ? "psc-up" : n < 0 ? "psc-down" : "";
  return { text: `${sign}${n.toFixed(2)}%`, cls };
}

function formatTurnover(value) {
  const n = Number(value);
  if (!n || Number.isNaN(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} млн $`;
  if (n >= 1_000) return `${Math.round(n / 1000)} тыс $`;
  return `${Math.round(n)} $`;
}

function formatBookPrice(p) {
  const n = Number(p);
  if (n >= 1000) return n.toFixed(1);
  if (n >= 1) return n.toFixed(4);
  return n.toPrecision(4);
}

function formatBookSize(s) {
  const n = Number(s);
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(1);
}

function fmtPrice(n) {
  const x = Number(n);
  if (Number.isNaN(x) || !x) return "—";
  if (x >= 100) return x.toFixed(2);
  if (x >= 1) return x.toFixed(4);
  return x.toPrecision(4);
}

function encodeMini(mini) {
  if (!mini || !mini.length) return "";
  return mini.join(",");
}

function drawStrategyMini(canvas) {
  const raw = canvas.dataset.mini || "";
  if (!raw) return;
  const values = raw.split(",").map(Number).filter((n) => !Number.isNaN(n));
  if (values.length < 2) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  ctx.strokeStyle = "#6ee7b7";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * (w - 4) + 2;
    const y = h - 4 - ((v - min) / span) * (h - 8);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function fmt(n) {
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return x.toFixed(1);
}

function resizePumpStrategyChart() {
  const container = document.getElementById("psc-candle-chart");
  if (!container || !pumpStrategyState.chart || container.clientWidth <= 0) return;
  pumpStrategyState.chart.resize(container.clientWidth, container.clientHeight || 420);
  drawPumpStrategyBookOverlay();
}

window.pumpStrategy = {
  initPumpStrategyTab,
  onPumpStrategyBoard,
  onPumpStrategySnapshot,
  onPumpStrategyDetail,
  resizeChart: resizePumpStrategyChart,
};
