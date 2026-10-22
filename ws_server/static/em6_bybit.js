(function () {
  const num = (v) => (v == null || v === "" ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v == null || v === "" ? "—" : `${Number(v).toFixed(2)}%`);
  const ts = (ms) => {
    if (!ms) return "—";
    return new Date(ms).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
  };

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
      <div class="paper-card"><span class="label">Маржа / плечо</span><div class="value">$${num(s.margin_usd ?? 50)} × ${s.leverage ?? 10} ($${num(s.notional_usd ?? 500)})</div></div>
    `;
  }

  function rowOpen(r) {
    return `<tr>
      <td>${r.symbol}</td>
      <td>${r.side}</td>
      <td>${num(r.entry_price)}</td>
      <td>${num(r.stop_price)}</td>
      <td>${num(r.exchange_stop ?? r.stop_price)}</td>
      <td>${pct(r.max_roe)}</td>
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

  function renderTables(data) {
    const open = document.getElementById("em6b-open");
    const closed = document.getElementById("em6b-closed");
    if (open) {
      const rows = (data.open_trades || []).map(rowOpen).join("");
      open.innerHTML = `<thead><tr>
        <th>Symbol</th><th>Сторона</th><th>Вход</th><th>Стоп (расч.)</th><th>Стоп (биржа)</th>
        <th>Max ROE</th><th>Маржа</th><th>Открыта</th></tr></thead><tbody>${rows || "<tr><td colspan='8'>Нет открытых</td></tr>"}</tbody>`;
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
