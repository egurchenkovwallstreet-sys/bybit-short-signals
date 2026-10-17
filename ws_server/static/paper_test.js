/* Вкладка «Тест стратегии»: виртуальные шорты после пампа. Данные считает сервер. */
(() => {
  const paper = {
    data: null,
    closed: [],
    history: [],
    selected: null, // {type: "open"|"closed"|"cand", id}
    variant: "t20",
    period: "all",
    closedVariant: "",
    interval: "15",
    chart: null,
    series: null,
    lines: [],
    equityChart: null,
    equityOn: {},
    lastListFetch: 0,
    chartKey: "",
  };

  const KIND = { short: "Короткий", long: "Длинный" };
  const TRIGGER = { "4h": "≤4 ч", "24h": "24 ч", "7d": "7 д", "14d": "14 д" };
  const EXIT = { trailing_stop: "Трейлинг-стоп", liquidation: "Ликвидация" };
  const SCORE_PARTS = {
    ema: "Пробои EMA",
    double_top: "Двойная вершина",
    round_level: "Круглый уровень",
    long_liq: "Ликвидации лонгов",
    oi_1h: "Падение OI 1 ч",
    oi_4h: "Падение OI 4 ч",
    funding: "Funding",
    btc_down: "BTC падает",
    short_liq_90: "Ликв. шортов затихли ≥90%",
    distribution: "Раздача (объём есть, цена вниз)",
    strong_top: "Сильная двойная вершина",
  };
  const VARIANT_COLORS = { t20: "#5dade2", p10: "#c084fc", mln: "#4cc9f0", t20p: "#1d4e89", p10p: "#6d28d9", mlnp: "#0e7490", lt20: "#3ddc84", css: "#f5a623", css2: "#e8c547", sc10: "#00c2c7", e5s: "#ff6b8a", e5p: "#ffb703", c3: "#ff8c42", mt1: "#2ec4b6", mt2: "#e76f51", mt2c: "#d62828", graf: "#f94144", dps: "#577590", pyl: "#43aa8b", vac: "#e9c46a", vps15: "#2a9d8f", vps5: "#48cae4", vps: "#2a9d8f", i5: "#9b5de5", i15: "#f15bb5" };
  const PLUS_VARIANTS = { t20p: true, p10p: true, mlnp: true };
  const MINI_VARIANTS = { mt1: true, mt2: true };
  const MINI_CHART_VARIANTS = { mt2c: true };
  const GRAF_VARIANTS = { graf: true };
  const DPS_VARIANTS = { dps: true };
  const PYL_VARIANTS = { pyl: true };
  const VAC_VARIANTS = { vac: true };
  const VPS_VARIANTS = { vps15: true, vps5: true, vps: true };
  function vpsChartInterval(v) {
    if (v === "vps5") return "5";
    return "15";
  }
  function vpsWatchRows() {
    if (!paper.data) return [];
    if (paper.variant === "vps5") return paper.data.vps5_watch || [];
    if (paper.variant === "vps15" || paper.variant === "vps") return paper.data.vps15_watch || [];
    return [];
  }
  const SCAN5_VARIANTS = { pyl: true, vac: true };
  const IMPULSE_VARIANTS = { i5: true, i15: true };
  const INTERVALS = [["5", "5m"], ["15", "15m"], ["60", "1H"], ["240", "4H"]];

  function esc(v) {
    return String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }
  function num(v, d = 2) {
    if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "—";
    return Number(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function price(v) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    const abs = Math.abs(n);
    const d = abs >= 1000 ? 2 : abs >= 1 ? 4 : abs >= 0.01 ? 6 : 8;
    return n.toFixed(d);
  }
  function pct(v, d = 2) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    return `<span class="${n > 0 ? "pos" : n < 0 ? "neg" : ""}">${n > 0 ? "+" : ""}${num(n, d)}%</span>`;
  }
  function usd(v, d = 2) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    return `<span class="${n > 0 ? "pos" : n < 0 ? "neg" : ""}">${n > 0 ? "+" : ""}$${num(n, d)}</span>`;
  }
  function plainUsd(v) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Math.abs(n) >= 1e6) return `$${num(n / 1e6, 2)} млн`;
    if (Math.abs(n) >= 1e3) return `$${num(n / 1e3, 1)} тыс`;
    return `$${num(n, 0)}`;
  }
  function time(ts) {
    if (!ts) return "—";
    return new Date(Number(ts)).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function dur(min) {
    if (min === null || min === undefined) return "—";
    const m = Math.round(Number(min));
    if (m < 60) return `${m} мин`;
    if (m < 48 * 60) return `${Math.floor(m / 60)} ч ${m % 60} мин`;
    return `${Math.floor(m / 1440)} д ${Math.floor((m % 1440) / 60)} ч`;
  }
  function pumpLine(p) {
    if (!p) return "—";
    if (p.kind === "growth" || p.anchor_price !== undefined) {
      return `Рост: +${num(p.rally_pct ?? p.growth_pct, 1)}% от ${price(p.anchor_price ?? p.valley_price)}`;
    }
    if (p.kind === "css2") {
      return `Курсор СС 2: +${num(p.growth_pct, 1)}% от ${price(p.valley_price)} → ${price(p.peak_price)}`;
    }
    if (p.kind === "impulse") {
      const dir = p.side === "long" ? "лонг" : p.side === "short" ? "шорт" : "";
      return `Импульс ${p.trigger || ""}: ${dir} ${num(p.growth_pct, 2)}%`;
    }
    if (p.kind === "css" || p.trigger === "fast") {
      return `Cursor SS: +${num(p.growth_pct, 1)}% от ${price(p.valley_price)} → ${price(p.peak_price)}`;
    }
    if (p.kind === "sc10" || (p.side && (p.kind || "").startsWith("sc10"))) {
      return `Скальп 10: ${p.side === "short" ? "шорт" : "лонг"} пробой 1м`;
    }
    if (p.kind === "vps15" || p.kind === "vps5" || p.kind === "vps") {
      const tf = p.trigger || (p.kind === "vps5" ? "5" : "15");
      const dir = p.side === "long" ? "лонг" : p.side === "short" ? "шорт" : "pivot";
      return `Пылесос ${tf}m: ${dir}`;
    }
    if (p.growth_pct === undefined) return "—";
    return `${KIND[p.kind] || p.kind}: +${num(p.growth_pct, 1)}% за ${dur(p.duration_min)} (окно ${TRIGGER[p.trigger] || p.trigger || "?"})`;
  }
  function labels() {
    if (!paper.data) return {};
    if (paper.variant === "lt20") return paper.data.growth_check_labels || {};
    if (paper.variant === "css") return paper.data.css_check_labels || {};
    if (paper.variant === "css2") return paper.data.css2_check_labels || {};
    if (paper.variant === "sc10") return paper.data.sc10_check_labels || {};
    if (paper.variant === "e5s" || paper.variant === "e5p") return paper.data.e5s_check_labels || {};
    if (paper.variant === "c3") return paper.data.c3_check_labels || {};
    if (PYL_VARIANTS[paper.variant]) return paper.data.pyl_check_labels || {};
    if (VAC_VARIANTS[paper.variant]) return paper.data.vac_check_labels || {};
    if (VPS_VARIANTS[paper.variant]) return paper.data.vps_check_labels || {};
    if (DPS_VARIANTS[paper.variant]) return paper.data.dps_check_labels || {};
    if (GRAF_VARIANTS[paper.variant]) return paper.data.graf_check_labels || {};
    if (MINI_CHART_VARIANTS[paper.variant]) return paper.data.mini_chart_check_labels || {};
    if (MINI_VARIANTS[paper.variant]) return paper.data.mini_check_labels || {};
    if (IMPULSE_VARIANTS[paper.variant]) return paper.data.impulse_check_labels || {};
    if (PLUS_VARIANTS[paper.variant]) return paper.data.plus_check_labels || {};
    return paper.data.check_labels || {};
  }
  function mandatory() {
    if (!paper.data) return [];
    if (paper.variant === "lt20") return paper.data.growth_mandatory || [];
    if (paper.variant === "css") return paper.data.css_mandatory || [];
    if (paper.variant === "css2") return paper.data.css2_mandatory || [];
    if (paper.variant === "sc10") return paper.data.sc10_mandatory || [];
    if (paper.variant === "e5s" || paper.variant === "e5p") return paper.data.e5s_mandatory || [];
    if (paper.variant === "c3") return paper.data.c3_mandatory || [];
    if (PYL_VARIANTS[paper.variant]) return paper.data.pyl_mandatory || [];
    if (VAC_VARIANTS[paper.variant]) return paper.data.vac_mandatory || [];
    if (VPS_VARIANTS[paper.variant]) return paper.data.vps_mandatory || [];
    if (DPS_VARIANTS[paper.variant]) return paper.data.dps_mandatory || [];
    if (GRAF_VARIANTS[paper.variant]) return paper.data.graf_mandatory || [];
    if (MINI_CHART_VARIANTS[paper.variant]) return paper.data.mini_chart_mandatory || [];
    if (MINI_VARIANTS[paper.variant]) return paper.data.mini_mandatory || [];
    if (paper.variant === "i5") {
      return (paper.data.impulse_mandatory || []).concat(paper.data.impulse5_mandatory || []);
    }
    if (IMPULSE_VARIANTS[paper.variant]) return paper.data.impulse_mandatory || [];
    if (PLUS_VARIANTS[paper.variant]) return paper.data.plus_mandatory || [];
    return paper.data.mandatory || [];
  }
  const TABLE_HIDDEN = { lt20: true, sc10: true };
  function variants() {
    return (paper.data && paper.data.variants) || ["t20", "p10", "t20p", "mlnp", "mt2", "graf"];
  }
  function variantProfit(v) {
    const start = ((paper.data && paper.data.summary) || {}).start_balance || 1000;
    const a = account(v);
    const t = vstats(v).trades || {};
    const equity = a.equity != null ? a.equity : a.balance != null ? a.balance : t.balance != null ? t.balance : start;
    return Number(equity) - start;
  }
  function tableVariants() {
    const all = variants();
    return all
      .filter((v) => !TABLE_HIDDEN[v])
      .slice()
      .sort((a, b) => variantProfit(b) - variantProfit(a) || all.indexOf(a) - all.indexOf(b));
  }
  function candEval(r) {
    const ev = (r && r.eval) || {};
    if (paper.variant === "e5s" || paper.variant === "e5p") return ev.e5s || ev;
    if (paper.variant === "c3") return ev.c3 || { checks: {}, passed_count: undefined, failed: [] };
    if (PYL_VARIANTS[paper.variant]) return ev.pyl || { checks: {}, passed_count: undefined, failed: [] };
    if (VAC_VARIANTS[paper.variant]) return ev.vac || { checks: {}, passed_count: undefined, failed: [] };
    if (VPS_VARIANTS[paper.variant]) {
      const v = paper.variant === "vps" ? "vps15" : paper.variant;
      return ev[v] || { checks: {}, passed_count: undefined, failed: [] };
    }
    if (DPS_VARIANTS[paper.variant]) return ev.dps || { checks: {}, passed_count: undefined, failed: [] };
    if (GRAF_VARIANTS[paper.variant]) return ev.graf || { checks: {}, passed_count: undefined, failed: [] };
    if (MINI_CHART_VARIANTS[paper.variant]) return ev.mini_chart || { checks: {}, passed_count: undefined, failed: [] };
    if (MINI_VARIANTS[paper.variant]) return ev.mini || { checks: {}, passed_count: undefined, failed: [] };
    if (PLUS_VARIANTS[paper.variant]) return ev.plus || { checks: {}, passed_count: undefined };
    return ev;
  }
  function candidateRows() {
    const rows = (paper.data && paper.data.candidates) || [];
    if (paper.variant === "css") return rows.filter((r) => r.episode === "css");
    if (paper.variant === "css2") return rows.filter((r) => r.episode === "css2");
    if (paper.variant === "lt20") return rows.filter((r) => r.episode === "growth");
    if (paper.variant === "sc10" || IMPULSE_VARIANTS[paper.variant] || SCAN5_VARIANTS[paper.variant] || VPS_VARIANTS[paper.variant]) return [];
    return rows.filter((r) => r.episode !== "css" && r.episode !== "css2" && r.episode !== "sc10" && r.episode !== "growth");
  }
  function vlabel(v) {
    return ((paper.data && paper.data.variant_labels) || {})[v] || v;
  }
  function vbadge(v) {
    return `<span class="paper-vbadge" style="border-color:${VARIANT_COLORS[v] || "#8e9aab"};color:${VARIANT_COLORS[v] || "#8e9aab"}">${esc(vlabel(v))}</span>`;
  }
  function account(v) {
    return (((paper.data && paper.data.summary) || {}).accounts || {})[v] || {};
  }
  function vstats(v) {
    return ((((paper.data && paper.data.analytics) || {}).variants) || {})[v] || {};
  }
  function passedText(ev) {
    if (!ev || ev.passed_count === undefined) return "—";
    return `${ev.passed_count}/${mandatory().length || 9}`;
  }

  // --- данные ---

  function onSnapshot(data) {
    if (!data) return;
    paper.data = data;
    const rows = tableVariants();
    if (rows.length && !rows.includes(paper.variant)) paper.variant = rows[0];
    if (!isVisible()) return;
    render();
  }

  function isVisible() {
    const paperView = document.getElementById("view-paper");
    const balanceView = document.getElementById("view-balance");
    return (paperView && !paperView.hidden) || (balanceView && !balanceView.hidden);
  }

  function balanceVisible() {
    const view = document.getElementById("view-balance");
    return !!(view && !view.hidden);
  }

  async function onTab() {
    if (!paper.data) {
      try {
        const res = await fetch("/api/paper/snapshot");
        if (res.ok) paper.data = await res.json();
      } catch (_err) {
        /* ignore */
      }
    }
    await fetchLists(true);
    render();
  }

  async function onBalanceTab() {
    if (!paper.data) {
      try {
        const res = await fetch("/api/paper/snapshot");
        if (res.ok) paper.data = await res.json();
      } catch (_err) {
        /* ignore */
      }
    }
    render();
    requestAnimationFrame(() => paper.equityChart && paper.equityChart.resize());
  }

  async function fetchLists(force) {
    const now = Date.now();
    if (!force && now - paper.lastListFetch < 30000 && paper.closedVariant === paper.variant) return;
    paper.lastListFetch = now;
    const variant = paper.variant;
    try {
      const [closed, hist] = await Promise.all([
        fetch(`/api/paper/trades?status=closed&limit=500&variant=${encodeURIComponent(variant)}`).then((r) => r.json()),
        fetch("/api/paper/candidates?limit=500").then((r) => r.json()),
      ]);
      if (variant !== paper.variant) return;
      paper.closed = closed.rows || [];
      paper.closedVariant = variant;
      paper.history = hist.rows || [];
    } catch (_err) {
      /* ignore */
    }
  }

  function render() {
    renderVariants();
    renderPeriods();
    renderSummary();
    renderEquity();
    renderOpen();
    renderCandidates();
    renderClosed();
    renderBreakdowns();
    renderCandAnalytics();
    renderHistory();
    renderDetail();
    fetchLists(false).then(() => {
      renderClosed();
      renderHistory();
    });
  }

  // --- сводка ---

  function accountResult(a, t, start) {
    const base = Number(start) || 1000;
    const balance = a.balance != null ? Number(a.balance) : t.balance != null ? Number(t.balance) : base;
    const equity = a.equity != null ? Number(a.equity) : balance;
    const total = equity - base;
    const day = Number(t.day_pnl) || 0;
    const pctOf = (amount) => (base ? (amount / base) * 100 : 0);
    return { balance, equity, total, totalPct: pctOf(total), day, dayPct: pctOf(day) };
  }

  function renderVariants() {
    const table = document.getElementById("paper-variants");
    if (!table) return;
    const start = ((paper.data && paper.data.summary) || {}).start_balance || 1000;
    table.innerHTML = `<thead><tr>
      <th>Вариант</th><th>Баланс</th><th>Equity</th><th>Итог P&amp;L</th><th>Сутки P&amp;L</th>
      <th>Закрыто</th><th>Win rate</th><th>PF</th>
      <th>Ср. ROE</th><th>Макс. просадка</th><th>Открыто</th><th>Маржа в работе</th>
    </tr></thead><tbody>${tableVariants()
      .map((v) => {
        const a = account(v);
        const t = vstats(v).trades || {};
        const row = accountResult(a, t, start);
        return `<tr class="clickable${v === paper.variant ? " selected" : ""}" data-variant="${v}">
          <td>${vbadge(v)}</td>
          <td>$${num(row.balance)}</td>
          <td>$${num(row.equity)}</td>
          <td>${usd(row.total)} ${pct(row.totalPct)}</td>
          <td>${usd(row.day)} ${pct(row.dayPct)}${t.day_trades ? `<div class="quiet">${t.day_trades} закр. сегодня</div>` : ""}</td>
          <td>${t.closed ?? 0} (${t.wins ?? 0} / ${t.losses ?? 0})</td>
          <td>${num(t.win_rate ?? 0, 1)}%</td>
          <td>${t.profit_factor ?? "—"}</td>
          <td>${pct(t.avg_roe ?? 0, 1)}</td>
          <td>${num(t.max_drawdown_pct ?? 0)}%</td>
          <td>${a.open_trades ?? t.open ?? 0}</td>
          <td>$${num(a.used_margin ?? 0)}</td>
        </tr>`;
      })
      .join("")}</tbody>`;
    table.querySelectorAll("tr[data-variant]").forEach((tr) => {
      tr.addEventListener("click", () => {
        if (paper.variant === tr.dataset.variant) return;
        paper.variant = tr.dataset.variant;
        if (VPS_VARIANTS[paper.variant]) paper.interval = vpsChartInterval(paper.variant);
        if (paper.selected && (paper.selected.type === "open" || paper.selected.type === "closed")) {
          paper.selected = null;
          paper.chartKey = "";
        }
        render();
        fetchLists(true).then(() => {
          renderClosed();
          renderHistory();
        });
      });
    });
  }

  function emptySlice() {
    return { n: 0, wins: 0, win_pct: null, profit: 0, loss: 0, net: 0, base: 0, profit_pct: 0, loss_pct: 0, net_pct: 0 };
  }

  function withPct(profit, loss, base) {
    const net = profit + loss;
    const pctOf = (amount) => (base ? Math.round((amount / base) * 10000) / 100 : 0);
    return { profit, loss, net, base, profit_pct: pctOf(profit), loss_pct: pctOf(loss), net_pct: pctOf(net) };
  }

  function liveSlice(variant) {
    const pnls = ((paper.data && paper.data.open_trades) || [])
      .filter((r) => r.variant === variant)
      .map((r) => Number(r.pnl_usd) || 0);
    const wins = pnls.filter((p) => p > 0);
    const losses = pnls.filter((p) => p < 0);
    const profit = wins.reduce((acc, p) => acc + p, 0);
    const loss = losses.reduce((acc, p) => acc + p, 0);
    const base = ((paper.data && paper.data.summary) || {}).start_balance || 1000;
    return {
      n: pnls.length,
      wins: wins.length,
      win_pct: pnls.length ? Math.round((wins.length / pnls.length) * 1000) / 10 : null,
      ...withPct(profit, loss, base),
    };
  }

  function sumSlices(rows) {
    const n = rows.reduce((acc, s) => acc + (s.n || 0), 0);
    const wins = rows.reduce((acc, s) => acc + (s.wins || 0), 0);
    const profit = rows.reduce((acc, s) => acc + (s.profit || 0), 0);
    const loss = rows.reduce((acc, s) => acc + (s.loss || 0), 0);
    const base = rows.reduce((acc, s) => acc + (Number(s.base) || 0), 0);
    return {
      n,
      wins,
      win_pct: n ? Math.round((wins / n) * 1000) / 10 : null,
      ...withPct(profit, loss, base),
    };
  }

  function moneyPct(amount, percent) {
    return `${usd(amount || 0)} ${pct(percent || 0)}`;
  }

  function periodCells(slice) {
    const row = slice || emptySlice();
    if (!row.n) return ["0", "—", moneyPct(0, 0), moneyPct(0, 0), moneyPct(0, 0)];
    const wr = row.win_pct === null || row.win_pct === undefined ? "—" : `${num(row.win_pct, 1)}%`;
    return [String(row.n), wr, moneyPct(row.profit, row.profit_pct), moneyPct(row.loss, row.loss_pct), moneyPct(row.net, row.net_pct)];
  }

  function renderPeriods() {
    const row = document.getElementById("paper-period-row");
    const table = document.getElementById("paper-periods");
    const note = document.getElementById("paper-period-note");
    if (!row || !table) return;
    const analytics = (paper.data && paper.data.analytics) || {};
    const labels = analytics.period_labels || {
      all: "Всё время",
      month: "Месяц",
      week: "Неделя",
      yesterday: "Вчера",
      now: "Сейчас открытые",
    };
    const keys = ["all", "month", "week", "yesterday", "now"];
    if (!keys.includes(paper.period)) paper.period = "all";
    const notes = {
      all: "Все закрытые сделки живых стратегий. Прибыль, убыток и итог — в процентах от стартовых $1000.",
      month: "Закрытые с 1-го числа текущего месяца, 00:00 МСК. Процент от стартовых $1000.",
      week: "Закрытые с полуночи МСК семь суток назад. Процент от стартовых $1000.",
      yesterday: "Закрытые за полные предыдущие сутки, 00:00–24:00 МСК. Процент от стартовых $1000.",
      now: "Открытые позиции. Плавающий результат в процентах от стартовых $1000.",
    };
    if (note) {
      const stamp = analytics.period_as_of ? ` Снимок ${analytics.period_as_of} МСК.` : "";
      note.textContent = `${notes[paper.period]}${stamp}`;
    }
    row.innerHTML = keys
      .map(
        (key) =>
          `<button type="button" class="paper-btn${paper.period === key ? " active" : ""}" data-period="${key}">${esc(labels[key] || key)}</button>`,
      )
      .join("");
    row.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        paper.period = btn.dataset.period;
        renderPeriods();
      });
    });
    const slices = variants().map((variant) => ({
      variant,
      slice: paper.period === "now" ? liveSlice(variant) : (vstats(variant).periods || {})[paper.period] || emptySlice(),
    }));
    const total = sumSlices(slices.map((item) => item.slice));
    table.innerHTML = `<thead><tr>
      <th>Стратегия</th><th>Сделок</th><th>В плюсе</th><th>Прибыль</th><th>Убыток</th><th>Итог</th>
    </tr></thead><tbody>${slices
      .map(
        (item) => `<tr>
        <td>${vbadge(item.variant)}</td>
        ${periodCells(item.slice).map((cell) => `<td>${cell}</td>`).join("")}
      </tr>`,
      )
      .join("")}<tr class="paper-total"><td>Все вместе</td>${periodCells(total).map((cell) => `<td>${cell}</td>`).join("")}</tr></tbody>`;
  }

  function renderSummary() {
    const root = document.getElementById("paper-summary");
    if (!root) return;
    const title = document.getElementById("paper-variant-title");
    if (title) title.innerHTML = `Вариант: ${vbadge(paper.variant)}`;
    const s = (paper.data && paper.data.summary) || {};
    const a = account(paper.variant);
    const t = vstats(paper.variant).trades || {};
    const start = s.start_balance || 1000;
    const row = accountResult(a, t, start);
    const cards = [
      ["Баланс", `$${num(row.balance)}`, `старт $${num(start, 0)}`],
      ["Equity", `$${num(row.equity)}`, `плавающий ${usd(a.unrealized ?? 0)}`],
      ["Открыто сделок", a.open_trades ?? 0, `маржа в работе $${num(a.used_margin ?? 0)}`],
      ["Закрыто сделок", t.closed ?? 0, `${t.wins ?? 0} в плюс · ${t.losses ?? 0} в минус`],
      ["Win rate", `${num(t.win_rate ?? 0, 1)}%`, `PF ${t.profit_factor ?? "—"}`],
      ["Итог P&L", `${usd(row.total)} ${pct(row.totalPct)}`, `счёт минус старт $${num(start, 0)} · ср. ROE ${num(t.avg_roe ?? 0, 1)}%`],
      ["Сутки P&L (МСК)", `${usd(row.day)} ${pct(row.dayPct)}`, `от старта $${num(start, 0)} · закрыто сегодня ${t.day_trades ?? 0}`],
      ["Средняя прибыль", usd(t.avg_win ?? 0), `средний убыток ${usd(t.avg_loss ?? 0)}`],
      ["Макс. просадка", `${num(t.max_drawdown_pct ?? 0)}%`, `лучшая ${usd(t.best ?? 0)} · худшая ${usd(t.worst ?? 0)}`],
      ["Трейлинг / ликвидации", `${t.trailing_wins ?? 0} / ${t.liquidations ?? 0}`, `ср. длительность ${dur(t.avg_duration_min ?? 0)}`],
      ["Комиссии / funding", `$${num(t.fees ?? 0)}`, `funding ${usd(t.funding ?? 0)}`],
      ["Кандидаты", s.candidates ?? 0, `теневых открыто ${s.shadows_open ?? 0}`],
      [
        "BTC за 4 ч",
        s.btc_4h_pct === null || s.btc_4h_pct === undefined ? "—" : pct(s.btc_4h_pct),
        s.btc_strict ? "строгий режим входа" : "обычный режим",
      ],
    ];
    root.innerHTML = cards
      .map(([label, value, sub]) => `<div class="paper-card"><span class="label">${label}</span><div class="value">${value}</div><div class="sub">${sub}</div></div>`)
      .join("");
  }

  function loadEquityOn() {
    try {
      const raw = JSON.parse(localStorage.getItem("paperEquityOn") || "{}");
      if (raw && typeof raw === "object") paper.equityOn = raw;
    } catch (_err) {
      paper.equityOn = {};
    }
  }

  function saveEquityOn() {
    const on = {};
    Object.keys(paper.equityOn).forEach((key) => {
      if (paper.equityOn[key] === true) on[key] = true;
    });
    paper.equityOn = on;
    localStorage.setItem("paperEquityOn", JSON.stringify(on));
  }

  function renderEquityToggles() {
    const row = document.getElementById("paper-equity-toggles");
    if (!row) return;
    row.innerHTML = tableVariants()
      .map((v) => {
        const on = paper.equityOn[v] === true;
        const color = VARIANT_COLORS[v] || "#8e9aab";
        return `<button type="button" class="paper-eq-toggle${on ? " on" : ""}" data-variant="${v}" style="--eq:${color}">${esc(vlabel(v))}</button>`;
      })
      .join("");
    row.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const variant = btn.dataset.variant;
        paper.equityOn[variant] = paper.equityOn[variant] !== true;
        saveEquityOn();
        renderEquity();
      });
    });
  }

  function renderEquity() {
    renderEquityToggles();
    const box = document.getElementById("paper-equity");
    if (!box || typeof echarts === "undefined") return;
    if (!paper.equityChart) {
      if (!balanceVisible()) return;
      paper.equityChart = echarts.init(box, null, { renderer: "canvas" });
    }
    const start = Number(((paper.data && paper.data.summary) || {}).start_balance) || 1000;
    const enabled = tableVariants().filter((v) => paper.equityOn[v] === true);
    let yMin = start;
    let yMax = start;
    let t0 = Infinity;
    let t1 = -Infinity;
    tableVariants().forEach((v) => {
      (vstats(v).equity || []).forEach((row) => {
        const ts = Number(row[0]);
        if (Number.isFinite(ts)) {
          t0 = Math.min(t0, ts);
          t1 = Math.max(t1, ts);
        }
      });
    });
    const series = enabled.map((v) => {
      const rows = vstats(v).equity || [];
      const color = VARIANT_COLORS[v] || "#8e9aab";
      rows.forEach((row) => {
        const value = Number(row[2]);
        if (!Number.isFinite(value)) return;
        yMin = Math.min(yMin, value);
        yMax = Math.max(yMax, value);
      });
      return {
        name: vlabel(v),
        type: "line",
        showSymbol: false,
        data: rows.map((row) => [row[0], row[2]]),
        lineStyle: { color, width: 1.6 },
        itemStyle: { color },
      };
    });
    if (!Number.isFinite(t0) || !Number.isFinite(t1)) {
      t1 = Date.now();
      t0 = t1 - 3_600_000;
    }
    if (t0 === t1) t1 = t0 + 60_000;
    series.push({
      name: "Старт",
      type: "line",
      silent: true,
      showSymbol: false,
      data: [[t0, start], [t1, start]],
      lineStyle: { color: "#f3d27a", width: 1.5 },
      itemStyle: { color: "#f3d27a" },
      tooltip: { show: false },
      z: 10,
    });
    const pad = Math.max((yMax - yMin) * 0.08, 20);
    paper.equityChart.setOption(
      {
        backgroundColor: "transparent",
        grid: { left: 64, right: 24, top: 24, bottom: 32 },
        tooltip: {
          trigger: "axis",
          formatter(params) {
            const rows = (Array.isArray(params) ? params : [params]).filter((item) => item.seriesName !== "Старт");
            if (!rows.length) return "";
            const lines = rows.map((item) => {
              const value = Array.isArray(item.value) ? item.value[1] : item.value;
              return `${item.marker}${item.seriesName}: ${Number(value).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            });
            return [`${rows[0].axisValueLabel || ""}`, ...lines].join("<br>");
          },
        },
        legend: { show: false },
        xAxis: { type: "time", axisLabel: { color: "#8e9aab" } },
        yAxis: {
          type: "value",
          min: yMin - pad,
          max: yMax + pad,
          axisLabel: { color: "#8e9aab" },
          splitLine: { lineStyle: { color: "#2c3544" } },
        },
        series,
      },
      true,
    );
    if (balanceVisible()) paper.equityChart.resize();
  }

  // --- таблицы ---

  function bindRows(table, type) {
    table.querySelectorAll("tr[data-id]").forEach((tr) => {
      tr.addEventListener("click", () => {
        const id = Number(tr.dataset.id);
        const same = paper.selected && paper.selected.type === type && paper.selected.id === id;
        paper.selected = same ? null : { type, id };
        paper.chartKey = "";
        render();
        if (!same) document.getElementById("paper-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function isSel(type, id) {
    return paper.selected && paper.selected.type === type && paper.selected.id === id ? " selected" : "";
  }

  function renderOpen() {
    const table = document.getElementById("paper-open-table");
    if (!table) return;
    const rows = ((paper.data && paper.data.open_trades) || []).filter((r) => r.variant === paper.variant);
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Открытых сделок в этом варианте нет.</td></tr></tbody>';
      return;
    }
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>Условий</th><th>Вход</th><th>Цена входа</th><th>Текущая</th><th>Изм. цены</th>
      <th>Стоп</th><th>Лучшая</th><th>ROE</th><th>P&amp;L</th><th>Макс. ROE</th><th>Маржа</th><th>Funding</th><th>Сила</th><th>В сделке</th>
    </tr></thead><tbody>${rows
      .map(
        (r) => `<tr class="clickable${isSel("open", r.id)}" data-id="${r.id}">
        <td><b>${esc(r.symbol)}</b></td>
        <td>${pumpLine(r.pump)}</td>
        <td>${passedText(r.entry)}</td>
        <td>${time(r.opened_at)}</td>
        <td>${price(r.entry_price)}</td>
        <td>${price(r.last_price)}</td>
        <td>${pct(r.price_change_pct)}</td>
        <td>${price(r.stop_price)}</td>
        <td>${price(r.best_price)}</td>
        <td>${pct(r.roe_pct, 1)}</td>
        <td>${usd(r.pnl_usd)}</td>
        <td>${pct(r.max_roe, 1)}</td>
        <td>$${num(r.margin)}</td>
        <td>${usd(r.funding_paid, 4)}</td>
        <td class="grade-${r.grade}">${r.grade} · ${num(r.score, 1)}</td>
        <td>${dur(r.duration_min)}</td>
      </tr>`,
      )
      .join("")}</tbody>`;
    bindRows(table, "open");
  }

  function checkDots(ev) {
    const checks = (ev && ev.checks) || {};
    return `<span class="paper-checks">${mandatory()
      .map((key) => {
        const c = checks[key];
        return `<span class="paper-check${c && c.ok ? " ok" : ""}" title="${esc(labels()[key] || key)}"></span>`;
      })
      .join("")}</span>`;
  }

  function renderCandidates() {
    const section = document.getElementById("paper-cand-section");
    if (section) section.hidden = paper.variant === "sc10" || !!IMPULSE_VARIANTS[paper.variant];
    const table = document.getElementById("paper-cand-table");
    if (!table) return;
    if (VPS_VARIANTS[paper.variant]) {
      if (section) section.hidden = false;
      const candNote = document.querySelector("#paper-cand-section .quiet");
      if (candNote) {
        candNote.textContent =
          `${vpsChartInterval(paper.variant)}m: новый pivot-max → шорт, новый pivot-min → лонг (без сравнения с прошлым уровнем). Одна сделка до нового сигнала. Стоп −10% ROE, трейл − 10 п.п.`;
      }
      const tf = vpsChartInterval(paper.variant);
      const rows = vpsWatchRows();
      const total = mandatory().length;
      if (!rows.length) {
        table.innerHTML =
          `<tbody><tr><td class="quiet">Нет сигналов: ждём новый pivot ${tf}m (max → шорт, min → лонг).</td></tr></tbody>`;
        return;
      }
      table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Условия</th><th>Не хватает</th><th>Сторона</th><th>Pivot</th><th>Готово</th><th>Сила</th>
    </tr></thead><tbody>${rows
        .map((r) => {
          const vk = paper.variant === "vps" ? "vps15" : paper.variant;
          const ev = (r.eval && r.eval[vk]) || {};
          const m = ev.metrics || {};
          const failed = (r.failed || []).map((k) => labels()[k] || k);
          const side = r.side || m.side;
          return `<tr class="clickable" data-vps-symbol="${esc(r.symbol)}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${checkDots(ev)} ${r.passed_count}/${total}</td>
          <td>${esc(failed.join(", ") || "—")}</td>
          <td>${side === "long" ? "лонг" : side === "short" ? "шорт" : "—"}</td>
          <td>${m.pivot_time_ms ? `${time(m.pivot_time_ms)} · ${price(m.pivot_price)}` : "—"}</td>
          <td>${r.ready ? "да" : "нет"}</td>
          <td class="grade-${r.grade || "C"}">${r.grade || "—"} · ${num(r.score, 1)}</td>
        </tr>`;
        })
        .join("")}</tbody>`;
      table.querySelectorAll("tr[data-vps-symbol]").forEach((tr) => {
        tr.addEventListener("click", () => {
          const sym = tr.dataset.vpsSymbol;
          const row = rows.find((x) => x.symbol === sym);
          if (!row) return;
          paper.selected = { type: "vps_watch", symbol: sym, row };
          paper.interval = vpsChartInterval(paper.variant);
          paper.chartKey = "";
          render();
          document.getElementById("paper-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
      return;
    }
    if (VAC_VARIANTS[paper.variant]) {
      if (section) section.hidden = false;
      const rows = (paper.data && paper.data.vac_watch) || [];
      const total = mandatory().length;
      if (!rows.length) {
        table.innerHTML =
          '<tbody><tr><td class="quiet">Нет претендентов: ждём A→C→B на 5m или триггер входа.</td></tr></tbody>';
        return;
      }
      table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Условия</th><th>Не хватает</th><th>B</th><th>После B</th><th>Готово</th><th>Сила</th>
    </tr></thead><tbody>${rows
        .map((r) => {
          const ev = (r.eval && r.eval.vac) || {};
          const m = ev.metrics || {};
          const failed = (r.failed || []).map((k) => labels()[k] || k);
          return `<tr class="clickable" data-vac-symbol="${esc(r.symbol)}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${checkDots(ev)} ${r.passed_count}/${total}</td>
          <td>${esc(failed.join(", ") || "—")}</td>
          <td>${time(m.b_ts)}</td>
          <td>${m.b_ts ? time(m.b_ts) : "—"}</td>
          <td>${r.ready ? "да" : "нет"}</td>
          <td class="grade-${r.grade || "C"}">${r.grade || "—"} · ${num(r.score, 1)}</td>
        </tr>`;
        })
        .join("")}</tbody>`;
      return;
    }
    if (PYL_VARIANTS[paper.variant]) {
      if (section) section.hidden = false;
      const rows = (paper.data && paper.data.pyl_watch) || [];
      const total = mandatory().length;
      if (!rows.length) {
        table.innerHTML =
          '<tbody><tr><td class="quiet">Нет претендентов: на 15m пока нет пары pivot-вершин с lower high.</td></tr></tbody>';
        return;
      }
      table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Условия</th><th>Не хватает</th><th>V₂ high</th><th>Смещение</th><th>Готово</th><th>Сила</th>
    </tr></thead><tbody>${rows
        .map((r) => {
          const ev = (r.eval && r.eval.pyl) || {};
          const m = ev.metrics || {};
          const failed = (r.failed || []).map((k) => labels()[k] || k);
          return `<tr class="clickable" data-pyl-symbol="${esc(r.symbol)}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${checkDots(ev)} ${r.passed_count}/${total}</td>
          <td>${esc(failed.join(", ") || "—")}</td>
          <td>${price(m.vertex_high)}</td>
          <td>${m.offset_bars != null ? m.offset_bars + "×15m" : "—"}</td>
          <td>${r.ready ? "да" : "нет"}</td>
          <td class="grade-${r.grade || "C"}">${r.grade || "—"} · ${num(r.score, 1)}</td>
        </tr>`;
        })
        .join("")}</tbody>`;
      return;
    }
    const rows = candidateRows();
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Сейчас нет монет после пампа по условиям стратегии.</td></tr></tbody>';
      return;
    }
    const total = mandatory().length;
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>С пика</th><th>Диапазон</th><th>Объём ×</th><th>Покупки на росте</th>
      <th>Продажи 5/10/15м</th><th>OI 1ч / 4ч</th><th>Funding</th><th>Условия</th><th>Не хватает</th>
      <th>Вершина</th><th>Подходит / в сделке</th><th>Сила</th><th>Тень</th>
    </tr></thead><tbody>${rows
      .map((r) => {
        const ev = candEval(r);
        const m = ev.metrics || {};
        const p = r.pump || {};
        const ss = m.sell_share || {};
        const gateLabels = (paper.data && paper.data.entry_gate_labels) || {};
        const blocked = (ev.entry_blocked || []).map((k) => gateLabels[k] || k);
        const failed = (ev.failed || []).map((k) => labels()[k] || k);
        const passed = ev.passed_count ?? total - (ev.failed || mandatory()).length;
        const sh = r.shadow ? `${pct(r.shadow.roe_pct, 1)}` : "—";
        const st = m.strong_top;
        const fits = (ev.variants || []).map(vbadge).join(" ") || "—";
        const inTrade = (r.open_in || []).map(vbadge).join(" ");
        return `<tr class="clickable${isSel("cand", r.id)}" data-id="${r.id}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${pumpLine(p)}</td>
          <td>${dur(m.since_peak_min)}</td>
          <td>${m.range_pct === null || m.range_pct === undefined ? "—" : num(m.range_pct, 1) + "%"}</td>
          <td>${p.volume_ratio === null || p.volume_ratio === undefined ? "—" : "×" + num(p.volume_ratio, 1)}</td>
          <td>${p.buy_share_pct === null || p.buy_share_pct === undefined ? `нет ленты (${p.tape_minutes || 0} мин)` : num(p.buy_share_pct, 1) + "%"}</td>
          <td>${[ss["5m"], ss["10m"], ss["15m"]].map((v) => (v === null || v === undefined ? "—" : num(v, 0))).join(" / ")}</td>
          <td>${pct(m.oi_1h_pct)} / ${pct(m.oi_4h_pct)}</td>
          <td>${m.funding_rate === null || m.funding_rate === undefined ? "—" : num(m.funding_rate * 100, 4) + "%"}</td>
          <td>${checkDots(ev)} ${passed}/${total}</td>
          <td>${esc(paper.variant === "c3" || MINI_VARIANTS[paper.variant] ? (failed.join(", ") || "—") : (r.note || blocked.join(", ") || failed.join(", ") || "—"))}</td>
          <td>${st ? `${st.interval === "60" ? "1H" : "30m"} −${num(st.diff_pct, 1)}%` : "—"}</td>
          <td>${fits}${inTrade ? `<br><span class="quiet">в сделке:</span> ${inTrade}` : ""}</td>
          <td class="grade-${ev.grade || "C"}">${ev.grade || "—"} · ${num(ev.score, 1)}</td>
          <td>${sh}</td>
        </tr>`;
      })
      .join("")}</tbody>`;
    bindRows(table, "cand");
  }

  function renderClosed() {
    const table = document.getElementById("paper-closed-table");
    if (!table) return;
    const rows = paper.closedVariant === paper.variant ? paper.closed || [] : [];
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Закрытых сделок в этом варианте пока нет.</td></tr></tbody>';
      return;
    }
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>Условий</th><th>Вход</th><th>Выход</th><th>Цена входа</th><th>Цена выхода</th><th>Причина</th>
      <th>ROE</th><th>P&amp;L</th><th>Макс. ROE</th><th>Мин. ROE</th><th>Комиссии</th><th>Funding</th><th>Сила</th><th>Баланс после</th>
    </tr></thead><tbody>${rows
      .map((r) => {
        const p = ((r.entry || {}).metrics || {}).pump || {};
        return `<tr class="clickable${isSel("closed", r.id)}" data-id="${r.id}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${pumpLine(p)}</td>
          <td>${passedText(r.entry)}</td>
          <td>${time(r.opened_at)}</td>
          <td>${time(r.closed_at)} (${dur((r.closed_at - r.opened_at) / 60000)})</td>
          <td>${price(r.entry_price)}</td>
          <td>${price(r.exit_price)}</td>
          <td>${EXIT[r.exit_reason] || esc(r.exit_reason)}</td>
          <td>${pct(r.roe_pct, 1)}</td>
          <td>${usd(r.pnl_usd)}</td>
          <td>${pct(r.max_roe, 1)}</td>
          <td>${pct(r.min_roe, 1)}</td>
          <td>$${num((r.entry_fee || 0) + (r.exit_fee || 0), 4)}</td>
          <td>${usd(r.funding_paid, 4)}</td>
          <td class="grade-${r.grade}">${r.grade || "—"} · ${num(r.score, 1)}</td>
          <td>$${num(r.balance_after)}</td>
        </tr>`;
      })
      .join("")}</tbody>`;
    bindRows(table, "closed");
  }

  function groupTable(title, rows) {
    if (!rows || !rows.length) return `<div><h4>${title}</h4><p class="quiet">нет данных</p></div>`;
    return `<div><h4>${title}</h4><table class="paper-table"><thead><tr><th></th><th>Сделок</th><th>Win%</th><th>P&amp;L</th></tr></thead><tbody>${rows
      .map((r) => `<tr><td>${esc(r.label)}</td><td>${r.count}</td><td>${num(r.win_rate, 1)}%</td><td>${usd(r.pnl)}</td></tr>`)
      .join("")}</tbody></table></div>`;
  }

  function renderBreakdowns() {
    const root = document.getElementById("paper-breakdowns");
    if (!root) return;
    const a = vstats(paper.variant);
    root.innerHTML = [
      groupTable("По числу условий при входе", a.by_passed),
      groupTable("По причине выхода", a.by_reason),
      groupTable("По типу пампа", a.by_kind),
      groupTable("По окну роста", a.by_trigger),
      groupTable("По силе сигнала", a.by_grade),
      groupTable("По режиму BTC", a.by_btc),
    ].join("");
  }

  function renderCandAnalytics() {
    const section = document.getElementById("paper-cand-analytics-section");
    if (section) section.hidden = paper.variant === "sc10" || !!IMPULSE_VARIANTS[paper.variant];
    const root = document.getElementById("paper-cand-analytics");
    if (!root) return;
    const c = ((paper.data && paper.data.analytics) || {}).candidates || {};
    const st = c.by_status || {};
    const L = labels();
    let html = `<p>Всего кандидатов: <b>${c.total || 0}</b> · ведутся: ${st.watching || 0} · закончились со входом: ${st.entered || 0} · без входа ни в одном варианте: ${st.expired || 0}</p>`;
    const blockers = Object.entries(c.blockers || {});
    const failRate = c.fail_rate || {};
    html += `<h4>Какие условия не выполнялись</h4><table class="paper-table"><thead><tr><th>Условие</th><th>Блокировало в конце (кандидатов)</th><th>Не выполнялось, % проверок</th></tr></thead><tbody>${mandatory()
      .map((key) => {
        const b = (blockers.find(([k]) => k === key) || [key, 0])[1];
        return `<tr><td>${esc(L[key] || key)}</td><td>${b}</td><td>${failRate[key] === undefined ? "—" : num(failRate[key], 1) + "%"}</td></tr>`;
      })
      .join("")}</tbody></table>`;
    const shadows = c.shadows || [];
    html += `<h4>Теневые сделки (маржа $${num(c.shadow_margin || 50, 0)}, те же правила выхода)</h4>`;
    if (!shadows.length) {
      html += '<p class="quiet">Теневых сделок пока нет.</p>';
    } else {
      html += `<table class="paper-table"><thead><tr><th>Не хватало условия</th><th>Всего</th><th>Закрыто</th><th>В плюс</th><th>Win%</th><th>Ср. ROE</th><th>P&amp;L</th><th>Позже вошли</th></tr></thead><tbody>${shadows
        .map(
          (r) => `<tr><td>${esc(L[r.missing] || r.missing)}</td><td>${r.count}</td><td>${r.closed}</td><td>${r.wins}</td>
            <td>${r.win_rate === null ? "—" : num(r.win_rate, 1) + "%"}</td><td>${r.avg_roe === null ? "—" : pct(r.avg_roe, 1)}</td>
            <td>${usd(r.pnl)}</td><td>${r.entered_later}</td></tr>`,
        )
        .join("")}</tbody></table>`;
    }
    root.innerHTML = html;
  }

  function renderHistory() {
    const table = document.getElementById("paper-cand-history");
    if (!table) return;
    const rows = paper.history || [];
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">История пуста.</td></tr></tbody>';
      return;
    }
    const L = labels();
    const STATUS = { entered: "Вход", expired: "Без входа" };
    table.innerHTML = `<thead><tr><th>Монета</th><th>Памп</th><th>Начало</th><th>Конец</th><th>Итог</th><th>Причина</th>
      <th>Лучшее: условий</th><th>Не хватало в конце</th><th>Тень: не хватало</th><th>Тень: итог</th></tr></thead><tbody>${rows
      .map((r) => {
        const ev = r.last_eval || {};
        const p = (ev.metrics || {}).pump || { kind: r.kind, growth_pct: r.growth_pct, duration_min: (r.peak_ts - r.valley_ts) / 60000 };
        const failed = (ev.failed || []).map((k) => L[k] || k).join(", ");
        const shadow =
          r.shadow_status === "closed"
            ? `${pct(r.shadow_roe, 1)} (${EXIT[r.shadow_exit_reason] || r.shadow_exit_reason})`
            : r.shadow_status === "open"
              ? "идёт"
              : "—";
        return `<tr class="clickable${isSel("hist", r.id)}" data-id="${r.id}">
          <td><b>${esc(r.symbol)}</b></td><td>${pumpLine(p)}</td><td>${time(r.started_at)}</td><td>${time(r.ended_at)}</td>
          <td>${STATUS[r.status] || esc(r.status)}${(r.variants || []).length ? "<br>" + r.variants.map(vbadge).join(" ") : ""}</td><td>${esc(r.end_reason || "—")}</td>
          <td>${r.best_passed}/${mandatory().length}</td><td>${esc(failed || "—")}</td>
          <td>${esc(L[r.near_miss_missing] || r.near_miss_missing || "—")}</td><td>${shadow}</td>
        </tr>`;
      })
      .join("")}</tbody>`;
    bindRows(table, "hist");
  }

  // --- детальная карточка ---

  function selectedItem() {
    const sel = paper.selected;
    if (!sel || !paper.data) return null;
    if (sel.type === "open") {
      const r = (paper.data.open_trades || []).find((x) => x.id === sel.id);
      return r ? { kind: "trade", live: true, row: r, symbol: r.symbol, ev: r.entry } : null;
    }
    if (sel.type === "closed") {
      const r = (paper.closed || []).find((x) => x.id === sel.id);
      return r ? { kind: "trade", live: false, row: r, symbol: r.symbol, ev: r.entry } : null;
    }
    if (sel.type === "cand") {
      const r = (paper.data.candidates || []).find((x) => x.id === sel.id);
      return r ? { kind: "cand", row: r, symbol: r.symbol, ev: candEval(r) } : null;
    }
    if (sel.type === "hist") {
      const r = (paper.history || []).find((x) => x.id === sel.id);
      return r ? { kind: "hist", row: r, symbol: r.symbol, ev: r.last_eval } : null;
    }
    if (sel.type === "vps_watch") {
      const r = sel.row;
      const vk = paper.variant === "vps" ? "vps15" : paper.variant;
      return r ? { kind: "vps_watch", row: r, symbol: sel.symbol, ev: (r.eval && r.eval[vk]) || {} } : null;
    }
    return null;
  }

  function kv(rows) {
    return `<dl class="paper-kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  }

  function valueText(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") {
      return Object.entries(v)
        .map(([k, x]) => `${esc(k)}: ${x === null || x === undefined ? "—" : typeof x === "number" ? num(x, Math.abs(x) >= 100 ? 0 : 2) : esc(x)}`)
        .join(" · ");
    }
    if (typeof v === "number") return num(v, 2);
    return esc(v);
  }

  function evalHtml(ev) {
    if (!ev || !ev.checks) return '<p class="quiet">Нет данных проверки.</p>';
    const L = labels();
    const m = ev.metrics || {};
    const p = m.pump || {};
    const pylOnly = PYL_VARIANTS[paper.variant] || (p.kind === "pyl" && paper.variant === "pyl");
    const vacOnly = VAC_VARIANTS[paper.variant] || (p.kind === "vac" && paper.variant === "vac");
    const vpsOnly =
      VPS_VARIANTS[paper.variant] ||
      (p.kind === paper.variant && VPS_VARIANTS[paper.variant]) ||
      ((p.kind === "vps15" || p.kind === "vps5") && VPS_VARIANTS[paper.variant]);
    if (vpsOnly) {
      let html = `<h4>Условия: выполнено ${passedText(ev)} · ${esc(vlabel(paper.variant))}</h4><ul class="paper-check-list">`;
      html += mandatory()
        .map((key) => {
          const c = ev.checks[key] || {};
          return `<li class="${c.ok ? "ok" : "fail"}">${c.ok ? "✓" : "✗"} ${esc(L[key] || key)}: <b>${valueText(c.value)}</b><span class="need">нужно: ${esc(c.need || "")}</span></li>`;
        })
        .join("");
      html += "</ul>";
      if (m.pivot_time_ms) {
        html += kv([
          ["Сторона", m.side === "long" ? "лонг" : m.side === "short" ? "шорт" : "—"],
          ["Pivot 15m", `${time(m.pivot_time_ms)} · ${price(m.pivot_price)}`],
          ["Стоп / трейл", "−10% ROE, дальше пик − 10 п.п. ROE"],
        ]);
      }
      return html;
    }
    if (vacOnly) {
      let html = `<h4>Условия: выполнено ${passedText(ev)} · ${esc(vlabel(paper.variant))}</h4><ul class="paper-check-list">`;
      html += mandatory()
        .map((key) => {
          const c = ev.checks[key] || {};
          return `<li class="${c.ok ? "ok" : "fail"}">${c.ok ? "✓" : "✗"} ${esc(L[key] || key)}: <b>${valueText(c.value)}</b><span class="need">нужно: ${esc(c.need || "")}</span></li>`;
        })
        .join("");
      html += "</ul>";
      if (m.b_ts) {
        html += kv([
          ["A / C / B", `${time(m.a_ts)} → ${time(m.c_ts)} → ${time(m.b_ts)}`],
          ["B / вход", `${time(m.b_ts)} → ${time(m.confirm_ts)}`],
          ["Триггер", m.entry_trigger || "—"],
        ]);
      }
      return html;
    }
    if (pylOnly) {
      let html = `<h4>Условия: выполнено ${passedText(ev)} · ${esc(vlabel(paper.variant))}</h4><ul class="paper-check-list">`;
      html += mandatory()
        .map((key) => {
          const c = ev.checks[key] || {};
          return `<li class="${c.ok ? "ok" : "fail"}">${c.ok ? "✓" : "✗"} ${esc(L[key] || key)}: <b>${valueText(c.value)}</b><span class="need">нужно: ${esc(c.need || "")}</span></li>`;
        })
        .join("");
      html += "</ul>";
      if (m.v2_ts) {
        html += kv([
          ["V₁ / V₂", `${time(m.v1_ts)} → ${time(m.v2_ts)}`],
          ["High V₂", price(m.vertex_high)],
          ["Смещение подтверждения", m.offset_bars != null ? `${m.offset_bars}×15m` : "—"],
        ]);
      }
      return html;
    }
    const g = p.growth || {};
    const fits = (ev.variants || []).map(vbadge).join(" ");
    let html = `<h4>Условия: выполнено ${passedText(ev)}${fits ? ` · подходит под ${fits}` : ""}</h4><ul class="paper-check-list">`;
    html += mandatory()
      .map((key) => {
        const c = ev.checks[key] || {};
        return `<li class="${c.ok ? "ok" : "fail"}">${c.ok ? "✓" : "✗"} ${esc(L[key] || key)}: <b>${valueText(c.value)}</b><span class="need">нужно: ${esc(c.need || "")}</span></li>`;
      })
      .join("");
    html += "</ul>";
    html += "<h4>Памп</h4>" + kv([
      ["Тип", `${KIND[p.kind] || "—"} (окно ${TRIGGER[p.trigger] || p.trigger || "—"})`],
      ["Рост", `+${num(p.growth_pct, 1)}% за ${dur(p.duration_min)}`],
      ["Дно → пик", `${price(p.valley_price)} (${time(p.valley_ts)}) → ${price(p.peak_price)} (${time(p.peak_ts)})`],
      ["Рост к пику за 4ч / 24ч / 7д / 14д", ["4h", "24h", "7d", "14d"].map((k) => (g[k] === null || g[k] === undefined ? "—" : `${num(g[k], 1)}%`)).join(" / ")],
      ["Объём на росте (макс. / средний бар)", `×${num(p.volume_ratio, 1)} / ×${num(p.volume_avg_ratio, 1)}`],
      ["Агрессивные покупки на росте", p.buy_share_pct === null || p.buy_share_pct === undefined ? `нет ленты (${p.tape_minutes || 0} мин)` : `${num(p.buy_share_pct, 1)}% (лента ${p.tape_minutes} мин)`],
      ["Оборот 24ч", plainUsd(m.turnover_24h_usd)],
    ]);
    const ss = m.sell_share || {};
    html += "<h4>Торможение и поток</h4>" + kv([
      ["С пика", dur(m.since_peak_min)],
      ["Ширина диапазона", m.range_pct === null || m.range_pct === undefined ? "—" : `${num(m.range_pct, 2)}%`],
      ["Откат от пика", `${num(m.drawdown_from_peak_pct, 2)}%`],
      ["Покупки 15 мин / пик 15 мин", `${plainUsd(m.buys_15m_usd)} / ${plainUsd(m.buys_peak15_usd)} (${m.buys_fade_ratio === null ? "—" : num(m.buys_fade_ratio * 100, 0) + "%"})`],
      ["Доля продаж 5 / 10 / 15 мин", [ss["5m"], ss["10m"], ss["15m"]].map((v) => (v === null || v === undefined ? "—" : `${num(v, 1)}%`)).join(" / ")],
      ["Объём 20 мин к пику", m.volume_ratio_20m === null || m.volume_ratio_20m === undefined ? "—" : `${num(m.volume_ratio_20m * 100, 0)}%`],
      ["Цена за 20 мин", pct(m.price_20m_pct)],
      ["Раздача", m.distribution ? "да" : "нет"],
    ]);
    html += "<h4>Ликвидации, OI, funding, BTC</h4>" + kv([
      ["Ликвидации шортов 15 мин", `${plainUsd(m.short_liq_15m_usd)} (затухание ${num(m.short_liq_fade_pct, 0)}%)`],
      ["Ликвидации лонгов 15 мин", plainUsd(m.long_liq_15m_usd)],
      ["OI 1 ч / 4 ч", `${pct(m.oi_1h_pct)} / ${pct(m.oi_4h_pct)}`],
      ["Funding", m.funding_rate === null || m.funding_rate === undefined ? "—" : `${num(m.funding_rate * 100, 4)}%`],
      ["BTC за 4 ч", `${pct(m.btc_4h_pct)}${ev.strict_btc ? " — строгий режим" : ""}`],
    ]);
    const emas = m.ema || {};
    const tfs = [["15m", "15m"], ["30m", "30m"], ["1H", "1H"], ["4H", "4H"]];
    html += `<h4>EMA (зелёная — закрытие ниже, пробита)</h4><table class="paper-ema"><thead><tr><th></th><th>EMA50</th><th>EMA100</th><th>EMA200</th></tr></thead><tbody>${tfs
      .map(
        ([tf, label]) =>
          `<tr><th>${label}</th>${[50, 100, 200]
            .map((per) => {
              const e = emas[`${tf}_EMA${per}`] || {};
              return `<td class="${e.broken ? "broken" : ""}">${e.ema === null || e.ema === undefined ? "—" : price(e.ema)}</td>`;
            })
            .join("")}</tr>`,
      )
      .join("")}</tbody></table>`;
    const dt = m.double_top;
    const st = m.strong_top;
    const rl = m.round_level;
    html += kv([
      [
        "Сильная двойная вершина",
        st
          ? `${st.interval === "60" ? "1H" : "30m"}: ${price(st.first_price)} → ${price(st.second_price)} (ниже на ${num(st.diff_pct, 2)}%), ${st.bars_between} свечей, после 2-й ${num(st.hours_after, 1)} ч`
          : "нет",
      ],
      ["Двойная вершина", dt ? `${dt.interval === "60" ? "1H" : "30m"}: ${price(dt.first_price)} / ${price(dt.second_price)}, разница ${num(dt.diff_pct, 2)}%, ${dt.bars_between} свечей, после 2-й ${num(dt.hours_after, 1)} ч` : "нет"],
      ["Круглый уровень", rl ? `${rl.level} (до пика ${num(rl.distance_pct, 2)}%)` : "нет"],
    ]);
    const parts = ev.score_parts || {};
    html += `<h4>Сила сигнала: <span class="grade-${ev.grade}">${ev.grade} · ${num(ev.score, 1)}</span></h4>` +
      kv(Object.entries(parts).map(([k, v]) => [SCORE_PARTS[k] || k, `+${num(v, 1)}`]));
    return html;
  }

  function tradeHtml(item) {
    const r = item.row;
    if (item.live) {
      return kv([
        ["Вариант", vbadge(r.variant)],
        ["Цена входа", price(r.entry_price)],
        ["Время входа", time(r.opened_at)],
        ["Текущая цена", `${price(r.last_price)} (${pct(r.price_change_pct)})`],
        ["ROE / P&L", `${pct(r.roe_pct, 1)} / ${usd(r.pnl_usd)}`],
        ["Стоп сейчас", price(r.stop_price)],
        ["Ликвидация", price(r.liq_price)],
        ["Лучшая цена", `${price(r.best_price)} (макс. ROE ${pct(r.max_roe, 1)})`],
        ["Худший ROE", pct(r.min_roe, 1)],
        ["Маржа / позиция", `$${num(r.margin)} / $${num(r.notional)} (×${(paper.data.summary || {}).leverage || 10})`],
        ["Количество", num(r.qty, 4)],
        ["Комиссия входа", `$${num(r.entry_fee, 4)}`],
        ["Funding получено/уплачено", `${usd(r.funding_paid, 4)}${r.next_funding_ts ? ` · след. ${time(r.next_funding_ts)}` : ""}`],
        ["В сделке", dur(r.duration_min)],
      ]);
    }
    return kv([
      ["Вариант", vbadge(r.variant)],
      ["Вход", `${price(r.entry_price)} · ${time(r.opened_at)}`],
      ["Выход", `${price(r.exit_price)} · ${time(r.closed_at)} · ${EXIT[r.exit_reason] || esc(r.exit_reason)}`],
      ["ROE / P&L", `${pct(r.roe_pct, 1)} / ${usd(r.pnl_usd)}`],
      ["Макс. / мин. ROE", `${pct(r.max_roe, 1)} / ${pct(r.min_roe, 1)}`],
      ["Лучшая цена", price(r.best_price)],
      ["Маржа / позиция", `$${num(r.margin)} / $${num(r.notional)}`],
      ["Комиссии", `$${num((r.entry_fee || 0) + (r.exit_fee || 0), 4)}`],
      ["Funding", usd(r.funding_paid, 4)],
      ["Длительность", dur((r.closed_at - r.opened_at) / 60000)],
      ["Баланс до → после", `$${num(r.balance_before)} → $${num(r.balance_after)}`],
    ]);
  }

  function candHtml(item) {
    const r = item.row;
    if (item.kind === "cand") {
      return kv([
        ["Ведётся", `${dur(r.watch_min)} · проверок ${r.scans}`],
        ["Лучший результат", `${r.best_passed}/${mandatory().length} условий`],
        ["Вошли в вариантах", (r.entered || []).map(vbadge).join(" ") || "нет"],
        ["Сейчас в сделке", (r.open_in || []).map(vbadge).join(" ") || "нет"],
        ["Теневая сделка", r.shadow ? `вход ${price(r.shadow.entry_price)}, ROE ${pct(r.shadow.roe_pct, 1)}, не хватало: ${esc(labels()[r.shadow.missing] || r.shadow.missing)}` : "нет"],
      ]);
    }
    return kv([
      ["Итог", `${r.status === "entered" ? "Вход" : "Без входа"} · ${esc(r.end_reason || "")}`],
      ["Вошли в вариантах", (r.variants || []).map(vbadge).join(" ") || "нет"],
      ["Период", `${time(r.started_at)} → ${time(r.ended_at)}`],
      ["Проверок", r.scans],
      ["Лучший результат", `${r.best_passed}/${mandatory().length} условий`],
      [
        "Теневая сделка",
        r.shadow_status
          ? `вход ${price(r.shadow_entry_price)} (${time(r.shadow_opened_at)}), не хватало: ${esc(labels()[r.near_miss_missing] || r.near_miss_missing)}; ${
              r.shadow_status === "closed" ? `итог ${pct(r.shadow_roe, 1)} / ${usd(r.shadow_pnl_usd)}, макс. ROE ${pct(r.shadow_max_roe, 1)}` : "идёт"
            }`
          : "нет",
      ],
    ]);
  }

  function renderDetail() {
    const panel = document.getElementById("paper-detail");
    if (!panel) return;
    const item = selectedItem();
    if (!item) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    const title = document.getElementById("paper-detail-title");
    const what =
      item.kind === "trade"
        ? item.live
          ? "Открытая сделка"
          : "Закрытая сделка"
        : item.kind === "vps_watch"
          ? "Сигнал Пылесос"
          : "Кандидат";
    title.textContent = `${item.symbol} — ${what}${item.kind === "trade" && item.row.variant ? ` (${vlabel(item.row.variant)})` : ""}`;
    const info = document.getElementById("paper-detail-info");
    const scroll = info.scrollTop;
    info.innerHTML =
      (item.kind === "trade" ? tradeHtml(item) : item.kind === "vps_watch" ? "" : candHtml(item)) + evalHtml(item.ev);
    info.scrollTop = scroll;
    renderTfRow();
    const key = `${item.symbol}|${paper.interval}|${item.kind}|${paper.selected.id ?? paper.selected.symbol ?? ""}`;
    if (paper.chartKey !== key) {
      paper.chartKey = key;
      loadChart(item);
    } else {
      drawLines(item);
    }
  }

  function renderTfRow() {
    const row = document.getElementById("paper-tf-row");
    if (!row || row.dataset.bound) {
      row?.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.iv === paper.interval));
      return;
    }
    row.dataset.bound = "1";
    row.innerHTML = INTERVALS.map(([iv, label]) => `<button type="button" class="paper-btn" data-iv="${iv}">${label}</button>`).join("");
    row.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => {
        paper.interval = b.dataset.iv;
        paper.chartKey = "";
        renderDetail();
      });
      b.classList.toggle("active", b.dataset.iv === paper.interval);
    });
  }

  function ensureChart() {
    if (paper.chart || typeof LightweightCharts === "undefined") return;
    const box = document.getElementById("paper-chart");
    paper.chart = LightweightCharts.createChart(box, {
      layout: { background: { color: "#151a22" }, textColor: "#8e9aab" },
      grid: { vertLines: { color: "#1f2733" }, horzLines: { color: "#1f2733" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#2c3544" },
      autoSize: true,
    });
    paper.series = paper.chart.addCandlestickSeries({
      upColor: "#3dd68c",
      downColor: "#ff5d73",
      wickUpColor: "#3dd68c",
      wickDownColor: "#ff5d73",
      borderVisible: false,
    });
  }

  async function loadChart(item) {
    ensureChart();
    if (!paper.series) return;
    const key = paper.chartKey;
    try {
      const res = await fetch(`/api/klines/${item.symbol}?interval=${paper.interval}`);
      const body = await res.json();
      if (key !== paper.chartKey) return;
      const tzOffset = -new Date().getTimezoneOffset() * 60;
      const candles = (body.candles || []).map((c) => ({
        time: Math.floor(c.timestamp / 1000) + tzOffset,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
      paper.series.setData(candles);
      paper.chart.timeScale().fitContent();
      drawLines(item);
    } catch (_err) {
      /* ignore */
    }
  }

  function drawLines(item) {
    if (!paper.series) return;
    paper.lines.forEach((line) => paper.series.removePriceLine(line));
    paper.lines = [];
    const add = (value, color, title, style = 2) => {
      if (value === null || value === undefined || !Number(value)) return;
      paper.lines.push(paper.series.createPriceLine({ price: Number(value), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    };
    const r = item.row;
    const p = r.pump || ((item.ev || {}).metrics || {}).pump || {};
    add(p.peak_price || r.peak_price, "#f6d365", "пик");
    add(p.anchor_price || p.valley_price || r.valley_price, "#8d97a8", p.kind === "growth" ? "якорь" : "дно");
    const tzOffset = -new Date().getTimezoneOffset() * 60;
    const markers = [];
    if (item.kind === "trade") {
      add(r.entry_price, "#5dade2", "вход", 0);
      if (item.live) {
        add(r.stop_price, "#ff9f43", "стоп");
        add(r.liq_price, "#ff5d73", "ликв.");
      } else {
        add(r.exit_price, "#ff9f43", "выход", 0);
      }
      if (r.side === "long") {
        markers.push({ time: Math.floor(r.opened_at / 1000) + tzOffset, position: "belowBar", color: "#3ddc84", shape: "arrowUp", text: "лонг" });
      } else {
        markers.push({ time: Math.floor(r.opened_at / 1000) + tzOffset, position: "aboveBar", color: "#5dade2", shape: "arrowDown", text: "шорт" });
      }
      if (r.closed_at) markers.push({ time: Math.floor(r.closed_at / 1000) + tzOffset, position: "belowBar", color: "#ff9f43", shape: "arrowUp", text: "выход" });
    } else if (item.kind === "hist" && r.shadow_entry_price) {
      add(r.shadow_entry_price, "#5dade2", "тень: вход", 0);
      if (r.shadow_exit_price) add(r.shadow_exit_price, "#ff9f43", "тень: выход", 0);
    } else if (item.kind === "cand" && r.shadow) {
      add(r.shadow.entry_price, "#5dade2", "тень: вход", 0);
    }
    const vpsEv = item.ev || {};
    const vpsM = vpsEv.metrics || {};
    if (VPS_VARIANTS[paper.variant] || vpsM.kind === "vps15" || vpsM.kind === "vps5" || vpsM.kind === "vps") {
      (vpsM.peaks || []).slice(-5).forEach((p, i) => add(p.price, "#e76f51", `LH${i + 1}`, 3));
      (vpsM.troughs || []).slice(-5).forEach((p, i) => add(p.price, "#2a9d8f", `HL${i + 1}`, 3));
      if (vpsM.pivot_price) add(vpsM.pivot_price, "#f6d365", "pivot", 0);
    }
    const step = { "5": 300, "15": 900, "60": 3600, "240": 14400 }[paper.interval] || 900;
    paper.series.setMarkers(
      markers
        .map((mk) => ({ ...mk, time: Math.floor((mk.time - tzOffset) / step) * step + tzOffset }))
        .sort((a, b) => a.time - b.time),
    );
  }

  loadEquityOn();

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("paper-detail-close")?.addEventListener("click", () => {
      paper.selected = null;
      paper.chartKey = "";
      render();
    });
  });
  window.addEventListener("resize", () => paper.equityChart && paper.equityChart.resize());

  window.paperTest = { onSnapshot, onTab, onBalanceTab };
})();
