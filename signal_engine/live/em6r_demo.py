"""EMA60-6 · real → ордера на Bybit Demo Trading (api-demo.bybit.com)."""

from __future__ import annotations

import logging
import math
from typing import Any

import config

log = logging.getLogger(__name__)


def em6r_live_configured() -> bool:
    return bool(
        config.em6r_live_enabled()
        and config.BYBIT_DEMO_API_KEY
        and config.BYBIT_DEMO_API_SECRET
    )


class Em6rDemoBroker:
    """Market open/close USDT linear на Demo; paper остаётся источником сигналов."""

    def __init__(self) -> None:
        self._http: Any = None
        self._qty_step: dict[str, float] = {}

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        from pybit.unified_trading import HTTP

        self._http = HTTP(
            testnet=False,
            demo=True,
            api_key=config.BYBIT_DEMO_API_KEY,
            api_secret=config.BYBIT_DEMO_API_SECRET,
        )
        return self._http

    def _qty_step_for(self, symbol: str) -> float:
        if symbol in self._qty_step:
            return self._qty_step[symbol]
        step = 0.001
        try:
            resp = self._client().get_instruments_info(category="linear", symbol=symbol)
            row = (resp.get("result") or {}).get("list") or []
            if row:
                filt = row[0].get("lotSizeFilter") or {}
                step = float(filt.get("qtyStep") or filt.get("minOrderQty") or step)
        except Exception:
            log.exception("em6r demo: lot size %s", symbol)
        if step <= 0:
            step = 0.001
        self._qty_step[symbol] = step
        return step

    def _format_qty(self, symbol: str, qty: float) -> str | None:
        if qty <= 0:
            return None
        step = self._qty_step_for(symbol)
        n = math.floor(qty / step + 1e-12)
        if n <= 0:
            return None
        value = n * step
        decimals = max(0, min(8, int(round(-math.log10(step))) if step < 1 else 0))
        return f"{value:.{decimals}f}".rstrip("0").rstrip(".") or str(value)

    def _ensure_leverage(self, symbol: str) -> None:
        lev = str(config.PAPER_LEVERAGE)
        self._client().set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=lev,
            sellLeverage=lev,
        )

    def open_market(self, trade_id: int, symbol: str, side: str, qty: float) -> None:
        if not em6r_live_configured():
            return
        qty_s = self._format_qty(symbol, qty)
        if not qty_s:
            log.warning("em6r demo: qty too small %s %s", symbol, qty)
            return
        order_side = "Buy" if side == "long" else "Sell"
        try:
            self._ensure_leverage(symbol)
        except Exception as exc:
            log.warning("em6r demo: set_leverage %s: %s", symbol, exc)
        link = f"em6r-o-{trade_id}"
        resp = self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            orderLinkId=link[:36],
        )
        log.info("em6r demo OPEN %s %s qty=%s resp=%s", order_side, symbol, qty_s, resp.get("retCode"))

    def close_market(self, trade_id: int, symbol: str, side: str, qty: float) -> None:
        if not em6r_live_configured():
            return
        qty_s = self._format_qty(symbol, qty)
        if not qty_s:
            log.warning("em6r demo: close qty too small %s", symbol)
            return
        order_side = "Sell" if side == "long" else "Buy"
        link = f"em6r-c-{trade_id}"
        resp = self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            reduceOnly=True,
            orderLinkId=link[:36],
        )
        log.info("em6r demo CLOSE %s %s qty=%s resp=%s", order_side, symbol, qty_s, resp.get("retCode"))
