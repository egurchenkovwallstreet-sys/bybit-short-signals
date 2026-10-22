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
        self._max_mkt_qty: dict[str, float] = {}

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
        max_mkt = 0.0
        try:
            resp = self._client().get_instruments_info(category="linear", symbol=symbol)
            row = (resp.get("result") or {}).get("list") or []
            if row:
                lot = row[0].get("lotSizeFilter") or {}
                price = row[0].get("priceFilter") or {}
                step = float(lot.get("qtyStep") or lot.get("minOrderQty") or step)
                tick = float(price.get("tickSize") or tick)
                max_mkt = float(
                    lot.get("maxMktOrderQty") or lot.get("maxOrderQty") or 0
                )
        except Exception:
            log.exception("instrument %s", symbol)
        self._qty_step[symbol] = max(step, 1e-8)
        self._tick_size[symbol] = max(tick, 1e-8)
        if max_mkt > 0:
            self._max_mkt_qty[symbol] = max_mkt
        return self._qty_step[symbol], self._tick_size[symbol]

    def cap_order_qty(self, symbol: str, qty: float) -> float:
        if qty <= 0:
            return qty
        self._instrument(symbol)
        cap = self._max_mkt_qty.get(symbol) or 0.0
        if cap > 0 and qty > cap:
            log.warning(
                "em6 bybit %s: qty %.4f > maxMktOrderQty %.4f, cap",
                symbol,
                qty,
                cap,
            )
            return cap
        return qty

    def qty_for_margin(
        self,
        symbol: str,
        price: float,
        margin_usd: float,
        leverage: int,
    ) -> tuple[float, float] | None:
        """Подобрать qty под целевую маржу; (qty, фактическая маржа) или None."""
        if price <= 0 or margin_usd <= 0 or leverage <= 0:
            return None
        target_notional = margin_usd * leverage
        raw_qty = self.cap_order_qty(symbol, target_notional / price)
        if raw_qty <= 0:
            return None
        step, _ = self._instrument(symbol)
        steps = max(1, int(math.floor(raw_qty / step + 1e-12)))
        qty = steps * step
        cap = self._max_mkt_qty.get(symbol) or 0.0
        if cap > 0 and qty > cap:
            steps = max(1, int(math.floor(cap / step + 1e-12)))
            qty = steps * step
        if qty <= 0:
            return None
        notional = qty * price
        if notional + 1e-9 < config.EM6_BYBIT_MIN_ORDER_VALUE_USDT:
            return None
        actual_margin = notional / leverage
        min_margin = margin_usd * 0.95
        if actual_margin + 1e-9 < min_margin:
            extra_steps = int(math.ceil((margin_usd * leverage / price) / step - steps))
            for _ in range(max(0, extra_steps) + 2):
                steps += 1
                qty = steps * step
                if cap > 0 and qty > cap:
                    return None
                notional = qty * price
                actual_margin = notional / leverage
                if actual_margin + 1e-9 >= min_margin:
                    break
            if actual_margin + 1e-9 < min_margin:
                return None
        return qty, actual_margin

    def format_qty(self, symbol: str, qty: float) -> str | None:
        if qty <= 0:
            return None
        qty = self.cap_order_qty(symbol, qty)
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
                    "leverage": float(
                        p.get("leverage") or config.em6_bybit_leverage()
                    ),
                }
            )
        return out

    def set_leverage(self, symbol: str) -> None:
        lev = str(config.em6_bybit_leverage())
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

    def clamp_stop_for_exchange(
        self, symbol: str, side: str, stop_price: float, ref_price: float
    ) -> float:
        """Bybit: SL лонга строго ниже LastPrice, шорта — выше."""
        if ref_price <= 0:
            return stop_price
        _, tick = self._instrument(symbol)
        buffer = tick * 2
        if side == "long":
            return min(stop_price, ref_price - buffer)
        return max(stop_price, ref_price + buffer)

    def open_market_with_stop(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        link: str,
        *,
        ref_price: float,
    ) -> dict[str, Any]:
        qty_s = self.format_qty(symbol, qty)
        if not qty_s:
            raise ValueError("qty too small")
        stop_price = self.clamp_stop_for_exchange(symbol, side, stop_price, ref_price)
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

    def set_stop_loss(
        self, symbol: str, stop_price: float, *, side: str, ref_price: float
    ) -> dict[str, Any]:
        stop_price = self.clamp_stop_for_exchange(symbol, side, stop_price, ref_price)
        stop_s = self.format_price(symbol, stop_price)
        return self._client().set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=stop_s,
            slTriggerBy="LastPrice",
            positionIdx=0,
        )

    def fetch_closed_pnl(self, symbol: str, start_ms: int, *, limit: int = 100) -> list[dict[str, Any]]:
        try:
            resp = self._client().get_closed_pnl(
                category="linear",
                symbol=symbol,
                startTime=max(0, start_ms),
                limit=min(limit, 100),
            )
        except Exception:
            log.exception("get_closed_pnl %s", symbol)
            return []
        rows = (resp.get("result") or {}).get("list") or []
        return [dict(r) for r in rows]

    @staticmethod
    def _closed_pnl_key(row: dict[str, Any]) -> str:
        return f"{row.get('createdTime')}|{row.get('orderId')}|{row.get('closedPnl')}"

    def match_closed_pnl(
        self,
        symbol: str,
        opened_at_ms: int,
        entry_price: float,
        *,
        closed_at_ms: int | None = None,
        used_keys: set[str] | None = None,
    ) -> dict[str, float] | None:
        """Сопоставить сделку с записью closed PnL (не «последнюю по символу»)."""
        start = max(0, opened_at_ms - 300_000)
        rows = self.fetch_closed_pnl(symbol, start, limit=100)
        if not rows:
            return None
        used = used_keys or set()
        best: tuple[float, dict[str, Any]] | None = None
        for row in rows:
            key = self._closed_pnl_key(row)
            if key in used:
                continue
            ct = int(row.get("createdTime") or row.get("updatedTime") or 0)
            if ct < opened_at_ms - 180_000:
                continue
            if closed_at_ms is not None and ct > closed_at_ms + 900_000:
                continue
            avg_ent = float(row.get("avgEntryPrice") or 0)
            if avg_ent <= 0:
                continue
            if abs(avg_ent - entry_price) / avg_ent > 0.025:
                continue
            target = closed_at_ms if closed_at_ms is not None else opened_at_ms
            dist = abs(ct - target)
            if best is None or dist < best[0]:
                best = (dist, row)
        if best is None:
            return None
        row = best[1]
        used.add(self._closed_pnl_key(row))
        return {
            "exit_price": float(row.get("avgExitPrice") or 0),
            "pnl_usd": float(row.get("closedPnl") or 0),
            "closed_at_ms": int(row.get("createdTime") or row.get("updatedTime") or 0),
        }

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
