/* Вкладка «Памп-скан»: лидеры +24h и стадии ослабления. */

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
};

function initPumpScanTab() {
  if (window.__pumpScanBound) return;
  window.__pumpScanBound = true;
  document.getElementById("pump-columns")?.addEventListener("click", (event) => {
    const card = event.target instanceof Element ? event.target.closest(".pump-card") : null;
    if (card?.dataset.symbol) selectPumpSymbol(card.dataset.symbol);
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

function onPumpScanDetail(symbol, data) {
  if (pumpState.selected && pumpState.selected !== symbol) return;
  pumpState.selected = symbol;
  pumpState.detail = data;
  renderPumpDetail();
}

function selectPumpSymbol(symbol) {
  pumpState.selected = symbol;
  renderPumpBoard();
  if (window.signalSocket && window.signalSocket.readyState === WebSocket.OPEN) {
    window.signalSocket.send(JSON.stringify({ type: "select_pump_scan", symbol }));
  }
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
    return;
  }
  const s = detail.signal;
  const checks = PUMP_CHECKS.map(([key, label]) => {
    let on = false;
    if (key === "taker_sellers") on = s.taker_ratio != null && s.taker_ratio < 1;
    else on = !!s[key];
    return `<li class="${on ? "ok" : ""}">${label}</li>`;
  }).join("");
  const emaBlock = renderEmaBlock(s.ema_by_tf);
  const funding =
    s.funding_rate != null ? `${(s.funding_rate * 100).toFixed(4)}%` : "—";
  const taker = s.taker_ratio != null ? s.taker_ratio.toFixed(2) : "—";
  root.innerHTML = `
    <header class="detail-head">
      <h2>${s.symbol}</h2>
      <span class="tag">${s.status} ${s.label}</span>
      <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${s.symbol}" target="_blank" rel="noopener">Bybit</a>
    </header>
    <dl class="detail-stats">
      <div><dt>Рост 24h</dt><dd>+${fmt(s.price_24h_pct)}%</dd></div>
      <div><dt>Цена</dt><dd>${s.last_price}</dd></div>
      <div><dt>Funding</dt><dd>${funding}</dd></div>
      <div><dt>Taker buy/sell</dt><dd>${taker}</dd></div>
      <div><dt>Объём × к MA</dt><dd>${s.volume_ratio != null ? s.volume_ratio.toFixed(1) : "—"}</dd></div>
      <div><dt>OI Δ</dt><dd>${s.oi_change_pct != null ? s.oi_change_pct.toFixed(2) + "%" : "—"}</dd></div>
    </dl>
    <h3>Признаки ослабления</h3>
    <ul class="checklist">${checks}</ul>
    <h3>EMA 50 / 100 / 200</h3>
    ${emaBlock}
    <h3>Стакан (стены)</h3>
    ${bookHtml(detail.book)}
  `;
}

function renderEmaBlock(map) {
  if (!map || !Object.keys(map).length) {
    return '<p class="quiet">Нужны закрытые свечи 15m, 30m, 1H, 4H (до 200 баров).</p>';
  }
  const rows = Object.entries(map)
    .map(
      ([tf, info]) =>
        `<tr><td>${tf}</td><td>${info.summary}</td><td>${info.depth}/3</td></tr>`
    )
    .join("");
  return `<div class="table-wrap"><table class="ema-table"><thead><tr><th>TF</th><th>Состояние</th><th>Глубина</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function bookHtml(book) {
  if (!book?.walls?.length) return '<p class="quiet">Крупных стен нет или стакан ещё не загружен.</p>';
  return `<ul class="wall-list">${book.walls
    .map((w) => `<li>${w.side} ${w.price} · ${w.kind} · ${w.size}</li>`)
    .join("")}</ul>`;
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
