/* Вкладка «Поиск пампов»: крупные карточки, липкий список. */

const pumpStrategyState = {
  signals: [],
};

function initPumpStrategyTab() {
  if (window.__pumpStrategyBound) return;
  window.__pumpStrategyBound = true;
  document.getElementById("pump-strategy-grid")?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const dismiss = target?.closest("[data-dismiss-board]");
    if (dismiss?.dataset.dismissBoard && dismiss.dataset.symbol) {
      void dismissPumpStrategy(dismiss.dataset.dismissBoard, dismiss.dataset.symbol);
    }
  });
}

async function dismissPumpStrategy(board, symbol) {
  try {
    await fetch("/api/watch/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board, symbol }),
    });
    pumpStrategyState.signals = pumpStrategyState.signals.filter((row) => row.symbol !== symbol);
    renderPumpStrategyBoard();
  } catch (_e) {
    /* ignore */
  }
}

function onPumpStrategyBoard(data) {
  pumpStrategyState.signals = Array.isArray(data) ? data : [];
  renderPumpStrategyBoard();
}

function onPumpStrategySnapshot(board) {
  pumpStrategyState.signals = Array.isArray(board) ? board : [];
  renderPumpStrategyBoard();
}

function renderPumpStrategyBoard() {
  const root = document.getElementById("pump-strategy-grid");
  if (!root) return;
  const rows = pumpStrategyState.signals;
  if (!rows.length) {
    root.innerHTML =
      '<p class="quiet pump-strategy-empty">Пока нет монет. Быстрый памп: ≥40% за 1–12 ч. Длинный: ≥80% за 20 д. Оборот ≥300 тыс USDT за сутки.</p>';
    return;
  }
  const shortRows = rows.filter((r) => r.kind === "short");
  const longRows = rows.filter((r) => r.kind !== "short");
  let html = "";
  if (shortRows.length) {
    html += `<h2 class="psc-section-title">Быстрый памп (1–12 ч)</h2><div class="psc-section-grid">${shortRows.map((row) => pumpStrategyCardHtml(row)).join("")}</div>`;
  }
  if (longRows.length) {
    html += `<h2 class="psc-section-title">Длинный рост (до 20 д)</h2><div class="psc-section-grid">${longRows.map((row) => pumpStrategyCardHtml(row)).join("")}</div>`;
  }
  root.innerHTML = html;
  root.querySelectorAll("canvas.mini-strategy").forEach(drawStrategyMini);
  root.querySelectorAll(".psc-section-grid").forEach((grid) => {
    if (grid instanceof HTMLElement) {
      grid.classList.add("pump-strategy-grid-inner");
    }
  });
}

function pumpStrategyCardHtml(row) {
  const oi1 = formatOiChange(row.oi_change_1h_pct);
  const oi4 = formatOiChange(row.oi_change_4h_pct);
  return `<article class="pump-strategy-card" data-symbol="${row.symbol}">
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

window.pumpStrategy = {
  initPumpStrategyTab,
  onPumpStrategyBoard,
  onPumpStrategySnapshot,
};
