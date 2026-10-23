/** Вкладка «Памп сигналы»: колонки + карточки монет. */

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

  function renderCard(sig) {
    const col = sig.column || "red";
    const card = document.createElement("article");
    card.className = `psig-card ${CARD_CLASS[col] || ""}`;
    card.dataset.symbol = sig.symbol;

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
