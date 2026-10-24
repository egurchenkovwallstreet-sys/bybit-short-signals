/** Вкладка «Памп сигналы»: колонки + карточки; клик — детали и 15m график. */

(function () {
  const COL_CLASS = {
    green: "psig-col-green",
    yellow: "psig-col-yellow",
    red: "psig-col-red",
    purple: "psig-col-purple",
  };

  const CARD_CLASS = {
    green: "psig-card-green",
    yellow: "psig-card-yellow",
    red: "psig-card-red",
    purple: "psig-card-purple",
  };

  let columns = [];
  let selected = null;
  let chartApi = null;
  let chartSeries = null;
  let ema50Series = null;
  let ema100Series = null;
  let ema200Series = null;
  let peakLine = null;
  let valleyLine = null;
  let chartLoadSeq = 0;
  const CHART_HEIGHT = 520;

  function fmtNum(v, digits = 1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(digits);
  }

  function fmtPct(v) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
  }

  function fmtVolRatio(v) {
    if (v === null || v === undefined) return "—";
    return `×${Number(v).toFixed(1)}`;
  }

  function fmtTurnover(v) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
    if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}k`;
    return `$${n.toFixed(0)}`;
  }

  function metric(label, value, extraClass) {
    const row = document.createElement("div");
    row.className = "psig-metric";
    const lab = document.createElement("span");
    lab.className = "psig-m-label";
    lab.textContent = label;
    const val = document.createElement("span");
    val.className = `psig-m-value${extraClass ? ` ${extraClass}` : ""}`;
    val.textContent = value;
    row.appendChild(lab);
    row.appendChild(val);
    return row;
  }

  function parseCandles(raw, interval) {
    const sec =
      interval === "15" ? 900 : interval === "5" ? 300 : interval === "1" ? 60 : 900;
    const out = [];
    for (const row of raw || []) {
      let t;
      let o;
      let h;
      let l;
      let c;
      if (Array.isArray(row)) {
        t = Number(row[0]);
        o = Number(row[1]);
        h = Number(row[2]);
        l = Number(row[3]);
        c = Number(row[4]);
      } else if (row && typeof row === "object") {
        t = Number(row.time ?? row.timestamp ?? row.t);
        o = Number(row.open ?? row.o);
        h = Number(row.high ?? row.h);
        l = Number(row.low ?? row.l);
        c = Number(row.close ?? row.c);
      } else continue;
      if (!t || !c) continue;
      const time = t > 1e12 ? Math.floor(t / 1000) : Math.floor(t);
      out.push({ time, open: o, high: h, low: l, close: c });
    }
    out.sort((a, b) => a.time - b.time);
    const dedup = [];
    let lastT = 0;
    for (const b of out) {
      if (b.time <= lastT) b.time = lastT + sec;
      lastT = b.time;
      dedup.push(b);
    }
    return dedup;
  }

  function emaRollingValues(values, period) {
    const BC = window.boardChart;
    if (BC?.emaRollingValues) {
      return BC.emaRollingValues(values, period);
    }
    const out = new Array(values?.length || 0).fill(null);
    const p = period;
    if (p < 1 || !values?.length) return out;
    const k = 2 / (p + 1);
    let ema = null;
    for (let i = 0; i < values.length; i++) {
      const v = Number(values[i]);
      if (Number.isNaN(v)) continue;
      if (ema == null) {
        if (i < p - 1) continue;
        let sum = 0;
        for (let j = i - p + 1; j <= i; j++) sum += Number(values[j]);
        ema = sum / p;
        out[i] = ema;
        continue;
      }
      ema = v * k + ema * (1 - k);
      out[i] = ema;
    }
    return out;
  }

  function emaLineData(bars, period) {
    const closes = (bars || []).map((b) => Number(b.close));
    const ema = emaRollingValues(closes, period);
    const out = [];
    for (let i = 0; i < bars.length; i++) {
      if (ema[i] != null) out.push({ time: bars[i].time, value: ema[i] });
    }
    return out;
  }

  function ensureChart() {
    const el = document.getElementById("psig-chart");
    if (!el || !window.LightweightCharts || chartApi) return;
    chartApi = window.LightweightCharts.createChart(el, {
      layout: { background: { color: "#10141b" }, textColor: "#c5d0de" },
      grid: { vertLines: { color: "#222a36" }, horzLines: { color: "#222a36" } },
      localization: { locale: "ru-RU" },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    chartSeries = chartApi.addCandlestickSeries({
      upColor: "#3dd68c",
      downColor: "#ff5d73",
      borderVisible: true,
      wickUpColor: "#3dd68c",
      wickDownColor: "#ff5d73",
    });
    ema50Series = chartApi.addLineSeries({
      color: "#58a6ff",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: "EMA50",
    });
    ema100Series = chartApi.addLineSeries({
      color: "#d29922",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: "EMA100",
    });
    ema200Series = chartApi.addLineSeries({
      color: "#bc8cff",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: "EMA200",
    });
    const resize = () => {
      if (chartApi && el.clientWidth > 0) chartApi.resize(el.clientWidth, CHART_HEIGHT);
    };
    new ResizeObserver(resize).observe(el);
    requestAnimationFrame(resize);
  }

  function clearPriceLines() {
    if (!chartSeries) return;
    if (peakLine) {
      chartSeries.removePriceLine(peakLine);
      peakLine = null;
    }
    if (valleyLine) {
      chartSeries.removePriceLine(valleyLine);
      valleyLine = null;
    }
  }

  function addPriceLine(price, title, color) {
    if (!chartSeries || !price || price <= 0) return null;
    return chartSeries.createPriceLine({
      price: Number(price),
      color,
      lineWidth: 2,
      lineStyle: 2,
      axisLabelVisible: true,
      title,
    });
  }

  async function loadChart(sig) {
    if (!sig?.symbol) return;
    ensureChart();
    const wrap = document.getElementById("psig-detail-wrap");
    const title = document.getElementById("psig-chart-title");
    if (wrap) wrap.hidden = false;
    if (title) {
      title.textContent = `${sig.symbol} · 15m · EMA50/100/200 · пик M15 зафиксирован`;
    }
    const seq = ++chartLoadSeq;
    const q = new URLSearchParams({ interval: "15", days: "5", refresh: "1" });
    const resp = await fetch(`/api/klines/${encodeURIComponent(sig.symbol)}?${q}`);
    if (seq !== chartLoadSeq || !chartSeries) return;
    const payload = await resp.json();
    const bars = parseCandles(payload.candles || payload.klines || [], "15");
    if (!bars.length) return;
    chartSeries.setData(bars);
    if (ema50Series) ema50Series.setData(emaLineData(bars, 50));
    if (ema100Series) ema100Series.setData(emaLineData(bars, 100));
    if (ema200Series) ema200Series.setData(emaLineData(bars, 200));
    clearPriceLines();
    peakLine = addPriceLine(sig.peak_price_m15, "пик M15", "#f0b429");
    valleyLine = addPriceLine(sig.valley_price, "дно", "#3dd68c");
    chartApi.timeScale().fitContent();
  }

  function renderDetail(sig) {
    const box = document.getElementById("psig-detail-metrics");
    const head = document.getElementById("psig-detail-title");
    if (!box || !sig) return;
    if (head) head.textContent = sig.symbol || "Памп";
    box.replaceChildren();
    const grid = document.createElement("div");
    grid.className = "psig-metrics psig-detail-grid";
    const dd = sig.drawdown_from_peak_pct;
    grid.appendChild(metric("Пик M15 (зафикс.)", sig.peak_msk || "—"));
    grid.appendChild(metric("Цена пика", fmtNum(sig.peak_price_m15, 6)));
    grid.appendChild(metric("Дно / старт", sig.growth_start_msk || "—"));
    grid.appendChild(metric("Рост к пику", fmtPct(sig.growth_pct)));
    grid.appendChild(metric("С пика, мин", fmtNum(sig.since_peak_min, 0)));
    grid.appendChild(metric("Откат от пика", fmtPct(dd)));
    grid.appendChild(metric("Триггер", sig.trigger || "—"));
    grid.appendChild(metric("Объём", fmtVolRatio(sig.volume_ratio)));
    grid.appendChild(
      metric(
        "Покупки / продажи",
        `${fmtNum(sig.taker_buy_pct, 0)}% / ${fmtNum(sig.taker_sell_pct, 0)}%`
      )
    );
    grid.appendChild(
      metric("OI 1ч / 4ч", `${fmtPct(sig.oi_1h_pct)} / ${fmtPct(sig.oi_4h_pct)}`)
    );
    grid.appendChild(
      metric("Шлюз · ослабление", `${sig.passed_count ?? "—"} / 9 · ${sig.weaken_score ?? "—"}`)
    );
    grid.appendChild(metric("Оборот 24ч", fmtTurnover(sig.turnover_24h_usdt)));
    grid.appendChild(metric("CVD див.", sig.cvd_divergence ? "да" : "нет"));
    grid.appendChild(metric("Цена сейчас", fmtNum(sig.last_price, 6)));
    box.appendChild(grid);
  }

  function selectCard(sig, cardEl) {
    selected = sig;
    document.querySelectorAll(".psig-card-selected").forEach((el) => {
      el.classList.remove("psig-card-selected");
    });
    if (cardEl) cardEl.classList.add("psig-card-selected");
    renderDetail(sig);
    loadChart(sig);
  }

  function renderCard(sig) {
    const col = sig.column || "red";
    const card = document.createElement("article");
    card.className = `psig-card ${CARD_CLASS[col] || ""}`;
    card.dataset.symbol = sig.symbol;
    if (selected && selected.symbol === sig.symbol) {
      card.classList.add("psig-card-selected");
    }

    const head = document.createElement("header");
    head.className = "psig-card-head";
    const sym = document.createElement("strong");
    sym.className = "psig-symbol";
    sym.textContent = sig.symbol || "—";
    const meta = document.createElement("span");
    meta.className = "psig-meta";
    meta.textContent = sig.trigger || "";
    head.appendChild(sym);
    head.appendChild(meta);
    card.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "psig-metrics";
    const dd = sig.drawdown_from_peak_pct;
    const ddClass = dd != null && Number(dd) > 0 ? "psig-val-warn" : "";
    const growthClass = sig.growth_pct != null && Number(sig.growth_pct) >= 0 ? "psig-val-up" : "";
    grid.appendChild(metric("Пик M15", sig.peak_msk || "—"));
    grid.appendChild(metric("Старт (МСК)", sig.growth_start_msk || "—"));
    grid.appendChild(metric("Прошло", sig.elapsed_label || "—"));
    grid.appendChild(metric("Рост от дна", fmtPct(sig.growth_pct), growthClass));
    grid.appendChild(metric("Объём", fmtVolRatio(sig.volume_ratio)));
    grid.appendChild(
      metric(
        "Покупки / продажи",
        `${fmtNum(sig.taker_buy_pct, 0)}% / ${fmtNum(sig.taker_sell_pct, 0)}%`
      )
    );
    grid.appendChild(
      metric("OI 1ч / 4ч", `${fmtPct(sig.oi_1h_pct)} / ${fmtPct(sig.oi_4h_pct)}`)
    );
    grid.appendChild(metric("Откат от пика", fmtPct(dd), ddClass));
    grid.appendChild(
      metric(
        "Шлюз · ослабление",
        `${sig.passed_count ?? "—"} / 9 · ${sig.weaken_score ?? "—"}`
      )
    );
    card.appendChild(grid);

    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.addEventListener("click", () => selectCard(sig, card));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectCard(sig, card);
      }
    });
    return card;
  }

  function render() {
    const root = document.getElementById("psig-board");
    if (!root) return;
    root.replaceChildren();
    if (!columns.length) {
      const empty = document.createElement("p");
      empty.className = "quiet psig-empty";
      empty.textContent =
        "Пока нет монет на доске. Нужен живой поток collector + signal-engine и памп по правилам unified.";
      root.appendChild(empty);
      return;
    }
    for (const col of columns) {
      const wrap = document.createElement("section");
      wrap.className = `psig-col ${COL_CLASS[col.id] || ""}`;

      const panel = document.createElement("div");
      panel.className = "psig-col-panel";

      const title = document.createElement("h3");
      title.className = "psig-col-title";
      title.textContent = col.title || col.id;
      panel.appendChild(title);

      if (col.hint) {
        const hint = document.createElement("p");
        hint.className = "psig-hint";
        hint.textContent = col.hint;
        panel.appendChild(hint);
      }

      const list = document.createElement("div");
      list.className = "psig-list";
      const signals = col.signals || [];
      if (!signals.length) {
        const none = document.createElement("p");
        none.className = "psig-none";
        none.textContent = "Пусто";
        list.appendChild(none);
      } else {
        for (const sig of signals) {
          list.appendChild(renderCard(sig));
        }
      }
      panel.appendChild(list);
      wrap.appendChild(panel);
      root.appendChild(wrap);
    }
    if (selected) {
      let found = null;
      for (const col of columns) {
        for (const sig of col.signals || []) {
          if (sig.symbol === selected.symbol) {
            found = sig;
            break;
          }
        }
        if (found) break;
      }
      if (found) {
        selected = found;
        renderDetail(found);
        loadChart(found);
        const el = root.querySelector(`[data-symbol="${CSS.escape(found.symbol)}"]`);
        if (el) el.classList.add("psig-card-selected");
      }
    }
  }

  const EMPTY_COLUMNS = [
    {
      id: "green",
      title: "Готовы к шорту",
      hint: "Памп остановился, откат от пика ≤15%",
      signals: [],
    },
    {
      id: "yellow",
      title: "Затухание",
      hint: "Нет новых пиков, ослабление пампа",
      signals: [],
    },
    {
      id: "red",
      title: "Активный рост",
      hint: "Памп идёт, затухания мало",
      signals: [],
    },
    {
      id: "purple",
      title: "Памп прошёл",
      hint: "Откат от пика 15–70% — дамп уже идёт",
      signals: [],
    },
  ];

  function onBoard(data) {
    const raw = Array.isArray(data) ? data : data?.columns || [];
    columns = raw.length ? raw : EMPTY_COLUMNS;
    render();
  }

  function onTab() {
    render();
    fetch("/api/pump/signals")
      .then((r) => r.json())
      .then((payload) => onBoard(payload.columns))
      .catch(() => {});
  }

  window.pumpSignals = {
    onBoard,
    onTab,
    onSnapshot(payload) {
      if (payload) onBoard(payload);
    },
  };
})();
