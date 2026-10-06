/* Страница сигналов. Данные приходят по WebSocket, страница сама ничего не считает по рынку. */

const CHECKS = [
  ["pump", "Памп"],
  ["liquidations_faded", "Ликвидации затихли"],
  ["oi_drop", "OI падает"],
  ["volume_faded", "Объём спал"],
  ["sweep", "Свуп на старшем ТФ"],
];

const EXTRAS = [
  ["cvd_divergence", "CVD дивергенция"],
  ["taker_seller", "Продавцы в контроле"],
  ["obv_divergence", "OBV дивергенция"],
  ["funding_extreme", "Funding перегрет"],
  ["round_level", "Круглый уровень"],
];

const INTERVALS = [
  ["1", "1m"],
  ["5", "5m"],
  ["15", "15m"],
  ["60", "1H"],
  ["240", "4H"],
  ["D", "1D"],
];

const state = {
  board: [],
  selected: null,
  interval: "1",
  detail: null,
  stats: null,
  tips: {},
  chart: null,
  series: null,
  priceLines: [],
  gauges: {},
  equity: null,
  sortKey: "created_at",
  sortDir: -1,
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

const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

socket.addEventListener("open", () => {
  document.getElementById("link-state").textContent = "канал открыт";
});

socket.addEventListener("close", () => {
  document.getElementById("link-state").textContent = "нет связи";
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
  } else if (message.type === "btc_test" && window.btcTest) {
    window.btcTest.onBtcMessage(message.data);
  } else if (message.type === "board") {
    setDemo(message.demo);
    state.board = message.data || [];
    renderBoard();
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

function setDemo(demo) {
  document.getElementById("demo-banner").hidden = !demo;
  document.getElementById("link-state").textContent = demo ? "пример, Redis недоступен" : "живой поток";
}

function showTab(name) {
  tooltip.hidden = true;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.getElementById("view-signals").hidden = name !== "signals";
  document.getElementById("view-stats").hidden = name !== "stats";
  const btcView = document.getElementById("view-btc");
  if (btcView) btcView.hidden = name !== "btc";
  if (name === "btc" && window.btcTest) {
    window.btcTest.initBtcTab();
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
    return;
  }
  const same =
    root.dataset.symbol === signal.symbol &&
    root.dataset.interval === (detail.interval || state.interval) &&
    root.querySelector("#candle-chart");
  if (!same) {
    root.dataset.symbol = signal.symbol;
    root.dataset.interval = detail.interval || state.interval;
    root.innerHTML = detailHtml(signal, detail.interval || state.interval);
    root.querySelectorAll(".tf").forEach((button) => {
      button.addEventListener("click", () => {
        state.interval = button.dataset.interval;
        socket.send(JSON.stringify({ type: "interval", interval: state.interval }));
      });
    });
    root.querySelector(".bybit-btn").addEventListener("click", () => openBybit(signal.symbol));
    mountCandleChart();
  } else {
    const info = root.querySelector(".signal-info");
    if (info) info.innerHTML = infoHtml(signal);
  }
  drawCandles(detail.candles || [], signal);
  drawBook(document.getElementById("book-map"), detail.book || {});
  drawLiquidations(document.getElementById("liq-map"), detail.liquidations || []);
  drawLine("oi-chart", "OI", pointsOf(detail.oi, "open_interest"));
  drawLine("cvd-chart", "CVD", pointsOf(detail.cvd, "value"));
  drawLine("obv-chart", "OBV", pointsOf(detail.obv, "value"));
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
  return `<h3>ГРАФИК + КАРТА ЛИКВИДНОСТИ</h3>
    <div class="tf-row">${buttons}</div>
    <div class="chart-row">
      <div id="candle-chart"></div>
      <div>
        <canvas id="book-map"></canvas>
        <div class="walls" id="walls"></div>
      </div>
    </div>
    <div class="signal-info">${infoHtml(signal)}</div>
    <h3>КАРТА ЛИКВИДАЦИЙ (S: Sell — шортисты)</h3>
    <canvas id="liq-map"></canvas>
    <div class="market-grid">
      <div id="oi-chart" class="plot"></div>
      <div class="metric"><div>Funding Rate</div><strong data-funding>—</strong></div>
      <div id="cvd-chart" class="plot"></div>
      <div class="metric"><div>Taker Ratio</div><strong data-taker>—</strong></div>
      <div id="obv-chart" class="plot"></div>
      <div class="metric"><div>Ликвидации</div><strong data-liq>—</strong></div>
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
  return `    <div class="ticker">${signal.symbol} · ${signal.status}</div>
    <div class="scale" style="color: var(--${signal.color || "gray"})">${scale}</div>
    <p>Вероятность ${Number(signal.probability || 0).toFixed(0)}% ${pnl}</p>
    <ul class="checks">${rows}</ul>`;
}

function mountCandleChart() {
  const container = document.getElementById("candle-chart");
  if (!container || !window.LightweightCharts) return;
  state.chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
    grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: "#2c3544" },
  });
  state.series = state.chart.addCandlestickSeries({
    upColor: "#3dd68c",
    downColor: "#ff5d73",
    borderVisible: false,
    wickUpColor: "#3dd68c",
    wickDownColor: "#ff5d73",
  });
  state.priceLines = [];
  const resize = () => {
    if (state.chart && container.clientWidth > 0) state.chart.resize(container.clientWidth, 280);
  };
  new ResizeObserver(resize).observe(container);
  requestAnimationFrame(resize);
}

function drawCandles(candles, signal) {
  if (!state.series) return;
  const bars = (candles || [])
    .map((candle) => ({
      time: Math.floor(Number(candle.timestamp) / 1000),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
    }))
    .filter((bar) => bar.time && !Number.isNaN(bar.close));
  state.series.setData(bars);
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
  if (chartBox && chartBox.clientWidth > 0) state.chart.resize(chartBox.clientWidth, 280);
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
    state.chart.timeScale().fitContent();
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
  canvas.width = width * ratio;
  canvas.height = 180 * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, 180);
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
    const y = 170 - ((Number(point.price) - p0) / (p1 - p0 || 1)) * 160;
    const age = (now - Number(point.time)) / (t1 - t0 || 1);
    const alpha = Math.max(0.12, (1 - age) * (0.35 + 0.65 * (Number(point.size) / maxSize)));
    ctx.fillStyle = `rgba(255, 120, 90, ${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y, 3 + 8 * (Number(point.size) / maxSize), 0, Math.PI * 2);
    ctx.fill();
  });
}

function pointsOf(rows, valueKey) {
  return (rows || [])
    .map((row) => [row.time || row.timestamp, row[valueKey] ?? row.value ?? row.open_interest])
    .filter((row) => row[0] != null && row[1] != null);
}

function drawLine(id, name, points) {
  const node = document.getElementById(id);
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  chart.setOption({
    backgroundColor: "transparent",
    title: { text: name, textStyle: { color: "#8e9aab", fontSize: 12 } },
    grid: { left: 36, right: 8, top: 28, bottom: 20 },
    xAxis: { type: "time", axisLabel: { color: "#8e9aab", hideOverlap: true } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
    series: [{ type: "line", showSymbol: false, data: points, lineStyle: { color: "#5dade2" } }],
  });
}

function formatFunding(rate) {
  if (rate == null) return "—";
  return `${(Number(rate) * 100).toFixed(3)}%`;
}

async function openBybit(symbol) {
  const note = document.getElementById("bybit-note");
  const response = await fetch(`/api/open-bybit/${symbol}`, { method: "POST" });
  const data = await response.json();
  if (note) note.textContent = response.ok ? `Открыт график: ${data.url}` : "Тикер отклонён";
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

function gauge(key, value, min, max, colors, formatter) {
  const node = document.querySelector(`[data-gauge="${key}"]`);
  if (!node) return;
  const chart = state.gauges[key] || echarts.init(node);
  state.gauges[key] = chart;
  chart.setOption({
    series: [
      {
        type: "gauge",
        min,
        max,
        animationDuration: 800,
        progress: { show: false },
        axisLine: { lineStyle: { width: 14, color: colors } },
        pointer: { itemStyle: { color: "#e8eef6" } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: "#8e9aab", distance: 14 },
        detail: { valueAnimation: true, formatter, color: "#e8eef6", fontSize: 16 },
        data: [{ value: Number(value) || 0 }],
      },
    ],
  });
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
