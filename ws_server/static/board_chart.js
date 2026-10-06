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
  PREFETCH_CONCURRENCY: 3,
  /** Стакан в боковой панели: глубина ±10% от текущей цены. */
  BOOK_DEPTH_PCT: 0.1,
  BOOK_PANEL: {
    maxRowsPerSide: 28,
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

  bookBinSize(refPrice, vis) {
    const tick = window.boardChart.inferPriceTick(refPrice);
    return tick * (vis.binTicks ?? 15);
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

  prepareBookDepth(book, refPrice, depthPct) {
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
    let bids = BC.mergeBookLevels(bidsRaw, true);
    let asks = BC.mergeBookLevels(asksRaw, false);
    const cap = BC.BOOK_PANEL.maxRowsPerSide;
    const nearMid = (r) => Math.abs(r.price - mid);
    bids = [...bids].sort((a, b) => nearMid(a) - nearMid(b)).slice(0, cap);
    asks = [...asks].sort((a, b) => nearMid(a) - nearMid(b)).slice(0, cap);
    bids.sort((a, b) => b.price - a.price);
    asks.sort((a, b) => a.price - b.price);
    const walls = new Map();
    for (const w of book?.walls || []) {
      const p = Number(w.price);
      if (p > 0) walls.set(p, w);
    }
    return { mid, lo, hi, asks, bids, depthPct: band, walls };
  },

  bookPaneHtml(data) {
    const BC = window.boardChart;
    const { mid, lo, hi, asks, bids, depthPct, walls } = data;
    const pct = Math.round((depthPct ?? BC.BOOK_DEPTH_PCT) * 100);
    if (!asks.length && !bids.length) {
      return `<p class="quiet">Нет заявок в ±${pct}% от ${BC.formatBookPrice(mid) || "цены"}. Загрузка с биржи…</p>`;
    }
    const maxAsk = Math.max(...asks.map((r) => r.size), 1);
    const maxBid = Math.max(...bids.map((r) => r.size), 1);
    const wallAt = (price) => {
      for (const [p, w] of walls.entries()) {
        if (Math.abs(p - price) <= Math.max(price, p) * 0.00003) return w;
      }
      return null;
    };
    const rowHtml = (r, side, max) => {
      const bar = Math.max(8, Math.round((r.size / max) * 100));
      const tag = BC.wallTag(wallAt(r.price));
      return `<tr class="psc-book-tr ${side}">
        <td class="psc-book-price">${BC.formatBookPrice(r.price)}</td>
        <td class="psc-book-size-cell">
          <div class="psc-book-bar-track"><div class="psc-book-bar ${side}" style="width:${bar}%"></div></div>
          <span class="psc-book-size">${BC.formatBookSize(r.size)}${tag}</span>
        </td>
      </tr>`;
    };
    const askRows = [...asks].reverse().map((r) => rowHtml(r, "ask", maxAsk)).join("");
    const bidRows = bids.map((r) => rowHtml(r, "bid", maxBid)).join("");
    return `<table class="psc-book-table">
      <thead><tr><th>Цена</th><th>Объём · продажа</th></tr></thead>
      <tbody class="psc-book-asks">${askRows || `<tr><td colspan="2" class="quiet">нет ask в диапазоне</td></tr>`}</tbody>
      <tbody class="psc-book-mid-body"><tr class="psc-book-mid-row">
        <td colspan="2"><strong>${BC.formatBookPrice(mid)}</strong>
        <span class="quiet"> ±${pct}% (${BC.formatBookPrice(lo)} – ${BC.formatBookPrice(hi)})</span></td>
      </tr></tbody>
      <thead><tr><th>Цена</th><th>Объём · покупка</th></tr></thead>
      <tbody class="psc-book-bids">${bidRows || `<tr><td colspan="2" class="quiet">нет bid в диапазоне</td></tr>`}</tbody>
    </table>
    <p class="quiet psc-book-legend">Каждая строка — цена и суммарный объём лимиток на этом уровне. Крупные: «стена», «нарастает», «сняли».</p>`;
  },

  bookLevelCount(book) {
    const BC = window.boardChart;
    return BC.normalizeBookSide(book?.bids).length + BC.normalizeBookSide(book?.asks).length;
  },

  async fetchBookFromApi(symbol) {
    try {
      const res = await fetch(`/api/orderbook/${encodeURIComponent(symbol)}?refresh=1`);
      if (!res.ok) return null;
      const payload = await res.json();
      return payload.book || null;
    } catch (_e) {
      return null;
    }
  },

  renderBookPane(containerId, book, refPrice, symbol) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const sym = symbol || "";
    const paint = (b) => {
      const data = window.boardChart.prepareBookDepth(b, refPrice);
      el.innerHTML = window.boardChart.bookPaneHtml(data);
    };
    if (book && window.boardChart.bookLevelCount(book) >= 3) {
      paint(book);
      return;
    }
    el.innerHTML = '<p class="quiet">Загрузка стакана с биржи…</p>';
    if (!sym) return;
    const pending = window.boardChart._bookFetch.get(sym);
    if (pending) {
      void pending.then((b) => b && paint(b));
      return;
    }
    const job = window.boardChart.fetchBookFromApi(sym).finally(() => {
      window.boardChart._bookFetch.delete(sym);
    });
    window.boardChart._bookFetch.set(sym, job);
    void job.then((b) => {
      if (b) paint(b);
      else el.innerHTML = '<p class="quiet">Не удалось получить стакан. Повтор через несколько секунд.</p>';
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
    return { map: new Map(), queue: [], active: 0 };
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

  schedulePrefetch(store, symbols, intervals) {
    const list = intervals?.length ? intervals : ["15"];
    for (const symbol of symbols) {
      for (const interval of list) {
        window.boardChart._enqueuePrefetch(store, symbol, interval);
      }
    }
    window.boardChart._drainPrefetch(store);
  },

  _enqueuePrefetch(store, symbol, interval) {
    const key = `${symbol}:${interval}`;
    const bucket = store.map.get(symbol) || { intervals: new Map() };
    store.map.set(symbol, bucket);
    if (bucket.intervals.has(interval)) return;
    if (store.queue.some((j) => j.key === key)) return;
    store.queue.push({ symbol, interval, key });
  },

  _drainPrefetch(store) {
    const BC = window.boardChart;
    while (store.active < BC.PREFETCH_CONCURRENCY && store.queue.length) {
      const job = store.queue.shift();
      if (!job) break;
      store.active += 1;
      void BC._fetchKlines(job.symbol, job.interval).then((candles) => {
        const bucket = store.map.get(job.symbol) || { intervals: new Map() };
        bucket.intervals.set(job.interval, candles);
        store.map.set(job.symbol, bucket);
      }).finally(() => {
        store.active -= 1;
        BC._drainPrefetch(store);
      });
    }
  },

  async _fetchKlines(symbol, interval) {
    try {
      const q = new URLSearchParams({
        interval,
        days: String(window.boardChart.FETCH_DAYS),
        refresh: "1",
      });
      const res = await fetch(`/api/klines/${encodeURIComponent(symbol)}?${q}`);
      if (!res.ok) return [];
      const payload = await res.json();
      return payload.candles || [];
    } catch (_e) {
      return [];
    }
  },

  async ensureCandles(store, symbol, interval, detail) {
    const BC = window.boardChart;
    const need = BC.minBarsForDays(interval, BC.FETCH_DAYS);
    const bucket = store.map.get(symbol);
    const cached = bucket?.intervals?.get(interval);
    if (cached && cached.length >= need) return cached;
    const candles = await BC._fetchKlines(symbol, interval);
    if (candles.length) {
      const b = store.map.get(symbol) || { intervals: new Map() };
      b.intervals.set(interval, candles);
      store.map.set(symbol, b);
      return candles;
    }
    if (detail?.candles?.length && detail.interval === interval) return detail.candles;
    return [];
  },

  mount(runtime, chartElId) {
    if (runtime.chart) return;
    const container = document.getElementById(chartElId);
    if (!container || !window.LightweightCharts) return;
    runtime.chart = LightweightCharts.createChart(container, {
      layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
      grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 7 },
      rightPriceScale: { borderColor: "#2c3544" },
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
    const resize = () => {
      if (!runtime.chart || container.clientWidth <= 0) return;
      runtime.chart.resize(container.clientWidth, container.clientHeight || 420);
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

  drawCandles(runtime, candles, interval, resetScale, chartElId) {
    if (!runtime.series) return;
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
    if (bars.length) {
      runtime.priceRange = {
        min: Math.min(...bars.map((b) => b.low)),
        max: Math.max(...bars.map((b) => b.high)),
      };
    }
    const container = document.getElementById(chartElId);
    if (container && runtime.chart && container.clientWidth > 0) {
      runtime.chart.resize(container.clientWidth, container.clientHeight || 420);
    }
    if (resetScale && bars.length && runtime.chart) {
      const step = window.boardChart.INTERVAL_SEC[interval] || 3600;
      const last = bars[bars.length - 1].time;
      const to = typeof last === "object" ? last : last + step;
      runtime.chart.timeScale().setVisibleRange({ from: bars[0].time, to });
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
};
