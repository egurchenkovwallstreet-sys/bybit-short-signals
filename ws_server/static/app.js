/* Страница сигналов. Данные приходят по WebSocket, страница сама ничего не считает по рынку. */

const CHECKS = [
  ["pump", "Памп"],
  ["liquidations_faded", "Ликвидации затихли"],
  ["oi_drop", "Открытый интерес падает"],
  ["volume_faded", "Объём спал"],
  ["sweep", "Свуп на старшем ТФ"],
];

const EXTRAS = [
  ["cvd_divergence", "Дивергенция дельты объёма"],
  ["taker_seller", "Продавцы в контроле"],
  ["obv_divergence", "Дивергенция баланса объёма"],
  ["funding_extreme", "Перегретое финансирование"],
  ["round_level", "Круглый уровень"],
];

const CHART_MIN_CANDLES = 100;
const DETAIL_CHART_WINDOW_HOURS = 48;

const INTERVALS = [
  ["1", "1m"],
  ["5", "5m"],
  ["15", "15m"],
  ["60", "1H"],
  ["240", "4H"],
  ["D", "1D"],
];

const state = {
  demo: false,
  board: [],
  selected: null,
  interval: "1",
  detail: null,
  stats: null,
  tips: {},
  chart: null,
  series: null,
  volumeSeries: null,
  priceLines: [],
  gauges: {},
  equity: null,
  sortKey: "created_at",
  sortDir: -1,
  lastCandleBarCount: 0,
};

const tooltip = document.getElementById("tooltip");

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.tab));
});

document.querySelectorAll("#signal-table th").forEach((header) => {
  header.addEventListener("click", () => {
    const key = header.dataset.sort;
    state.sortDir = state.sortKey === key ? -state.sortDir : 1;
    state.sortKey = key;
    renderTable();
  });
});

document.body.addEventListener("mouseover", (event) => {
  const node = event.target instanceof Element ? event.target.closest("[data-tip]") : null;
  if (!node) {
    tooltip.hidden = true;
    return;
  }
  const text = state.tips[node.dataset.tip];
  if (!text) return;
  tooltip.textContent = text;
  tooltip.hidden = false;
  const box = node.getBoundingClientRect();
  tooltip.style.left = `${Math.min(box.left, window.innerWidth - 300)}px`;
  tooltip.style.top = `${box.bottom + 6}px`;
});

document.body.addEventListener("mouseout", (event) => {
  const node = event.target instanceof Element ? event.target.closest("[data-tip]") : null;
  if (!node) return;
  const next = event.relatedTarget instanceof Element ? event.relatedTarget.closest("[data-tip]") : null;
  if (next !== node) tooltip.hidden = true;
});

fetch("/api/tooltips")
  .then((response) => response.json())
  .then((tips) => {
    state.tips = tips;
    tooltip.dataset.ready = String(Object.keys(tips).length);
  })
  .catch(() => {});

let socket = null;
let wsBackoffMs = 800;
let wsReconnectTimer = null;
let wsPingTimer = null;
let wsOpen = false;

function updateLinkState() {
  const el = document.getElementById("link-state");
  if (!el) return;
  if (!wsOpen) {
    el.textContent = "переподключение…";
    return;
  }
  el.textContent = state.demo ? "пример, Redis недоступен" : "живой поток";
}

function connectSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  if (socket) {
    socket.onclose = null;
    socket.onerror = null;
    try {
      socket.close();
    } catch (_err) {
      /* ignore */
    }
  }
  if (wsPingTimer) {
    clearInterval(wsPingTimer);
    wsPingTimer = null;
  }

  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  window.signalSocket = socket;

  socket.addEventListener("open", () => {
    wsBackoffMs = 800;
    wsOpen = true;
    updateLinkState();
    wsPingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
  });

  socket.addEventListener("close", () => {
    wsOpen = false;
    if (wsPingTimer) {
      clearInterval(wsPingTimer);
      wsPingTimer = null;
    }
    updateLinkState();
    wsReconnectTimer = setTimeout(connectSocket, wsBackoffMs);
    wsBackoffMs = Math.min(wsBackoffMs * 1.6, 12000);
  });

  socket.addEventListener("error", () => {
    wsOpen = false;
    updateLinkState();
  });

  socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.type === "snapshot") {
    setDemo(message.demo);
    state.board = message.board || [];
    state.stats = message.stats;
    state.detail = message.detail;
    state.selected = message.detail && message.detail.signal ? message.detail.signal.symbol : state.selected;
    renderBoard();
    renderDetail();
    renderStats();
    if (message.btc_test && window.btcTest) window.btcTest.onBtcMessage(message.btc_test);
    if (window.pumpScan) {
      window.pumpScan.onPumpScanSnapshot(message.pump_scan_board, message.pump_scan_detail);
    }
  } else if (message.type === "btc_test" && window.btcTest) {
    window.btcTest.onBtcMessage(message.data);
  } else if (message.type === "board") {
    setDemo(message.demo);
    state.board = message.data || [];
    renderBoard();
  } else if (message.type === "pump_scan_board" && window.pumpScan) {
    setDemo(message.demo);
    window.pumpScan.onPumpScanBoard(message.data);
  } else if (message.type === "pump_scan_detail" && window.pumpScan) {
    window.pumpScan.onPumpScanDetail(message.symbol, message.data);
  } else if (message.type === "detail" && (!state.selected || message.symbol === state.selected)) {
    const changed = state.selected !== message.symbol;
    state.selected = message.symbol;
    state.detail = message.data;
    if (changed) renderBoard();
    renderDetail();
  } else if (message.type === "pnl") {
    applyPnl(message.items || []);
  } else if (message.type === "stats") {
    state.stats = message.data;
    renderStats();
  }
  });
}

connectSocket();

function setDemo(demo) {
  state.demo = !!demo;
  document.getElementById("demo-banner").hidden = !demo;
  updateLinkState();
}

function showTab(name) {
  tooltip.hidden = true;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.getElementById("view-signals").hidden = name !== "signals";
  const pumpView = document.getElementById("view-pump-scan");
  if (pumpView) pumpView.hidden = name !== "pump_scan";
  document.getElementById("view-pending").hidden = name !== "pending";
  document.getElementById("view-stats").hidden = name !== "stats";
  const btcView = document.getElementById("view-btc");
  if (btcView) btcView.hidden = name !== "btc";
  if (name === "btc" && window.btcTest) {
    requestAnimationFrame(() => {
      window.btcTest.initBtcTab();
      window.btcTest.fetchBtcFallback?.();
    });
  }
  if (name === "pump_scan" && window.pumpScan) {
    window.pumpScan.initPumpScanTab();
  }
  if (name === "pending") {
    renderPending();
  }
  if (name === "stats") {
    renderStats();
    requestAnimationFrame(() => {
      Object.values(state.gauges).forEach((chart) => chart.resize());
      if (state.equity) state.equity.resize();
    });
  } else if (state.chart) {
    requestAnimationFrame(() => state.chart.resize());
  }
}

function renderBoard() {
  const root = document.getElementById("columns");
  root.innerHTML = state.board
    .map((column) => {
      const cards = (column.signals || []).map((signal) => cardHtml(signal, column.color)).join("");
      return `<section class="column ${column.color}">
        <h2>${column.status} ${column.label}</h2>
        ${cards || '<p class="quiet">нет сигналов</p>'}
      </section>`;
    })
    .join("");
  root.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => selectSymbol(card.dataset.symbol));
  });
  root.querySelectorAll("canvas.mini").forEach(drawMini);
}

function cardHtml(signal, color) {
  const selected = signal.symbol === state.selected ? " selected" : "";
  const scale = [1, 2, 3, 4, 5]
    .map((step) => `<i class="${step <= signal.strength ? "on" : ""}"></i>`)
    .join("");
  const checks = CHECKS.map(([key, label]) => {
    const yes = signal.checks && signal.checks[key];
    return `<li class="${yes ? "yes" : ""}" data-tip="${key}">${yes ? "✓" : "·"} ${label}</li>`;
  }).join("");
  const pnl =
    signal.strength === 5
      ? `<div class="pnl" data-pnl="${signal.symbol}">${formatPnl(signal.pnl_pct)}</div>`
      : "";
  const series = (signal.mini || []).join(",");
  return `<button type="button" class="card${selected}" data-symbol="${signal.symbol}">
    <div class="ticker">${signal.symbol}</div>
    <div class="scale">${scale}</div>
    <ul class="checks">${checks}</ul>
    <p class="prob">Вероятность ${Number(signal.probability || 0).toFixed(0)}%</p>
    <canvas class="mini" data-series="${series}" data-color="${color}"></canvas>
    ${pnl}
  </button>`;
}

function drawMini(canvas) {
  const values = (canvas.dataset.series || "")
    .split(",")
    .map(Number)
    .filter((value) => !Number.isNaN(value));
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(rect.width, 40) * ratio;
  canvas.height = 36 * ratio;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  ctx.strokeStyle = canvas.dataset.color === "green" ? "#3dd68c" : "#8e9aab";
  ctx.lineWidth = 2 * ratio;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = (index / (values.length - 1)) * canvas.width;
    const y = canvas.height - ((value - min) / span) * (canvas.height - 4) - 2;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function selectSymbol(symbol) {
  state.selected = symbol;
  renderBoard();
  socket.send(JSON.stringify({ type: "select", symbol }));
}

function applyPnl(items) {
  items.forEach((item) => {
    const node = document.querySelector(`[data-pnl="${item.symbol}"]`);
    if (node) node.innerHTML = formatPnl(item.pnl_pct);
    if (state.detail && state.detail.signal && state.detail.signal.symbol === item.symbol) {
      state.detail.signal.last_price = item.last_price;
      state.detail.signal.pnl_pct = item.pnl_pct;
    }
  });
}

function formatPnl(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  const arrow = number > 0 ? "▲" : number < 0 ? "▼" : "•";
  const css = number > 0 ? "up" : number < 0 ? "down" : "";
  return `<span class="${css}">${arrow} ${number.toFixed(1)}%</span>`;
}

function renderDetail() {
  const root = document.getElementById("detail");
  const detail = state.detail;
  const signal = detail && detail.signal;
  if (!signal) {
    root.innerHTML = '<p class="empty">Выберите сигнал слева.</p>';
    state.chart = null;
    state.volumeSeries = null;
    return;
  }
  const same =
    root.dataset.symbol === signal.symbol &&
    root.dataset.interval === (detail.interval || state.interval) &&
    root.querySelector("#candle-chart");
  if (!same) {
    root.dataset.symbol = signal.symbol;
    root.dataset.interval = detail.interval || state.interval;
    state.lastCandleBarCount = 0;
    root.innerHTML = detailHtml(signal, detail.interval || state.interval);
    root.querySelectorAll(".tf").forEach((button) => {
      button.addEventListener("click", () => {
        state.interval = button.dataset.interval;
        socket.send(JSON.stringify({ type: "interval", interval: state.interval }));
      });
    });
    root.querySelector(".bybit-btn").addEventListener("click", () => openBybit(signal.symbol));
    const expandAllBtn = root.querySelector(".detail-expand-all-btn");
    if (expandAllBtn) {
      expandAllBtn.addEventListener("click", () => {
        root.classList.toggle("detail--expanded");
        expandAllBtn.textContent = root.classList.contains("detail--expanded")
          ? "Свернуть графики"
          : "Увеличить графики (80% экрана)";
        requestAnimationFrame(resizeAllDetailCharts);
      });
    }
    mountCandleChart();
  } else {
    const info = root.querySelector(".signal-info");
    if (info) info.innerHTML = infoHtml(signal);
  }
  const resetChartScale = !same;
  void ensureCandles(signal.symbol, detail.interval || state.interval, detail).then((candles) => {
    drawCandles(candles, signal, detail, resetChartScale);
  });
  drawBook(document.getElementById("book-map"), detail.book || {});
  drawLiquidations(document.getElementById("liq-map"), detail.liquidations || []);
  drawLine("oi-chart", "Открытый интерес (48 ч)", pointsOf(detail.oi, "open_interest"), "#58a6ff");
  drawLine("cvd-chart", "Дельта объёма (48 ч)", pointsOf(detail.cvd, "value"), "#ffb86c");
  drawLine("obv-chart", "Баланс объёма (48 ч)", pointsOf(detail.obv, "value"), "#bd93f9");
  resizeAllDetailCharts();
  const funding = root.querySelector("[data-funding]");
  const taker = root.querySelector("[data-taker]");
  const liq = root.querySelector("[data-liq]");
  if (funding) funding.textContent = formatFunding(detail.funding_rate);
  if (taker) taker.textContent = detail.taker_ratio == null ? "—" : Number(detail.taker_ratio).toFixed(2);
  if (liq) {
    liq.textContent = signal.checks && signal.checks.liquidations_faded ? "затихли" : "ещё идут";
  }
}

function detailHtml(signal, interval) {
  const buttons = INTERVALS.map(
    ([code, label]) =>
      `<button type="button" class="tf${code === interval ? " active" : ""}" data-interval="${code}">${label}</button>`,
  ).join("");
  return `<div class="detail-head">
      <h3>Графики сигнала · ${signal.symbol}</h3>
      <button type="button" class="detail-expand-all-btn">Увеличить графики (80% экрана)</button>
    </div>
    <p class="quiet detail-window-hint">Индикаторы ниже — последние ${DETAIL_CHART_WINDOW_HOURS} ч (2 суток), обновление в реальном времени.</p>
    <div class="tf-row">${buttons}</div>
    <div class="signal-info">${infoHtml(signal)}</div>
    <div class="detail-visual-stack">
      <section class="chart-block">
        <h4>Свечи и объём</h4>
        <div class="candle-chart-wrap">
          <div id="chart-legend" class="chart-legend" aria-hidden="true"></div>
          <div id="candle-chart"></div>
        </div>
      </section>
      <section class="chart-block">
        <h4>Карта ликвидности (стакан)</h4>
        <canvas id="book-map"></canvas>
        <div class="walls" id="walls"></div>
      </section>
      <section class="chart-block">
        <h4>Ликвидации шортов (S: Sell)</h4>
        <canvas id="liq-map"></canvas>
      </section>
      <section class="chart-block">
        <div id="oi-chart" class="plot"></div>
      </section>
      <section class="chart-block">
        <div id="cvd-chart" class="plot"></div>
      </section>
      <section class="chart-block">
        <div id="obv-chart" class="plot"></div>
      </section>
      <div class="detail-metrics-row">
        <div class="metric"><div>Ставка финансирования</div><strong data-funding>—</strong></div>
        <div class="metric"><div>Доля покупок (тейкеры)</div><strong data-taker>—</strong></div>
        <div class="metric"><div>Ликвидации</div><strong data-liq>—</strong></div>
      </div>
    </div>
    <button type="button" class="bybit-btn">Открыть график на Bybit</button>
    <p class="quiet" id="bybit-note"></p>`;
}

function infoHtml(signal) {
  const scale = [1, 2, 3, 4, 5]
    .map((step) => `<i class="${step <= signal.strength ? "on" : ""}"></i>`)
    .join("");
  const rows = [...CHECKS, ...EXTRAS]
    .map(([key, label]) => {
      const bag = signal.checks && key in signal.checks ? signal.checks : signal.extras || {};
      const yes = Boolean(bag[key]);
      return `<li class="${yes ? "yes" : ""}"><span class="tip" data-tip="${key}">${yes ? "✓" : "·"} ${label}</span></li>`;
    })
    .join("");
  const pnl = signal.strength === 5 ? formatPnl(signal.pnl_pct) : "";
  const ch5 = signal.price_change_5m != null ? `${Number(signal.price_change_5m).toFixed(1)}%` : "—";
  const ch15 = signal.price_change_15m != null ? `${Number(signal.price_change_15m).toFixed(1)}%` : "—";
  return `    <div class="ticker">${signal.symbol} · ${signal.status}</div>
    <div class="scale" style="color: var(--${signal.color || "gray"})">${scale}</div>
    <p>Рост: 5m ${ch5} · 15m ${ch15} · цена ≥30%/1ч или ≥50%/сут · объём ×5/×6/×8/×10/×12 (5m→1D); 1h: только при ≥30% и ×8</p>
    <p>Вероятность ${Number(signal.probability || 0).toFixed(0)}% ${pnl}</p>
    <ul class="checks">${rows}</ul>`;
}

function mountCandleChart() {
  const container = document.getElementById("candle-chart");
  if (!container || !window.LightweightCharts) return;
  state.chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
    grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 12,
      barSpacing: 8,
      fixRightEdge: false,
    },
    rightPriceScale: { borderColor: "#2c3544" },
  });
  state.series = state.chart.addCandlestickSeries({
    upColor: "#3dd68c",
    downColor: "#ff5d73",
    borderVisible: true,
    wickUpColor: "#3dd68c",
    wickDownColor: "#ff5d73",
  });
  state.series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
  state.volumeSeries = state.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
  });
  state.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  state.priceLines = [];
  const resize = () => {
    if (state.chart && container.clientWidth > 0) {
      state.chart.resize(container.clientWidth, detailChartHeight(container));
    }
  };
  new ResizeObserver(resize).observe(container);
  requestAnimationFrame(resize);
}

function candleTimeSec(raw) {
  const n = Number(raw);
  if (!n || Number.isNaN(n)) return 0;
  return n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
}

function candleTimeForChart(raw, interval) {
  const sec = candleTimeSec(raw);
  if (!sec) return 0;
  if (interval === "D") {
    const d = new Date(sec * 1000);
    return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
  }
  return sec;
}

async function ensureCandles(symbol, interval, detail) {
  let candles = detail.candles || [];
  const needFetch = candles.length < CHART_MIN_CANDLES;
  try {
    const url = `/api/klines/${encodeURIComponent(symbol)}?interval=${encodeURIComponent(interval)}${needFetch ? "&refresh=1" : ""}`;
    const res = await fetch(url);
    if (!res.ok) return candles;
    const data = await res.json();
    const loaded = data.candles || [];
    if (loaded.length >= candles.length) {
      detail.candles = loaded;
      candles = loaded;
    }
    return candles;
  } catch (_err) {
    return candles;
  }
}

const INTERVAL_SEC = { 1: 60, 5: 300, 15: 900, 60: 3600, 240: 14400, D: 86400 };

function chartTimeEnd(time, interval) {
  if (typeof time === "object") return time;
  const step = INTERVAL_SEC[interval] || 3600;
  return time + step;
}

function focusChartOnCandles(bars, interval, resetChartScale) {
  if (!state.chart || !bars.length || !resetChartScale) return;
  const width = document.getElementById("candle-chart")?.clientWidth || 640;
  const spacing = Math.min(16, Math.max(6, Math.floor(width / Math.max(bars.length, 8))));
  state.chart.timeScale().applyOptions({ barSpacing: spacing });
  const from = bars[0].time;
  const to = chartTimeEnd(bars[bars.length - 1].time, interval);
  state.chart.timeScale().setVisibleRange({ from, to });
}

function updateChartLegend(detail) {
  const el = document.getElementById("chart-legend");
  if (!el) return;
  const fr = detail?.funding_rate != null ? `${(Number(detail.funding_rate) * 100).toFixed(3)}%` : "—";
  const tk = detail?.taker_ratio != null ? Number(detail.taker_ratio).toFixed(2) : "—";
  el.innerHTML = `
    <span class="lg-price">Свечи (цена)</span>
    <span class="lg-vol">■ Объём</span>
    <span class="lg-meta">Финансирование ${fr} · Тейкеры ${tk}</span>`;
}

function drawCandles(candles, signal, detail, resetChartScale) {
  if (!state.series) return;
  const interval = detail?.interval || state.interval || "1";
  const byTime = new Map();
  for (const candle of candles || []) {
    const time = candleTimeForChart(candle.timestamp ?? candle.time, interval);
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
  state.series.setData(bars);
  if (state.volumeSeries) {
    state.volumeSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(61, 214, 140, 0.45)" : "rgba(255, 93, 115, 0.45)",
      })),
    );
  }
  if (detail) updateChartLegend(detail);
  state.priceLines.forEach((line) => state.series.removePriceLine(line));
  state.priceLines = [];
  (signal.chart_levels || []).forEach((level) => {
    state.priceLines.push(
      state.series.createPriceLine({
        price: Number(level.price),
        color: level.kind === "strong" ? "#3dd68c" : level.kind === "medium" ? "#f6d365" : "#8d97a8",
        lineWidth: 1,
        title: `${level.timeframe}${level.swept ? " свуп" : ""} ${level.kind}`,
      }),
    );
  });
  (signal.round_prices || []).forEach((price) => {
    state.priceLines.push(
      state.series.createPriceLine({
        price: Number(price),
        color: "#9aa6b8",
        lineStyle: LightweightCharts.LineStyle.Dashed,
        lineWidth: 1,
        title: "круглый",
      }),
    );
  });
  const chartBox = document.getElementById("candle-chart");
  const h = detailChartHeight(chartBox);
  if (chartBox && chartBox.clientWidth > 0) state.chart.resize(chartBox.clientWidth, h);
  if (!bars.length && chartBox) {
    chartBox.dataset.empty = "1";
    return;
  }
  if (chartBox) chartBox.dataset.empty = "0";
  if (bars.length) {
    const markers = (signal.chart_levels || [])
      .filter((level) => level.swept)
      .map((level) => ({
        time: bars[bars.length - 1].time,
        position: "aboveBar",
        color: "#f6d365",
        shape: "arrowDown",
        text: `свуп ${level.timeframe}`,
      }));
    state.series.setMarkers(markers);
    const grew = bars.length > state.lastCandleBarCount + 5;
    state.lastCandleBarCount = bars.length;
    focusChartOnCandles(bars, interval, resetChartScale || grew);
  }
}

function drawBook(canvas, book) {
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 280;
  canvas.width = width * ratio;
  canvas.height = 280 * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, 280);
  const bids = book.bids || [];
  const asks = book.asks || [];
  const rows = [...bids.map((row) => ({ price: row[0], size: row[1], bid: true })), ...asks.map((row) => ({ price: row[0], size: row[1], bid: false }))];
  if (!rows.length) {
    ctx.fillStyle = "#8e9aab";
    ctx.fillText("нет стакана", 12, 24);
    return;
  }
  const prices = rows.map((row) => Number(row.price));
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const maxSize = Math.max(...rows.map((row) => Number(row.size)));
  rows.forEach((row) => {
    const y = 270 - ((Number(row.price) - min) / span) * 260;
    const length = 20 + (Number(row.size) / maxSize) * (width - 40);
    ctx.fillStyle = row.bid ? "rgba(61, 214, 140, 0.85)" : "rgba(255, 93, 115, 0.85)";
    ctx.fillRect(width - length, y, length, 6);
  });
  const walls = document.getElementById("walls");
  if (walls) {
    walls.innerHTML = (book.walls || [])
      .map((wall) => `<span class="wall ${wall.kind}">${wallLabel(wall.kind)} ${Number(wall.price).toPrecision(4)}</span>`)
      .join("");
  }
}

function wallLabel(kind) {
  if (kind === "holding") return "Holding";
  if (kind === "spoof") return "Spoof";
  return "Building";
}

function drawLiquidations(canvas, points) {
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 640;
  const height = canvas.clientHeight || 180;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  if (!points.length) {
    ctx.fillStyle = "#8e9aab";
    ctx.fillText("нет ликвидаций шортов", 12, 24);
    return;
  }
  const times = points.map((point) => Number(point.time));
  const prices = points.map((point) => Number(point.price));
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const p0 = Math.min(...prices);
  const p1 = Math.max(...prices);
  const maxSize = Math.max(...points.map((point) => Number(point.size) || 0), 1);
  const now = t1;
  points.forEach((point) => {
    const x = ((Number(point.time) - t0) / (t1 - t0 || 1)) * (width - 16) + 8;
    const y = height - 10 - ((Number(point.price) - p0) / (p1 - p0 || 1)) * (height - 20);
    const age = (now - Number(point.time)) / (t1 - t0 || 1);
    const alpha = Math.max(0.12, (1 - age) * (0.35 + 0.65 * (Number(point.size) / maxSize)));
    ctx.fillStyle = `rgba(255, 120, 90, ${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y, 3 + 8 * (Number(point.size) / maxSize), 0, Math.PI * 2);
    ctx.fill();
  });
}

function pointTimeMs(raw) {
  const n = Number(raw);
  if (!n || Number.isNaN(n)) return null;
  return n > 1e12 ? n : n * 1000;
}

function pointsOf(rows, valueKey, windowHours = DETAIL_CHART_WINDOW_HOURS) {
  const cutoff = Date.now() - windowHours * 3600 * 1000;
  const out = [];
  for (const row of rows || []) {
    const t = pointTimeMs(row.time ?? row.timestamp);
    const v = Number(row[valueKey] ?? row.value ?? row.open_interest);
    if (t == null || Number.isNaN(v)) continue;
    if (t >= cutoff) out.push([t, v]);
  }
  out.sort((a, b) => a[0] - b[0]);
  if (!out.length && rows.length) {
    for (const row of rows.slice(-120)) {
      const t = pointTimeMs(row.time ?? row.timestamp);
      const v = Number(row[valueKey] ?? row.value ?? row.open_interest);
      if (t == null || Number.isNaN(v)) continue;
      out.push([t, v]);
    }
  }
  return out;
}

function detailChartHeight(el) {
  if (!el) return 280;
  const detail = document.getElementById("detail");
  if (detail?.classList.contains("detail--expanded")) {
    return Math.max(320, Math.floor(window.innerHeight * 0.8));
  }
  const h = el.clientHeight;
  return h > 40 ? h : el.id === "candle-chart" ? 300 : 200;
}

function resizeAllDetailCharts() {
  const candleBox = document.getElementById("candle-chart");
  if (state.chart && candleBox && candleBox.clientWidth > 0) {
    state.chart.resize(candleBox.clientWidth, detailChartHeight(candleBox));
  }
  for (const id of ["oi-chart", "cvd-chart", "obv-chart"]) {
    const node = document.getElementById(id);
    if (!node || !window.echarts) continue;
    const chart = echarts.getInstanceByDom(node);
    if (chart) chart.resize();
  }
}

function drawLine(id, name, points, color = "#5dade2") {
  const node = document.getElementById(id);
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  const now = Date.now();
  const windowMs = DETAIL_CHART_WINDOW_HOURS * 3600 * 1000;
  let xmin = now - windowMs;
  let xmax = now + 60000;
  if (points.length) {
    const t0 = Math.min(...points.map((p) => p[0]));
    const t1 = Math.max(...points.map((p) => p[0]));
    xmin = Math.min(xmin, t0);
    xmax = Math.max(xmax, t1);
  }
  chart.setOption({
    backgroundColor: "transparent",
    title: { text: name, textStyle: { color: "#c5d0de", fontSize: 13, fontWeight: 500 } },
    grid: { left: 44, right: 12, top: 32, bottom: 28 },
    xAxis: {
      type: "time",
      min: xmin,
      max: xmax,
      axisLabel: { color: "#8e9aab", hideOverlap: true, formatter: (v) => {
        const d = new Date(v);
        return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
      } },
    },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
    series: [
      {
        type: "line",
        showSymbol: points.length <= 30,
        data: points,
        lineStyle: { color, width: 2 },
      },
    ],
    graphic: points.length
      ? []
      : [
          {
            type: "text",
            left: "center",
            top: "middle",
            style: { text: "Нет данных OI — загрузка с биржи…", fill: "#8e9aab", fontSize: 13 },
          },
        ],
  });
  requestAnimationFrame(() => chart.resize());
}

function formatFunding(rate) {
  if (rate == null) return "—";
  return `${(Number(rate) * 100).toFixed(3)}%`;
}

function openBybit(symbol) {
  const note = document.getElementById("bybit-note");
  const url = `https://www.bybit.com/trade/usdt/${encodeURIComponent(symbol)}`;
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (note) {
    note.textContent = opened
      ? `Открыта новая вкладка Bybit: ${url}`
      : `Разрешите всплывающие окна или откройте вручную: ${url}`;
  }
}

function renderPending() {
  const body = document.querySelector("#pending-table tbody");
  if (!body) return;
  fetch("/api/signals/unprocessed")
    .then((response) => response.json())
    .then((payload) => {
      const rows = payload.rows || [];
      body.innerHTML = rows
        .map((row) => {
          const ch5 = row.price_change_5m != null ? Number(row.price_change_5m).toFixed(1) : "—";
          const ch15 = row.price_change_15m != null ? Number(row.price_change_15m).toFixed(1) : "—";
          const pnl = row.pnl_pct != null ? Number(row.pnl_pct).toFixed(2) : "—";
          const ts = new Date(row.updated_at || row.created_at).toLocaleString();
          return `<tr class="pending-row" data-symbol="${row.symbol}">
            <td>${row.symbol}</td>
            <td>${row.status || "—"}</td>
            <td>${row.label || "—"}</td>
            <td>${ch5}% / ${ch15}%</td>
            <td>${row.outcome || "OPEN"}</td>
            <td>${pnl}</td>
            <td>${ts}</td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".pending-row").forEach((tr) => {
        tr.addEventListener("click", () => {
          const symbol = tr.dataset.symbol;
          state.selected = symbol;
          socket.send(JSON.stringify({ type: "select", symbol }));
          showTab("signals");
        });
      });
    })
    .catch(() => {
      body.innerHTML = "<tr><td colspan=\"7\">Не удалось загрузить журнал.</td></tr>";
    });
}

function renderStats() {
  const stats = state.stats;
  if (!stats || !window.echarts) return;
  const root = document.getElementById("gauges");
  if (!root.childElementCount) {
    [
      ["win_rate", "Win Rate"],
      ["profit_factor", "Profit Factor"],
      ["avg_return", "Средняя доходность"],
      ["max_drawdown", "Max Drawdown"],
      ["count", "Сигналы"],
    ].forEach(([key, title]) => {
      const card = document.createElement("div");
      card.className = "gauge-card";
      card.innerHTML = `<div class="plot" data-gauge="${key}"></div><div class="gauge-title">${title}</div>`;
      card.title = title;
      root.appendChild(card);
    });
  }
  gauge("win_rate", stats.win_rate, 0, 100, [
    [0.4, "#ff5d73"],
    [0.55, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}%");
  gauge("profit_factor", Math.min(stats.profit_factor, 3), 0, 3, [
    [1 / 3, "#ff5d73"],
    [0.5, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}");
  gauge("avg_return", stats.avg_return, -5, 5, [
    [0.5, "#ff5d73"],
    [0.6, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}%");
  gauge("max_drawdown", Math.min(stats.max_drawdown, 40), 0, 40, [
    [0.25, "#3dd68c"],
    [0.625, "#f6d365"],
    [1, "#ff5d73"],
  ], "{value}%");
  gauge("count", stats.count, 0, Math.max(20, stats.count), [
    [1, "#5dade2"],
  ], "{value}");
  requestAnimationFrame(() => {
    Object.values(state.gauges).forEach((c) => c.resize());
  });
  const equityNode = document.getElementById("equity");
  state.equity = echarts.getInstanceByDom(equityNode) || echarts.init(equityNode);
  state.equity.setOption({
    backgroundColor: "transparent",
    title: { text: "Доходность по времени", textStyle: { color: "#e8eef6", fontSize: 14 } },
    grid: { left: 40, right: 16, top: 40, bottom: 28 },
    xAxis: { type: "category", data: (stats.equity || []).map((_, index) => index), axisLabel: { color: "#8e9aab" } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
    series: [{ type: "line", data: stats.equity || [], areaStyle: { color: "rgba(61,214,140,0.15)" }, lineStyle: { color: "#3dd68c" }, showSymbol: false }],
  });
  renderTable();
}

function gaugeLabel(value, max) {
  const n = Number(value);
  if (Number.isNaN(n)) return "";
  if (max <= 5 && minNegativeScale(max)) return n.toFixed(1);
  if (n >= 100) return String(Math.round(n));
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

function minNegativeScale(max) {
  return max <= 10;
}

function gauge(key, value, min, max, colors, formatter) {
  const node = document.querySelector(`[data-gauge="${key}"]`);
  if (!node) return;
  const chart = state.gauges[key] || echarts.init(node);
  state.gauges[key] = chart;
  const splitNumber = max <= 5 ? 4 : 5;
  chart.setOption(
    {
      series: [
        {
          type: "gauge",
          min,
          max,
          center: ["50%", "56%"],
          radius: "92%",
          startAngle: 210,
          endAngle: -30,
          splitNumber,
          animationDuration: 800,
          progress: { show: false },
          axisLine: { lineStyle: { width: 12, color: colors } },
          pointer: {
            length: "58%",
            width: 5,
            itemStyle: { color: "#e8eef6" },
          },
          anchor: { show: true, size: 8, itemStyle: { color: "#e8eef6" } },
          axisTick: { show: false },
          splitLine: { length: 10, distance: -12, lineStyle: { width: 2, color: "#3a4558" } },
          axisLabel: {
            color: "#8e9aab",
            distance: 22,
            fontSize: 10,
            hideOverlap: true,
            formatter: (v) => gaugeLabel(v, max),
          },
          detail: {
            valueAnimation: true,
            formatter,
            color: "#e8eef6",
            fontSize: 18,
            offsetCenter: [0, "24%"],
          },
          data: [{ value: Number(value) || 0 }],
        },
      ],
    },
    true,
  );
  chart.resize();
}

function renderTable() {
  const body = document.querySelector("#signal-table tbody");
  if (!body || !state.stats) return;
  const rows = [...(state.stats.rows || [])].sort((left, right) => {
    const a = left[state.sortKey];
    const b = right[state.sortKey];
    if (a === b) return 0;
    return a > b ? state.sortDir : -state.sortDir;
  });
  body.innerHTML = rows
    .map((row) => {
      const when = row.created_at ? new Date(row.created_at).toLocaleString("ru-RU") : "";
      const pnl = row.pnl_pct == null ? "—" : Number(row.pnl_pct).toFixed(1);
      return `<tr><td>${row.symbol}</td><td>${row.outcome || ""}</td><td>${pnl}</td><td>${Number(row.rating || 0).toFixed(0)}</td><td>${when}</td></tr>`;
    })
    .join("");
}

window.signalCharts = {
  drawBook,
  drawLine,
  pointsOf,
  DETAIL_CHART_WINDOW_HOURS,
};
