/* Вкладка «Памп-скан»: лидеры +24h, стакан, объём и OI. */

const PUMP_TF = [
  ["1", "1m"],
  ["5", "5m"],
  ["15", "15m"],
  ["30", "30m"],
  ["60", "1H"],
  ["240", "4H"],
  ["D", "1D"],
];

const PUMP_CHECKS = [
  ["liquidations_faded", "Ликвидации шортов затихли"],
  ["oi_drop", "OI падает"],
  ["volume_faded", "Объём спал"],
  ["cvd_divergence", "Дивергенция CVD"],
  ["taker_sellers", "Продавцы в контроле"],
];

/** Сколько дней истории запрашиваем с биржи (прокрутка назад). */
const PUMP_FETCH_DAYS = 30;
/** Стартовый вид: последние N дней; дальше — колёсико и ползунок. */
const PUMP_INITIAL_VIEW_DAYS = 7;

const TF_TO_OI = {
  "1": "5min",
  "5": "5min",
  "15": "15min",
  "30": "30min",
  "60": "1h",
  "240": "4h",
  D: "1d",
};

const pumpState = {
  board: [],
  selected: null,
  detail: null,
  interval: "15",
  layoutSymbol: null,
  volLoadKey: "",
  oiLoadKey: "",
  chartGen: 0,
};

function initPumpScanTab() {
  if (window.__pumpScanBound) return;
  window.__pumpScanBound = true;
  document.getElementById("pump-columns")?.addEventListener("click", (event) => {
    const card = event.target instanceof Element ? event.target.closest(".pump-card") : null;
    if (card?.dataset.symbol) selectPumpSymbol(card.dataset.symbol);
  });
  document.getElementById("pump-detail")?.addEventListener("click", (event) => {
    const btn = event.target instanceof Element ? event.target.closest("[data-pump-interval]") : null;
    if (!btn) return;
    setPumpInterval(btn.dataset.pumpInterval);
  });
}

function onPumpScanBoard(data) {
  pumpState.board = data || [];
  renderPumpBoard();
}

function onPumpScanSnapshot(board, detail) {
  pumpState.board = board || [];
  if (detail?.signal) {
    pumpState.selected = detail.signal.symbol;
    pumpState.detail = detail;
  }
  renderPumpBoard();
  renderPumpDetail();
}

/** WS обновляет стакан/сигнал; TF и свечи — только с REST по pumpState.interval. */
function mergePumpLiveDetail(data) {
  if (!data) return;
  const prev = pumpState.detail || {};
  pumpState.detail = {
    ...prev,
    signal: data.signal ?? prev.signal,
    book: data.book ?? prev.book,
    funding_rate: data.funding_rate ?? prev.funding_rate,
    taker_ratio: data.taker_ratio ?? prev.taker_ratio,
    liquidations: data.liquidations ?? prev.liquidations,
    cvd: data.cvd ?? prev.cvd,
  };
}

function onPumpScanDetail(symbol, data) {
  if (pumpState.selected && pumpState.selected !== symbol) return;
  pumpState.selected = symbol;
  mergePumpLiveDetail(data);
  syncPumpTfButtons();
  updatePumpMeta(pumpState.detail?.signal, pumpState.detail);
  drawPumpBookLadder(document.getElementById("pump-book-map"), pumpState.detail?.book || {});
}

function oiIntervalForTf(tf) {
  return TF_TO_OI[tf] || "5min";
}

function pumpDataZoom(points, viewDays = PUMP_INITIAL_VIEW_DAYS) {
  if (!points.length) {
    return [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, height: 20, bottom: 4, filterMode: "none" },
    ];
  }
  const tMin = points[0][0];
  const tMax = points[points.length - 1][0];
  const span = Math.max(tMax - tMin, 1);
  const viewMs = viewDays * 24 * 3600 * 1000;
  const start = Math.max(0, Math.min(100, ((tMax - viewMs - tMin) / span) * 100));
  const zoom = { start, end: 100 };
  return [
    { type: "inside", xAxisIndex: 0, filterMode: "none", ...zoom },
    {
      type: "slider",
      xAxisIndex: 0,
      height: 20,
      bottom: 4,
      filterMode: "none",
      ...zoom,
    },
  ];
}

function selectPumpSymbol(symbol) {
  pumpState.selected = symbol;
  pumpState.layoutSymbol = null;
  pumpState.volLoadKey = "";
  pumpState.oiLoadKey = "";
  renderPumpBoard();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_pump_scan", symbol }));
  }
}

function syncPumpTfButtons() {
  document.querySelectorAll("[data-pump-interval]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.pumpInterval === pumpState.interval);
  });
}

function setPumpInterval(interval) {
  if (!interval || pumpState.interval === interval) return;
  pumpState.interval = interval;
  pumpState.volLoadKey = "";
  pumpState.oiLoadKey = "";
  pumpState.chartGen += 1;
  syncPumpTfButtons();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "pump_scan_interval", interval }));
  }
  void refreshPumpCharts();
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
  const emaHint = emaHintText(row.ema_by_tf);
  return `<article class="card pump-card ${color}${active ? " active" : ""}" data-symbol="${row.symbol}">
    <header><strong>${row.symbol}</strong> <span class="tag">+${fmt(row.price_24h_pct)}% / 24h</span></header>
    <div class="meta">ослабление ${row.weaken_score} · EMA ${row.ema_depth}/3</div>
    <canvas class="mini" width="120" height="36" data-symbol="${row.symbol}"></canvas>
    <p class="quiet ema-hint">${emaHint}</p>
  </article>`;
}

function emaHintText(map) {
  if (!map || !Object.keys(map).length) return "EMA: ждём свечи 15m–4H";
  return Object.entries(map)
    .map(([tf, info]) => `${tf}: ${info.summary}`)
    .slice(0, 2)
    .join(" · ");
}

function renderPumpDetail() {
  const root = document.getElementById("pump-detail");
  if (!root) return;
  const detail = pumpState.detail;
  if (!detail?.signal) {
    root.innerHTML = '<p class="empty">Выберите монету слева (+35% за сутки).</p>';
    pumpState.layoutSymbol = null;
    return;
  }
  const s = detail.signal;
  if (pumpState.layoutSymbol !== s.symbol) {
    pumpState.layoutSymbol = s.symbol;
    root.innerHTML = pumpDetailShell(s);
  }
  updatePumpMeta(s, detail);
  syncPumpTfButtons();
  void refreshPumpCharts();
}

function pumpDetailShell(s) {
  const tfButtons = PUMP_TF.map(
    ([code, label]) =>
      `<button type="button" class="tf pump-tf${code === pumpState.interval ? " active" : ""}" data-pump-interval="${code}">${label}</button>`,
  ).join("");
  return `
    <header class="detail-head pump-detail-head">
      <h2>${s.symbol}</h2>
      <span class="tag">${s.status} ${s.label}</span>
      <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${s.symbol}" target="_blank" rel="noopener">Bybit</a>
    </header>
    <dl class="detail-stats" id="pump-stats"></dl>
    <h3>Признаки ослабления</h3>
    <ul class="checklist" id="pump-checks"></ul>
    <h3>EMA 50 / 100 / 200</h3>
    <div id="pump-ema"></div>
    <p class="quiet">Объём/OI: история до ${PUMP_FETCH_DAYS} д · OI по TF · прокрутка — колёсико мыши на графике или ползунок внизу (влево = раньше).</p>
    <div class="tf-row pump-tf-row">${tfButtons}</div>
    <div class="pump-visual-stack detail-visual-stack">
      <section class="chart-block">
        <h4>Объём</h4>
        <div id="pump-vol-chart" class="plot"></div>
      </section>
      <section class="chart-block">
        <h4>Открытый интерес</h4>
        <div id="pump-oi-chart" class="plot"></div>
      </section>
      <section class="chart-block">
        <h4>Стакан (пропорционально)</h4>
        <canvas id="pump-book-map" class="pump-book-canvas"></canvas>
        <div class="walls" id="pump-walls"></div>
      </section>
    </div>`;
}

function updatePumpMeta(s, detail) {
  const stats = document.getElementById("pump-stats");
  const checksEl = document.getElementById("pump-checks");
  const emaEl = document.getElementById("pump-ema");
  if (!stats) return;
  const funding = s.funding_rate != null ? `${(s.funding_rate * 100).toFixed(4)}%` : "—";
  const taker = s.taker_ratio != null ? s.taker_ratio.toFixed(2) : "—";
  stats.innerHTML = `
    <div><dt>Рост 24h</dt><dd>+${fmt(s.price_24h_pct)}%</dd></div>
    <div><dt>Цена</dt><dd>${s.last_price}</dd></div>
    <div><dt>Funding</dt><dd>${funding}</dd></div>
    <div><dt>Taker buy/sell</dt><dd>${taker}</dd></div>
    <div><dt>Объём × к MA</dt><dd>${s.volume_ratio != null ? s.volume_ratio.toFixed(1) : "—"}</dd></div>
    <div><dt>OI Δ</dt><dd>${s.oi_change_pct != null ? s.oi_change_pct.toFixed(2) + "%" : "—"}</dd></div>`;
  if (checksEl) {
    checksEl.innerHTML = PUMP_CHECKS.map(([key, label]) => {
      let on = false;
      if (key === "taker_sellers") on = s.taker_ratio != null && s.taker_ratio < 1;
      else on = !!s[key];
      return `<li class="${on ? "ok" : ""}">${label}</li>`;
    }).join("");
  }
  if (emaEl) emaEl.innerHTML = renderEmaBlock(s.ema_by_tf);
}

function renderEmaBlock(map) {
  if (!map || !Object.keys(map).length) {
    return '<p class="quiet">Нужны закрытые свечи 15m, 30m, 1H, 4H (до 200 баров).</p>';
  }
  const rows = Object.entries(map)
    .map(
      ([tf, info]) =>
        `<tr><td>${tf}</td><td>${info.summary}</td><td>${info.depth}/3</td></tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table class="ema-table"><thead><tr><th>TF</th><th>Состояние</th><th>Глубина</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function ensurePumpCandles(symbol, interval) {
  const detail = pumpState.detail;
  if (!detail) return [];
  const loadKey = `${symbol}:${interval}:${PUMP_FETCH_DAYS}`;
  if (pumpState.volLoadKey === loadKey && (detail.candles || []).length >= 20) {
    return detail.candles;
  }
  try {
    const q = new URLSearchParams({
      interval,
      days: String(PUMP_FETCH_DAYS),
      refresh: "1",
    });
    const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
    if (!res.ok) return detail.candles || [];
    const payload = await res.json();
    detail.candles = payload.candles || [];
    detail.interval = interval;
    pumpState.volLoadKey = loadKey;
    return detail.candles;
  } catch (_e) {
    return detail.candles || [];
  }
}

async function ensurePumpOi(symbol, chartInterval) {
  const detail = pumpState.detail;
  if (!detail) return [];
  const oiInterval = oiIntervalForTf(chartInterval);
  const loadKey = `${symbol}:${oiInterval}:${PUMP_FETCH_DAYS}`;
  if (pumpState.oiLoadKey === loadKey && (detail.oi || []).length >= 20) {
    return detail.oi;
  }
  try {
    const q = new URLSearchParams({
      interval: oiInterval,
      days: String(PUMP_FETCH_DAYS),
      refresh: "1",
    });
    const res = await fetch(`/api/open-interest/${encodeURIComponent(symbol)}?${q}`);
    if (!res.ok) return detail.oi || [];
    const payload = await res.json();
    detail.oi = payload.points || [];
    detail.oi_interval = oiInterval;
    pumpState.oiLoadKey = loadKey;
    return detail.oi;
  } catch (_e) {
    return detail.oi || [];
  }
}

async function refreshPumpCharts() {
  const detail = pumpState.detail;
  if (!detail?.signal) return;
  const gen = ++pumpState.chartGen;
  const symbol = detail.signal.symbol;
  const interval = pumpState.interval;
  const candles = await ensurePumpCandles(symbol, interval);
  if (gen !== pumpState.chartGen) return;
  const oiRows = await ensurePumpOi(symbol, interval);
  if (gen !== pumpState.chartGen) return;
  drawPumpVolumeChart(candles, interval);
  drawPumpOiChart(oiRows, interval);
  drawPumpBookLadder(document.getElementById("pump-book-map"), detail.book || {});
  syncPumpTfButtons();
}

function candleVolumePoints(candles) {
  const out = [];
  for (const row of candles || []) {
    const t = Number(row.timestamp ?? row.time);
    const ms = t > 1e12 ? t : t * 1000;
    const v = Number(row.volume ?? row.v ?? 0);
    if (!ms || Number.isNaN(v)) continue;
    out.push([ms, v]);
  }
  out.sort((a, b) => a[0] - b[0]);
  return out;
}

function oiSeriesPoints(oiRows) {
  const out = [];
  for (const row of oiRows || []) {
    const t = Number(row.timestamp ?? row.time);
    const ms = t > 1e12 ? t : t * 1000;
    const v = Number(row.open_interest ?? row.value);
    if (!ms || Number.isNaN(v)) continue;
    out.push([ms, v]);
  }
  out.sort((a, b) => a[0] - b[0]);
  return out;
}

function drawPumpVolumeChart(candles, interval) {
  const node = document.getElementById("pump-vol-chart");
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  const points = candleVolumePoints(candles);
  const tfLabel = PUMP_TF.find(([c]) => c === interval)?.[1] || interval;
  chart.setOption({
    backgroundColor: "transparent",
    title: {
      text: `Объём · ${tfLabel}`,
      textStyle: { color: "#c5d0de", fontSize: 13 },
    },
    grid: { left: 52, right: 12, top: 36, bottom: 44 },
    dataZoom: pumpDataZoom(points),
    xAxis: {
      type: "time",
      axisLabel: { color: "#8e9aab" },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8e9aab", formatter: formatAxisNumber },
      splitLine: { lineStyle: { color: "#2c3544" } },
    },
    series: [
      {
        type: "bar",
        data: points,
        itemStyle: { color: "rgba(93, 173, 226, 0.75)" },
      },
    ],
    graphic: points.length
      ? []
      : [
          {
            type: "text",
            left: "center",
            top: "middle",
            style: { text: "Загрузка объёма…", fill: "#8e9aab", fontSize: 13 },
          },
        ],
  });
  requestAnimationFrame(() => chart.resize());
}

function drawPumpOiChart(oiRows, chartInterval) {
  const node = document.getElementById("pump-oi-chart");
  if (!node || !window.echarts) return;
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  const points = oiSeriesPoints(oiRows);
  const oiIv = oiIntervalForTf(chartInterval);
  chart.setOption({
    backgroundColor: "transparent",
    title: {
      text: `Открытый интерес · ${oiIv}`,
      textStyle: { color: "#c5d0de", fontSize: 13 },
    },
    grid: { left: 52, right: 12, top: 36, bottom: 44 },
    dataZoom: pumpDataZoom(points),
    xAxis: {
      type: "time",
      axisLabel: { color: "#8e9aab" },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8e9aab", formatter: formatAxisNumber },
      splitLine: { lineStyle: { color: "#2c3544" } },
    },
    series: [
      {
        type: "line",
        showSymbol: points.length <= 40,
        data: points,
        lineStyle: { color: "#58a6ff", width: 2 },
      },
    ],
    graphic: points.length
      ? []
      : [
          {
            type: "text",
            left: "center",
            top: "middle",
            style: { text: "Загрузка OI…", fill: "#8e9aab", fontSize: 13 },
          },
        ],
  });
  requestAnimationFrame(() => chart.resize());
}

function normalizeBookSide(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map((row) => ({ price: Number(row[0]), size: Number(row[1]) })).filter((r) => r.price > 0);
  }
  return Object.entries(raw)
    .map(([p, s]) => ({ price: Number(p), size: Number(s) }))
    .filter((r) => r.price > 0 && r.size > 0);
}

function drawPumpBookLadder(canvas, book) {
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 320;
  const height = 320;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const bids = normalizeBookSide(book.bids).sort((a, b) => b.price - a.price).slice(0, 14);
  const asks = normalizeBookSide(book.asks).sort((a, b) => a.price - b.price).slice(0, 14);
  if (!bids.length && !asks.length) {
    ctx.fillStyle = "#8e9aab";
    ctx.font = "13px Segoe UI, sans-serif";
    ctx.fillText("Стакан загружается…", 12, 24);
    return;
  }

  const midX = width / 2;
  const rowH = Math.min(18, Math.floor((height - 24) / Math.max(bids.length, asks.length, 1)));
  const maxSize = Math.max(...[...bids, ...asks].map((r) => r.size), 1);
  const maxBar = midX - 88;

  ctx.font = "11px Segoe UI, sans-serif";
  ctx.fillStyle = "#8e9aab";
  ctx.fillText("BID", 8, 14);
  ctx.fillText("ASK", width - 32, 14);

  bids.forEach((row, i) => {
    const y = 22 + i * rowH;
    const bar = 4 + (row.size / maxSize) * maxBar;
    ctx.fillStyle = "rgba(61, 214, 140, 0.85)";
    ctx.fillRect(midX - bar, y, bar, rowH - 3);
    ctx.fillStyle = "#e8eef6";
    ctx.textAlign = "right";
    ctx.fillText(formatBookPrice(row.price), midX - bar - 4, y + rowH - 6);
    ctx.fillStyle = "#8e9aab";
    ctx.textAlign = "left";
    ctx.fillText(formatBookSize(row.size), 6, y + rowH - 6);
  });

  asks.forEach((row, i) => {
    const y = 22 + i * rowH;
    const bar = 4 + (row.size / maxSize) * maxBar;
    ctx.fillStyle = "rgba(255, 93, 115, 0.85)";
    ctx.fillRect(midX, y, bar, rowH - 3);
    ctx.fillStyle = "#e8eef6";
    ctx.textAlign = "left";
    ctx.fillText(formatBookPrice(row.price), midX + bar + 4, y + rowH - 6);
    ctx.fillStyle = "#8e9aab";
    ctx.textAlign = "right";
    ctx.fillText(formatBookSize(row.size), width - 6, y + rowH - 6);
  });

  ctx.strokeStyle = "#2c3544";
  ctx.beginPath();
  ctx.moveTo(midX, 18);
  ctx.lineTo(midX, height - 4);
  ctx.stroke();

  const walls = document.getElementById("pump-walls");
  if (walls) {
    walls.innerHTML = (book.walls || [])
      .map((w) => {
        const kind =
          w.kind === "holding" ? "Holding" : w.kind === "spoof" ? "Spoof" : "Building";
        return `<span class="wall ${w.kind}">${kind} ${formatBookPrice(w.price)} · ${formatBookSize(w.size)}</span>`;
      })
      .join("");
  }
}

function formatAxisNumber(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toFixed(n >= 10 ? 0 : 2);
}

function formatBookPrice(p) {
  const n = Number(p);
  if (n >= 1000) return n.toFixed(1);
  if (n >= 1) return n.toFixed(4);
  return n.toPrecision(4);
}

function formatBookSize(s) {
  const n = Number(s);
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(1);
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

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(1);
}

window.pumpScan = {
  initPumpScanTab,
  onPumpScanBoard,
  onPumpScanSnapshot,
  onPumpScanDetail,
};
