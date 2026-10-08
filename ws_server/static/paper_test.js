/* Вкладка «Тест стратегии»: виртуальные шорты после пампа. Данные считает сервер. */
(() => {
  const paper = {
    data: null,
    closed: [],
    history: [],
    selected: null, // {type: "open"|"closed"|"cand", id}
    interval: "15",
    chart: null,
    series: null,
    lines: [],
    equityChart: null,
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
  };
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
    if (!p || p.growth_pct === undefined) return "—";
    return `${KIND[p.kind] || p.kind}: +${num(p.growth_pct, 1)}% за ${dur(p.duration_min)} (окно ${TRIGGER[p.trigger] || p.trigger || "?"})`;
  }
  function labels() {
    return (paper.data && paper.data.check_labels) || {};
  }
  function mandatory() {
    return (paper.data && paper.data.mandatory) || [];
  }

  // --- данные ---

  function onSnapshot(data) {
    if (!data) return;
    paper.data = data;
    if (!isVisible()) return;
    render();
  }

  function isVisible() {
    const view = document.getElementById("view-paper");
    return view && !view.hidden;
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

  async function fetchLists(force) {
    const now = Date.now();
    if (!force && now - paper.lastListFetch < 30000) return;
    paper.lastListFetch = now;
    try {
      const [closed, hist] = await Promise.all([
        fetch("/api/paper/trades?status=closed&limit=500").then((r) => r.json()),
        fetch("/api/paper/candidates?limit=500").then((r) => r.json()),
      ]);
      paper.closed = closed.rows || [];
      paper.history = hist.rows || [];
    } catch (_err) {
      /* ignore */
    }
  }

  function render() {
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

  function renderSummary() {
    const root = document.getElementById("paper-summary");
    if (!root) return;
    const s = (paper.data && paper.data.summary) || {};
    const t = ((paper.data && paper.data.analytics) || {}).trades || {};
    const start = s.start_balance || 1000;
    const balance = s.balance ?? t.balance ?? start;
    const cards = [
      ["Баланс", `$${num(balance)}`, `старт $${num(start, 0)} · ${pct(((balance - start) / start) * 100)}`],
      ["Equity", `$${num(s.equity ?? balance)}`, `плавающий ${usd(s.unrealized ?? 0)}`],
      ["Открыто сделок", s.open_trades ?? 0, `маржа в работе $${num(s.used_margin ?? 0)}`],
      ["Закрыто сделок", t.closed ?? 0, `${t.wins ?? 0} в плюс · ${t.losses ?? 0} в минус`],
      ["Win rate", `${num(t.win_rate ?? 0, 1)}%`, `PF ${t.profit_factor ?? "—"}`],
      ["Итог P&L", usd(t.total_pnl ?? 0), `ср. ROE ${num(t.avg_roe ?? 0, 1)}%`],
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

  function renderEquity() {
    const box = document.getElementById("paper-equity");
    if (!box || typeof echarts === "undefined") return;
    const rows = ((paper.data && paper.data.analytics) || {}).equity || [];
    if (!paper.equityChart) paper.equityChart = echarts.init(box, null, { renderer: "canvas" });
    paper.equityChart.setOption({
      backgroundColor: "transparent",
      grid: { left: 60, right: 20, top: 20, bottom: 30 },
      tooltip: { trigger: "axis" },
      legend: { data: ["Баланс", "Equity"], textStyle: { color: "#8e9aab" }, top: 0 },
      xAxis: { type: "time", axisLabel: { color: "#8e9aab" } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#8e9aab" }, splitLine: { lineStyle: { color: "#2c3544" } } },
      series: [
        { name: "Баланс", type: "line", showSymbol: false, data: rows.map((r) => [r[0], r[1]]), lineStyle: { color: "#5dade2" } },
        { name: "Equity", type: "line", showSymbol: false, data: rows.map((r) => [r[0], r[2]]), lineStyle: { color: "#3dd68c", type: "dashed" } },
      ],
    });
    paper.equityChart.resize();
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
    const rows = (paper.data && paper.data.open_trades) || [];
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Открытых сделок нет.</td></tr></tbody>';
      return;
    }
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>Вход</th><th>Цена входа</th><th>Текущая</th><th>Изм. цены</th>
      <th>Стоп</th><th>Лучшая</th><th>ROE</th><th>P&amp;L</th><th>Макс. ROE</th><th>Маржа</th><th>Funding</th><th>Сила</th><th>В сделке</th>
    </tr></thead><tbody>${rows
      .map(
        (r) => `<tr class="clickable${isSel("open", r.id)}" data-id="${r.id}">
        <td><b>${esc(r.symbol)}</b></td>
        <td>${pumpLine(r.pump)}</td>
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
    const table = document.getElementById("paper-cand-table");
    if (!table) return;
    const rows = (paper.data && paper.data.candidates) || [];
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Сейчас нет монет после пампа по условиям стратегии.</td></tr></tbody>';
      return;
    }
    const total = mandatory().length;
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>С пика</th><th>Диапазон</th><th>Объём ×</th><th>Покупки на росте</th>
      <th>Продажи 5/10/15м</th><th>OI 1ч / 4ч</th><th>Funding</th><th>Условия</th><th>Не хватает</th><th>Сила</th><th>Тень</th>
    </tr></thead><tbody>${rows
      .map((r) => {
        const ev = r.eval || {};
        const m = ev.metrics || {};
        const p = r.pump || {};
        const ss = m.sell_share || {};
        const failed = (ev.failed || []).map((k) => labels()[k] || k);
        const passed = total - (ev.failed || mandatory()).length;
        const sh = r.shadow ? `${pct(r.shadow.roe_pct, 1)}` : "—";
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
          <td>${esc(r.note || failed.join(", ") || "—")}</td>
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
    const rows = paper.closed || [];
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="quiet">Закрытых сделок пока нет.</td></tr></tbody>';
      return;
    }
    table.innerHTML = `<thead><tr>
      <th>Монета</th><th>Памп</th><th>Вход</th><th>Выход</th><th>Цена входа</th><th>Цена выхода</th><th>Причина</th>
      <th>ROE</th><th>P&amp;L</th><th>Макс. ROE</th><th>Мин. ROE</th><th>Комиссии</th><th>Funding</th><th>Сила</th><th>Баланс после</th>
    </tr></thead><tbody>${rows
      .map((r) => {
        const p = ((r.entry || {}).metrics || {}).pump || {};
        return `<tr class="clickable${isSel("closed", r.id)}" data-id="${r.id}">
          <td><b>${esc(r.symbol)}</b></td>
          <td>${pumpLine(p)}</td>
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
    const a = (paper.data && paper.data.analytics) || {};
    root.innerHTML = [
      groupTable("По причине выхода", a.by_reason),
      groupTable("По типу пампа", a.by_kind),
      groupTable("По окну роста", a.by_trigger),
      groupTable("По силе сигнала", a.by_grade),
      groupTable("По режиму BTC", a.by_btc),
    ].join("");
  }

  function renderCandAnalytics() {
    const root = document.getElementById("paper-cand-analytics");
    if (!root) return;
    const c = ((paper.data && paper.data.analytics) || {}).candidates || {};
    const st = c.by_status || {};
    const L = labels();
    let html = `<p>Всего кандидатов: <b>${c.total || 0}</b> · ведутся: ${st.watching || 0} · вошли: ${st.entered || 0} · истекли без входа: ${st.expired || 0}</p>`;
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
          <td>${STATUS[r.status] || esc(r.status)}</td><td>${esc(r.end_reason || "—")}</td>
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
      return r ? { kind: "cand", row: r, symbol: r.symbol, ev: r.eval } : null;
    }
    if (sel.type === "hist") {
      const r = (paper.history || []).find((x) => x.id === sel.id);
      return r ? { kind: "hist", row: r, symbol: r.symbol, ev: r.last_eval } : null;
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
    const g = p.growth || {};
    let html = "<h4>Обязательные условия</h4><ul class=\"paper-check-list\">";
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
    const rl = m.round_level;
    html += kv([
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
        ["Теневая сделка", r.shadow ? `вход ${price(r.shadow.entry_price)}, ROE ${pct(r.shadow.roe_pct, 1)}, не хватало: ${esc(labels()[r.shadow.missing] || r.shadow.missing)}` : "нет"],
      ]);
    }
    return kv([
      ["Итог", `${r.status === "entered" ? "Вход" : "Без входа"} · ${esc(r.end_reason || "")}`],
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
    const what = item.kind === "trade" ? (item.live ? "Открытая сделка" : "Закрытая сделка") : "Кандидат";
    title.textContent = `${item.symbol} — ${what}`;
    const info = document.getElementById("paper-detail-info");
    const scroll = info.scrollTop;
    info.innerHTML = (item.kind === "trade" ? tradeHtml(item) : candHtml(item)) + evalHtml(item.ev);
    info.scrollTop = scroll;
    renderTfRow();
    const key = `${item.symbol}|${paper.interval}|${item.kind}|${paper.selected.id}`;
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
    const p = ((item.ev || {}).metrics || {}).pump || r.pump || {};
    add(p.peak_price || r.peak_price, "#f6d365", "пик");
    add(p.valley_price || r.valley_price, "#8d97a8", "дно");
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
      markers.push({ time: Math.floor(r.opened_at / 1000) + tzOffset, position: "aboveBar", color: "#5dade2", shape: "arrowDown", text: "шорт" });
      if (r.closed_at) markers.push({ time: Math.floor(r.closed_at / 1000) + tzOffset, position: "belowBar", color: "#ff9f43", shape: "arrowUp", text: "выход" });
    } else if (item.kind === "hist" && r.shadow_entry_price) {
      add(r.shadow_entry_price, "#5dade2", "тень: вход", 0);
      if (r.shadow_exit_price) add(r.shadow_exit_price, "#ff9f43", "тень: выход", 0);
    } else if (item.kind === "cand" && r.shadow) {
      add(r.shadow.entry_price, "#5dade2", "тень: вход", 0);
    }
    const step = { "5": 300, "15": 900, "60": 3600, "240": 14400 }[paper.interval] || 900;
    paper.series.setMarkers(
      markers
        .map((mk) => ({ ...mk, time: Math.floor((mk.time - tzOffset) / step) * step + tzOffset }))
        .sort((a, b) => a.time - b.time),
    );
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("paper-detail-close")?.addEventListener("click", () => {
      paper.selected = null;
      paper.chartKey = "";
      render();
    });
  });
  window.addEventListener("resize", () => paper.equityChart && paper.equityChart.resize());

  window.paperTest = { onSnapshot, onTab };
})();
