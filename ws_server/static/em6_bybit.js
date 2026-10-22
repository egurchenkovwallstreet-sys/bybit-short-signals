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
  let ema60Series = null;
  let lineSeries = [];

  function renderSummary(data) {
    const s = data.summary || {};
    const el = document.getElementById("em6b-summary");
    if (!el) return;
    const pnlClosed = Number(s.total_pnl_closed || 0);
    const pnlOpen = Number(s.total_unrealised_pnl || 0);
    const src = s.data_source === "bybit" ? "Bybit Demo" : "локальный журнал";
    const marginAvail = Number(s.wallet_available ?? s.wallet_equity ?? 0);
    const balText = marginAvail > 0 ? `$${num(marginAvail)}` : "—";
    el.innerHTML = `
      <div class="paper-card em6b-balance-main"><span class="label">Доступная маржа USDT</span><div class="value">${balText}</div><span class="hint">${src}</span></div>
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
    const target = Number(r.trail_roe_target ?? r.trail_roe_pct ?? 0);
    const onEx = Number(r.trail_roe_exchange ?? 0);
    if (trail > 0 || target > 0 || onEx > 0) {
      if (onEx > 0) {
        if (target > 0 && Math.abs(onEx - target) > 1.5) {
          return `trail ${onEx.toFixed(1)}% (цель ${target.toFixed(1)}%)`;
        }
        return `trail ${onEx.toFixed(1)}% ROE`;
      }
      if (target > 0) return `trail цель ${target.toFixed(1)}% ROE`;
      return `trail ${num(trail)}`;
    }
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
      <td>${fmtStop(r)}${r.trail_armed ? " ✓" : ""}</td>
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
    return `<tr class="em6b-cand-row" data-symbol="${c.symbol}">
      <td><strong>${c.symbol}</strong></td>
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
                `<li class="em6b-cand-pick" data-symbol="${c.symbol}"><strong>${c.symbol}</strong> ${c.side} · ${Number(c.stretch_pct).toFixed(2)}% · ${c.phase}</li>`
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
        <th>Пик</th><th>Arm band</th></tr></thead><tbody>${rows || "<tr><td colspan='7'>Нет претендентов (отрыв от EMA60 ≥6%)</td></tr>"}</tbody>`;
    }
    bindChartClicks();
  }

  let chartInterval = "1";
  let lastChartCtx = null;
  let selectedChartSymbol = null;
  let chartLoadSeq = 0;
  let chartRefreshTimer = null;
  let chartViewKey = "";
  let lastCandleBars = [];
  let priceLines = [];
  const candleCache = new Map();
  const ema60Cache = new Map();
  const CHART_GRID_LINE_CAP = 55;
  const GRID_FLOOR_PCT = 6;
  const GRID_STEP_PCT = 0.5;
  const GRID_AWAY_PCT = 3;

  function findOpenTrade(symbol) {
    return (lastData?.open_trades || []).find((r) => r.symbol === symbol);
  }

  function findCandidate(symbol) {
    return (lastData?.candidates || []).find((r) => r.symbol === symbol);
  }

  function candleTime(raw, interval) {
    const BC = window.boardChart;
    if (BC?.candleTime) return BC.candleTime(raw, interval);
    const n = Number(raw);
    const sec = n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
    if (!sec) return 0;
    if (interval === "D") {
      const d = new Date(sec * 1000);
      return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
    }
    return sec + 3 * 3600;
  }

  function parseCandleBars(rawCandles, interval) {
    const BC = window.boardChart;
    const byTime = new Map();
    for (const candle of rawCandles || []) {
      const raw = candle.timestamp ?? candle.time ?? candle.t;
      const time = candleTime(raw, interval);
      if (!time) continue;
      const open = Number(candle.open ?? candle.o);
      const high = Number(candle.high ?? candle.h);
      const low = Number(candle.low ?? candle.l);
      const close = Number(candle.close ?? candle.c);
      if ([open, high, low, close].some((x) => Number.isNaN(x))) continue;
      const key = typeof time === "object" ? JSON.stringify(time) : String(time);
      const sec = BC?.utcSecFromRaw ? BC.utcSecFromRaw(raw) : 0;
      byTime.set(key, { time, open, high, low, close, _utcSec: sec || undefined });
    }
    return [...byTime.values()].sort((a, b) => {
      const ta = typeof a.time === "object" ? Date.UTC(a.time.year, a.time.month - 1, a.time.day) : a.time;
      const tb = typeof b.time === "object" ? Date.UTC(b.time.year, b.time.month - 1, b.time.day) : b.time;
      return ta - tb;
    });
  }

  async function fetchCandles(symbol, interval, forceRefresh) {
    const bars = interval === "1" ? "360" : "240";
    const key = `${symbol}:${interval}`;
    if (!forceRefresh && candleCache.has(key)) {
      return candleCache.get(key);
    }
    const q = new URLSearchParams({ interval, bars, refresh: forceRefresh ? "1" : "0" });
    const resp = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
    if (!resp.ok) return [];
    const payload = await resp.json();
    const parsed = parseCandleBars(payload.candles || payload.klines || [], interval);
    if (parsed.length) candleCache.set(key, parsed);
    return parsed;
  }

  function stretchAtPrice(price, ema) {
    const p = Number(price);
    const e = Number(ema);
    if (!e || e <= 0 || !p || p <= 0) return 0;
    return (Math.abs(p - e) / e) * 100;
  }

  function gridAnchorStretch(peakStretch, currentStretch) {
    const floor = Number(lastData?.summary?.stretch_floor_pct) || GRID_FLOOR_PCT;
    return Math.max(floor, Number(peakStretch) || 0, Number(currentStretch) || 0);
  }

  function levelBandStretches(anchorStretch) {
    const floor = Number(lastData?.summary?.stretch_floor_pct) || GRID_FLOOR_PCT;
    const step = GRID_STEP_PCT;
    const away = GRID_AWAY_PCT;
    const hi = anchorStretch + away;
    const seen = new Set();
    for (let x = floor; x <= hi + 1e-9; x += step) {
      seen.add(Math.round(x * 10000) / 10000);
      seen.add(Math.round((x + step) * 10000) / 10000);
    }
    return [...seen].sort((a, b) => a - b);
  }

  function timeSortKey(time) {
    if (typeof time === "object") return Date.UTC(time.year, time.month - 1, time.day);
    return Number(time);
  }

  /** Линия EMA60 (5m) на таймлайне графика (1m или 5m). */
  function ema60LineOnChart(chartBars, bars5, chartInterval) {
    const BC = window.boardChart;
    if (!chartBars?.length || !bars5?.length || !BC?.ema333EngineLineData) return [];
    const src5 = chartInterval === "5" ? chartBars : bars5;
    const { center } = BC.ema333EngineLineData(src5, { interval: "5" });
    if (!center.length) return [];
    if (chartInterval === "5") return center;
    let j = 0;
    const out = [];
    for (const bar of chartBars) {
      const tk = timeSortKey(bar.time);
      while (j + 1 < center.length && timeSortKey(center[j + 1].time) <= tk) j += 1;
      if (timeSortKey(center[j].time) <= tk) {
        out.push({ time: bar.time, value: center[j].value });
      }
    }
    return out;
  }

  async function resolveEma60(symbol, ctx, forceRefresh) {
    const fromCtx = Number(ctx?.ema60 || 0);
    if (fromCtx > 0 && !forceRefresh) return fromCtx;
    const key = symbol;
    if (!forceRefresh && ema60Cache.has(key)) return ema60Cache.get(key);
    const bars5 = await fetchCandles(symbol, "5", forceRefresh);
    const BC = window.boardChart;
    if (!bars5.length || !BC?.ema333EngineLineData) {
      return fromCtx;
    }
    const { center } = BC.ema333EngineLineData(bars5, { interval: "5" });
    const ema = center.length ? Number(center[center.length - 1].value) : 0;
    if (ema > 0) ema60Cache.set(key, ema);
    return ema > 0 ? ema : fromCtx;
  }

  function enrichChartCtx(ctx) {
    const sym = ctx?.symbol;
    if (!sym) return ctx;
    const cand = findCandidate(sym);
    const out = { ...ctx };
    if ((!out.ema60 || out.ema60 <= 0) && cand?.ema60) out.ema60 = cand.ema60;
    if (!out.peak_stretch && cand?.peak_stretch) out.peak_stretch = cand.peak_stretch;
    if (!out.levels?.length && cand?.levels?.length) out.levels = cand.levels;
    return out;
  }

  function markChartSelectedRow(symbol) {
    document.querySelectorAll(".em6b-chart-selected").forEach((el) => el.classList.remove("em6b-chart-selected"));
    if (!symbol) return;
    document.querySelectorAll(`tr.em6b-open-row[data-symbol="${symbol}"], tr.em6b-cand-row[data-symbol="${symbol}"]`).forEach((el) => {
      el.classList.add("em6b-chart-selected");
    });
  }

  function scheduleChartRefreshFromSnapshot() {
    if (!selectedChartSymbol) return;
    clearTimeout(chartRefreshTimer);
    chartRefreshTimer = setTimeout(() => {
      const trade = findOpenTrade(selectedChartSymbol);
      if (trade) {
        showEm6Chart({ ...trade, kind: "open" }, false);
        return;
      }
      const cand = findCandidate(selectedChartSymbol);
      if (cand) showEm6Chart({ ...cand, kind: "candidate" }, false);
    }, 400);
  }

  function bindChartTf() {
    const wrap = document.getElementById("em6b-chart-wrap");
    if (!wrap || wrap.dataset.tfBound) return;
    wrap.dataset.tfBound = "1";
    wrap.querySelectorAll(".em6b-iv-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const iv = btn.getAttribute("data-iv") || "1";
        if (iv === chartInterval) return;
        chartInterval = iv;
        wrap.querySelectorAll(".em6b-iv-btn").forEach((b) => {
          b.classList.toggle("active", b.getAttribute("data-iv") === iv);
        });
        if (lastChartCtx) showEm6Chart(lastChartCtx, true);
      });
    });
  }

  function priceAtStretch(ema, side, stretchPct) {
    const e = Number(ema);
    const s = Number(stretchPct);
    if (!e || e <= 0) return 0;
    if (side === "long") return e * (1 - s / 100);
    return e * (1 + s / 100);
  }

  /** Уникальные границы сетки в % отрыва (6, 6.25, 6.5 …). */
  function gridStretchLevels(ctx, bandRows) {
    const seen = new Set();
    const add = (v) => {
      const n = Number(v);
      if (Number.isFinite(n)) seen.add(Math.round(n * 10000) / 10000);
    };
    if (bandRows?.length) {
      bandRows.forEach((lv) => {
        add(lv.stretch_lo);
        add(lv.stretch_hi);
      });
    } else {
      for (const band of ctx.levels || []) {
        const lo = Array.isArray(band) ? band[0] : band.stretch_lo;
        const hi = Array.isArray(band) ? band[1] : band.stretch_hi;
        add(lo);
        add(hi);
      }
    }
    return [...seen].sort((a, b) => a - b);
  }

  function ensureChart(el) {
    if (chartApi) return;
    el.innerHTML = "";
    const w = el.clientWidth || el.parentElement?.clientWidth || 640;
    chartApi = window.LightweightCharts.createChart(el, {
      width: w,
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
    ema60Series = chartApi.addLineSeries({
      color: "#f0b429",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: "EMA60 5m",
    });
    const resize = () => {
      if (chartApi && el.clientWidth > 0) chartApi.resize(el.clientWidth, 360);
    };
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(el);
    requestAnimationFrame(resize);
  }

  function applyCandleBarUpdates(bars) {
    if (!chartSeries || !bars.length) return;
    const prev = lastCandleBars;
    if (!prev.length) {
      chartSeries.setData(bars);
      lastCandleBars = bars;
      return;
    }
    const sameStart =
      timeSortKey(prev[0].time) === timeSortKey(bars[0].time);
    if (!sameStart || bars.length < prev.length) {
      chartSeries.setData(bars);
      lastCandleBars = bars;
      return;
    }
    if (bars.length === prev.length) {
      chartSeries.update(bars[bars.length - 1]);
    } else {
      for (let i = prev.length; i < bars.length; i += 1) {
        chartSeries.update(bars[i]);
      }
    }
    lastCandleBars = bars;
  }

  function clearPriceLinesOnly() {
    priceLines.forEach((pl) => {
      try {
        chartSeries.removePriceLine(pl);
      } catch (_) {
        /* ignore */
      }
    });
    priceLines = [];
  }

  function clearOverlays() {
    lineSeries.forEach((s) => {
      try {
        chartApi.removeSeries(s);
      } catch (_) {
        /* ignore */
      }
    });
    lineSeries = [];
    priceLines.forEach((pl) => {
      try {
        chartSeries.removePriceLine(pl);
      } catch (_) {
        /* ignore */
      }
    });
    priceLines = [];
    if (ema60Series) ema60Series.setData([]);
  }

  function addPriceLine(price, color, title) {
    const p = Number(price);
    if (!chartSeries || !p || p <= 0) return;
    try {
      priceLines.push(
        chartSeries.createPriceLine({
          price: p,
          color,
          lineWidth: 1,
          title,
        })
      );
    } catch (_) {
      /* ignore */
    }
  }

  async function showEm6Chart(ctx, forceRefresh) {
    const wrap = document.getElementById("em6b-chart-wrap");
    const title = document.getElementById("em6b-chart-title");
    const el = document.getElementById("em6b-chart");
    if (!wrap || !el || !ctx || !window.LightweightCharts) return;
    const loadSeq = ++chartLoadSeq;
    const base = enrichChartCtx(ctx);
    lastChartCtx = base;
    selectedChartSymbol = base.symbol;
    markChartSelectedRow(base.symbol);
    bindChartTf();
    wrap.hidden = false;
    const kind = base.kind === "candidate" ? "претендент" : "позиция";
    const tfLabel = chartInterval === "1" ? "1m" : "5m";
    const viewKey = `${base.symbol}:${chartInterval}`;
    const resetView = !!forceRefresh || viewKey !== chartViewKey;
    if (resetView) chartViewKey = viewKey;

    ensureChart(el);
    const prevVisibleRange =
      !resetView && chartApi
        ? chartApi.timeScale().getVisibleLogicalRange()
        : null;

    if (resetView) {
      title.textContent = `${base.symbol} · ${base.side} · ${kind} · ${tfLabel} · загрузка…`;
      clearOverlays();
      if (chartSeries) chartSeries.setData([]);
      lastCandleBars = [];
    } else {
      clearPriceLinesOnly();
    }

    const refresh = !!forceRefresh;
    const bars = await fetchCandles(base.symbol, chartInterval, refresh);
    const bars5 =
      chartInterval === "5" ? bars : await fetchCandles(base.symbol, "5", refresh);
    if (loadSeq !== chartLoadSeq) return;

    title.textContent = `${base.symbol} · ${base.side} · ${kind} · ${tfLabel} · EMA60 (5m) + сетка`;
    if (!bars.length) {
      title.textContent += " — нет свечей (обновите позже)";
      if (resetView) chartSeries.setData([]);
      return;
    }
    if (resetView) {
      chartSeries.setData(bars);
      lastCandleBars = bars;
    } else {
      applyCandleBarUpdates(bars);
    }

    const emaLine = ema60LineOnChart(bars, bars5, chartInterval);
    if (ema60Series && emaLine.length) {
      ema60Series.setData(emaLine);
    }
    const ema =
      emaLine.length > 0
        ? Number(emaLine[emaLine.length - 1].value)
        : await resolveEma60(base.symbol, base, refresh);

    const mark =
      Number(base.mark_price || 0) > 0 ? Number(base.mark_price) : Number(bars[bars.length - 1].close);

    const side = base.side || "short";
    const bandRows = base.grid_levels?.length ? base.grid_levels : null;
    let stretches = gridStretchLevels(base, bandRows);
    if (!stretches.length && ema > 0) {
      const cur = stretchAtPrice(mark, ema);
      const peak = Number(base.peak_stretch) || cur;
      stretches = levelBandStretches(gridAnchorStretch(peak, cur));
    }
    if (stretches.length > CHART_GRID_LINE_CAP) {
      const step = Math.ceil(stretches.length / CHART_GRID_LINE_CAP);
      stretches = stretches.filter((_, i) => i % step === 0 || i === stretches.length - 1);
    }
    stretches.forEach((stretchPct) => {
      const p = priceAtStretch(ema, side, stretchPct);
      if (p > 0) addPriceLine(p, "rgba(160, 120, 255, 0.85)", `${stretchPct}%`);
    });

    const entry = Number(base.entry_price || 0);
    if (entry > 0) addPriceLine(entry, "#ffffff", "Entry");
    if (mark > 0) addPriceLine(mark, "#58a6ff", "Mark");

    if (resetView) {
      chartApi.timeScale().fitContent();
    } else if (prevVisibleRange) {
      try {
        chartApi.timeScale().setVisibleLogicalRange(prevVisibleRange);
      } catch (_) {
        /* ignore */
      }
    }
    requestAnimationFrame(() => {
      if (loadSeq !== chartLoadSeq) return;
      if (chartApi && el.clientWidth > 0) chartApi.resize(el.clientWidth, 360);
      if (!resetView && prevVisibleRange) {
        try {
          chartApi.timeScale().setVisibleLogicalRange(prevVisibleRange);
        } catch (_) {
          /* ignore */
        }
      }
    });
  }

  function openChartForSymbol(symbol) {
    selectedChartSymbol = symbol;
    const trade = findOpenTrade(symbol);
    if (trade) {
      showEm6Chart({ ...trade, kind: "open" }, true);
      return;
    }
    const cand = findCandidate(symbol);
    if (cand) showEm6Chart({ ...cand, kind: "candidate" }, true);
  }

  function bindChartClicks() {
    const open = document.getElementById("em6b-open");
    if (open && !open.dataset.chartBound) {
      open.dataset.chartBound = "1";
      open.addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr.em6b-open-row");
        if (!tr) return;
        openChartForSymbol(tr.getAttribute("data-symbol"));
      });
    }
    const candTable = document.getElementById("em6b-candidates");
    if (candTable && !candTable.dataset.chartBound) {
      candTable.dataset.chartBound = "1";
      candTable.addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr.em6b-cand-row");
        if (!tr) return;
        openChartForSymbol(tr.getAttribute("data-symbol"));
      });
    }
    const candGrid = document.getElementById("em6b-candidates-grid");
    if (candGrid && !candGrid.dataset.chartBound) {
      candGrid.dataset.chartBound = "1";
      candGrid.addEventListener("click", (ev) => {
        const li = ev.target.closest(".em6b-cand-pick");
        if (!li) return;
        openChartForSymbol(li.getAttribute("data-symbol"));
      });
    }
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
      bindChartClicks();
      markChartSelectedRow(selectedChartSymbol);
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
    scheduleChartRefreshFromSnapshot();
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

  setInterval(() => {
    const view = document.getElementById("view-em6-bybit");
    if (view && !view.hidden) fetchFallback();
  }, 1000);
})();
