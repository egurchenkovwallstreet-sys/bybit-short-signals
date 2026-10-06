/* Вкладка тестовой BTC-стратегии (intraday + scalp). */

const FACTOR_LABELS = {
  d_veto_ok: "1D не против",
  bias_4h: "4H bias",
  bias_1h: "1H bias",
  m30_structure: "30m структура",
  m15_vol: "15m объём",
  m5_trigger: "5m триггер",
  m1_trigger: "1m триггер",
  vol_perp: "Объём перп",
  funding_perp: "Funding",
  oi_perp: "OI",
  liq_perp: "Ликвидации",
};

const btcState = {
  data: null,
  chart: null,
  series: null,
  interval: "5",
};

function initBtcTab() {
  const box = document.getElementById("btc-chart");
  if (!box || btcState.chart) return;
  btcState.chart = LightweightCharts.createChart(box, {
    layout: { background: { color: "#0d1117" }, textColor: "#c9d1d9" },
    grid: { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
    timeScale: { timeVisible: true },
  });
  btcState.series = btcState.chart.addCandlestickSeries({
    upColor: "#3fb950",
    downColor: "#f85149",
    borderVisible: false,
    wickUpColor: "#3fb950",
    wickDownColor: "#f85149",
  });
  window.addEventListener("resize", () => btcState.chart && btcState.chart.resize());
  document.querySelectorAll("[data-btc-interval]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btcState.interval = btn.dataset.btcInterval;
      document.querySelectorAll("[data-btc-interval]").forEach((b) => b.classList.toggle("active", b === btn));
      requestBtcCandles();
    });
  });
}

function requestBtcCandles() {
  /* Свечи приходят в payload; переключение интервала — через следующий push с сервера. */
  renderBtcChart();
}

function onBtcMessage(data) {
  btcState.data = data;
  renderBtcHeader();
  renderBtcChart();
  renderBtcJournal();
  renderBtcAnalytics();
}

function renderBtcHeader() {
  const d = btcState.data;
  if (!d) return;
  const el = document.getElementById("btc-meta");
  if (!el) return;
  const fr = d.funding != null ? (Number(d.funding) * 100).toFixed(4) + "%" : "—";
  el.textContent = `Bias: ${d.bias || "—"} · Funding: ${fr} · Цена: ${d.last_price ?? "—"}`;
}

function renderBtcChart() {
  if (!btcState.series || !btcState.data) return;
  const candles = btcState.data.candles || [];
  btcState.series.setData(candles);
  const markers = (btcState.data.markers || []).map((m) => ({
    time: m.time,
    position: m.side === "long" ? "belowBar" : "aboveBar",
    color: m.side === "long" ? "#3fb950" : "#f85149",
    shape: m.side === "long" ? "arrowUp" : "arrowDown",
    text: `${m.grade} ${m.mode === "scalp" ? "S" : "D"}`,
  }));
  btcState.series.setMarkers(markers);
  btcState.chart.timeScale().scrollToRealTime();
}

function renderBtcJournal() {
  const body = document.querySelector("#btc-signal-table tbody");
  if (!body || !btcState.data) return;
  const rows = btcState.data.signals || [];
  body.innerHTML = rows
    .slice(0, 80)
    .map((s) => {
      const checks = s.checks || {};
      const hit = Object.keys(FACTOR_LABELS).filter((k) => checks[k]).length;
      const pnl = s.pnl_pct != null ? Number(s.pnl_pct).toFixed(2) : "…";
      const out = s.outcome || "OPEN";
      return `<tr>
        <td>${new Date(s.entry_ts).toLocaleString()}</td>
        <td>${s.mode}</td>
        <td>${s.side}</td>
        <td class="grade-${s.grade}">${s.grade}</td>
        <td>${s.score}</td>
        <td>${hit}/11</td>
        <td>${out}</td>
        <td>${pnl}</td>
        <td>${s.exit_reason || ""}</td>
      </tr>`;
    })
    .join("");
}

function renderBtcAnalytics() {
  const root = document.getElementById("btc-analytics");
  if (!root || !btcState.data) return;
  const a = btcState.data.analytics || {};
  const wins = a.factors_wins || {};
  const losses = a.factors_losses || {};
  const keys = new Set([...Object.keys(wins), ...Object.keys(losses)]);
  const grade = a.by_grade || {};
  let html = `<p>Закрыто: <b>${a.closed || 0}</b> · Win rate: <b>${a.win_rate || 0}%</b> (W ${a.wins || 0} / L ${a.losses || 0})</p>`;
  html += "<p>По grade: ";
  html += Object.entries(grade)
    .map(([g, v]) => `${g}: ${v.win_rate}% (${v.trades})`)
    .join(" · ");
  html += "</p><div class=\"btc-factor-grid\">";
  keys.forEach((k) => {
    const label = FACTOR_LABELS[k] || k;
    html += `<div class="factor-row"><span>${label}</span><span class="win">+ ${wins[k]?.pct ?? 0}%</span><span class="loss">− ${losses[k]?.pct ?? 0}%</span></div>`;
  });
  html += "</div>";
  root.innerHTML = html;
}

window.btcTest = { initBtcTab, onBtcMessage };
