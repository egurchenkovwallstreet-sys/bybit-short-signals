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
    el.innerHTML = `
      <div class="paper-card"><span>Equity Demo</span><strong>$${num(s.wallet_equity)}</strong></div>
      <div class="paper-card"><span>Доступно</span><strong>$${num(s.wallet_available)}</strong></div>
      <div class="paper-card"><span>Открыто</span><strong>${s.open_trades ?? 0}</strong></div>
      <div class="paper-card"><span>Закрыто</span><strong>${s.closed_trades ?? 0}</strong></div>
      <div class="paper-card"><span>Win rate</span><strong>${pct(s.win_rate)}</strong></div>
      <div class="paper-card"><span>PnL закрытых</span><strong>$${num(s.total_pnl_closed)}</strong></div>
      <div class="paper-card"><span>Маржа / плечо</span><strong>${s.margin_pct ?? 5}% × ${s.leverage ?? 10}</strong></div>
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
