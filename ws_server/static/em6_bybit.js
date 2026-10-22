(function () {
  const num = (v) => (v == null || v === "" ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v == null || v === "" ? "—" : `${Number(v).toFixed(2)}%`);
  const ts = (ms) => {
    if (!ms) return "—";
    return new Date(ms).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
  };

  let lastData = null;
  let chartApi = null;
  let chartSeries = null;
  let lineSeries = [];

  function renderSummary(data) {
    const s = data.summary || {};
    const el = document.getElementById("em6b-summary");
    if (!el) return;
    const pnl = Number(s.total_pnl_closed || 0);
    const pnlCls = pnl >= 0 ? "pos" : "neg";
    el.innerHTML = `
      <div class="paper-card"><span class="label">Equity Demo</span><div class="value">$${num(s.wallet_equity)}</div></div>
      <div class="paper-card"><span class="label">Доступно</span><div class="value">$${num(s.wallet_available)}</div></div>
      <div class="paper-card"><span class="label">Открыто</span><div class="value">${s.open_trades ?? 0}</div></div>
      <div class="paper-card"><span class="label">Закрыто</span><div class="value">${s.closed_trades ?? 0}</div></div>
      <div class="paper-card"><span class="label">Win rate</span><div class="value">${pct(s.win_rate)}</div></div>
      <div class="paper-card"><span class="label">PnL закрытых</span><div class="value ${pnlCls}">$${num(s.total_pnl_closed)}</div></div>
      <div class="paper-card"><span class="label">Претенденты</span><div class="value">${s.watch_count ?? 0}</div></div>
      <div class="paper-card"><span class="label">Маржа / трейл</span><div class="value">$${num(s.margin_usd ?? 50)} × ${s.leverage ?? 10} · −14% ROE</div></div>
    `;
  }

  function rowOpen(r) {
    return `<tr class="em6b-open-row" data-symbol="${r.symbol}">
      <td>${r.symbol}</td>
      <td>${r.side}</td>
      <td>${num(r.entry_price)}</td>
      <td>${num(r.stop_price)}</td>
      <td>${pct(r.trail_roe_pct ?? 14)} trail</td>
      <td>${pct(r.max_roe)}</td>
      <td>$${num(r.notional_usd ?? r.margin * 10)}</td>
      <td>${num(r.margin)}</td>
      <td>${ts(r.opened_at)}</td>
    </tr>`;
  }

  function rowClosed(r) {
    const pnl = Number(r.pnl_usd || 0);
    const cls = pnl >= 0 ? "pos" : "neg";
    return `<tr>
      <td>${r.symbol}</td>
      <td>${r.side}</td>
      <td>${num(r.entry_price)}</td>
      <td>${num(r.exit_price)}</td>
      <td class="${cls}">$${num(r.pnl_usd)}</td>
      <td>${pct(r.roe_pct)}</td>
      <td>${pct(r.max_roe)}</td>
      <td>${r.exit_reason || "—"}</td>
      <td>${ts(r.closed_at)}</td>
    </tr>`;
  }

  function rowCand(c) {
    return `<tr>
      <td>${c.symbol}</td>
      <td>${c.side}</td>
      <td>${pct(c.stretch_pct)}</td>
      <td>${c.stretch_column || "—"}</td>
      <td>${c.phase || "—"}</td>
      <td>${pct(c.peak_stretch)}</td>
      <td>${c.armed_band_lo != null ? pct(c.armed_band_lo) : "—"}</td>
    </tr>`;
  }

  function renderCandidates(data) {
    const grid = document.getElementById("em6b-candidates-grid");
    const table = document.getElementById("em6b-candidates");
    const cols = data.candidate_columns || [];
    if (grid) {
      grid.innerHTML = cols
        .map(
          (col) => `<div class="paper-panel em6b-col">
          <h4>${col.label}</h4>
          <ul>${(col.candidates || [])
            .map(
              (c) =>
                `<li><strong>${c.symbol}</strong> ${c.side} · ${Number(c.stretch_pct).toFixed(2)}% · ${c.phase}</li>`
            )
            .join("") || "<li class='quiet'>—</li>"}</ul>
        </div>`
        )
        .join("");
    }
    if (table) {
      const rows = (data.candidates || []).map(rowCand).join("");
      table.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Отрыв</th><th>Колонка</th><th>Фаза</th>
        <th>Пик</th><th>Arm band</th></tr></thead><tbody>${rows || "<tr><td colspan='7'>Нет претендентов (≥4%)</td></tr>"}</tbody>`;
    }
  }

  function findOpenTrade(symbol) {
    return (lastData?.open_trades || []).find((r) => r.symbol === symbol);
  }

  function clearLevelLines() {
    lineSeries.forEach((s) => {
      try {
        chartApi.removeSeries(s);
      } catch (_) {
        /* ignore */
      }
    });
    lineSeries = [];
  }

  async function showTradeChart(trade) {
    const wrap = document.getElementById("em6b-chart-wrap");
    const title = document.getElementById("em6b-chart-title");
    const el = document.getElementById("em6b-chart");
    if (!wrap || !el || !trade || !window.LightweightCharts) return;
    wrap.hidden = false;
    title.textContent = `${trade.symbol} · ${trade.side} · EMA60 + уровни отрыва`;

    if (!chartApi) {
      el.innerHTML = "";
      chartApi = window.LightweightCharts.createChart(el, {
        width: el.clientWidth || 640,
        height: 360,
        layout: { background: { color: "#0f1419" }, textColor: "#9aa4b2" },
        grid: { vertLines: { color: "#1e2834" }, horzLines: { color: "#1e2834" } },
      });
      chartSeries = chartApi.addCandlestickSeries({
        upColor: "#26a69a",
        downColor: "#ef5350",
        borderVisible: false,
        wickUpColor: "#26a69a",
        wickDownColor: "#ef5350",
      });
    }
    clearLevelLines();

    const resp = await fetch(
      `/api/klines/${encodeURIComponent(trade.symbol)}?interval=5&limit=240`
    );
    if (!resp.ok) return;
    const payload = await resp.json();
    const candles = (payload.candles || payload.klines || []).map((c) => ({
      time: Math.floor((c.t || c.time) / 1000),
      open: +c.o,
      high: +c.h,
      low: +c.l,
      close: +c.c,
    }));
    chartSeries.setData(candles);

    const ema = Number(trade.ema60 || 0);
    if (ema > 0) {
      const emaLine = chartApi.addLineSeries({ color: "#f0b429", lineWidth: 2, title: "EMA60" });
      lineSeries.push(emaLine);
      emaLine.setData(candles.map((c) => ({ time: c.time, value: ema })));
    }

    (trade.grid_levels || []).forEach((lv, i) => {
      const p = Number(lv.price_lo);
      if (!p) return;
      const s = chartApi.addLineSeries({
        color: i % 2 ? "rgba(120,160,255,0.55)" : "rgba(160,120,255,0.45)",
        lineWidth: 1,
        lineStyle: 2,
        title: `${lv.stretch_lo}–${lv.stretch_hi}%`,
      });
      lineSeries.push(s);
      s.setData(candles.map((c) => ({ time: c.time, value: p })));
      const ph = Number(lv.price_hi);
      if (ph && ph !== p) {
        const s2 = chartApi.addLineSeries({
          color: "rgba(120,160,255,0.25)",
          lineWidth: 1,
          lineStyle: 2,
        });
        lineSeries.push(s2);
        s2.setData(candles.map((c) => ({ time: c.time, value: ph })));
      }
    });

    const entry = Number(trade.entry_price);
    if (entry > 0) {
      const ent = chartApi.addLineSeries({ color: "#fff", lineWidth: 1, title: "Entry" });
      lineSeries.push(ent);
      ent.setData(candles.map((c) => ({ time: c.time, value: entry })));
    }
    chartApi.timeScale().fitContent();
  }

  function bindOpenClicks() {
    const open = document.getElementById("em6b-open");
    if (!open || open.dataset.bound) return;
    open.dataset.bound = "1";
    open.addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr.em6b-open-row");
      if (!tr) return;
      const sym = tr.getAttribute("data-symbol");
      const trade = findOpenTrade(sym);
      if (trade) showTradeChart(trade);
    });
  }

  function renderTables(data) {
    const open = document.getElementById("em6b-open");
    const closed = document.getElementById("em6b-closed");
    if (open) {
      const rows = (data.open_trades || []).map(rowOpen).join("");
      open.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Вход</th><th>Стоп (расч.)</th><th>Трейл</th>
        <th>Max ROE</th><th>Номинал</th><th>Маржа</th><th>Открыта</th></tr></thead><tbody>${rows || "<tr><td colspan='9'>Нет открытых</td></tr>"}</tbody>`;
      bindOpenClicks();
    }
    if (closed) {
      const rows = (data.closed_trades || []).map(rowClosed).join("");
      closed.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>PnL</th><th>ROE</th>
        <th>Max ROE</th><th>Причина</th><th>Закрыта</th></tr></thead><tbody>${rows || "<tr><td colspan='9'>Пока нет</td></tr>"}</tbody>`;
    }
  }

  function onSnapshot(payload) {
    const data = payload && payload.data ? payload.data : payload;
    if (!data) return;
    lastData = data;
    renderSummary(data);
    renderCandidates(data);
    renderTables(data);
  }

  async function fetchFallback() {
    try {
      const r = await fetch("/api/em6-bybit/snapshot");
      if (r.ok) onSnapshot(await r.json());
    } catch (_) {
      /* ignore */
    }
  }

  window.em6Bybit = {
    onSnapshot,
    onTab() {
      fetchFallback();
    },
  };
})();
