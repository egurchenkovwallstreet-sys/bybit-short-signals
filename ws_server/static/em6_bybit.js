(function () {
  const num = (v) => (v == null || v === "" ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v == null || v === "" ? "—" : `${Number(v).toFixed(2)}%`);
  const ts = (ms) => {
    if (!ms) return "—";
    return new Date(ms).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
  };

  const pnlClass = (v) => {
    const n = Number(v);
    if (Number.isNaN(n) || v == null || v === "") return "";
    if (n > 0) return "pos";
    if (n < 0) return "neg";
    return "flat";
  };

  const sideLabel = (side) => {
    if (side === "long") return '<span class="em6b-side em6b-long">LONG</span>';
    if (side === "short") return '<span class="em6b-side em6b-short">SHORT</span>';
    return side || "—";
  };

  let lastData = null;
  let chartApi = null;
  let chartSeries = null;
  let lineSeries = [];

  function renderSummary(data) {
    const s = data.summary || {};
    const el = document.getElementById("em6b-summary");
    if (!el) return;
    const pnlClosed = Number(s.total_pnl_closed || 0);
    const pnlOpen = Number(s.total_unrealised_pnl || 0);
    const src = s.data_source === "bybit" ? "Bybit Demo" : "локальный журнал";
    const marginAvail = Number(s.wallet_available ?? s.wallet_equity ?? 0);
    el.innerHTML = `
      <div class="paper-card em6b-balance-main"><span class="label">Доступная маржа USDT</span><div class="value">$${num(marginAvail)}</div><span class="hint">${src}</span></div>
      <div class="paper-card"><span class="label">uPnL открытых</span><div class="value ${pnlClass(pnlOpen)}">$${num(pnlOpen)}</div></div>
      <div class="paper-card"><span class="label">Открыто</span><div class="value">${s.open_trades ?? 0}</div></div>
      <div class="paper-card"><span class="label">Закрыто</span><div class="value">${s.closed_trades ?? 0}</div></div>
      <div class="paper-card"><span class="label">Win rate</span><div class="value">${pct(s.win_rate)}</div></div>
      <div class="paper-card"><span class="label">PnL закрытых</span><div class="value ${pnlClass(pnlClosed)}">$${num(pnlClosed)}</div></div>
      <div class="paper-card"><span class="label">Претенденты</span><div class="value">${s.watch_count ?? 0}</div></div>
      <div class="paper-card"><span class="label">Цель номинала</span><div class="value">$${num(s.notional_usd ?? 500)} · ${s.leverage ?? 10}×</div></div>
    `;
  }

  function fmtStop(r) {
    const trail = Number(r.trailing_stop || 0);
    const sl = Number(r.stop_loss || 0);
    if (trail > 0) return `trail ${num(trail)}`;
    if (sl > 0) return num(sl);
    if (r.stop_price != null) return `${num(r.stop_price)} (расч.)`;
    return "—";
  }

  function rowOpen(r) {
    const upnl = r.unrealised_pnl;
    const roe = r.roe_pct;
    const rowCls = r.side === "long" ? "em6b-row-long" : "em6b-row-short";
    return `<tr class="em6b-open-row ${rowCls}" data-symbol="${r.symbol}">
      <td><strong>${r.symbol}</strong></td>
      <td>${sideLabel(r.side)}</td>
      <td>${num(r.entry_price)}</td>
      <td>${num(r.mark_price)}</td>
      <td class="${pnlClass(upnl)}">$${num(upnl)}</td>
      <td class="${pnlClass(roe)}">${pct(roe)}</td>
      <td>${fmtStop(r)} · ${pct(r.trail_roe_pct)}${r.trail_armed ? " ✓" : ""}</td>
      <td>${pct(r.max_roe)}</td>
      <td>$${num(r.notional_usd)}</td>
      <td>${num(r.margin)}</td>
      <td>${ts(r.opened_at)}</td>
    </tr>`;
  }

  function rowClosed(r) {
    const pnl = Number(r.pnl_usd || 0);
    const roe = r.roe_pct;
    const cls = pnlClass(pnl);
    const rowCls = r.side === "long" ? "em6b-row-long" : "em6b-row-short";
    return `<tr class="${rowCls} em6b-closed-row ${cls}">
      <td><strong>${r.symbol}</strong></td>
      <td>${sideLabel(r.side)}</td>
      <td>${num(r.entry_price)}</td>
      <td>${num(r.exit_price)}</td>
      <td class="${cls}"><strong>$${num(r.pnl_usd)}</strong></td>
      <td class="${pnlClass(roe)}">${pct(roe)}</td>
      <td>${r.source === "bybit" ? "биржа" : r.exit_reason || "—"}</td>
      <td>${ts(r.closed_at)}</td>
    </tr>`;
  }

  function rowCand(c) {
    return `<tr>
      <td>${c.symbol}</td>
      <td>${sideLabel(c.side)}</td>
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
    const srcNote = document.getElementById("em6b-source-note");
    if (srcNote) {
      const src = data.summary?.data_source === "bybit" ? "Данные позиций и PnL — с Bybit Demo." : "Биржа недоступна — локальный журнал.";
      srcNote.textContent = src;
    }
    if (open) {
      const rows = (data.open_trades || []).map(rowOpen).join("");
      open.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Вход</th><th>Mark</th><th>uPnL</th><th>ROE</th>
        <th>SL / trail</th><th>Max ROE</th><th>Номинал</th><th>Маржа</th><th>Открыта</th></tr></thead><tbody>${rows || "<tr><td colspan='11'>Нет открытых на бирже</td></tr>"}</tbody>`;
      bindOpenClicks();
    }
    if (closed) {
      const rows = (data.closed_trades || []).map(rowClosed).join("");
      closed.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>PnL</th><th>ROE</th>
        <th>Источник</th><th>Закрыта</th></tr></thead><tbody>${rows || "<tr><td colspan='8'>Пока нет</td></tr>"}</tbody>`;
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
