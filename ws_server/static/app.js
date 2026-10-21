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

const CHART_FETCH_BARS = 300;
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
  statsSort: "net",
  statsSideFilter: "all",
  statsPeriodMode: "days",
  lastCandleBarCount: 0,
};

const tooltip = document.getElementById("tooltip");

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.tab));
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
    state.stats = message.stats;
    renderStats();
    if (message.paper_test && window.paperTest) {
      window.paperTest.onSnapshot(message.paper_test);
    }
    if (message.em6_bybit && window.em6Bybit) {
      window.em6Bybit.onSnapshot(message.em6_bybit);
    }
  } else if (message.type === "paper_test") {
    if (window.paperTest) window.paperTest.onSnapshot(message.data);
  } else if (message.type === "em6_bybit") {
    if (window.em6Bybit) window.em6Bybit.onSnapshot(message.data);
  } else if (message.type === "stats") {
    state.stats = message.data;
    renderStats();
  }
  });
}

connectSocket();
showTab("paper");

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
  document.getElementById("view-stats").hidden = name !== "stats";
  const paperView = document.getElementById("view-paper");
  if (paperView) paperView.hidden = name !== "paper";
  const balanceView = document.getElementById("view-balance");
  if (balanceView) balanceView.hidden = name !== "balance";
  const em6View = document.getElementById("view-em6-bybit");
  if (em6View) em6View.hidden = name !== "em6-bybit";
  if (name === "em6-bybit" && window.em6Bybit) {
    requestAnimationFrame(() => window.em6Bybit.onTab());
  }
  if (name === "paper" && window.paperTest) {
    requestAnimationFrame(() => window.paperTest.onTab());
  }
  if (name === "balance" && window.paperTest) {
    requestAnimationFrame(() => window.paperTest.onBalanceTab());
  }
  if (name === "stats") {
    renderStats();
    scheduleStatsChartResize();
  }
}

document.getElementById("view-stats")?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;
  if (target.id === "stats-sort") {
    state.statsSort = target.value;
    renderStats();
  } else if (target.id === "stats-side") {
    state.statsSideFilter = target.value;
    renderStats();
  } else if (target.id === "stats-period") {
    state.statsPeriodMode = target.value;
    renderStats();
  }
});

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
  const fr = detail.funding_rate ?? signal.funding_rate;
  if (funding) funding.textContent = formatFunding(fr);
  if (taker) {
    const tr = detail.taker_ratio ?? signal.taker_ratio;
    taker.textContent = tr == null ? "—" : Number(tr).toFixed(2);
  }
  const oi1El = root.querySelector("[data-oi-1h]");
  const oi4El = root.querySelector("[data-oi-4h]");
  if (oi1El || oi4El) {
    const { h1, h4 } = window.boardChart.resolveOi1h4h(signal, detail);
    const o1 = window.boardChart.formatOiChange(h1);
    const o4 = window.boardChart.formatOiChange(h4);
    if (oi1El) {
      oi1El.textContent = o1.text;
      oi1El.className = o1.cls;
    }
    if (oi4El) {
      oi4El.textContent = o4.text;
      oi4El.className = o4.cls;
    }
  }
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
        <div class="metric"><div>Открытый интерес · 1 ч</div><strong data-oi-1h class="psc-muted">—</strong></div>
        <div class="metric"><div>Открытый интерес · 4 ч</div><strong data-oi-4h class="psc-muted">—</strong></div>
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
  const { h1, h4 } = window.boardChart.resolveOi1h4h(signal, null);
  const o1 = window.boardChart.formatOiChange(h1);
  const o4 = window.boardChart.formatOiChange(h4);
  return `    <div class="ticker">${signal.symbol} · ${signal.status}</div>
    <div class="scale" style="color: var(--${signal.color || "gray"})">${scale}</div>
    <p>Рост: 5m ${ch5} · 15m ${ch15} · OI 1ч <span class="${o1.cls}">${o1.text}</span> · OI 4ч <span class="${o4.cls}">${o4.text}</span></p>
    <p class="quiet">Порог пампа: ≥30%/1ч или ≥50%/сут · объём ×5…×12 (5m→1D)</p>
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
  window.boardChart.ensureSmaSeries(state);
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
  const BC = window.boardChart;
  if (BC?.candleTime) return BC.candleTime(raw, interval);
  const sec = candleTimeSec(raw);
  if (!sec) return 0;
  if (interval === "D") {
    const d = new Date(sec * 1000);
    return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
  }
  return sec + 3 * 3600;
}

async function ensureCandles(symbol, interval, detail) {
  let candles = detail.candles || [];
  const needBars = CHART_FETCH_BARS;
  const needFetch = candles.length < needBars;
  try {
    const q = new URLSearchParams({
      interval,
      bars: String(CHART_FETCH_BARS),
    });
    if (needFetch) q.set("refresh", "1");
    const url = `/api/klines/${encodeURIComponent(symbol)}?${q}`;
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
  const sig = state.detail?.signal ?? null;
  const fr = window.boardChart.formatFunding(detail?.funding_rate ?? sig?.funding_rate);
  const tkRaw = detail?.taker_ratio ?? sig?.taker_ratio;
  const tk = tkRaw == null ? "—" : Number(tkRaw).toFixed(2);
  const { h1, h4 } = window.boardChart.resolveOi1h4h(sig, detail);
  const o1 = window.boardChart.formatOiChange(h1);
  const o4 = window.boardChart.formatOiChange(h4);
  el.innerHTML = `
    <span class="lg-price">Свечи (цена)</span>
    <span class="lg-sma"><span style="color:#ff5d73">верх</span> · <span style="color:#3dd68c">низ</span> SMA25 · <span style="color:#58a6ff">EMA60</span></span>
    <span class="lg-vol">■ Объём</span>
    <span class="lg-meta">OI 1ч <span class="${o1.cls}">${o1.text}</span> · OI 4ч <span class="${o4.cls}">${o4.text}</span> · Фин. ${fr} · Тейкеры ${tk}</span>`;
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
  window.boardChart.updateAvgPriceCorridor(state, bars);
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
          openAnalysisSub("signals");
        });
      });
    })
    .catch(() => {
      body.innerHTML = "<tr><td colspan=\"7\">Не удалось загрузить журнал.</td></tr>";
    });
}

function disposeStatsGauges() {
  Object.entries(state.gauges).forEach(([key, chart]) => {
    if (key === "equity") return;
    try {
      chart.dispose();
    } catch (_err) {
      /* ignore */
    }
  });
  state.gauges = {};
}

function renderStats() {
  const stats = state.stats;
  if (!stats || !window.echarts || !stats.paper) return;

  disposeStatsGauges();

  const toolbar = document.getElementById("stats-toolbar");
  if (toolbar) {
    toolbar.innerHTML = `
      <div class="stats-toolbar-row">
        <span class="stats-as-of">${stats.as_of ? `Обновлено: ${stats.as_of}` : ""}${stats.demo ? " · пример" : ""}</span>
        <label>Сортировка
          <select id="stats-sort">
            <option value="net">Итог P&amp;L</option>
            <option value="short_net">P&amp;L шортов</option>
            <option value="long_net">P&amp;L лонгов</option>
            <option value="win_rate">Win rate</option>
            <option value="closed">Сделок</option>
          </select>
        </label>
        <label>Фокус
          <select id="stats-side">
            <option value="all">Все сделки</option>
            <option value="short">Только шорты</option>
            <option value="long">Только лонги</option>
          </select>
        </label>
        <label>Периоды
          <select id="stats-period">
            <option value="days">10 дней</option>
            <option value="weeks">8 недель</option>
          </select>
        </label>
      </div>`;
    const sortEl = toolbar.querySelector("#stats-sort");
    const sideEl = toolbar.querySelector("#stats-side");
    const periodEl = toolbar.querySelector("#stats-period");
    if (sortEl) sortEl.value = state.statsSort;
    if (sideEl) sideEl.value = state.statsSideFilter;
    if (periodEl) periodEl.value = state.statsPeriodMode;
  }

  const globalBlock = document.getElementById("stats-global");
  const g = stats.global || {};
  const gm = pickSideMetrics(g.metrics || {}, g.sides || {}, state.statsSideFilter);
  if (globalBlock) {
    globalBlock.innerHTML = `
      <h2 class="stats-section-title">Все стратегии</h2>
      ${sideSummaryHtml(g.sides)}
      <div class="gauges stats-gauges">${gaugeCardsHtml("global", gm)}</div>`;
    renderGaugeSet("global", gm);
  }

  const equityNode = document.getElementById("equity");
  if (equityNode) {
    state.equity = echarts.getInstanceByDom(equityNode) || echarts.init(equityNode);
    const curve = g.equity || [1000];
    state.equity.setOption({
      backgroundColor: "transparent",
      title: { text: "Капитал по закрытым сделкам (все варианты)", textStyle: { color: "#e8eef6", fontSize: 14 } },
      grid: { left: 48, right: 16, top: 40, bottom: 28 },
      xAxis: { type: "category", data: curve.map((_, index) => index), axisLabel: { color: "#8e9aab" } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
      series: [{
        type: "line",
        data: curve,
        areaStyle: { color: "rgba(61,214,140,0.15)" },
        lineStyle: { color: "#3dd68c" },
        showSymbol: false,
      }],
    }, true);
  }

  const variantsRoot = document.getElementById("stats-variants");
  if (!variantsRoot) return;
  const sorted = sortedVariants(stats.variants || []);
  variantsRoot.innerHTML = sorted
    .map((variant) => {
      const m = pickSideMetrics(variant.metrics || {}, variant.sides || {}, state.statsSideFilter);
      const periods = state.statsPeriodMode === "weeks" ? variant.weeks : variant.days;
      const periodTitle = state.statsPeriodMode === "weeks" ? "8 недель (МСК)" : "10 дней (МСК)";
      const dim = (variant.metrics?.closed || 0) === 0 ? " stats-variant--empty" : "";
      return `
        <article class="stats-variant${dim}" data-variant="${variant.id}">
          <header class="stats-variant-head">
            <h3><span class="stats-variant-id">${variant.id}</span> ${escapeHtml(variant.label || variant.id)}</h3>
            ${sideSummaryHtml(variant.sides)}
          </header>
          <div class="gauges stats-gauges">${gaugeCardsHtml(variant.id, m)}</div>
          <div class="stats-period-block">
            <h4>${periodTitle}</h4>
            ${periodTableHtml(periods || [], state.statsSideFilter)}
          </div>
        </article>`;
    })
    .join("");
  sorted.forEach((variant) => {
    const m = pickSideMetrics(variant.metrics || {}, variant.sides || {}, state.statsSideFilter);
    renderGaugeSet(variant.id, m);
  });

  scheduleStatsChartResize();
}

function scheduleStatsChartResize() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      Object.values(state.gauges).forEach((c) => {
        try {
          c.resize();
        } catch (_err) {
          /* ignore */
        }
      });
      if (state.equity) state.equity.resize();
    });
  });
}

function sortedVariants(variants) {
  const key = state.statsSort;
  const score = (v) => {
    const m = v.metrics || {};
    const s = v.sides || {};
    if (key === "short_net") return Number(s.short?.net) || 0;
    if (key === "long_net") return Number(s.long?.net) || 0;
    if (key === "win_rate") return Number(m.win_rate) || 0;
    if (key === "closed") return Number(m.closed) || 0;
    return Number(m.total_pnl) || 0;
  };
  return [...variants].sort((a, b) => score(b) - score(a));
}

function pickSideMetrics(allMetrics, sides, filter) {
  if (filter === "short") return sideAsMetrics(sides.short, allMetrics);
  if (filter === "long") return sideAsMetrics(sides.long, allMetrics);
  return allMetrics;
}

function sideAsMetrics(side, fallback) {
  const n = Number(side?.n) || 0;
  if (!n) {
    return {
      closed: 0,
      wins: 0,
      win_rate: 0,
      total_pnl: 0,
      total_pnl_pct: side?.net_pct ?? 0,
      profit_factor_gauge: 0,
      max_drawdown_pct: 0,
      avg_trade: 0,
      avg_win: 0,
      avg_loss: 0,
      fees: 0,
      liquidations: 0,
    };
  }
  const net = Number(side.net) || 0;
  const winPct = Number(side.win_pct) || 0;
  return {
    closed: n,
    wins: Number(side.wins) || 0,
    win_rate: winPct,
    total_pnl: net,
    total_pnl_pct: side.net_pct ?? 0,
    profit_factor_gauge: fallback.profit_factor_gauge ?? 0,
    max_drawdown_pct: fallback.max_drawdown_pct ?? 0,
    avg_trade: n ? net / n : 0,
    avg_win: fallback.avg_win ?? 0,
    avg_loss: fallback.avg_loss ?? 0,
    fees: fallback.fees ?? 0,
    liquidations: fallback.liquidations ?? 0,
  };
}

function sideSummaryHtml(sides) {
  if (!sides) return "";
  const sh = sides.short || {};
  const lo = sides.long || {};
  return `
    <div class="stats-side-row">
      <span class="stats-side stats-side--short">Шорты: <b>${sh.n ?? 0}</b> · ${formatUsd(sh.net)} (${formatPct(sh.net_pct)})</span>
      <span class="stats-side stats-side--long">Лонги: <b>${lo.n ?? 0}</b> · ${formatUsd(lo.net)} (${formatPct(lo.net_pct)})</span>
    </div>`;
}

function gaugeCardsHtml(prefix, m) {
  const defs = [
    ["win_rate", "Win rate", "{value}%"],
    ["pf", "Profit factor", "{value}"],
    ["pnl", "P&amp;L $", "{value}"],
    ["pnl_pct", "P&amp;L %", "{value}%"],
    ["dd", "Max DD", "{value}%"],
    ["closed", "Закрыто", "{value}"],
    ["avg", "Средняя $", "{value}"],
    ["fees", "Комиссии", "{value}"],
  ];
  return defs
    .map(([key, title]) => {
      return `<div class="gauge-card"><div class="plot" data-gauge="${prefix}-${key}"></div><div class="gauge-title">${title}</div></div>`;
    })
    .join("");
}

function renderGaugeSet(prefix, m) {
  gauge(`${prefix}-win_rate`, m.win_rate || 0, 0, 100, [
    [0.4, "#ff5d73"],
    [0.55, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}%");
  gauge(`${prefix}-pf`, Math.min(Number(m.profit_factor_gauge) || 0, 3), 0, 3, [
    [1 / 3, "#ff5d73"],
    [0.5, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}");
  const pnl = Number(m.total_pnl) || 0;
  const pnlMax = Math.max(50, Math.abs(pnl) * 1.2);
  gauge(`${prefix}-pnl`, pnl, -pnlMax, pnlMax, [
    [0.45, "#ff5d73"],
    [0.55, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}");
  gauge(`${prefix}-pnl_pct`, Number(m.total_pnl_pct) || 0, -20, 20, [
    [0.45, "#ff5d73"],
    [0.55, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}%");
  gauge(`${prefix}-dd`, Math.min(Number(m.max_drawdown_pct) || 0, 40), 0, 40, [
    [0.25, "#3dd68c"],
    [0.625, "#f6d365"],
    [1, "#ff5d73"],
  ], "{value}%");
  const closed = Number(m.closed) || 0;
  gauge(`${prefix}-closed`, closed, 0, Math.max(20, closed), [[1, "#5dade2"]], "{value}");
  gauge(`${prefix}-avg`, Number(m.avg_trade) || 0, -10, 10, [
    [0.45, "#ff5d73"],
    [0.55, "#f6d365"],
    [1, "#3dd68c"],
  ], "{value}");
  gauge(`${prefix}-fees`, Number(m.fees) || 0, 0, Math.max(5, Number(m.fees) || 0), [[1, "#c39bd3"]], "{value}");
}

function periodTableHtml(periods, sideFilter) {
  if (!periods.length) return `<p class="empty">Нет закрытых сделок.</p>`;
  const col = sideFilter === "all" ? "all" : sideFilter;
  const head =
    sideFilter === "all"
      ? `<tr><th>Период</th><th>Сделок</th><th>Win%</th><th>P&amp;L $</th><th>Шорты</th><th>Лонги</th></tr>`
      : `<tr><th>Период</th><th>Сделок</th><th>Win%</th><th>P&amp;L $</th><th>P&amp;L %</th></tr>`;
  const rows = periods
    .map((p) => {
      const st = (p.stats || {})[col] || {};
      const n = st.n ?? 0;
      const win = st.win_pct != null ? `${st.win_pct}%` : "—";
      const net = formatUsd(st.net);
      if (sideFilter === "all") {
        const sh = p.stats?.short || {};
        const lo = p.stats?.long || {};
        return `<tr><td>${escapeHtml(p.label)}</td><td>${n}</td><td>${win}</td><td class="${pnlClass(st.net)}">${net}</td><td>${sh.n ?? 0} · ${formatUsd(sh.net)}</td><td>${lo.n ?? 0} · ${formatUsd(lo.net)}</td></tr>`;
      }
      return `<tr><td>${escapeHtml(p.label)}</td><td>${n}</td><td>${win}</td><td class="${pnlClass(st.net)}">${net}</td><td>${formatPct(st.net_pct)}</td></tr>`;
    })
    .join("");
  return `<div class="table-wrap stats-period-table"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}

function formatUsd(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}$`;
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function pnlClass(value) {
  const n = Number(value);
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "";
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
  const node = document.querySelector(`[data-gauge="${CSS.escape(key)}"]`);
  if (!node) return;
  let chart = echarts.getInstanceByDom(node);
  const cached = state.gauges[key];
  if (cached && cached !== chart) {
    try {
      cached.dispose();
    } catch (_err) {
      /* ignore */
    }
  }
  if (!chart) {
    chart = echarts.init(node);
  }
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

window.signalCharts = {
  drawBook,
  drawLine,
  pointsOf,
  DETAIL_CHART_WINDOW_HOURS,
};
