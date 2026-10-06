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

const pumpState = {
  board: [],
  selected: null,
  detail: null,
  interval: "15",
  layoutSymbol: null,
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
    if (detail.interval) pumpState.interval = detail.interval;
  }
  renderPumpBoard();
  renderPumpDetail();
}

function onPumpScanDetail(symbol, data) {
  if (pumpState.selected && pumpState.selected !== symbol) return;
  pumpState.selected = symbol;
  pumpState.detail = data;
  if (data?.interval) pumpState.interval = data.interval;
  renderPumpDetail();
}

function selectPumpSymbol(symbol) {
  pumpState.selected = symbol;
  pumpState.layoutSymbol = null;
  renderPumpBoard();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_pump_scan", symbol }));
  }
}

function setPumpInterval(interval) {
  if (!interval || pumpState.interval === interval) return;
  pumpState.interval = interval;
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "pump_scan_interval", interval }));
  }
  void refreshPumpCharts();
  const root = document.getElementById("pump-detail");
  root?.querySelectorAll("[data-pump-interval]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.pumpInterval === interval);
  });
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
    <p class="quiet">Объём — по свечам выбранного TF. OI — поток ~5m, окно 48 ч.</p>
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
  if (detail.interval === interval && (detail.candles || []).length >= 30) {
    return detail.candles;
  }
  try {
    const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?interval=${encodeURIComponent(interval)}`);
    if (!res.ok) return detail.candles || [];
    const payload = await res.json();
    detail.candles = payload.candles || [];
    detail.interval = interval;
    return detail.candles;
  } catch (_e) {
    return detail.candles || [];
  }
}

async function refreshPumpCharts() {
  const detail = pumpState.detail;
  if (!detail?.signal) return;
  const symbol = detail.signal.symbol;
  const interval = pumpState.interval;
  const candles = await ensurePumpCandles(symbol, interval);
  drawPumpVolumeChart(candles, interval);
  drawPumpOiChart(detail.oi || []);
  drawPumpBookLadder(document.getElementById("pump-book-map"), detail.book || {});
}

function candleVolumePoints(candles) {
  const windowH = window.signalCharts?.DETAIL_CHART_WINDOW_HOURS ?? 48;
  const cutoff = Date.now() - windowH * 3600 * 1000;
  const out = [];
  for (const row of candles || []) {
    const t = Number(row.timestamp ?? row.time);
    const ms = t > 1e12 ? t : t * 1000;
    const v = Number(row.volume ?? row.v ?? 0);
    if (!ms || Number.isNaN(v)) continue;
    if (ms >= cutoff) out.push([ms, v]);
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
  const now = Date.now();
  const windowH = window.signalCharts?.DETAIL_CHART_WINDOW_HOURS ?? 48;
  chart.setOption({
    backgroundColor: "transparent",
    title: { text: `Объём · ${tfLabel}`, textStyle: { color: "#c5d0de", fontSize: 13 } },
    grid: { left: 48, right: 12, top: 36, bottom: 28 },
    xAxis: {
      type: "time",
      min: now - windowH * 3600 * 1000,
      max: now + 60000,
      axisLabel: { color: "#8e9aab" },
    },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
    series: [
      {
        type: "bar",
        data: points,
        itemStyle: { color: "rgba(93, 173, 226, 0.75)" },
      },
    ],
  });
  requestAnimationFrame(() => chart.resize());
}

function drawPumpOiChart(oiRows) {
  const node = document.getElementById("pump-oi-chart");
  if (!node || !window.echarts) return;
  const pointsFn = window.signalCharts?.pointsOf;
  const drawLine = window.signalCharts?.drawLine;
  if (pointsFn && drawLine) {
    drawLine("pump-oi-chart", "Открытый интерес (48 ч)", pointsFn(oiRows, "open_interest"), "#58a6ff");
    return;
  }
  const chart = echarts.getInstanceByDom(node) || echarts.init(node);
  chart.setOption({ title: { text: "OI", textStyle: { color: "#c5d0de" } } });
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
