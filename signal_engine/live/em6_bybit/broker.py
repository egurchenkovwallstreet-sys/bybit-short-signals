"""Bybit Demo API: кошелёк, позиции, ордера, trading-stop."""

from __future__ import annotations

import logging
import math
from typing import Any

import config

log = logging.getLogger(__name__)


class Em6BybitBroker:
    def __init__(self) -> None:
        self._http: Any = None
        self._qty_step: dict[str, float] = {}
        self._tick_size: dict[str, float] = {}

    def configured(self) -> bool:
        return bool(
            config.em6_bybit_enabled()
            and config.BYBIT_DEMO_API_KEY
            and config.BYBIT_DEMO_API_SECRET
        )

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

    def _instrument(self, symbol: str) -> tuple[float, float]:
        if symbol in self._qty_step and symbol in self._tick_size:
            return self._qty_step[symbol], self._tick_size[symbol]
        step, tick = 0.001, 0.0001
        try:
            resp = self._client().get_instruments_info(category="linear", symbol=symbol)
            row = (resp.get("result") or {}).get("list") or []
            if row:
                lot = row[0].get("lotSizeFilter") or {}
                price = row[0].get("priceFilter") or {}
                step = float(lot.get("qtyStep") or lot.get("minOrderQty") or step)
                tick = float(price.get("tickSize") or tick)
        except Exception:
            log.exception("instrument %s", symbol)
        self._qty_step[symbol] = max(step, 1e-8)
        self._tick_size[symbol] = max(tick, 1e-8)
        return self._qty_step[symbol], self._tick_size[symbol]

    def format_qty(self, symbol: str, qty: float) -> str | None:
        if qty <= 0:
            return None
        step, _ = self._instrument(symbol)
        n = math.floor(qty / step + 1e-12)
        if n <= 0:
            return None
        value = n * step
        decimals = max(0, min(8, int(round(-math.log10(step))) if step < 1 else 0))
        return f"{value:.{decimals}f}".rstrip("0").rstrip(".") or str(value)

    def format_price(self, symbol: str, price: float) -> str:
        _, tick = self._instrument(symbol)
        n = round(price / tick)
        value = n * tick
        decimals = max(0, min(8, int(round(-math.log10(tick))) if tick < 1 else 0))
        return f"{value:.{decimals}f}".rstrip("0").rstrip(".") or str(value)

    def wallet_usdt(self) -> dict[str, float]:
        resp = self._client().get_wallet_balance(accountType="UNIFIED")
        total = avail = 0.0
        for acct in (resp.get("result") or {}).get("list") or []:
            for coin in acct.get("coin") or []:
                if str(coin.get("coin")) == "USDT":
                    total += float(coin.get("equity") or coin.get("walletBalance") or 0)
                    avail += float(coin.get("availableToWithdraw") or coin.get("availableBalance") or 0)
        if avail <= 0 and total > 0:
            avail = total
        return {"equity": total, "available": avail}

    def linear_positions(self) -> list[dict[str, Any]]:
        resp = self._client().get_positions(category="linear", settleCoin="USDT")
        out: list[dict[str, Any]] = []
        for p in (resp.get("result") or {}).get("list") or []:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue
            side_raw = str(p.get("side") or "")
            out.append(
                {
                    "symbol": str(p.get("symbol")),
                    "side": "long" if side_raw == "Buy" else "short",
                    "size": size,
                    "avg_price": float(p.get("avgPrice") or 0),
                    "mark_price": float(p.get("markPrice") or 0),
                    "stop_loss": float(p.get("stopLoss") or 0),
                    "unrealised_pnl": float(p.get("unrealisedPnl") or 0),
                    "leverage": float(p.get("leverage") or config.PAPER_LEVERAGE),
                }
            )
        return out

    def set_leverage(self, symbol: str) -> None:
        lev = str(config.PAPER_LEVERAGE)
        try:
            self._client().set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=lev,
                sellLeverage=lev,
            )
        except Exception as exc:
            if "110043" not in str(exc):
                log.warning("set_leverage %s: %s", symbol, exc)

    def open_market_with_stop(
        self, symbol: str, side: str, qty: float, stop_price: float, link: str
    ) -> dict[str, Any]:
        qty_s = self.format_qty(symbol, qty)
        if not qty_s:
            raise ValueError("qty too small")
        stop_s = self.format_price(symbol, stop_price)
        order_side = "Buy" if side == "long" else "Sell"
        self.set_leverage(symbol)
        resp = self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            stopLoss=stop_s,
            slTriggerBy="LastPrice",
            orderLinkId=link[:36],
        )
        return resp

    def set_stop_loss(self, symbol: str, stop_price: float) -> dict[str, Any]:
        stop_s = self.format_price(symbol, stop_price)
        return self._client().set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=stop_s,
            slTriggerBy="LastPrice",
            positionIdx=0,
        )

    def close_market(self, symbol: str, side: str, qty: float, link: str) -> dict[str, Any]:
        qty_s = self.format_qty(symbol, qty)
        if not qty_s:
            raise ValueError("qty too small")
        order_side = "Sell" if side == "long" else "Buy"
        return self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            reduceOnly=True,
            orderLinkId=link[:36],
        )
