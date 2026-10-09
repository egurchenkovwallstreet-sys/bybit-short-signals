/* Вкладка «Анализ пампа»: быстрый / средний / длинный, фазы цветом, 30 метрик. */

const PUMP_LAB_SECTIONS = [
  ["fast", "Быстрый", "минуты — часы"],
  ["medium", "Средний", "до 2 суток назад"],
  ["long", "Длинный", "до 20 суток назад"],
];

const HORIZONS = [
  ["short", "Короткий"],
  ["mid", "Средний"],
  ["long", "Длинный"],
];

const plState = {
  board: null,
  selectedId: null,
  detail: null,
  charts: {},
};

function initPumpLabTab() {
  const dismissAll = document.getElementById("pl-dismiss-all");
  if (dismissAll && !dismissAll.dataset.inited) {
    dismissAll.dataset.inited = "1";
    dismissAll.addEventListener("click", (e) => {
      e.preventDefault();
      dismissAllActive();
    });
  }
  const root = document.getElementById("pump-lab-sections");
  if (!root || root.dataset.inited) return;
  root.dataset.inited = "1";
  root.innerHTML = PUMP_LAB_SECTIONS.map(
    ([id, title, hint]) => `
    <section class="pl-section" data-section="${id}">
      <header class="pl-section-head">
        <h2>${title}</h2>
        <span class="quiet">${hint}</span>
        <span class="pl-legend">
          <span class="pl-dot pl-red"></span> рост
          <span class="pl-dot pl-yellow"></span> торможение
          <span class="pl-dot pl-green"></span> снижение
          <span class="pl-dot pl-purple"></span> прошёл — скрыт
        </span>
      </header>
      <div class="pl-cards" id="pl-cards-${id}"></div>
    </section>`
  ).join("");
}

function onPumpLabBoard(data) {
  if (!data) return;
  plState.board = data;
  initPumpLabTab();
  for (const [id] of PUMP_LAB_SECTIONS) {
    const wrap = document.getElementById(`pl-cards-${id}`);
    if (!wrap) continue;
    let cards = [...((data.sections && data.sections[id]) || [])];
    cards.sort(compareCardPriority);
    if (!cards.length) {
      wrap.innerHTML = `<p class="quiet pl-empty">Пампов этого типа пока нет.</p>`;
      continue;
    }
    wrap.innerHTML = cards
      .map((c) => {
        const phaseClass = c.phase === "green" ? "pl-green" : c.phase === "yellow" ? "pl-yellow" : "pl-red";
        const dd = c.drawdown_pct != null ? `${c.drawdown_pct}% от пика` : "";
        const gr = c.growth_pct != null ? `+${Number(c.growth_pct).toFixed(1)}%` : "";
        const pro = c.summary ? (c.summary.for_short ?? c.summary.bearish) : 0;
        const anti = c.summary ? (c.summary.against_short ?? c.summary.bullish) : 0;
        return `<div class="pl-card ${phaseClass}" data-episode-id="${c.episode_id}">
          <button type="button" class="pl-card-dismiss" title="Убрать с отслеживания" aria-label="Убрать">×</button>
          <button type="button" class="pl-card-body">
            <span class="pl-card-symbol">${c.symbol}</span>
            <span class="pl-card-phase">${c.phase_label || ""}</span>
            <span class="pl-card-meta">${gr} · ${dd}</span>
            <span class="pl-card-meta"><span class="pl-short-yes">за шорт: ${pro}</span> · <span class="pl-short-no">против: ${anti}</span></span>
          </button>
        </div>`;
      })
      .join("");
  }
  document.querySelectorAll(".pl-card-body").forEach((btn) => {
    const wrap = btn.closest(".pl-card");
    btn.addEventListener("click", () => loadEpisode(Number(wrap.dataset.episodeId)));
  });
  document.querySelectorAll(".pl-card-dismiss").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      const wrap = btn.closest(".pl-card");
      dismissEpisode(Number(wrap.dataset.episodeId));
    });
  });
  if (plState.selectedId) {
    const still = cardsFlat(data).find((c) => c.episode_id === plState.selectedId);
    if (!still) {
      plState.selectedId = null;
      hideDetail();
    }
  }
}

function compareCardPriority(a, b) {
  const order = { green: 0, yellow: 1, red: 2 };
  const pa = order[a.phase] ?? 3;
  const pb = order[b.phase] ?? 3;
  if (pa !== pb) return pa - pb;
  const proA = a.summary ? (a.summary.for_short ?? a.summary.bearish ?? 0) : 0;
  const proB = b.summary ? (b.summary.for_short ?? b.summary.bearish ?? 0) : 0;
  const antiA = a.summary ? (a.summary.against_short ?? a.summary.bullish ?? 0) : 0;
  const antiB = b.summary ? (b.summary.against_short ?? b.summary.bullish ?? 0) : 0;
  if (a.phase === "red") {
    if (antiB !== antiA) return antiB - antiA;
    if (proB !== proA) return proB - proA;
  } else {
    if (proB !== proA) return proB - proA;
    if (antiB !== antiA) return antiB - antiA;
  }
  return String(a.symbol || "").localeCompare(String(b.symbol || ""));
}

function cardsFlat(data) {
  const out = [];
  const sec = data.sections || {};
  for (const key of Object.keys(sec)) out.push(...(sec[key] || []));
  return out;
}

function hideDetail() {
  const pane = document.getElementById("pump-lab-detail");
  if (pane) pane.hidden = true;
}

async function dismissEpisode(id) {
  try {
    const res = await fetch(`/api/pump-lab/episode/${id}/dismiss`, { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.board) onPumpLabBoard(data.board);
    if (plState.selectedId === id) {
      plState.selectedId = null;
      hideDetail();
    }
  } catch {
    /* ignore */
  }
}

async function dismissAllActive() {
  const btn = document.getElementById("pl-dismiss-all");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/pump-lab/dismiss-all", { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.board) onPumpLabBoard(data.board);
    plState.selectedId = null;
    hideDetail();
  } catch {
    /* ignore */
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadEpisode(id) {
  plState.selectedId = id;
  document.querySelectorAll(".pl-card").forEach((b) => {
    b.classList.toggle("selected", Number(b.dataset.episodeId) === id);
  });
  const pane = document.getElementById("pump-lab-detail");
  if (pane) {
    pane.hidden = false;
    pane.innerHTML = `<p class="quiet">Загрузка…</p>`;
  }
  try {
    const res = await fetch(`/api/pump-lab/episode/${id}`);
    if (!res.ok) throw new Error("not found");
    plState.detail = await res.json();
    renderDetail();
  } catch {
    if (pane) pane.innerHTML = `<p class="quiet">Не удалось загрузить эпизод.</p>`;
  }
}

function renderDetail() {
  const pane = document.getElementById("pump-lab-detail");
  const d = plState.detail;
  if (!pane || !d || !d.episode) return;
  const ep = d.episode;
  const metrics = ep.metrics || {};
  const labels = d.metric_labels || {};
  const groups = d.metric_groups || [];
  const byGroup = {};
  for (const id of Object.keys(labels)) {
    const g = metricGroupId(id);
    byGroup[g] = byGroup[g] || [];
    byGroup[g].push(id);
  }
  let html = `<div class="pl-detail-head">
    <h3>${ep.symbol}</h3>
    <p class="quiet">Пик ${ep.peak_price} · рост ${ep.growth_pct != null ? ep.growth_pct.toFixed(1) : "—"}%</p>
    <p class="pl-metric-legend"><span class="pl-short-yes">■</span> за шорт · <span class="pl-short-neutral">■</span> нейтрально · <span class="pl-short-no">■</span> против</p>
    <a class="bybit-btn" href="https://www.bybit.com/trade/usdt/${ep.symbol}" target="_blank" rel="noopener">Bybit</a>
  </div>`;
  for (const g of groups.length ? groups : [{ id: "flow", title: "Метрики" }]) {
    let ids = byGroup[g.id] || Object.keys(labels);
    ids = sortMetricIds(ids, metrics);
    html += `<div class="pl-metric-group"><h4>${g.title}</h4><div class="pl-metric-table-wrap"><table class="pl-metric-table"><thead><tr><th></th>${HORIZONS.map(([, t]) => `<th>${t}</th>`).join("")}</tr></thead><tbody>`;
    for (const mid of ids) {
      const row = metrics[mid] || {};
      html += `<tr><td class="pl-m-name">${labels[mid] || mid}</td>`;
      for (const [h] of HORIZONS) {
        const cell = row[h] || {};
        const v = cell.value;
        const favor = cell.short_favor != null ? cell.short_favor : cell.signal || 0;
        const cls = favor > 0 ? "pl-short-yes" : favor < 0 ? "pl-short-no" : "pl-short-neutral";
        html += `<td class="${cls}">${v != null ? formatVal(v) : "—"}<canvas class="pl-spark" data-favor="${favor}" data-mid="${mid}" data-h="${h}" width="80" height="22"></canvas></td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table></div></div>`;
  }
  pane.innerHTML = html;
  drawSparks(d.history || {});
}

function metricRowRank(mid, metrics) {
  const row = metrics[mid] || {};
  let hasPro = false;
  let hasAnti = false;
  for (const [h] of HORIZONS) {
    const favor = (row[h] || {}).short_favor ?? (row[h] || {}).signal ?? 0;
    if (favor > 0) hasPro = true;
    if (favor < 0) hasAnti = true;
  }
  if (hasPro) return 0;
  if (!hasAnti) return 1;
  return 2;
}

function sortMetricIds(ids, metrics) {
  return [...ids].sort((a, b) => {
    const ra = metricRowRank(a, metrics);
    const rb = metricRowRank(b, metrics);
    if (ra !== rb) return ra - rb;
    return String(a).localeCompare(String(b));
  });
}

function metricGroupId(id) {
  if (["delta", "large_trades", "absorption", "tape_speed", "buy_sell_imbalance"].includes(id)) return "flow";
  if (id.startsWith("wall") || id.includes("book") || id.includes("spread") || id === "spoof_risk" || id === "thin_book") return "book";
  if (id.includes("liq") || id.includes("funding") || id.includes("oi") || id === "premium" || id === "crowd_skew") return "leverage";
  if (id.includes("break") || id.includes("sweep") || id.includes("structure") || id === "cvd_div") return "structure";
  return "market";
}

function formatVal(v) {
  const n = Number(v);
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(2);
}

function drawSparks(history) {
  document.querySelectorAll(".pl-spark").forEach((canvas) => {
    const mid = canvas.dataset.mid;
    const h = canvas.dataset.h;
    const series = (((history[mid] || {})[h]) || []).map((p) => p.value).filter((x) => x != null);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (series.length < 2) return;
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || 1;
    const favor = Number(canvas.dataset.favor || 0);
    ctx.strokeStyle = favor > 0 ? "#3dd68c" : favor < 0 ? "#ff5d73" : "#f6d365";
    ctx.beginPath();
    series.forEach((val, i) => {
      const x = (i / (series.length - 1)) * (canvas.width - 2) + 1;
      const y = canvas.height - 1 - ((val - min) / span) * (canvas.height - 4);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

window.pumpLab = {
  initPumpLabTab,
  onPumpLabBoard,
  onTab() {
    initPumpLabTab();
    if (plState.board) onPumpLabBoard(plState.board);
    else fetch("/api/pump-lab/board").then((r) => r.json()).then(onPumpLabBoard).catch(() => {});
  },
};
