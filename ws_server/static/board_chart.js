/* Общий график досок: свечи, объём, стакан по цене, prefetch свечей. */

window.boardChart = {
  TF: [
    ["1", "1m"],
    ["5", "5m"],
    ["15", "15m"],
    ["30", "30m"],
    ["60", "1H"],
    ["240", "4H"],
    ["D", "1D"],
  ],
  FETCH_DAYS: 30,
  INTERVAL_MINUTES: { 1: 1, 5: 5, 15: 15, 30: 30, 60: 60, 240: 240, D: 1440 },
  INTERVAL_SEC: { 1: 60, 5: 300, 15: 900, 30: 1800, 60: 3600, 240: 14400, D: 86400 },
  PREFETCH_CONCURRENCY: 4,
  PREFETCH_COOLDOWN_MS: 90_000,
  _assetCache: new Map(),
  _prefetchQueue: [],
  _prefetchActive: 0,
  _prefetchInflight: new Set(),
  /** Стакан в боковой панели: глубина ±10% от текущей цены. */
  BOOK_DEPTH_PCT: 0.1,
  /** Стакан на графике: шире диапазон, крупнее бины. */
  BOOK_CHART: {
    depthPct: 0.35,
    binTicks: 30,
  },
  /** Оценочные зоны ликвидации на графике (слева). */
  LIQ_CHART: {
    depthPct: 0.35,
    refreshMs: 45_000,
    /** Макс. ширина полоски — доля ширины графика от левого края. */
    widthPct: 0.3,
  },
  /** Суммы ликвидаций у свечей (Buy=long, Sell=short). */
  LIQ_CANDLE: {
    minUsd: 500,
    maxTooltipRows: 48,
  },
  _liqZonesFetch: new Map(),
  BOOK_PANEL: {
    maxGridRowsPerSide: 320,
    /** Объединение уровней: N тиков цены в одну строку (сумма объёма). */
    binTicks: 5,
  },
  _bookFetch: new Map(),

  normalizeBookSide(side) {
    const out = [];
    if (!side) return out;
    if (Array.isArray(side)) {
      for (const row of side) {
        if (Array.isArray(row) && row.length >= 2) {
          out.push([Number(row[0]), Number(row[1])]);
        } else if (row && typeof row === "object") {
          const p = Number(row.price ?? row[0]);
          const s = Number(row.size ?? row[1] ?? row.qty);
          if (p > 0 && s > 0) out.push([p, s]);
        }
      }
      return out;
    }
    if (typeof side === "object") {
      for (const [p, s] of Object.entries(side)) {
        const price = Number(p);
        const size = Number(s);
        if (price > 0 && size > 0) out.push([price, size]);
      }
    }
    return out;
  },

  inferPriceTick(price) {
    const p = Math.abs(Number(price));
    if (!p || Number.isNaN(p)) return 0.0001;
    const exp = Math.floor(Math.log10(p));
    return 10 ** (exp - 4);
  },

  bookMidPrice(book, refPrice) {
    const bids = window.boardChart.normalizeBookSide(book?.bids);
    const asks = window.boardChart.normalizeBookSide(book?.asks);
    const bestBid = bids.length ? Math.max(...bids.map(([p]) => p)) : 0;
    const bestAsk = asks.length ? Math.min(...asks.map(([p]) => p)) : 0;
    const mid = Number(refPrice);
    if (bestBid > 0 && bestAsk > 0) return (bestBid + bestAsk) / 2;
    if (mid > 0 && !Number.isNaN(mid)) return mid;
    if (bestBid > 0) return bestBid;
    if (bestAsk > 0) return bestAsk;
    return 0;
  },

  wallTag(wall) {
    if (!wall) return "";
    const kind =
      wall.kind === "holding"
        ? "стена"
        : wall.kind === "building"
          ? "нарастает"
          : wall.kind === "spoof"
            ? "сняли"
            : "";
    if (!kind) return "";
    return `<span class="psc-book-wall psc-book-wall--${wall.kind}">${kind}</span>`;
  },

  bookBinSize(refPrice, binTicks) {
    const tick = window.boardChart.inferPriceTick(refPrice);
    const n = Math.max(1, Number(binTicks ?? window.boardChart.BOOK_PANEL.binTicks) || 10);
    return tick * n;
  },

  bucketPrice(price, step) {
    if (!(step > 0)) return price;
    const idx = Math.floor(Number(price) / step + 1e-12);
    return idx * step;
  },

  aggregateBookLevels(pairs, isBid, refPrice, binTicks) {
    const BC = window.boardChart;
    const n = Math.max(1, Number(binTicks) || 1);
    if (n <= 1) return BC.mergeBookLevels(pairs, isBid);
    const step = BC.bookBinSize(refPrice, n);
    const m = new Map();
    for (const [priceRaw, sizeRaw] of pairs) {
      const price = Number(priceRaw);
      const size = Number(sizeRaw);
      if (!(price > 0) || !(size > 0)) continue;
      const bucket = BC.bucketPrice(price, step);
      m.set(bucket, (m.get(bucket) || 0) + size);
    }
    const out = [...m.entries()].map(([price, size]) => ({ price, size, bid: isBid, step }));
    if (isBid) out.sort((a, b) => b.price - a.price);
    else out.sort((a, b) => a.price - b.price);
    return out;
  },

  /** Все ценовые бины в ±band от mid (в т.ч. без заявок — объём 0). */
  fillBookSideGrid(mid, lo, hi, step, isBid, sizeByPrice) {
    const BC = window.boardChart;
    const rows = [];
    if (!(step > 0) || !(mid > 0)) return rows;
    const cap = BC.BOOK_PANEL.maxGridRowsPerSide ?? 320;
    const eps = step * 1e-6;
    if (isBid) {
      let p = BC.bucketPrice(mid - step, step);
      while (p >= mid - eps) p = BC.bucketPrice(p - step, step);
      while (p >= lo - eps && rows.length < cap) {
        rows.push({ price: p, size: sizeByPrice.get(p) || 0, step, bid: true });
        p = BC.bucketPrice(p - step, step);
      }
    } else {
      let p = BC.bucketPrice(mid + step, step);
      while (p <= mid + eps) p = BC.bucketPrice(p + step, step);
      while (p <= hi + eps && rows.length < cap) {
        rows.push({ price: p, size: sizeByPrice.get(p) || 0, step, bid: false });
        p = BC.bucketPrice(p + step, step);
      }
    }
    return rows;
  },

  mergeBookLevels(pairs, isBid) {
    const m = new Map();
    for (const [priceRaw, sizeRaw] of pairs) {
      const price = Number(priceRaw);
      const size = Number(sizeRaw);
      if (!(price > 0) || !(size > 0)) continue;
      m.set(price, (m.get(price) || 0) + size);
    }
    const out = [...m.entries()].map(([price, size]) => ({ price, size, bid: isBid }));
    if (isBid) out.sort((a, b) => b.price - a.price);
    else out.sort((a, b) => a.price - b.price);
    return out;
  },

  prepareBookDepth(book, refPrice, depthPct, binTicksOverride) {
    const BC = window.boardChart;
    const band = depthPct ?? BC.BOOK_DEPTH_PCT;
    const mid = BC.bookMidPrice(book, refPrice);
    if (!mid || mid <= 0) {
      return { mid: 0, lo: 0, hi: 0, asks: [], bids: [], depthPct: band, walls: new Map() };
    }
    const lo = mid * (1 - band);
    const hi = mid * (1 + band);
    const inBand = (p) => p >= lo - 1e-12 && p <= hi + 1e-12;
    const bidsRaw = BC.normalizeBookSide(book?.bids).filter(([p]) => inBand(p));
    const asksRaw = BC.normalizeBookSide(book?.asks).filter(([p]) => inBand(p));
    const binTicks = binTicksOverride ?? BC.BOOK_PANEL.binTicks ?? 10;
    const step = BC.bookBinSize(mid, binTicks);
    const bidsAgg = BC.aggregateBookLevels(bidsRaw, true, mid, binTicks);
    const asksAgg = BC.aggregateBookLevels(asksRaw, false, mid, binTicks);
    const bidMap = new Map(bidsAgg.map((r) => [r.price, r.size]));
    const askMap = new Map(asksAgg.map((r) => [r.price, r.size]));
    let bids = BC.fillBookSideGrid(mid, lo, hi, step, true, bidMap);
    let asks = BC.fillBookSideGrid(mid, lo, hi, step, false, askMap);
    const walls = new Map();
    for (const w of book?.walls || []) {
      const p = Number(w.price);
      if (p > 0) walls.set(p, w);
    }
    return { mid, lo, hi, asks, bids, depthPct: band, walls, binTicks };
  },

  bookPaneHtml(data) {
    const BC = window.boardChart;
    const { mid, lo, hi, asks, bids, depthPct, walls, binTicks } = data;
    const pct = Math.round((depthPct ?? BC.BOOK_DEPTH_PCT) * 100);
    const bin = Number(binTicks ?? BC.BOOK_PANEL.binTicks) || 20;
    if (!asks.length && !bids.length) {
      return `<p class="quiet">Нет заявок в ±${pct}% от ${BC.formatBookPrice(mid) || "цены"}. Загрузка с биржи…</p>`;
    }
    const step = asks[0]?.step || bids[0]?.step || BC.bookBinSize(mid, bin);
    const wallAt = (price) => {
      const hiP = price + (bin > 1 ? step : 0);
      for (const [p, w] of walls.entries()) {
        if (bin > 1) {
          if (p >= price - 1e-12 && p < hiP + 1e-12) return w;
        } else if (Math.abs(p - price) <= Math.max(price, p) * 0.00003) return w;
      }
      return null;
    };
    const maxAsk = Math.max(...asks.map((r) => r.size), 1);
    const maxBid = Math.max(...bids.map((r) => r.size), 1);
    const rowHtml = (r, side, maxVol) => {
      const empty = !(r.size > 0);
      const tag = empty ? "" : BC.wallTag(wallAt(r.price));
      const priceLabel = BC.formatBookPrice(r.price);
      const barPct = empty ? 0 : Math.max(4, Math.round((r.size / maxVol) * 100));
      return `<tr class="psc-book-tr ${side}${empty ? " psc-book-tr--empty" : ""}">
        <td class="psc-book-price">${priceLabel}</td>
        <td class="psc-book-vol">
          <span class="psc-book-vol-wrap">
            <span class="psc-book-vol-bar ${side}" style="width:${barPct}%"></span>
            <span class="psc-book-vol-text">${empty ? "—" : BC.formatBookSize(r.size)}${tag}</span>
          </span>
        </td>
      </tr>`;
    };
    const askRows = [...asks].reverse().map((r) => rowHtml(r, "ask", maxAsk)).join("");
    const bidRows = bids.map((r) => rowHtml(r, "bid", maxBid)).join("");
    const binOpts = [1, 5, 10, 20, 50]
      .map((t) => `<option value="${t}"${t === bin ? " selected" : ""}>${t} тик${t === 1 ? "" : "ов"}</option>`)
      .join("");
    return `<div class="psc-book-toolbar">
      <label class="quiet">Объединение</label>
      <select class="psc-book-bin" title="Сумма объёма за N шагов цены">${binOpts}</select>
      <span class="quiet psc-book-toolbar-hint">±${pct}% от mid · шкала = доля объёма</span>
    </div>
    <div class="psc-book-scroll">
      <div class="psc-book-scroll-pad">
        <table class="psc-book-table psc-book-table--dense">
          <thead><tr><th>Цена</th><th>Объём</th></tr></thead>
          <tbody class="psc-book-asks">${askRows || `<tr><td colspan="2" class="quiet">нет ask</td></tr>`}</tbody>
          <tbody class="psc-book-mid-body"><tr class="psc-book-mid-row" data-book-mid="1">
            <td colspan="2"><span class="psc-book-mid-tag">MID</span> <strong>${BC.formatBookPrice(mid)}</strong>
            <span class="quiet psc-book-mid-range">${BC.formatBookPrice(lo)} – ${BC.formatBookPrice(hi)}</span></td>
          </tr></tbody>
          <tbody class="psc-book-bids">${bidRows || `<tr><td colspan="2" class="quiet">нет bid</td></tr>`}</tbody>
        </table>
      </div>
    </div>`;
  },

  bookChartIdForPane(paneId) {
    const map = {
      "pump-scan-book-pane": "pump-scan-candle-chart",
      "x2-book-pane": "x2-candle-chart",
      "psc-book-pane": "psc-candle-chart",
    };
    return map[paneId] || null;
  },

  overlayHost(chartEl) {
    return chartEl?.closest?.(".psc-chart-wrap") || chartEl || null;
  },

  attachOverlayToHost(overlayEl, host, beforeEl) {
    if (!overlayEl || !host) return;
    if (overlayEl.parentElement !== host) {
      host.insertBefore(overlayEl, beforeEl || null);
    } else if (beforeEl && overlayEl.nextElementSibling !== beforeEl) {
      host.insertBefore(overlayEl, beforeEl);
    }
  },

  overlayPlotOffsetX(runtime) {
    const chartEl = runtime?._chartContainer;
    const host = runtime?.liqOverlayEl?.parentElement;
    if (!chartEl || !host) return 0;
    return chartEl.getBoundingClientRect().left - host.getBoundingClientRect().left;
  },

  clearLiqPriceLines(runtime) {
    if (!runtime?.series || !runtime._liqPriceLines?.length) return;
    for (const pl of runtime._liqPriceLines) {
      try {
        runtime.series.removePriceLine(pl);
      } catch (_e) {
        /* ignore */
      }
    }
    runtime._liqPriceLines = [];
  },

  syncLiqPriceLines(runtime, list) {
    const BC = window.boardChart;
    if (!runtime?.series) return;
    BC.clearLiqPriceLines(runtime);
    if (!list?.length) return;
    runtime._liqPriceLines = [];
    for (const z of list.slice(0, 16)) {
      const pending = Number(z.notional_pending_usd) || 0;
      if (pending <= 0) continue;
      const price = Number(z.price);
      if (!price || Number.isNaN(price)) continue;
      const color = z.side === "short" ? "rgba(255, 93, 115, 0.35)" : "rgba(61, 214, 140, 0.35)";
      runtime._liqPriceLines.push(
        runtime.series.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: 0,
          axisLabelVisible: false,
          title: "",
        }),
      );
    }
  },

  /** Pan/zoom по времени и цене; оверлеи синхронизируются в ensureBookOverlayHooks. */
  chartInteractionDefaults() {
    return {
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 7,
        fixLeftEdge: false,
        fixRightEdge: false,
      },
      rightPriceScale: { borderColor: "#2c3544", autoScale: true },
    };
  },

  markUserChartView(runtime) {
    if (!runtime?.series || runtime._programmaticChartView) return;
    runtime._userChartView = true;
    runtime.series.priceScale().applyOptions({ autoScale: false });
  },

  /** Горизонталь последней (формирующейся) свечи — правый край max-полоски liq. */
  lastCandleAnchorX(runtime) {
    const chart = runtime?.chart;
    const t = runtime._lastCandleTime;
    if (!chart || t == null) return null;
    const x = chart.timeScale().timeToCoordinate(t);
    if (x == null || Number.isNaN(x) || x <= 4) return null;
    return x;
  },

  syncChartOverlays(runtime) {
    const BC = window.boardChart;
    if (!runtime) return;
    if (runtime._syncOverlayRaf) return;
    runtime._syncOverlayRaf = requestAnimationFrame(() => {
      runtime._syncOverlayRaf = 0;
      BC.syncChartOverlaysNow(runtime);
    });
  },

  syncChartOverlaysNow(runtime) {
    const BC = window.boardChart;
    if (!runtime) return;
    const ctx = runtime._lastBookOverlay;
    if (ctx) BC.renderBookChartOverlay(runtime, ctx.book, ctx.refPrice, ctx.symbol, { skipLiqFetch: true });
    const liq = runtime._lastLiqCtx;
    if (liq) BC.renderLiqChartOverlay(runtime, liq.zones, liq.mark);
    BC.renderLiqCandleLabels(runtime);
  },

  scheduleThrottledOverlaySync(runtime) {
    const BC = window.boardChart;
    if (!runtime) return;
    const minMs = 72;
    const now = performance.now();
    const last = runtime._lastOverlaySyncMs || 0;
    if (now - last >= minMs) {
      runtime._lastOverlaySyncMs = now;
      runtime._overlaySyncTrailing = 0;
      BC.syncChartOverlaysNow(runtime);
      return;
    }
    if (runtime._overlaySyncTrailing) return;
    runtime._overlaySyncTrailing = window.setTimeout(() => {
      runtime._overlaySyncTrailing = 0;
      runtime._lastOverlaySyncMs = performance.now();
      BC.syncChartOverlaysNow(runtime);
    }, minMs);
  },

  resetChartSession(runtime, symbol) {
    const BC = window.boardChart;
    if (!runtime) return;
    runtime._activeSymbol = symbol || "";
    runtime._chartSymbol = symbol || "";
    runtime._lastBookOverlay = null;
    runtime._lastLiqCtx = null;
    runtime._liquidations = [];
    runtime._liqByBar = null;
    runtime._lastBars = [];
    runtime._liqFetchGen = (runtime._liqFetchGen || 0) + 1;
    if (runtime.bookOverlayEl) runtime.bookOverlayEl.innerHTML = "";
    if (runtime.liqOverlayEl) runtime.liqOverlayEl.innerHTML = "";
    if (runtime.liqCandleOverlayEl) runtime.liqCandleOverlayEl.innerHTML = "";
    if (runtime.liqCandleTipEl) runtime.liqCandleTipEl.hidden = true;
    BC.clearLiqPriceLines(runtime);
    if (runtime.series) {
      runtime.series.setData([]);
      runtime.volumeSeries?.setData([]);
    }
  },

  patchLiveLastBar(bars, livePrice) {
    const p = Number(livePrice);
    if (!p || !bars?.length) return;
    const last = bars[bars.length - 1];
    last.close = p;
    last.high = Math.max(last.high, p);
    last.low = Math.min(last.low, p);
  },

  /** Если live-цена вне видимой шкалы — вернуть autoScale (пока пользователь не зумил вручную). */
  maybeFitLivePriceScale(runtime, livePrice) {
    const series = runtime?.series;
    const host = runtime?._chartContainer;
    if (!series || !host || runtime._userChartView) return;
    const p = Number(livePrice);
    if (!p || p <= 0) return;
    const y = series.priceToCoordinate(p);
    const plotH = Math.max(1, host.clientHeight * 0.76);
    if (y == null || Number.isNaN(y) || y < 8 || y > plotH - 8) {
      series.priceScale().applyOptions({ autoScale: true });
    }
  },

  chartOverlayReady(runtime, symbol) {
    if (!runtime?._lastBars?.length) return false;
    if (symbol && runtime._activeSymbol && symbol !== runtime._activeSymbol) return false;
    return true;
  },

  barTimeKey(time) {
    return typeof time === "object" ? JSON.stringify(time) : String(time);
  },

  barTimeToSec(time) {
    if (typeof time === "object") {
      return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000);
    }
    return Number(time) || 0;
  },

  liqEventMs(raw) {
    const n = Number(raw);
    if (!n || Number.isNaN(n)) return 0;
    return n > 1e12 ? n : n * 1000;
  },

  aggregateLiqByBar(bars, liquidations, interval) {
    const BC = window.boardChart;
    const stepMs = (BC.INTERVAL_SEC[interval] || 3600) * 1000;
    const meta = (bars || []).map((b, idx) => {
      const startMs = BC.barTimeToSec(b.time) * 1000;
      const next = bars[idx + 1];
      const endMs = next ? BC.barTimeToSec(next.time) * 1000 : startMs + stepMs;
      return { key: BC.barTimeKey(b.time), time: b.time, startMs, endMs };
    });
    const map = new Map();
    for (const m of meta) {
      map.set(m.key, { longUsd: 0, shortUsd: 0, events: [], time: m.time });
    }
    for (const ev of liquidations || []) {
      const ts = BC.liqEventMs(ev.time ?? ev.timestamp);
      if (!ts) continue;
      const price = Number(ev.price);
      const size = Number(ev.size);
      if (!price || !size) continue;
      const usd = price * size;
      const side = String(ev.side || "");
      let bucket = null;
      for (const m of meta) {
        if (ts >= m.startMs && ts < m.endMs) {
          bucket = map.get(m.key);
          break;
        }
      }
      if (!bucket && meta.length) {
        const lastM = meta[meta.length - 1];
        if (ts >= lastM.startMs) bucket = map.get(lastM.key);
      }
      if (!bucket) continue;
      const row = {
        side,
        price,
        size,
        usd,
        time: ts,
        position: side === "Buy" ? "long" : side === "Sell" ? "short" : ev.position || "",
      };
      bucket.events.push(row);
      if (side === "Buy") bucket.longUsd += usd;
      else if (side === "Sell") bucket.shortUsd += usd;
    }
    return map;
  },

  setChartLiquidations(runtime, liquidations) {
    const BC = window.boardChart;
    if (!runtime) return;
    if (!runtime._lastBars?.length) {
      runtime._liquidations = Array.isArray(liquidations) ? liquidations : [];
      return;
    }
    runtime._liquidations = Array.isArray(liquidations) ? liquidations : [];
    const bars = runtime._lastBars || [];
    const iv = runtime._chartInterval || "60";
    runtime._liqByBar = BC.aggregateLiqByBar(bars, runtime._liquidations, iv);
    BC.renderLiqCandleLabels(runtime);
  },

  ensureLiqCandleOverlay(runtime, chartEl) {
    const BC = window.boardChart;
    if (!runtime || !chartEl) return;
    const host = BC.overlayHost(chartEl);
    if (!host) return;
    if (!runtime.liqCandleOverlayEl) {
      const ov = document.createElement("div");
      ov.className = "psc-liq-candle-overlay";
      ov.setAttribute("aria-hidden", "true");
      runtime.liqCandleOverlayEl = ov;
    }
    if (!runtime.liqCandleTipEl) {
      const tip = document.createElement("div");
      tip.className = "psc-liq-candle-tip";
      tip.hidden = true;
      runtime.liqCandleTipEl = tip;
    }
    BC.attachOverlayToHost(runtime.liqCandleOverlayEl, host, runtime.bookOverlayEl || null);
    if (runtime.liqCandleTipEl.parentElement !== host) {
      host.appendChild(runtime.liqCandleTipEl);
    }
  },

  ensureLiqCandleHooks(runtime) {
    const BC = window.boardChart;
    if (!runtime?.chart || runtime._liqCandleHooks) return;
    runtime._liqCandleHooks = true;
    runtime.chart.subscribeCrosshairMove((param) => {
      BC.updateLiqCandleTip(runtime, param);
    });
  },

  formatLiqUsd(usd) {
    const BC = window.boardChart;
    const n = Number(usd);
    if (!n || n < BC.LIQ_CANDLE.minUsd) return "";
    return BC.formatBookSize(n);
  },

  renderLiqCandleLabels(runtime) {
    const BC = window.boardChart;
    const el = runtime?.liqCandleOverlayEl;
    const chart = runtime?.chart;
    const series = runtime?.series;
    const bars = runtime._lastBars;
    const map = runtime._liqByBar;
    if (!el || !chart || !series || !bars?.length || !map) {
      if (el) el.innerHTML = "";
      return;
    }
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!range) {
      el.innerHTML = "";
      return;
    }
    const offX = BC.overlayPlotOffsetX(runtime);
    const from = Math.max(0, Math.floor(range.from));
    const to = Math.min(bars.length - 1, Math.ceil(range.to));
    const parts = [];
    for (let i = from; i <= to; i++) {
      const bar = bars[i];
      const key = BC.barTimeKey(bar.time);
      const agg = map.get(key);
      if (!agg) continue;
      const shortTxt = BC.formatLiqUsd(agg.shortUsd);
      const longTxt = BC.formatLiqUsd(agg.longUsd);
      if (!shortTxt && !longTxt) continue;
      const x = chart.timeScale().timeToCoordinate(bar.time);
      if (x == null || Number.isNaN(x)) continue;
      const anchorY = series.priceToCoordinate(Math.max(bar.high, bar.open, bar.close));
      if (anchorY == null || Number.isNaN(anchorY)) continue;
      const xPx = Math.round(x + offX);
      const yPx = Math.round(anchorY - 4);
      const lines = [];
      if (shortTxt) lines.push(`<span class="psc-liq-c-sum short">${shortTxt}</span>`);
      if (longTxt) lines.push(`<span class="psc-liq-c-sum long">${longTxt}</span>`);
      parts.push(`<div class="psc-liq-candle-tag" style="left:${xPx}px;top:${yPx}px">${lines.join("")}</div>`);
    }
    el.innerHTML = parts.join("");
  },

  updateLiqCandleTip(runtime, param) {
    const BC = window.boardChart;
    const tip = runtime?.liqCandleTipEl;
    const map = runtime?._liqByBar;
    if (!tip || !map || !param?.time || param.point?.x == null) {
      if (tip) tip.hidden = true;
      return;
    }
    const key = BC.barTimeKey(param.time);
    const agg = map.get(key);
    if (!agg?.events?.length) {
      tip.hidden = true;
      return;
    }
    const host = tip.parentElement;
    const offX = BC.overlayPlotOffsetX(runtime);
    const maxR = BC.LIQ_CANDLE.maxTooltipRows;
    const rows = agg.events
      .slice()
      .sort((a, b) => b.usd - a.usd)
      .slice(0, maxR)
      .map((e) => {
        const side = e.side === "Buy" ? "long" : e.side === "Sell" ? "short" : e.position || "?";
        const cls = side === "short" ? "short" : "long";
        return `<li class="${cls}">${BC.formatBookPrice(e.price)} · ${BC.formatBookSize(e.size)} · ~$${BC.formatBookSize(e.usd)}</li>`;
      })
      .join("");
    const more = agg.events.length > maxR ? `<li class="quiet">+${agg.events.length - maxR} ещё</li>` : "";
    tip.innerHTML = `<div class="psc-liq-candle-tip-head">Short $${BC.formatBookSize(agg.shortUsd)} · Long $${BC.formatBookSize(agg.longUsd)}</div><ul>${rows}${more}</ul>`;
    tip.hidden = false;
    const hostRect = host?.getBoundingClientRect();
    const left = Math.max(8, Math.min((host?.clientWidth || 400) - 220, param.point.x + offX + 12));
    const top = Math.max(8, param.point.y - 8);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  },

  startOverlayPriceSync(runtime) {
    const BC = window.boardChart;
    if (!runtime || runtime._overlayPriceSync) return;
    runtime._overlayPriceSync = true;
    let lastKey = "";
    const tick = () => {
      if (!runtime.series) {
        runtime._overlayRafId = requestAnimationFrame(tick);
        return;
      }
      const probe = runtime._overlayProbePrice;
      if (probe != null && probe > 0) {
        const y = runtime.series.priceToCoordinate(probe);
        const ax = BC.lastCandleAnchorX(runtime);
        const key = `${y == null ? "n" : Math.round(y * 16)}|${ax == null ? "x" : Math.round(ax)}`;
        if (key !== lastKey) {
          lastKey = key;
          BC.scheduleThrottledOverlaySync(runtime);
        }
      }
      runtime._overlayRafId = requestAnimationFrame(tick);
    };
    runtime._overlayRafId = requestAnimationFrame(tick);
  },

  ensureBookOverlay(runtime, chartEl) {
    const BC = window.boardChart;
    if (!runtime || !chartEl) return;
    chartEl._boardRuntime = runtime;
    const host = BC.overlayHost(chartEl);
    if (!host) return;
    if (!runtime.bookOverlayEl) {
      const ov = document.createElement("div");
      ov.className = "psc-book-chart-overlay";
      ov.setAttribute("aria-hidden", "true");
      runtime.bookOverlayEl = ov;
    }
    BC.attachOverlayToHost(runtime.bookOverlayEl, host, null);
    BC.ensureLiqOverlay(runtime, chartEl);
    BC.ensureBookOverlayHooks(runtime);
  },

  ensureLiqOverlay(runtime, chartEl) {
    const BC = window.boardChart;
    if (!runtime || !chartEl) return;
    const host = BC.overlayHost(chartEl);
    if (!host) return;
    if (!runtime.liqOverlayEl) {
      const ov = document.createElement("div");
      ov.className = "psc-liq-chart-overlay";
      ov.setAttribute("aria-hidden", "true");
      runtime.liqOverlayEl = ov;
    }
    BC.attachOverlayToHost(runtime.liqOverlayEl, host, runtime.bookOverlayEl || null);
    BC.ensureLiqCandleOverlay(runtime, chartEl);
  },

  ensureBookOverlayHooks(runtime) {
    const BC = window.boardChart;
    if (!runtime?.chart || runtime._bookOverlayHooks) return;
    runtime._bookOverlayHooks = true;
    const redraw = () => {
      BC.markUserChartView(runtime);
      BC.syncChartOverlays(runtime);
    };
    runtime.chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    if (typeof runtime.chart.timeScale().subscribeSizeChange === "function") {
      runtime.chart.timeScale().subscribeSizeChange(redraw);
    }
    BC.startOverlayPriceSync(runtime);
    BC.ensureLiqCandleHooks(runtime);
    const host = runtime.chart?.chartElement?.() || runtime.bookOverlayEl?.parentElement;
    if (host && !runtime._chartInputHooks) {
      runtime._chartInputHooks = true;
      const mark = () => BC.markUserChartView(runtime);
      for (const ev of ["wheel", "mousedown", "touchstart"]) {
        host.addEventListener(ev, mark, { passive: true });
      }
    }
  },

  renderBookChartOverlay(runtime, book, refPrice, symbol, options) {
    const BC = window.boardChart;
    const el = runtime?.bookOverlayEl;
    const series = runtime?.series;
    if (!el || !series) return;
    const sym = symbol || runtime._lastBookOverlay?.symbol || "";
    if (sym && runtime._activeSymbol && sym !== runtime._activeSymbol) return;
    if (!BC.chartOverlayReady(runtime, sym)) {
      runtime._lastBookOverlay = { book, refPrice, symbol: sym };
      el.innerHTML = "";
      return;
    }
    if (sym) runtime._chartSymbol = sym;
    runtime._lastBookOverlay = { book, refPrice, symbol: sym };
    const chartCfg = BC.BOOK_CHART;
    const data = BC.prepareBookDepth(book, refPrice, chartCfg.depthPct, chartCfg.binTicks);
    const { mid, asks, bids } = data;
    if (!mid) {
      el.innerHTML = "";
      if (sym && !options?.skipLiqFetch) BC.refreshLiqZonesOverlay(runtime, sym, refPrice);
      return;
    }
    runtime._overlayProbePrice = mid;
    const withVol = [
      ...asks.filter((r) => r.size > 0).map((r) => ({ ...r, side: "ask" })),
      ...bids.filter((r) => r.size > 0).map((r) => ({ ...r, side: "bid" })),
    ];
    const maxVol = Math.max(...withVol.map((r) => r.size), 1);
    const parts = [];
    const midY = series.priceToCoordinate(mid);
    if (midY != null) {
      parts.push(`<div class="psc-book-chart-mid" style="top:${Math.round(midY)}px"></div>`);
    }
    if (midY == null) {
      el.innerHTML = "";
      return;
    }
    for (const r of withVol) {
      const y = series.priceToCoordinate(r.price);
      if (y == null) continue;
      const yPx = Math.round(y);
      const bar = Math.min(100, Math.max(12, Math.round((r.size / maxVol) * 50) * 2));
      parts.push(`<div class="psc-book-chart-row ${r.side}" style="top:${yPx}px" title="${BC.formatBookPrice(r.price)} · ${BC.formatBookSize(r.size)}">
        <span class="psc-book-chart-bar" style="width:${bar}%"></span>
      </div>`);
    }
    el.innerHTML = parts.join("");
    if (sym && !options?.skipLiqFetch) BC.refreshLiqZonesOverlay(runtime, sym, refPrice);
  },

  async fetchLiqZones(symbol, interval) {
    const BC = window.boardChart;
    const iv = interval || "60";
    const key = `${symbol}|${iv}`;
    const bucket = BC.getAssetBucket(symbol);
    const now = Date.now();
    if (bucket.liq?.zones?.length && now - bucket.liqAt < BC.LIQ_CHART.refreshMs) return bucket.liq;
    const cached = BC._liqZonesFetch.get(key);
    if (cached?.data?.zones?.length && now - cached.ts < BC.LIQ_CHART.refreshMs) return cached.data;
    if (cached?.pending) return cached.pending;
    const job = BC._fetchLiqZonesRaw(symbol, iv)
      .catch(() => null)
      .finally(() => {
        const c = BC._liqZonesFetch.get(key);
        if (c) c.pending = null;
      });
    BC._liqZonesFetch.set(key, { ...(cached || {}), pending: job });
    let data = await job;
    if (data && !data.zones?.length) {
      data = await BC._fetchLiqZonesRaw(symbol, iv);
    }
    if (data?.zones?.length) {
      bucket.liq = data;
      bucket.liqAt = now;
      BC._liqZonesFetch.set(key, { data, ts: now, pending: null });
    }
    return data;
  },

  renderLiqChartOverlay(runtime, zones, mark) {
    const BC = window.boardChart;
    const el = runtime?.liqOverlayEl;
    const series = runtime?.series;
    if (!el || !series || !mark) return;
    if (!BC.chartOverlayReady(runtime, runtime._chartSymbol)) {
      el.innerHTML = "";
      return;
    }
    runtime._overlayProbePrice = Number(mark) || runtime._overlayProbePrice;
    BC.clearLiqPriceLines(runtime);
    const pendingOnly = (zones || [])
      .map((z) => {
        const pending = Number(z.notional_pending_usd);
        const vol =
          pending > 0
            ? pending
            : Number(z.notional_cleared_usd) > 0
              ? 0
              : Number(z.notional_usd) || 0;
        return { ...z, _vol: vol };
      })
      .filter((z) => z._vol > 0);
    if (!pendingOnly.length) {
      el.innerHTML = "";
      return;
    }
    const maxVol = Math.max(...pendingOnly.map((z) => z._vol), 1);
    const parts = [];
    for (const z of pendingOnly) {
      const y = series.priceToCoordinate(Number(z.price));
      if (y == null) continue;
      const yPx = Math.round(y);
      const barPct = Math.min(100, Math.max(10, Math.round((z._vol / maxVol) * 100)));
      const side = z.side === "short" ? "short" : "long";
      const src = z.source === "hist" ? "факт" : z.source === "model" ? "модель" : "смесь";
      parts.push(`<div class="psc-liq-chart-row ${side}" style="top:${yPx}px" title="${BC.formatBookPrice(z.price)} · ~$${BC.formatBookSize(z._vol)} · ${src}">
        <span class="psc-liq-chart-bar" style="width:${barPct}%"></span>
      </div>`);
    }
    el.innerHTML = parts.join("");
  },

  refreshLiqZonesOverlay(runtime, symbol, refPrice) {
    const BC = window.boardChart;
    if (!symbol || !runtime) return;
    if (runtime._activeSymbol && symbol !== runtime._activeSymbol) return;
    const interval = runtime._chartInterval || "60";
    const fetchGen = runtime._liqFetchGen || 0;
    void BC.fetchLiqZones(symbol, interval).then((data) => {
      if (fetchGen !== runtime._liqFetchGen) return;
      if (runtime._activeSymbol && symbol !== runtime._activeSymbol) return;
      if (!data?.zones?.length) return;
      const mark = Number(data.mark) || Number(refPrice);
      if (!mark) return;
      runtime._lastLiqCtx = { zones: data.zones, mark };
      BC.renderLiqChartOverlay(runtime, data.zones, mark);
    });
  },

  syncBookOverlayForChart(chartElId) {
    const BC = window.boardChart;
    const chartEl = document.getElementById(chartElId);
    const runtime = chartEl?._boardRuntime;
    if (runtime) BC.syncChartOverlays(runtime);
  },

  bookSectionHtml(paneId) {
    return `<div class="psc-book-section">
      <div class="psc-book-head">
        <h3 class="psc-info-subhead">Стакан ±10%</h3>
        <div class="psc-book-head-actions">
          <button type="button" class="psc-toggle-meta">Скрыть метрики</button>
          <button type="button" class="psc-book-fullscreen" title="Стакан на весь экран" aria-pressed="false">⛶</button>
        </div>
      </div>
      <div class="psc-book-pane" id="${paneId}"></div>
    </div>`;
  },

  setBookFullscreen(section, on) {
    if (!section) return;
    section.classList.toggle("psc-book-section--fullscreen", on);
    const btn = section.querySelector(".psc-book-fullscreen");
    if (btn) {
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.textContent = on ? "✕" : "⛶";
      btn.title = on ? "Вернуть стакан на место" : "Стакан на весь экран";
    }
    document.body.classList.toggle("psc-book-fs-active", on);
    const pane = section.querySelector(".psc-book-pane");
    if (pane) window.boardChart.scrollBookToMid(pane);
  },

  bookScrollEl(paneEl) {
    return paneEl?.querySelector(".psc-book-scroll") || paneEl;
  },

  ensureBookPaneScroll(paneEl) {
    if (!paneEl || paneEl._bookScrollHook) return;
    paneEl._bookScrollHook = true;
    paneEl.addEventListener(
      "scroll",
      (e) => {
        if (e.target.classList?.contains("psc-book-scroll")) paneEl._bookUserScrolled = true;
      },
      true,
    );
  },

  scrollBookToMid(paneEl) {
    const scrollEl = window.boardChart.bookScrollEl(paneEl);
    const midRow = scrollEl?.querySelector(".psc-book-mid-row");
    if (!scrollEl || !midRow) return;
    const apply = () => {
      const elRect = scrollEl.getBoundingClientRect();
      const rowRect = midRow.getBoundingClientRect();
      const rowCenter = rowRect.top - elRect.top + scrollEl.scrollTop + rowRect.height / 2;
      const top = rowCenter - scrollEl.clientHeight / 2;
      scrollEl.scrollTop = Math.max(0, Math.min(top, scrollEl.scrollHeight - scrollEl.clientHeight));
    };
    requestAnimationFrame(() => requestAnimationFrame(apply));
  },

  bookLevelCount(book) {
    const BC = window.boardChart;
    return BC.normalizeBookSide(book?.bids).length + BC.normalizeBookSide(book?.asks).length;
  },

  getAssetBucket(symbol) {
    const BC = window.boardChart;
    if (!symbol) return { intervals: new Map(), book: null, liq: null };
    let bucket = BC._assetCache.get(symbol);
    if (!bucket) {
      bucket = { intervals: new Map(), intervalAt: new Map(), book: null, bookAt: 0, liq: null, liqAt: 0 };
      BC._assetCache.set(symbol, bucket);
    }
    return bucket;
  },

  getCachedCandles(symbol, interval) {
    return window.boardChart.getAssetBucket(symbol).intervals.get(interval) || [];
  },

  paintCandlesFromCache(runtime, symbol, interval, resetScale, chartElId) {
    const BC = window.boardChart;
    const candles = BC.getCachedCandles(symbol, interval);
    if (candles.length < 24 || !runtime?.series) return false;
    BC.drawCandles(runtime, candles, interval, resetScale, chartElId);
    return true;
  },

  scheduleAssetsPrefetch(symbols, options) {
    const BC = window.boardChart;
    const list = [...new Set((symbols || []).filter(Boolean))];
    if (!list.length) return;
    const ivList =
      options?.intervals === undefined ? ["15", "60"] : Array.isArray(options.intervals) ? options.intervals : ["15", "60"];
    const priority = options?.priority === "high" ? 0 : 1;
    const wantBook = options?.book !== false;
    const wantLiq = options?.liq !== false;
    for (const symbol of list) {
      for (const interval of ivList) {
        BC._enqueueAssetJob({ kind: "klines", symbol, interval, priority, key: `k:${symbol}:${interval}` });
      }
      if (wantBook) BC._enqueueAssetJob({ kind: "book", symbol, priority, key: `b:${symbol}` });
      if (wantLiq && ivList.length) {
        const iv = ivList[0] || "60";
        BC._enqueueAssetJob({ kind: "liq", symbol, interval: iv, priority, key: `l:${symbol}:${iv}` });
      }
    }
    BC._drainAssetPrefetch();
  },

  _enqueueAssetJob(job) {
    const BC = window.boardChart;
    if (BC._prefetchInflight.has(job.key)) return;
    const bucket = BC.getAssetBucket(job.symbol);
    const now = Date.now();
    if (job.kind === "klines") {
      const candles = bucket.intervals.get(job.interval) || [];
      const at = bucket.intervalAt.get(job.interval) || 0;
      const need = BC.minBarsForDays(job.interval, BC.FETCH_DAYS);
      if (candles.length >= Math.min(need, 120) && now - at < BC.PREFETCH_COOLDOWN_MS) return;
      if (BC._prefetchQueue.some((j) => j.key === job.key)) return;
    } else if (job.kind === "book") {
      if (bucket.book && BC.bookLevelCount(bucket.book) >= 3 && now - bucket.bookAt < BC.PREFETCH_COOLDOWN_MS) return;
      if (BC._prefetchQueue.some((j) => j.key === job.key)) return;
    } else if (job.kind === "liq") {
      if (bucket.liq && now - bucket.liqAt < BC.LIQ_CHART.refreshMs) return;
      if (BC._prefetchQueue.some((j) => j.key === job.key)) return;
    }
    if (job.priority === 0) BC._prefetchQueue.unshift(job);
    else BC._prefetchQueue.push(job);
  },

  _drainAssetPrefetch() {
    const BC = window.boardChart;
    while (BC._prefetchActive < BC.PREFETCH_CONCURRENCY && BC._prefetchQueue.length) {
      const job = BC._prefetchQueue.shift();
      if (!job) break;
      BC._prefetchActive += 1;
      BC._prefetchInflight.add(job.key);
      void BC._runPrefetchJob(job)
        .catch(() => {})
        .finally(() => {
          BC._prefetchInflight.delete(job.key);
          BC._prefetchActive -= 1;
          BC._drainAssetPrefetch();
        });
    }
  },

  async _runPrefetchJob(job) {
    const BC = window.boardChart;
    const bucket = BC.getAssetBucket(job.symbol);
    if (job.kind === "klines") {
      const candles = await BC._fetchKlines(job.symbol, job.interval, false);
      if (candles.length) {
        bucket.intervals.set(job.interval, candles);
        bucket.intervalAt.set(job.interval, Date.now());
      }
      return;
    }
    if (job.kind === "book") {
      const book = await BC.fetchBookFromApi(job.symbol, false);
      if (book && BC.bookLevelCount(book) >= 3) {
        bucket.book = book;
        bucket.bookAt = Date.now();
      }
      return;
    }
    if (job.kind === "liq") {
      const data = await BC._fetchLiqZonesRaw(job.symbol, job.interval || "60");
      if (data) {
        bucket.liq = data;
        bucket.liqAt = Date.now();
      }
    }
  },

  async fetchBookFromApi(symbol, refresh) {
    const force = refresh === true;
    try {
      const q = force ? "?refresh=1" : "";
      const res = await fetch(`/api/orderbook/${encodeURIComponent(symbol)}${q}`);
      if (!res.ok) return null;
      const payload = await res.json();
      const book = payload.book || null;
      if (book && window.boardChart.bookLevelCount(book) >= 3) {
        const bucket = window.boardChart.getAssetBucket(symbol);
        bucket.book = book;
        bucket.bookAt = Date.now();
      }
      return book;
    } catch (_e) {
      return null;
    }
  },

  async _fetchLiqZonesRaw(symbol, interval) {
    try {
      const res = await fetch(
        `/api/liquidation-zones/${encodeURIComponent(symbol)}?interval=${encodeURIComponent(interval || "60")}`,
      );
      if (!res.ok) return null;
      return await res.json();
    } catch (_e) {
      return null;
    }
  },

  renderBookPane(containerId, book, refPrice, symbol, options) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const sym = symbol || "";
    const BC = window.boardChart;
    const paint = (b) => {
      const scrollEl = BC.bookScrollEl(el);
      const prevScroll = scrollEl.scrollTop;
      const centerKey = `${sym}|${containerId}`;
      const isNewOpen = Boolean(sym) && el._bookCenterKey !== centerKey;
      if (isNewOpen) {
        el._bookCenterKey = centerKey;
        el._bookUserScrolled = false;
      }
      const data = BC.prepareBookDepth(b, refPrice);
      el.innerHTML = BC.bookPaneHtml(data);
      el._bookCtx = { book: b, refPrice, symbol: sym };
      const chartId = BC.bookChartIdForPane(containerId);
      const chartEl = chartId ? document.getElementById(chartId) : null;
      if (chartEl?._boardRuntime) {
        if (sym) chartEl._boardRuntime._chartSymbol = sym;
        BC.renderBookChartOverlay(chartEl._boardRuntime, b, refPrice, sym, { skipLiqFetch: true });
      }
      BC.ensureBookPaneScroll(el);
      const sc = BC.bookScrollEl(el);
      if (options?.centerMid || isNewOpen) BC.scrollBookToMid(el);
      else if (el._bookUserScrolled) sc.scrollTop = prevScroll;
    };
    const cached = sym ? BC.getAssetBucket(sym).book : null;
    if ((!book || BC.bookLevelCount(book) < 3) && cached && BC.bookLevelCount(cached) >= 3) {
      book = cached;
    }
    if (book && BC.bookLevelCount(book) >= 3) {
      paint(book);
      BC.scheduleAssetsPrefetch([sym], { intervals: [], book: true, liq: false, priority: "low" });
      return;
    }
    el.innerHTML = '<p class="quiet">Загрузка стакана…</p>';
    if (!sym) return;
    const pending = BC._bookFetch.get(sym);
    if (pending) {
      void pending.then((b) => b && paint(b));
      return;
    }
    const job = BC.fetchBookFromApi(sym, false)
      .then((b) => b || BC.fetchBookFromApi(sym, true))
      .finally(() => {
        BC._bookFetch.delete(sym);
      });
    BC._bookFetch.set(sym, job);
    void job.then((b) => {
      if (b) paint(b);
      else el.innerHTML = '<p class="quiet">Стакан пока недоступен — идёт фоновая загрузка.</p>';
    });
  },

  createRuntime() {
    return {
      chart: null,
      series: null,
      volumeSeries: null,
      priceRange: { min: 0, max: 0 },
      chartGen: 0,
    };
  },

  createPrefetchStore() {
    return { map: window.boardChart._assetCache, queue: [], active: 0 };
  },

  minBarsForDays(interval, days) {
    const d = days ?? window.boardChart.FETCH_DAYS;
    const minutes = window.boardChart.INTERVAL_MINUTES[interval] || 60;
    return Math.max(24, Math.ceil((d * 24 * 60) / minutes));
  },

  formatOiChange(pct) {
    if (pct === null || pct === undefined || Number.isNaN(Number(pct))) {
      return { text: "нет данных", cls: "psc-muted" };
    }
    const n = Number(pct);
    const sign = n > 0 ? "+" : "";
    const cls = n > 0 ? "psc-up" : n < 0 ? "psc-down" : "";
    return { text: `${sign}${n.toFixed(2)}%`, cls };
  },

  oiChangeFromSeries(points, lookbackMin) {
    if (!points || points.length < 2) return null;
    const sorted = [...points]
      .map((p) => ({
        ts: Number(p.timestamp ?? p.time ?? 0),
        val: Number(p.open_interest ?? p.value ?? 0),
      }))
      .filter((p) => p.ts > 0 && p.val > 0)
      .sort((a, b) => a.ts - b.ts);
    if (sorted.length < 2) return null;
    const latest = sorted[sorted.length - 1];
    const cutoff = latest.ts - lookbackMin * 60 * 1000;
    let reference = sorted[0].val;
    for (const p of sorted) {
      if (p.ts <= cutoff) reference = p.val;
      else break;
    }
    if (reference <= 0) return null;
    return ((latest.val - reference) / reference) * 100;
  },

  resolveOi1h4h(row, detail) {
    const r = row || {};
    let h1 = r.oi_change_1h_pct;
    let h4 = r.oi_change_4h_pct;
    const series = detail?.oi;
    if (h1 == null && series?.length) {
      h1 = window.boardChart.oiChangeFromSeries(series, 60);
    }
    if (h4 == null && series?.length) {
      h4 = window.boardChart.oiChangeFromSeries(series, 240);
    }
    return { h1, h4 };
  },

  formatFunding(rate) {
    if (rate == null || Number.isNaN(Number(rate))) return "—";
    return `${(Number(rate) * 100).toFixed(4)}%`;
  },

  fundingFrom(row, detail) {
    const rate = detail?.funding_rate ?? row?.funding_rate;
    return window.boardChart.formatFunding(rate);
  },

  bindInfoPane(paneId, onClose, onDismiss) {
    const key = `__boardInfoBound_${paneId}`;
    if (window[key]) return;
    window[key] = true;
    document.getElementById(paneId)?.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest(".psc-close-chart")) {
        event.preventDefault();
        onClose();
        return;
      }
      const dismiss = target?.closest("[data-dismiss-board]");
      if (dismiss?.dataset.dismissBoard && dismiss.dataset.symbol) {
        onDismiss(dismiss.dataset.dismissBoard, dismiss.dataset.symbol);
      }
    });
  },

  bindTfRow(rowId, getInterval, setInterval) {
    const row = document.getElementById(rowId);
    if (!row || row.dataset.bound) return;
    row.dataset.bound = "1";
    row.innerHTML = window.boardChart.TF.map(
      ([code, label]) =>
        `<button type="button" class="tf psc-tf${code === getInterval() ? " active" : ""}" data-board-tf="${code}">${label}</button>`,
    ).join("");
    row.addEventListener("click", (event) => {
      const btn = event.target instanceof Element ? event.target.closest("[data-board-tf]") : null;
      if (!btn?.dataset.boardTf) return;
      setInterval(btn.dataset.boardTf);
      window.boardChart.syncTfButtons(getInterval, rowId);
    });
  },

  syncTfButtons(getInterval, rowId) {
    const iv = getInterval();
    const root = rowId ? document.getElementById(rowId) : document;
    if (!root) return;
    root.querySelectorAll("[data-board-tf]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.boardTf === iv);
    });
  },

  schedulePrefetch(_store, symbols, intervals) {
    window.boardChart.scheduleAssetsPrefetch(symbols, {
      intervals: intervals?.length ? intervals : ["15", "60"],
      book: true,
      liq: true,
      priority: "low",
    });
  },

  async _fetchKlines(symbol, interval, refresh) {
    try {
      const q = new URLSearchParams({
        interval,
        days: String(window.boardChart.FETCH_DAYS),
      });
      if (refresh) q.set("refresh", "1");
      const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
      if (!res.ok) return [];
      const payload = await res.json();
      return payload.candles || [];
    } catch (_e) {
      return [];
    }
  },

  async ensureCandles(_store, symbol, interval, detail, options) {
    const BC = window.boardChart;
    const need = BC.minBarsForDays(interval, BC.FETCH_DAYS);
    const bucket = BC.getAssetBucket(symbol);
    let cached = bucket.intervals.get(interval) || [];
    if (detail?.candles?.length && detail.interval === interval) {
      cached = detail.candles;
      bucket.intervals.set(interval, cached);
      bucket.intervalAt.set(interval, Date.now());
    }
    if (cached.length >= need) return cached;
    if (cached.length >= 24) return cached;
    let candles = await BC._fetchKlines(symbol, interval, false);
    if (candles.length) {
      bucket.intervals.set(interval, candles);
      bucket.intervalAt.set(interval, Date.now());
      return candles;
    }
    if (options?.refreshFallback) {
      candles = await BC._fetchKlines(symbol, interval, true);
      if (candles.length) {
        bucket.intervals.set(interval, candles);
        bucket.intervalAt.set(interval, Date.now());
        return candles;
      }
    }
    if (cached.length) return cached;
    if (detail?.candles?.length && detail.interval === interval) return detail.candles;
    return [];
  },

  mount(runtime, chartElId) {
    const BC = window.boardChart;
    const container = document.getElementById(chartElId);
    if (!container || !window.LightweightCharts) return;
    runtime._chartContainer = container;
    if (runtime.chart) {
      BC.ensureBookOverlay(runtime, container);
      return;
    }
    runtime.chart = LightweightCharts.createChart(container, {
      layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
      grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
      ...BC.chartInteractionDefaults(),
    });
    runtime.series = runtime.chart.addCandlestickSeries({
      upColor: "#3dd68c",
      downColor: "#ff5d73",
      borderVisible: true,
      wickUpColor: "#3dd68c",
      wickDownColor: "#ff5d73",
    });
    runtime.series.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } });
    runtime.volumeSeries = runtime.chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    runtime.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    window.boardChart.ensureBookOverlay(runtime, container);
    const resize = () => {
      if (!runtime.chart || container.clientWidth <= 0) return;
      runtime.chart.resize(container.clientWidth, container.clientHeight || 420);
      window.boardChart.syncBookOverlayForChart(chartElId);
    };
    new ResizeObserver(resize).observe(container);
    requestAnimationFrame(resize);
  },

  candleTime(raw, interval) {
    const n = Number(raw);
    if (!n || Number.isNaN(n)) return 0;
    const sec = n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
    if (interval === "D") {
      const d = new Date(sec * 1000);
      return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
    }
    return sec;
  },

  drawCandles(runtime, candles, interval, resetScale, chartElId, livePrice) {
    const BC = window.boardChart;
    if (!runtime.series) return;
    runtime._chartInterval = interval;
    if (resetScale) {
      runtime._programmaticChartView = true;
      runtime._userChartView = false;
      runtime.series.priceScale().applyOptions({ autoScale: true });
    } else if (runtime._userChartView) {
      runtime.series.priceScale().applyOptions({ autoScale: false });
    }
    const byTime = new Map();
    for (const candle of candles || []) {
      const time = window.boardChart.candleTime(candle.timestamp ?? candle.time, interval);
      if (!time) continue;
      const close = Number(candle.close);
      if (Number.isNaN(close)) continue;
      byTime.set(typeof time === "object" ? JSON.stringify(time) : String(time), {
        time,
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close,
        volume: Number(candle.volume ?? 0),
      });
    }
    const bars = [...byTime.values()].sort((a, b) => {
      const ta = typeof a.time === "object" ? Date.UTC(a.time.year, a.time.month - 1, a.time.day) : a.time;
      const tb = typeof b.time === "object" ? Date.UTC(b.time.year, b.time.month - 1, b.time.day) : b.time;
      return ta - tb;
    });
    BC.patchLiveLastBar(bars, livePrice);
    BC.maybeFitLivePriceScale(runtime, livePrice);
    runtime.series.setData(bars);
    if (runtime.volumeSeries) {
      runtime.volumeSeries.setData(
        bars.map((b) => ({
          time: b.time,
          value: b.volume,
          color: b.close >= b.open ? "rgba(61, 214, 140, 0.45)" : "rgba(255, 93, 115, 0.45)",
        })),
      );
    }
    runtime._lastBars = bars;
    if (bars.length) {
      runtime._lastCandleTime = bars[bars.length - 1].time;
      runtime.priceRange = {
        min: Math.min(...bars.map((b) => b.low)),
        max: Math.max(...bars.map((b) => b.high)),
      };
    } else {
      runtime._lastCandleTime = null;
    }
    if (runtime._liquidations?.length) {
      runtime._liqByBar = BC.aggregateLiqByBar(bars, runtime._liquidations, interval);
    } else if (!runtime._liqByBar) {
      runtime._liqByBar = null;
    }
    const container = document.getElementById(chartElId);
    if (container && runtime.chart && container.clientWidth > 0) {
      runtime.chart.resize(container.clientWidth, container.clientHeight || 420);
    }
    if (resetScale && bars.length && runtime.chart) {
      const step = BC.INTERVAL_SEC[interval] || 3600;
      const last = bars[bars.length - 1].time;
      const to = typeof last === "object" ? last : last + step;
      runtime.chart.timeScale().setVisibleRange({ from: bars[0].time, to });
    }
    if (resetScale) {
      queueMicrotask(() => {
        runtime._programmaticChartView = false;
      });
    }
    BC.syncChartOverlaysNow(runtime);
    if (runtime._chartSymbol && runtime.liqOverlayEl && runtime._activeSymbol === runtime._chartSymbol) {
      const ref = bars.length ? bars[bars.length - 1].close : runtime._overlayProbePrice;
      BC.refreshLiqZonesOverlay(runtime, runtime._chartSymbol, ref);
    }
  },

  renderWalls(containerId, book) {
    const walls = document.getElementById(containerId);
    if (!walls) return;
    const items = book?.walls || [];
    if (!items.length) {
      walls.innerHTML = '<p class="quiet">Крупные стены в стакане появятся при потоке данных.</p>';
      return;
    }
    walls.innerHTML = items
      .map((w) => {
        const kind = w.kind === "holding" ? "Holding" : w.kind === "spoof" ? "Spoof" : "Building";
        return `<span class="wall ${w.kind}">${kind} ${window.boardChart.formatBookPrice(w.price)} · ${window.boardChart.formatBookSize(w.size)}</span>`;
      })
      .join("");
  },

  formatBookPrice(p) {
    const n = Number(p);
    if (n >= 1000) return n.toFixed(1);
    if (n >= 1) return n.toFixed(4);
    return n.toPrecision(4);
  },

  formatBookSize(s) {
    const n = Number(s);
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
    return n.toFixed(1);
  },

  tfLabel(interval) {
    return window.boardChart.TF.find(([c]) => c === interval)?.[1] || interval;
  },

  initBookPaneUi() {
    const BC = window.boardChart;
    try {
      const saved = Number(localStorage.getItem("psc-book-bin"));
      if ([1, 5, 10, 20, 50].includes(saved)) BC.BOOK_PANEL.binTicks = saved;
    } catch (_e) {
      /* ignore */
    }
    if (BC._bookUiReady) return;
    BC._bookUiReady = true;
    document.addEventListener("change", (e) => {
      const sel = e.target.closest(".psc-book-bin");
      if (!sel) return;
      const ticks = Number(sel.value) || 5;
      BC.BOOK_PANEL.binTicks = ticks;
      try {
        localStorage.setItem("psc-book-bin", String(ticks));
      } catch (_e2) {
        /* ignore */
      }
      const pane = sel.closest(".psc-book-pane");
      const ctx = pane?._bookCtx;
      if (pane?.id && ctx?.book) {
        pane._bookUserScrolled = false;
        BC.renderBookPane(pane.id, ctx.book, ctx.refPrice, ctx.symbol, { centerMid: true });
      }
    });
    document.addEventListener("click", (e) => {
      const fsBtn = e.target.closest(".psc-book-fullscreen");
      if (fsBtn) {
        const section = fsBtn.closest(".psc-book-section");
        if (!section) return;
        const on = !section.classList.contains("psc-book-section--fullscreen");
        document.querySelectorAll(".psc-book-section--fullscreen").forEach((s) => {
          if (s !== section) BC.setBookFullscreen(s, false);
        });
        BC.setBookFullscreen(section, on);
        return;
      }
      const btn = e.target.closest(".psc-toggle-meta");
      if (!btn) return;
      const info = btn.closest(".psc-info-pane");
      const meta = info?.querySelector(".psc-info-meta");
      if (!meta) return;
      const hidden = meta.classList.toggle("psc-info-meta--hidden");
      btn.textContent = hidden ? "Метрики ▾" : "Скрыть метрики";
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      document.querySelectorAll(".psc-book-section--fullscreen").forEach((s) => BC.setBookFullscreen(s, false));
    });
  },
};

window.boardChart.initBookPaneUi();
