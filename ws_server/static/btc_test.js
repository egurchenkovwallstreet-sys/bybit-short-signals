/* Вкладка тестовой BTC-стратегии (intraday + scalp). */

const FACTOR_LABELS = {
  d_veto_ok: "1D не против сделки",
  bias_4h: "4H: направление bias",
  bias_1h: "1H: цена по тренду",
  m30_structure: "30m: структура / EMA20",
  m15_vol: "15m: объём и EMA20",
  m5_trigger: "5m: EMA9 + RSI через 50",
  m1_trigger: "1m: scalp-триггер",
  vol_perp: "Объём 5m ≥ 1.2× SMA20",
  funding_perp: "Funding в пользу стороны",
  oi_perp: "OI не против (15m)",
  liq_perp: "Ликвидации в пользу идеи",
};

const FACTOR_HINTS = {
  d_veto_ok: "Дневной тренд не блокирует long/short (мягкий veto).",
  bias_4h: "4H EMA20/50 и цена согласованы с режимом LONG/SHORT/BOTH.",
  bias_1h: "На 1H цена по нужную сторону от EMA20.",
  m30_structure: "30m: цена у EMA20 в сторону сделки.",
  m15_vol: "15m: закрытие за EMA20 и объём выше среднего.",
  m5_trigger: "5m: импульс — EMA9 и пересечение RSI 50.",
  m1_trigger: "Scalp: 1m EMA9 и RSI; intraday — автоматически OK.",
  vol_perp: "Всплеск объёма на 5m относительно 20 баров.",
  funding_perp: "Long: funding не перегрет; short: funding ≥ порога.",
  oi_perp: "Изменение OI за ~15 мин не против позиции.",
  liq_perp: "За 15 мин доминируют ликвидации «нужной» стороны.",
};

const btcState = {
  data: null,
  chart: null,
  candleSeries: null,
  ema20Series: null,
  ema50Series: null,
  volumeSeries: null,
  interval: "5",
  followLive: true,
  selectedSignalId: null,
  userAtLiveEdge: true,
  priceLines: [],
  activeSymbol: null,
  symbolRows: [],
};

function barTimeForMarker(entrySec, candles) {
  if (!candles.length) return entrySec;
  let chosen = candles[0].time;
  for (const c of candles) {
    if (c.time <= entrySec) chosen = c.time;
    else break;
  }
  return chosen;
}

function collectChartMarkers() {
  const candles = currentCandles();
  const raw = btcState.data?.markers?.length
    ? btcState.data.markers
    : (btcState.data?.signals || []).map((s) => ({
        time: Math.floor(Number(s.entry_ts) / 1000),
        side: s.side,
        grade: s.grade,
        mode: s.mode,
        open: !s.exit_ts,
        signal_id: s.id,
      }));
  const markers = [];
  for (const m of raw.slice(0, 100)) {
    const entrySec = Number(m.time);
    const isLong = m.side === "long";
    const time = barTimeForMarker(entrySec, candles);
    markers.push({
      time,
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#3fb950" : "#f85149",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: `${isLong ? "LONG" : "SHORT"} ${m.grade || ""}${m.open ? " OPEN" : ""}`.trim(),
      size: 2,
    });
  }
  return markers;
}

function updateBtcPriceLines() {
  if (!btcState.candleSeries) return;
  btcState.priceLines.forEach((line) => {
    try {
      btcState.candleSeries.removePriceLine(line);
    } catch (_e) {
      /* ignore */
    }
  });
  btcState.priceLines = [];
  const signals = btcState.data?.signals || [];
  const show = signals.filter((s) => !s.exit_ts || String(s.id) === String(btcState.selectedSignalId)).slice(0, 12);
  for (const s of show) {
    const isLong = s.side === "long";
    const line = btcState.candleSeries.createPriceLine({
      price: Number(s.entry_price),
      color: isLong ? "#3fb950" : "#f85149",
      lineWidth: s.exit_ts ? 1 : 2,
      lineStyle: s.exit_ts ? 2 : 0,
      title: `${isLong ? "LONG" : "SHORT"} #${s.id}`,
    });
    btcState.priceLines.push(line);
  }
}

async function fetchBtcFallback() {
  try {
    const res = await fetch("/api/btc-test/snapshot");
    if (!res.ok) return;
    const data = await res.json();
    if (data && (data.signals?.length || data.candles_by_tf)) onBtcMessage(data);
  } catch (_err) {
    /* offline */
  }
}

async function fetchBtcSymbols() {
  try {
    const res = await fetch("/api/btc-test/symbols");
    if (!res.ok) return;
    const payload = await res.json();
    btcState.activeSymbol = payload.active || btcState.data?.symbol || "BTCUSDT";
    btcState.symbolRows = payload.symbols || [];
    renderBtcSymbolTable();
  } catch (_err) {
    /* offline */
  }
}

function renderBtcSymbolTable() {
  const body = document.querySelector("#btc-symbol-table tbody");
  if (!body) return;
  const rows = btcState.symbolRows || [];
  const active = btcState.activeSymbol || btcState.data?.symbol || "BTCUSDT";
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="3" class="quiet">Список загружается (нужны часовые свечи с коллектора)…</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map((row) => {
      const isActive = row.symbol === active;
      const sel = isActive ? " selected" : "";
      const action = isActive
        ? '<span class="quiet">актив</span>'
        : '<button type="button" class="btc-sym-pick">Выбрать</button>';
      return `<tr class="btc-sym-row${sel}" data-symbol="${row.symbol}">
        <td>${row.symbol}</td>
        <td>${Number(row.volatility_pct || 0).toFixed(2)}</td>
        <td>${action}</td>
      </tr>`;
    })
    .join("");
  body.querySelectorAll(".btc-sym-pick").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const sym = btn.closest(".btc-sym-row")?.dataset.symbol;
      if (sym) void pickBtcSymbol(sym);
    });
  });
}

async function pickBtcSymbol(symbol) {
  const meta = document.getElementById("btc-meta");
  try {
    const res = await fetch("/api/btc-test/symbol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    });
    if (!res.ok) {
      if (meta) meta.textContent = "Не удалось сменить актив";
      return;
    }
    btcState.activeSymbol = symbol;
    btcState.selectedSignalId = null;
    renderBtcSymbolTable();
    if (meta) meta.textContent = `Переключаем на ${symbol}… (сервис подтянет свечи за несколько секунд)`;
  } catch (_err) {
    if (meta) meta.textContent = "Ошибка сети при смене актива";
  }
}

function resizeBtcChart() {
  const box = document.getElementById("btc-chart");
  if (!box || !btcState.chart) return;
  const w = box.clientWidth;
  const h = box.clientHeight || 560;
  if (w > 0) btcState.chart.resize(w, h);
}

function initBtcTab() {
  const box = document.getElementById("btc-chart");
  if (!box) return;
  if (btcState.chart) {
    void fetchBtcSymbols();
    requestAnimationFrame(() => {
      resizeBtcChart();
      requestAnimationFrame(() => {
        resizeBtcChart();
        renderBtcChart(true);
      });
    });
    return;
  }

  btcState.chart = LightweightCharts.createChart(box, {
    layout: { background: { color: "#0d1117" }, textColor: "#c9d1d9" },
    grid: { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
    timeScale: { timeVisible: true, rightOffset: 14, barSpacing: 7 },
    rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.22 } },
  });

  btcState.candleSeries = btcState.chart.addCandlestickSeries({
    upColor: "#3fb950",
    downColor: "#f85149",
    borderVisible: false,
    wickUpColor: "#3fb950",
    wickDownColor: "#f85149",
  });
  btcState.ema20Series = btcState.chart.addLineSeries({ color: "#58a6ff", lineWidth: 2, title: "EMA20" });
  btcState.ema50Series = btcState.chart.addLineSeries({ color: "#d2a8ff", lineWidth: 2, title: "EMA50" });
  btcState.volumeSeries = btcState.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
  });
  btcState.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  new ResizeObserver(() => resizeBtcChart()).observe(box);
  window.addEventListener("resize", resizeBtcChart);

  document.querySelectorAll("[data-btc-interval]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btcState.interval = btn.dataset.btcInterval;
      document.querySelectorAll("[data-btc-interval]").forEach((b) => b.classList.toggle("active", b === btn));
      renderBtcChart(true);
    });
  });

  const follow = document.getElementById("btc-follow");
  if (follow) {
    follow.addEventListener("change", () => {
      btcState.followLive = follow.checked;
      if (btcState.followLive) {
        btcState.userAtLiveEdge = true;
        scrollLive();
      }
    });
  }

  btcState.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (!range || !btcState.data) return;
    const candles = currentCandles();
    if (!candles.length) return;
    const lastIdx = candles.length - 1;
    btcState.userAtLiveEdge = range.to >= lastIdx - 2;
  });

  void fetchBtcSymbols();

  requestAnimationFrame(() => {
    resizeBtcChart();
    if (btcState.data) renderBtcChart(true);
    else fetchBtcFallback();
  });
}

function currentCandles() {
  if (!btcState.data) return [];
  const byTf = btcState.data.candles_by_tf || {};
  return byTf[btcState.interval] || btcState.data.candles || [];
}

function emaLine(candles, period) {
  if (candles.length < period) return [];
  const closes = candles.map((c) => c.close);
  const k = 2 / (period + 1);
  let prev = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const out = [{ time: candles[period - 1].time, value: prev }];
  for (let i = period; i < closes.length; i++) {
    prev = closes[i] * k + prev * (1 - k);
    out.push({ time: candles[i].time, value: prev });
  }
  return out;
}

function volumeBars(candles) {
  return candles.map((c) => ({
    time: c.time,
    value: c.volume != null ? c.volume : 0,
    color: c.close >= c.open ? "rgba(63,185,80,0.45)" : "rgba(248,81,73,0.45)",
  }));
}

function scrollLive() {
  if (!btcState.chart || !btcState.followLive || !btcState.userAtLiveEdge) return;
  try {
    const ts = btcState.chart.timeScale();
    if (typeof ts.scrollToPosition === "function") ts.scrollToPosition(0, false);
    else if (typeof ts.scrollToRealTime === "function") ts.scrollToRealTime();
  } catch (_err) {
    /* старые версии библиотеки */
  }
}

function onBtcMessage(incoming) {
  let data = incoming;
  if (btcState.data && data) {
    const noCandles = !data.candles_by_tf || !Object.keys(data.candles_by_tf).length;
    if (noCandles && btcState.data.candles_by_tf) {
      data = {
        ...data,
        candles_by_tf: btcState.data.candles_by_tf,
        candles: btcState.data.candles,
        last_price: data.last_price ?? btcState.data.last_price,
        bias: data.bias ?? btcState.data.bias,
        funding: data.funding ?? btcState.data.funding,
      };
    }
  }
  const prevSymbol = btcState.data?.symbol;
  btcState.data = data;
  if (data?.symbol && data.symbol !== prevSymbol) {
    btcState.activeSymbol = data.symbol;
    btcState.selectedSignalId = null;
  }
  const btcView = document.getElementById("view-btc");
  if (btcView && !btcView.hidden) {
    initBtcTab();
    void fetchBtcSymbols();
  }
  renderBtcHeader();
  renderBtcChart(false);
  renderBtcJournal();
  renderBtcAnalytics();
  renderBtcExtendedStats();
  if (btcState.selectedSignalId) renderBtcDecode(findSignal(btcState.selectedSignalId));
}

function renderBtcHeader() {
  const d = btcState.data;
  if (!d) return;
  const el = document.getElementById("btc-meta");
  if (!el) return;
  const fr = d.funding != null ? (Number(d.funding) * 100).toFixed(4) + "%" : "—";
  const opens = (d.signals || []).filter((s) => !s.exit_ts);
  const openHint = opens.length
    ? ` · Сделки OPEN: ${opens.map((s) => `${s.side.toUpperCase()} (${s.mode})`).join(", ")}`
    : " · Сделок OPEN нет (bias ≠ вход; ждём grade A/B/C)";
  const sym = d.symbol || btcState.activeSymbol || "BTCUSDT";
  el.textContent = `Актив: ${sym} · Режим: ${d.bias || "—"} · Финансирование: ${fr} · Цена: ${d.last_price ?? "—"} · TF: ${btcState.interval}${openHint}`;
}

function renderBtcChart(forceTf) {
  if (!btcState.data) return;
  if (!btcState.candleSeries) return;
  const candles = currentCandles();
  const root = document.getElementById("btc-chart");
  if (!candles.length) {
    if (root) {
      root.dataset.empty = "1";
    }
    return;
  }
  if (root) root.dataset.empty = "0";

  const withVol = candles.map((c) => ({
    ...c,
    volume: c.volume ?? c.v ?? 0,
  }));

  btcState.candleSeries.setData(withVol);
  btcState.ema20Series.setData(emaLine(withVol, 20));
  btcState.ema50Series.setData(emaLine(withVol, 50));
  btcState.volumeSeries.setData(volumeBars(withVol));

  btcState.candleSeries.setMarkers(collectChartMarkers());
  updateBtcPriceLines();

  if (forceTf || (btcState.followLive && btcState.userAtLiveEdge)) scrollLive();
}

function findSignal(id) {
  return (btcState.data?.signals || []).find((s) => String(s.id) === String(id));
}

function renderBtcJournal() {
  const body = document.querySelector("#btc-signal-table tbody");
  if (!body || !btcState.data) return;
  const rows = btcState.data.signals || [];
  body.innerHTML = rows
    .slice(0, 120)
    .map((s) => {
      const checks = s.checks || {};
      const hit = Object.keys(FACTOR_LABELS).filter((k) => checks[k]).length;
      const pnl = s.pnl_pct != null ? Number(s.pnl_pct).toFixed(2) : "…";
      const out = s.outcome || "OPEN";
      const sel = String(s.id) === String(btcState.selectedSignalId) ? " selected" : "";
      return `<tr class="btc-row${sel}" data-signal-id="${s.id}">
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

  body.querySelectorAll(".btc-row").forEach((row) => {
    row.addEventListener("click", () => {
      btcState.selectedSignalId = row.dataset.signalId;
      renderBtcJournal();
      renderBtcDecode(findSignal(btcState.selectedSignalId));
      document.getElementById("btc-decode")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  if (!btcState.selectedSignalId && rows[0]) {
    btcState.selectedSignalId = rows[0].id;
    renderBtcDecode(rows[0]);
  }
}

function renderBtcDecode(signal) {
  const root = document.getElementById("btc-decode-body");
  if (!root) return;
  if (!signal) {
    root.innerHTML = "<p class=\"quiet\">Нет данных.</p>";
    return;
  }
  const checks = signal.checks || {};
  const list = Object.keys(FACTOR_LABELS)
    .map((key) => {
      const ok = !!checks[key];
      const label = FACTOR_LABELS[key];
      const hint = FACTOR_HINTS[key] || "";
      return `<li class="${ok ? "yes" : "no"}"><strong>${ok ? "✓" : "✗"} ${label}</strong><br><span class="quiet">${hint}</span></li>`;
    })
    .join("");

  root.innerHTML = `
    <div class="decode-head">
      <span class="grade-${signal.grade}">Grade ${signal.grade}</span>
      <span>Score ${signal.score}</span>
      <span>${signal.mode} · ${signal.side}</span>
      <span>вход ${Number(signal.entry_price).toFixed(2)}</span>
      <span>${new Date(signal.entry_ts).toLocaleString()}</span>
    </div>
    <p class="quiet">Зелёные пункты участвовали в решении; красные — не выполнены (сигнал мог пройти за счёт других факторов и порога режима).</p>
    <ul class="decode-checks">${list}</ul>
  `;
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

function renderBtcExtendedStats() {
  const root = document.getElementById("btc-stats-extended");
  if (!root || !btcState.data) return;
  const a = btcState.data.analytics || {};
  const byMode = a.by_mode || {};
  const bySide = a.by_side || {};
  const reasons = a.exit_reasons || {};
  const equity = a.equity || [];

  let html = `<div class="btc-stats-grid">
    <div><span class="label">Всего в журнале</span><b>${a.total ?? 0}</b></div>
    <div><span class="label">Открыто сейчас</span><b>${a.open ?? 0}</b></div>
    <div><span class="label">Ср. WIN</span><b class="win">${a.avg_win_pnl ?? 0}%</b></div>
    <div><span class="label">Ср. LOSS</span><b class="loss">${a.avg_loss_pnl ?? 0}%</b></div>
  </div>`;

  html += "<h4>Режим и сторона (закрытые)</h4><table class=\"btc-mini-table\"><tr><th></th><th>Сделок</th><th>Win%</th><th>Ср.PnL%</th></tr>";
  for (const [label, block] of [
    ["Intraday", byMode.intraday],
    ["Scalp", byMode.scalp],
    ["Long", bySide.long],
    ["Short", bySide.short],
  ]) {
    if (!block) continue;
    html += `<tr><td>${label}</td><td>${block.trades}</td><td>${block.win_rate}%</td><td>${block.avg_pnl}%</td></tr>`;
  }
  html += "</table>";

  if (Object.keys(reasons).length) {
    html += `<h4>Выходы</h4><p>${Object.entries(reasons)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" · ")}</p>`;
  }

  if (equity.length) {
    html += `<h4>Кривая PnL (последние ${equity.length} закрытий; плечо и комиссия open+close taker)</h4>`;
    html += `<div class="btc-equity-scroll"><table class="btc-mini-table"><tr><th>#</th><th>PnL%</th><th>Кум.</th></tr>`;
    html += equity
      .slice()
      .reverse()
      .map(
        (e) =>
          `<tr><td>${e.id}</td><td class="${e.pnl_pct >= 0 ? "win" : "loss"}">${e.pnl_pct}</td><td>${e.cum_pnl_pct}</td></tr>`
      )
      .join("");
    html += "</table></div>";
  }

  root.innerHTML = html;
}

window.btcTest = { initBtcTab, onBtcMessage, fetchBtcFallback, fetchBtcSymbols };
