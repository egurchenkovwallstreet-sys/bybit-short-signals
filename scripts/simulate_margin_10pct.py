"""Virtual P&L if margin per entry were 10% of balance (same trades, prices, exits)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config

ACTUAL_MARGIN_PCT = config.PAPER_MARGIN_PCT
SIM_MARGIN_PCT = 10.0
START = config.PAPER_START_BALANCE_USD


def scale_pnl(row: sqlite3.Row) -> float:
    pnl = float(row["pnl_usd"] or 0)
    margin = float(row["margin"] or 0)
    if margin <= 0:
        return pnl * (SIM_MARGIN_PCT / ACTUAL_MARGIN_PCT)
    return pnl * (SIM_MARGIN_PCT / ACTUAL_MARGIN_PCT)


def summarize(rows: list[sqlite3.Row], label: str) -> None:
    if not rows:
        print(f"{label}: no trades")
        return
    pnls = [float(r["pnl_usd"] or 0) for r in rows]
    sim = [scale_pnl(r) for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    fees = sum(float(r["entry_fee"] or 0) + float(r["exit_fee"] or 0) for r in rows)
    sim_fees = fees * (SIM_MARGIN_PCT / ACTUAL_MARGIN_PCT)
    gross_win = sum(p for p in sim if p > 0)
    gross_loss = -sum(p for p in sim if p <= 0)
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    print(
        f"\n=== {label} ===\n"
        f"  closed: {len(rows)}  wins: {wins}  WR: {wins/len(rows)*100:.1f}%\n"
        f"  actual total P&L @ {ACTUAL_MARGIN_PCT:g}% margin: ${sum(pnls):+.2f}\n"
        f"  virtual total P&L @ {SIM_MARGIN_PCT:g}% margin: ${sum(sim):+.2f}  (×{SIM_MARGIN_PCT/ACTUAL_MARGIN_PCT:g})\n"
        f"  avg ROE unchanged (size only): actual avg {sum(float(r['roe_pct'] or 0) for r in rows)/len(rows):+.1f}%\n"
        f"  fees actual ${fees:.2f} → virtual ${sim_fees:.2f}\n"
        f"  liquidations: {sum(1 for r in rows if r['exit_reason']=='liquidation')}\n"
        f"  PF (virtual): {pf}"
    )
    best = max(sim)
    worst = min(sim)
    print(f"  best / worst trade (virtual): ${best:+.2f} / ${worst:+.2f}")


def balance_path(rows: list[sqlite3.Row], variant: str) -> None:
    """Sequential balance: each close applies scaled pnl (same order as closed_at)."""
    bal_act = START
    bal_sim = START
    peak_act = START
    peak_sim = START
    max_dd_act = 0.0
    max_dd_sim = 0.0
    for r in rows:
        p_act = float(r["pnl_usd"] or 0)
        p_sim = scale_pnl(r)
        bal_act += p_act
        bal_sim += p_sim
        peak_act = max(peak_act, bal_act)
        peak_sim = max(peak_sim, bal_sim)
        if peak_act > 0:
            max_dd_act = max(max_dd_act, (peak_act - bal_act) / peak_act * 100)
        if peak_sim > 0:
            max_dd_sim = max(max_dd_sim, (peak_sim - bal_sim) / peak_sim * 100)
    print(
        f"\n--- {variant} balance path (start ${START:.0f}) ---\n"
        f"  actual end balance: ${bal_act:.2f}  max DD {max_dd_act:.2f}%\n"
        f"  virtual @10% end balance: ${bal_sim:.2f}  max DD {max_dd_sim:.2f}%"
    )


def main() -> None:
    conn = sqlite3.connect(config.PAPER_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    print(
        f"Paper closed trades — virtual margin {SIM_MARGIN_PCT:g}% "
        f"(actual config {ACTUAL_MARGIN_PCT:g}%, leverage {config.PAPER_LEVERAGE}x)"
    )
    all_rows: list[sqlite3.Row] = []
    for variant in config.PAPER_VARIANTS:
        rows = list(
            conn.execute(
                "SELECT * FROM paper_trades WHERE status='closed' AND variant=? ORDER BY closed_at",
                (variant,),
            )
        )
        summarize(rows, f"variant {variant} ({config.PAPER_VARIANTS and variant})")
        balance_path(rows, variant)
        all_rows.extend(rows)

    summarize(all_rows, "BOTH variants combined")
    # overlap note: same symbol entries are independent per variant
    print("\nNote: linear scale — same entry/exit prices; ROE% per trade unchanged; P&L USD ×2.")


if __name__ == "__main__":
    main()
