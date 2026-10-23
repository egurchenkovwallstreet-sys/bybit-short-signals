/** Вкладка «Памп сигналы»: три колонки red / yellow / green. */

(function () {
  const COL_CLASS = {
    green: "psig-col-green",
    yellow: "psig-col-yellow",
    red: "psig-col-red",
    purple: "psig-col-purple",
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

  function renderCard(sig) {
    const col = sig.column || "red";
    const card = document.createElement("article");
    card.className = `psig-card ${COL_CLASS[col] || ""}`;
    card.dataset.symbol = sig.symbol;

    const oi1 = sig.oi_1h_pct;
    const oi4 = sig.oi_4h_pct;
    const buy = sig.taker_buy_pct;
    const sell = sig.taker_sell_pct;

    card.innerHTML = `
      <header class="psig-card-head">
        <strong class="psig-symbol">${sig.symbol}</strong>
        <span class="psig-meta">${sig.trigger || ""}</span>
      </header>
      <dl class="psig-dl">
        <div><dt>Старт роста (МСК)</dt><dd>${sig.growth_start_msk || "—"}</dd></div>
        <div><dt>Прошло</dt><dd>${sig.elapsed_label || "—"}</dd></div>
        <div><dt>Рост от дна</dt><dd>${fmtPct(sig.growth_pct)}</dd></div>
        <div><dt>Объём (ratio)</dt><dd>${fmtVolRatio(sig.volume_ratio)}</dd></div>
        <div><dt>Покупки / продажи</dt><dd>${fmtNum(buy, 0)}% / ${fmtNum(sell, 0)}%</dd></div>
        <div><dt>OI 1ч / 4ч</dt><dd>${fmtPct(oi1)} / ${fmtPct(oi4)}</dd></div>
        <div><dt>Откат от пика</dt><dd>${fmtPct(sig.drawdown_from_peak_pct)}</dd></div>
        <div><dt>Условий 9</dt><dd>${sig.passed_count ?? "—"} · ослабление ${sig.weaken_score ?? "—"}</dd></div>
      </dl>
    `;
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
      const title = document.createElement("h3");
      title.textContent = col.title || col.id;
      wrap.appendChild(title);
      if (col.hint) {
        const hint = document.createElement("p");
        hint.className = "quiet psig-hint";
        hint.textContent = col.hint;
        wrap.appendChild(hint);
      }
      const list = document.createElement("div");
      list.className = "psig-list";
      const signals = col.signals || [];
      if (!signals.length) {
        const none = document.createElement("p");
        none.className = "quiet";
        none.textContent = "—";
        list.appendChild(none);
      } else {
        for (const sig of signals) {
          list.appendChild(renderCard(sig));
        }
      }
      wrap.appendChild(list);
      root.appendChild(wrap);
    }
  }

  const EMPTY_COLUMNS = [
    { id: "green", title: "Готовы к шорту", hint: "", signals: [] },
    { id: "yellow", title: "Затухание", hint: "", signals: [] },
    { id: "red", title: "Активный рост", hint: "", signals: [] },
    { id: "purple", title: "Памп прошёл", hint: "", signals: [] },
  ];

  function onBoard(data) {
    const raw = Array.isArray(data) ? data : data?.columns || [];
    columns = raw.length ? raw : EMPTY_COLUMNS;
    render();
  }

  function onTab() {
    render();
    if (!columns.length) {
      fetch("/api/pump/signals")
        .then((r) => r.json())
        .then((payload) => onBoard(payload.columns))
        .catch(() => {});
    }
  }

  window.pumpSignals = { onBoard, onTab, onSnapshot(payload) {
    if (payload) onBoard(payload);
  } };
})();
