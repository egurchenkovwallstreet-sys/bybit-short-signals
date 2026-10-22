"""Bybit Demo API: кошелёк, позиции, ордера, trading-stop."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import config
from signal_engine.live.em6_bybit.stops import trailing_stop_distance_price

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

    def _qty_string_on_step(self, symbol: str, qty: float) -> str | None:
        step, _ = self._instrument(symbol)
        steps = int(math.floor(qty / step + 1e-12))
        if steps <= 0:
            return None
        value = steps * step
        decimals = max(0, min(8, int(round(-math.log10(step))) if step < 1 else 0))
        return f"{value:.{decimals}f}".rstrip("0").rstrip(".") or str(value)

    def prepare_fixed_notional_order(
        self, symbol: str, price: float
    ) -> tuple[str, float, float, float] | None:
        """qty для market: номинал ≥ $500 (ceil по шагу). (qty_s, qty, margin, notional)."""
        if price <= 0:
            return None
        target = config.em6_bybit_notional_usd()
        lev = config.em6_bybit_leverage()
        step, _ = self._instrument(symbol)
        raw_qty = target / price
        steps = max(1, int(math.ceil(raw_qty / step - 1e-12)))
        cap = self._max_mkt_qty.get(symbol) or 0.0
        steps_max = steps + 10_000
        if cap > 0:
            steps_max = max(1, int(math.floor(cap / step + 1e-12)))
        # Шаг лота + формат qty: notional ≥ target (IRYS qtyStep=10 → ~499.99$ без +1 step).
        while steps <= steps_max:
            qty = steps * step
            qty_s = self._qty_string_on_step(symbol, qty)
            if not qty_s:
                steps += 1
                continue
            qty_f = float(qty_s)
            notional = qty_f * price
            if notional + 1e-6 >= target:
                margin = notional / lev
                return qty_s, qty_f, margin, notional
            steps += 1
        log.warning(
            "em6 bybit %s: notional < $%.0f (price=%.6f steps=%s cap=%.4f)",
            symbol,
            target,
            price,
            steps_max,
            cap,
        )
        return None

    def qty_for_margin(
        self,
        symbol: str,
        price: float,
        margin_usd: float,
        leverage: int,
    ) -> tuple[float, float] | None:
        """Совместимость: жёстко $500 notional, margin из факта."""
        prep = self.prepare_fixed_notional_order(symbol, price)
        if prep is None:
            return None
        _, qty_f, margin, _ = prep
        return qty_f, margin

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
        """Доступная маржа USDT (кошелёк USDT − IM), не totalEquity unified."""
        resp = self._client().get_wallet_balance(accountType="UNIFIED")
        avail = 0.0
        wallet_usdt = 0.0
        for acct in (resp.get("result") or {}).get("list") or []:
            for coin in acct.get("coin") or []:
                if str(coin.get("coin")) != "USDT":
                    continue
                wallet_usdt = float(coin.get("walletBalance") or 0)
                eq = float(coin.get("equity") or wallet_usdt)
                im = float(coin.get("totalPositionIM") or 0)
                oim = float(coin.get("totalOrderIM") or 0)
                avail = max(0.0, eq - im - oim)
                if avail <= 0 and wallet_usdt > 0:
                    avail = max(0.0, wallet_usdt - im - oim)
            if avail <= 0:
                tav = acct.get("totalAvailableBalance")
                if tav not in (None, ""):
                    avail = float(tav or 0)
        return {
            "available": avail,
            "wallet_balance_usdt": wallet_usdt,
            "equity": avail,
        }

    def linear_positions(self) -> list[dict[str, Any]]:
        resp = self._client().get_positions(category="linear", settleCoin="USDT")
        out: list[dict[str, Any]] = []
        for p in (resp.get("result") or {}).get("list") or []:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue
            side_raw = str(p.get("side") or "")
            trail_raw = p.get("trailingStop") or "0"
            trail = float(trail_raw) if trail_raw not in ("", "0") else 0.0
            sl_raw = p.get("stopLoss") or "0"
            sl = float(sl_raw) if sl_raw not in ("", "0") else 0.0
            im_raw = p.get("positionIM") or p.get("positionIMByMp") or "0"
            position_im = float(im_raw) if im_raw not in ("", "0") else 0.0
            pv = float(p.get("positionValue") or 0)
            out.append(
                {
                    "symbol": str(p.get("symbol")),
                    "side": "long" if side_raw == "Buy" else "short",
                    "size": size,
                    "avg_price": float(p.get("avgPrice") or 0),
                    "mark_price": float(p.get("markPrice") or 0),
                    "stop_loss": sl,
                    "trailing_stop": trail,
                    "take_profit": float(p.get("takeProfit") or 0),
                    "liq_price": float(p.get("liqPrice") or 0),
                    "unrealised_pnl": float(p.get("unrealisedPnl") or 0),
                    "cur_realised_pnl": float(p.get("curRealisedPnl") or 0),
                    "position_value": pv,
                    "position_im": position_im,
                    "leverage": float(
                        p.get("leverage") or config.em6_bybit_leverage()
                    ),
                    "open_time_ms": int(p.get("createdTime") or p.get("updatedTime") or 0),
                }
            )
        return out

    def _parse_closed_pnl_row(self, row: dict[str, Any]) -> dict[str, Any]:
        side_raw = str(row.get("side") or "")
        side = "long" if side_raw == "Buy" else "short"
        ct = int(row.get("createdTime") or row.get("updatedTime") or 0)
        pnl = float(row.get("closedPnl") or 0)
        qty = float(row.get("qty") or row.get("closedSize") or 0)
        entry = float(row.get("avgEntryPrice") or 0)
        exit_p = float(row.get("avgExitPrice") or 0)
        lev = float(row.get("leverage") or config.em6_bybit_leverage())
        margin = (qty * entry / lev) if lev and entry and qty else 0.0
        roe = (pnl / margin * 100.0) if margin > 0 else 0.0
        return {
            "symbol": str(row.get("symbol") or ""),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_p,
            "qty": qty,
            "pnl_usd": pnl,
            "roe_pct": round(roe, 2),
            "closed_at": ct,
            "exit_reason": "exchange",
            "leverage": lev,
            "source": "bybit",
        }

    def _fetch_closed_pnl_page(
        self,
        *,
        start_ms: int | None,
        limit: int,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "category": "linear",
            "limit": min(max(1, limit), 100),
            "endTime": int(time.time() * 1000),
        }
        if start_ms is not None:
            kwargs["startTime"] = max(0, start_ms)
        if symbol:
            kwargs["symbol"] = symbol
        resp = self._client().get_closed_pnl(**kwargs)
        code = resp.get("retCode") if isinstance(resp, dict) else None
        if code not in (0, "0", None):
            log.warning("get_closed_pnl %s: %s", symbol or "all", resp)
            return []
        return (resp.get("result") or {}).get("list") or []

    def list_recent_closed_pnl(
        self,
        *,
        start_ms: int,
        limit: int = 100,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Закрытые позиции / PnL с биржи (linear)."""
        lim = min(max(1, limit), 100)
        rows: list[dict[str, Any]] = []
        if symbols:
            merged: list[dict[str, Any]] = []
            for sym in symbols[:40]:
                try:
                    merged.extend(
                        self._fetch_closed_pnl_page(
                            start_ms=start_ms, limit=50, symbol=sym
                        )
                    )
                except Exception:
                    continue
            rows = merged
        else:
            try:
                rows = self._fetch_closed_pnl_page(start_ms=start_ms, limit=lim)
            except Exception:
                log.exception("get_closed_pnl all")
                rows = []
            if not rows:
                try:
                    rows = self._fetch_closed_pnl_page(start_ms=None, limit=lim)
                except Exception:
                    log.exception("get_closed_pnl all (no start)")
                    rows = []
        out = [self._parse_closed_pnl_row(dict(r)) for r in rows]
        out.sort(key=lambda r: r.get("closed_at") or 0, reverse=True)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for r in out:
            key = f"{r['symbol']}|{r['closed_at']}|{r['pnl_usd']}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return deduped[:limit]

    def fetch_kline_envelope(
        self, symbol: str, interval: str, *, limit: int = 200
    ) -> dict[str, Any] | None:
        try:
            from collector.normalize import kline_message

            resp = self._client().get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=min(limit, 200),
            )
            rows = (resp.get("result") or {}).get("list") or []
            return kline_message(symbol, interval, rows)
        except Exception:
            log.exception("fetch_kline_envelope %s", symbol)
            return None

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

    def open_market_fixed_notional(
        self,
        symbol: str,
        side: str,
        price: float,
        link: str,
    ) -> tuple[dict[str, Any], float, float, float]:
        """Market на ≥ $500 notional. Возвращает (resp, qty, margin, notional)."""
        prep = self.prepare_fixed_notional_order(symbol, price)
        if prep is None:
            raise ValueError(f"cannot size {symbol} for ${config.em6_bybit_notional_usd():.0f} notional")
        qty_s, qty_f, margin, notional = prep
        order_side = "Buy" if side == "long" else "Sell"
        self.set_leverage(symbol)
        resp = self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            orderLinkId=link[:36],
        )
        return resp, qty_f, margin, notional

    def open_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        link: str,
    ) -> dict[str, Any]:
        qty_s = self.format_qty(symbol, qty)
        if not qty_s:
            raise ValueError("qty too small")
        order_side = "Buy" if side == "long" else "Sell"
        self.set_leverage(symbol)
        return self._client().place_order(
            category="linear",
            symbol=symbol,
            side=order_side,
            orderType="Market",
            qty=qty_s,
            orderLinkId=link[:36],
        )

    def set_trailing_stop_roe(
        self,
        symbol: str,
        *,
        ref_price: float,
        side: str,
        trail_roe_pct: float | None = None,
    ) -> dict[str, Any]:
        dist = trailing_stop_distance_price(ref_price, trail_roe_pct)
        _, tick = self._instrument(symbol)
        dist = max(dist, tick * 2)
        dist_s = self.format_price(symbol, dist)
        return self._client().set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss="0",
            trailingStop=dist_s,
            slTriggerBy="LastPrice",
            positionIdx=0,
        )

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
        """Legacy: market + fixed SL (не используется EMA6 Bybit)."""
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
            trailingStop="0",
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
