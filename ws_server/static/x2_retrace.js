/* Вкладка «2× откат»: рост от min 5d, LH 1H/4H, OI↓, EMA. */

const X2_TF = [
  ["60", "1H"],
  ["240", "4H"],
  ["15", "15m"],
  ["30", "30m"],
  ["D", "1D"],
];

const X2_FETCH_DAYS = 30;
const X2_INITIAL_VIEW_DAYS = 14;

const X2_TF_TO_OI = {
  "15": "15min",
  "30": "30min",
  "60": "1h",
  "240": "4h",
  D: "1d",
};

const x2State = {
  board: [],
  selected: null,
  detail: null,
  interval: "60",
  layoutSymbol: null,
  volLoadKey: "",
  oiLoadKey: "",
  chartGen: 0,
};

function initX2RetraceTab() {
  if (window.__x2RetraceBound) return;
  window.__x2RetraceBound = true;
  document.getElementById("x2-columns")?.addEventListener("click", (event) => {
    const card = event.target instanceof Element ? event.target.closest(".x2-card") : null;
    if (card?.dataset.symbol) selectX2Symbol(card.dataset.symbol);
  });
  document.getElementById("x2-detail")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const dismiss = target?.closest("[data-dismiss-board]");
    if (dismiss?.dataset.dismissBoard && x2State.selected) {
      void dismissX2Watch(dismiss.dataset.dismissBoard, x2State.selected);
      return;
    }
    const btn = target?.closest("[data-x2-interval]");
    if (!btn) return;
    setX2Interval(btn.dataset.x2Interval);
  });
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
    renderX2Detail();
    renderX2Board();
  } catch (_e) {
    /* ignore */
  }
}

function onX2Board(data) {
  x2State.board = data || [];
  renderX2Board();
}

function onX2Snapshot(board, detail) {
  x2State.board = board || [];
  if (detail?.signal) {
    x2State.selected = detail.signal.symbol;
    x2State.detail = detail;
  }
  renderX2Board();
  renderX2Detail();
}

function mergeX2LiveDetail(data) {
  if (!data) return;
  const prev = x2State.detail || {};
  x2State.detail = {
    ...prev,
    signal: data.signal ?? prev.signal,
    book: data.book ?? prev.book,
    funding_rate: data.funding_rate ?? prev.funding_rate,
  };
}

function onX2Detail(symbol, data) {
  if (x2State.selected && x2State.selected !== symbol) return;
  x2State.selected = symbol;
  mergeX2LiveDetail(data);
  syncX2TfButtons();
  updateX2Meta(x2State.detail?.signal);
}

function selectX2Symbol(symbol) {
  x2State.selected = symbol;
  x2State.layoutSymbol = null;
  x2State.volLoadKey = "";
  x2State.oiLoadKey = "";
  renderX2Board();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_x2_retrace", symbol }));
  }
}

function syncX2TfButtons() {
  document.querySelectorAll("[data-x2-interval]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.x2Interval === x2State.interval);
  });
}

function setX2Interval(interval) {
  if (!interval || x2State.interval === interval) return;
  x2State.interval = interval;
  x2State.volLoadKey = "";
  x2State.oiLoadKey = "";
  x2State.chartGen += 1;
  syncX2TfButtons();
  if (window.signalSocket?.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "x2_retrace_interval", interval }));
  }
  void refreshX2Charts();
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
  const mult = peak ? `пик ×${peak}` : row.multiplier != null ? `×${Number(row.multiplier).toFixed(2)}` : "×2+";
  const lh = `LH 1H:${row.lh_1h ?? 0} · 4H:${row.lh_4h ?? 0}`;
  const pb = row.pullback_pct != null ? `откат ${row.pullback_pct}%` : "—";
  return `<article class="card x2-card ${color}${active ? " active" : ""}" data-symbol="${row.symbol}">
    <header><strong>${row.symbol}</strong> <span class="tag">${mult} от min 5d</span></header>
    <div class="meta">${lh} · ${pb} · EMA ${row.ema_depth ?? 0}/3${row.pending_stage ? ` · →${row.pending_stage}?` : ""}</div>
    <canvas class="mini" width="120" height="36" data-symbol="${row.symbol}"></canvas>
    <p class="quiet">${row.oi_drop ? "OI ↓" : "OI —"} · 24h ${row.price_24h_pct != null ? "+" + fmt(row.price_24h_pct) + "%" : "—"}</p>
  </article>`;
}

function renderX2Detail() {
  const root = document.getElementById("x2-detail");
  if (!root) return;
  const detail = x2State.detail;
  if (!detail?.signal) {
    root.innerHTML = '<p class="empty">Выберите монету слева (рост ≥2× от min за 5 дней).</p>';
    x2State.layoutSymbol = null;
    return;
  }
  const s = detail.signal;
  if (x2State.layoutSymbol !== s.symbol) {
    x2State.layoutSymbol = s.symbol;
    root.innerHTML = x2DetailShell(s);
  }
  updateX2Meta(s);
  syncX2TfButtons();
  void refreshX2Charts();
}

function x2DetailShell(s) {
  const tfButtons = X2_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf x2-tf${code === x2State.interval ? " active" : ""}" data-x2-interval="${code}">${label}</button>`,
  ).join("");
  return `
    <header class="detail-head">
      <h2>${s.symbol}</h2>
      <span class="tag">${s.status} ${s.label}</span>
      <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${s.symbol}" target="_blank" rel="noopener">Bybit</a>
      <button type="button" class="dismiss-watch" data-dismiss-board="x2_retrace">Снять с отслеживания</button>
    </header>
    <dl class="detail-stats" id="x2-stats"></dl>
    <h3>EMA 50 / 100 / 200</h3>
    <div id="x2-ema"></div>
    <p class="quiet">Pivot-high на 1H/4H считаются по закрытым свечам с начала пампа. OI должен снижаться. Объём/OI — прокрутка колёсиком или ползунок.</p>
    <div class="tf-row">${tfButtons}</div>
    <div class="detail-visual-stack">
      <section class="chart-block"><h4>Объём</h4><div id="x2-vol-chart" class="plot"></div></section>
      <section class="chart-block"><h4>Открытый интерес</h4><div id="x2-oi-chart" class="plot"></div></section>
    </div>`;
}

function updateX2Meta(s) {
  if (!s) return;
  const stats = document.getElementById("x2-stats");
  const emaEl = document.getElementById("x2-ema");
  if (!stats) return;
  stats.innerHTML = `
    <div><dt>Рост от min 5d</dt><dd>×${fmt(s.multiplier)}</dd></div>
    <div><dt>Min low 5d</dt><dd>${s.min_low_5d ?? "—"}</dd></div>
    <div><dt>Откат от max 1H</dt><dd>${s.pullback_pct != null ? s.pullback_pct + "%" : "—"}</dd></div>
    <div><dt>LH (1H / 4H)</dt><dd>${s.lh_1h ?? 0} / ${s.lh_4h ?? 0}</dd></div>
    <div><dt>OI</dt><dd>${s.oi_drop ? "снижается" : "—"} ${s.oi_change_pct != null ? s.oi_change_pct.toFixed(2) + "%" : ""}</dd></div>
    <div><dt>Цена</dt><dd>${s.last_price}</dd></div>`;
  if (emaEl) emaEl.innerHTML = renderX2EmaBlock(s.ema_by_tf);
}

function renderX2EmaBlock(map) {
  if (!map || !Object.keys(map).length) {
    return '<p class="quiet">Нужны закрытые свечи 15m–4H (до 200 баров).</p>';
  }
  const rows = Object.entries(map)
    .map(
      ([tf, info]) =>
        `<tr><td>${tf}</td><td>${info.summary}</td><td>${info.depth}/3</td></tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table class="ema-table"><thead><tr><th>TF</th><th>Состояние</th><th>Глубина</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function ensureX2Candles(symbol, interval) {
  const detail = x2State.detail;
  if (!detail) return [];
  const loadKey = `${symbol}:${interval}:${X2_FETCH_DAYS}`;
  if (x2State.volLoadKey === loadKey && (detail.candles || []).length >= 20) {
    return detail.candles;
  }
  try {
    const q = new URLSearchParams({ interval, days: String(X2_FETCH_DAYS), refresh: "1" });
    const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
    if (!res.ok) return detail.candles || [];
    const payload = await res.json();
    detail.candles = payload.candles || [];
    x2State.volLoadKey = loadKey;
    return detail.candles;
  } catch (_e) {
    return detail.candles || [];
  }
}

async function ensureX2Oi(symbol, chartInterval) {
  const detail = x2State.detail;
  if (!detail) return [];
  const oiInterval = X2_TF_TO_OI[chartInterval] || "1h";
  const loadKey = `${symbol}:${oiInterval}:${X2_FETCH_DAYS}`;
  if (x2State.oiLoadKey === loadKey && (detail.oi || []).length >= 20) {
    return detail.oi;
  }
  try {
    const q = new URLSearchParams({ interval: oiInterval, days: String(X2_FETCH_DAYS), refresh: "1" });
    const res = await fetch(`/api/open-interest/${encodeURIComponent(symbol)}?${q}`);
    if (!res.ok) return detail.oi || [];
    const payload = await res.json();
    detail.oi = payload.points || [];
    x2State.oiLoadKey = loadKey;
    return detail.oi;
  } catch (_e) {
    return detail.oi || [];
  }
}

async function refreshX2Charts() {
  const detail = x2State.detail;
  if (!detail?.signal) return;
  const gen = ++x2State.chartGen;
  const symbol = detail.signal.symbol;
  const interval = x2State.interval;
  const candles = await ensureX2Candles(symbol, interval);
  if (gen !== x2State.chartGen) return;
  const oiRows = await ensureX2Oi(symbol, interval);
  if (gen !== x2State.chartGen) return;
  drawX2VolumeChart(candles, interval);
  drawX2OiChart(oiRows, interval);
  syncX2TfButtons();
}

function x2DataZoom(points) {
  if (!points.length) {
    return [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, height: 20, bottom: 4, filterMode: "none" },
    ];
  }
  const tMin = points[0][0];
  const tMax = points[points.length - 1][0];
  const span = Math.max(tMax - tMin, 1);
  const viewMs = X2_INITIAL_VIEW_DAYS * 24 * 3600 * 1000;
  const start = Math.max(0, Math.min(100, ((tMax - viewMs - tMin) / span) * 100));
  const zoom = { start, end: 100 };
  return [
    { type: "inside", xAxisIndex: 0, filterMode: "none", ...zoom },
    { type: "slider", xAxisIndex: 0, height: 20, bottom: 4, filterMode: "none", ...zoom },
  ];
}

function drawX2VolumeChart(candles, interval) {
  const node = document.getElementById("x2-vol-chart");
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  const points = [];
  for (const row of candles || []) {
    const t = Number(row.timestamp ?? row.time);
    const ms = t > 1e12 ? t : t * 1000;
    const v = Number(row.volume ?? 0);
    if (ms && !Number.isNaN(v)) points.push([ms, v]);
  }
  points.sort((a, b) => a[0] - b[0]);
  const tfLabel = X2_TF.find(([c]) => c === interval)?.[1] || interval;
  chart.setOption({
    backgroundColor: "transparent",
    title: { text: `Объём · ${tfLabel}`, textStyle: { color: "#c5d0de", fontSize: 13 } },
    grid: { left: 52, right: 12, top: 36, bottom: 44 },
    dataZoom: x2DataZoom(points),
    xAxis: { type: "time", axisLabel: { color: "#8e9aab" } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8e9aab", formatter: x2FormatAxis },
      splitLine: { lineStyle: { color: "#2c3544" } },
    },
    series: [{ type: "bar", data: points, itemStyle: { color: "rgba(93, 173, 226, 0.75)" } }],
  });
  requestAnimationFrame(() => chart.resize());
}

function drawX2OiChart(oiRows, chartInterval) {
  const node = document.getElementById("x2-oi-chart");
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  const points = [];
  for (const row of oiRows || []) {
    const t = Number(row.timestamp ?? row.time);
    const ms = t > 1e12 ? t : t * 1000;
    const v = Number(row.open_interest ?? row.value);
    if (ms && !Number.isNaN(v)) points.push([ms, v]);
  }
  points.sort((a, b) => a[0] - b[0]);
  const oiIv = X2_TF_TO_OI[chartInterval] || "1h";
  chart.setOption({
    backgroundColor: "transparent",
    title: { text: `Открытый интерес · ${oiIv}`, textStyle: { color: "#c5d0de", fontSize: 13 } },
    grid: { left: 52, right: 12, top: 36, bottom: 44 },
    dataZoom: x2DataZoom(points),
    xAxis: { type: "time", axisLabel: { color: "#8e9aab" } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8e9aab", formatter: x2FormatAxis },
      splitLine: { lineStyle: { color: "#2c3544" } },
    },
    series: [{ type: "line", data: points, lineStyle: { color: "#58a6ff", width: 2 } }],
  });
  requestAnimationFrame(() => chart.resize());
}

function x2FormatAxis(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toFixed(n >= 10 ? 0 : 2);
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
  ctx.strokeStyle = "#e67e22";
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

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(2);
}

window.x2Retrace = {
  initX2RetraceTab,
  onX2Board,
  onX2Snapshot,
  onX2Detail,
};
