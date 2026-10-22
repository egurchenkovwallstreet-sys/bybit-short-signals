"""Страница сигналов и WebSocket в браузер. Ордера отсюда не отправляются."""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import config
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ws_server import em6_bybit as em6_bybit_db
from ws_server import paper as paper_db
from ws_server.hub import Client, Hub


STATIC_DIR = Path(__file__).resolve().parent / "static"
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}$")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from collector.publisher import open_redis

    hub = Hub()
    app.state.hub = hub
    app.state.redis = await open_redis(config.REDIS_URL)
    import asyncio

    task = asyncio.create_task(hub.run())
    try:
        yield
    finally:
        hub.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            close = getattr(redis, "aclose", None)
            if close is not None:
                await close()


app = FastAPI(title="Сигналы шорт", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    return app.state.hub.stats()


@app.get("/api/paper/snapshot")
async def paper_snapshot() -> dict[str, Any]:
    data = app.state.hub.paper.view()
    if data:
        return data
    return await asyncio.to_thread(paper_db.snapshot_from_db)


@app.get("/api/em6-bybit/snapshot")
async def em6_bybit_snapshot() -> dict[str, Any]:
    cache = app.state.hub.em6_bybit.view()
    return await asyncio.to_thread(em6_bybit_db.snapshot_for_ui, cache)


@app.get("/api/paper/trades")
async def paper_trades(
    status: str = "closed",
    limit: int = 300,
    variant: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    if status not in {"open", "closed"}:
        raise HTTPException(status_code=400, detail="status: open или closed")
    if variant == "vps":
        variant = config.PAPER_VPS15_VARIANT
    if variant is not None and variant not in config.PAPER_VARIANTS:
        raise HTTPException(status_code=400, detail="неизвестный вариант")
    sym = (symbol or "").strip().upper() or None
    rows = await asyncio.to_thread(
        paper_db.trades, status, max(1, min(limit, 2000)), variant, sym
    )
    return {"rows": rows}


@app.get("/api/paper/candidates")
async def paper_candidates(limit: int = 300) -> dict[str, Any]:
    rows = await asyncio.to_thread(paper_db.candidates, max(1, min(limit, 2000)))
    return {"rows": rows}


@app.post("/api/paper/trades/{trade_id}/close")
async def paper_close_trade(trade_id: int) -> dict[str, Any]:
    if trade_id < 1:
        raise HTTPException(status_code=400, detail="некорректный id")
    ok = await asyncio.to_thread(paper_db.request_manual_close, trade_id)
    if not ok:
        raise HTTPException(status_code=404, detail="открытая сделка не найдена")
    return {"ok": True, "trade_id": trade_id}


@app.get("/api/tooltips")
async def tooltips() -> FileResponse:
    return FileResponse(STATIC_DIR / "tooltips.json", media_type="application/json")


@app.get("/api/open-bybit/{symbol}")
async def open_bybit_url(symbol: str) -> dict[str, str]:
    """Ссылка на график Bybit (открывается в браузере пользователя)."""
    return {"url": bybit_trade_url(symbol)}


@app.get("/api/signals/unprocessed")
async def signals_unprocessed() -> dict[str, Any]:
    from ws_server.journal import list_unprocessed

    return {"rows": list_unprocessed(config.SQLITE_PATH)}


_OI_INTERVALS = {"5min", "15min", "30min", "1h", "4h", "1d"}


@app.get("/api/open-interest/{symbol}")
async def open_interest(
    symbol: str,
    interval: str = "5min",
    refresh: bool = False,
    days: int = 0,
) -> dict[str, Any]:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    interval = interval.lower()
    if interval not in _OI_INTERVALS:
        raise HTTPException(status_code=400, detail="Некорректный интервал OI")
    window_days = days if days > 0 else config.PUMP_SCAN_CHART_FETCH_DAYS
    hub: Hub = app.state.hub
    cached = hub.cache.oi.get(symbol)
    min_pts = max(10, config.oi_bars_for_days(interval, window_days) // 4)
    if (
        cached
        and len(cached) >= min_pts
        and not refresh
        and days <= 0
        and hub.cache.oi_interval.get(symbol) == interval
    ):
        return {
            "symbol": symbol,
            "interval": interval,
            "window_days": window_days,
            "points": cached,
        }
    from collector.rest_client import BybitRest

    rest: BybitRest | None = getattr(app.state, "bybit_rest", None)
    if rest is None:
        rest = BybitRest()
        await rest.open()
        app.state.bybit_rest = rest
    if days > 0 or refresh:
        message = await rest.fetch_open_interest_for_days(symbol, interval, window_days)
    else:
        message = await rest.fetch_open_interest(symbol, interval)
    points = (message.get("data") or {}).get("points") or [] if message else []
    if points:
        hub.cache.oi[symbol] = list(points)
        hub.cache.oi_interval[symbol] = interval
        hub.cache.market_dirty = True
    elif cached:
        points = cached
    return {"symbol": symbol, "interval": interval, "window_days": window_days, "points": points}


@app.get("/api/orderbook/{symbol}")
async def orderbook(symbol: str, refresh: bool = False) -> dict[str, Any]:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    hub: Hub = app.state.hub
    view = hub.cache.book_view(symbol)
    levels = len(view.get("bids") or []) + len(view.get("asks") or [])
    if levels >= 80 and not refresh:
        return {"symbol": symbol, "book": view}
    from collector.rest_client import BybitRest

    rest: BybitRest | None = getattr(app.state, "bybit_rest", None)
    if rest is None:
        rest = BybitRest()
        await rest.open()
        app.state.bybit_rest = rest
    message = await rest.fetch_orderbook_snapshot(symbol)
    if message:
        hub.cache._market(message)
        hub.cache.market_dirty = True
        view = hub.cache.book_view(symbol)
    return {"symbol": symbol, "book": view}


@app.get("/api/liquidations/{symbol}")
async def chart_liquidations(symbol: str) -> dict[str, Any]:
    """Поток ликвидаций из кэша (48ч окно) для подписей на свечах."""
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    hub: Hub = app.state.hub
    rows = hub.cache.liquidations_for_chart(symbol)
    return {"symbol": symbol, "liquidations": rows}


@app.get("/api/liquidations-by-bar/{symbol}")
async def liquidations_by_bar(symbol: str, interval: str = "60", bars: int = 10) -> dict[str, Any]:
    """Суммы ликвидаций long/short по последним N свечам (быстро для графика)."""
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    if interval not in {"1", "5", "15", "30", "60", "240", "D"}:
        raise HTTPException(status_code=400, detail="Некорректный интервал")
    hub: Hub = app.state.hub
    return hub.cache.liquidations_by_bar(symbol, interval, bars)


@app.get("/api/liquidation-zones/{symbol}")
async def liquidation_zones(symbol: str, interval: str = "60") -> dict[str, Any]:
    """Оценочные зоны ликвидации (модель OI + история), не официальные данные Bybit."""
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    if interval not in {"1", "5", "15", "30", "60", "240", "D"}:
        raise HTTPException(status_code=400, detail="Некорректный интервал")
    hub: Hub = app.state.hub
    payload = hub.cache.liquidation_zones(symbol, interval)
    return {"symbol": symbol, "interval": interval, **payload}


def _kline_reply(
    symbol: str,
    interval: str,
    window_days: int,
    candles: list[dict[str, Any]],
    *,
    history_complete: bool,
    pivots: bool,
    now_ms: int,
    klines_bundle: dict[str, list] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "window_days": window_days,
        "candles": candles,
        "history_complete": history_complete,
    }
    if pivots and interval in config.VACUUM_LH_CONFLUENCE_INTERVALS:
        from signal_engine.vacuum_lh import chart_pivots_from_candles, enrich_pivots_senior_mtf

        packed = chart_pivots_from_candles(candles, interval, now_ms)
        bundle = dict(klines_bundle or {})
        bundle.setdefault(interval, candles)
        ap, at = enrich_pivots_senior_mtf(
            list(packed.get("anchor_peaks") or []),
            list(packed.get("anchor_troughs") or []),
            interval,
            bundle,
            now_ms,
        )
        pp, tt = enrich_pivots_senior_mtf(
            list(packed.get("peaks") or []),
            list(packed.get("troughs") or []),
            interval,
            bundle,
            now_ms,
        )
        payload["anchor_peaks"] = ap
        payload["anchor_troughs"] = at
        payload["ghost_peaks"] = packed.get("ghost_peaks") or []
        payload["ghost_troughs"] = packed.get("ghost_troughs") or []
        payload["peaks"] = pp
        payload["troughs"] = tt
        payload["pivots_ready"] = True
    return payload


async def _bybit_rest():
    from collector.rest_client import BybitRest

    rest: BybitRest | None = getattr(app.state, "bybit_rest", None)
    if rest is None:
        rest = BybitRest()
        await rest.open()
        app.state.bybit_rest = rest
    return rest


async def _refresh_kline_tail(symbol: str, interval: str, cached: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]] | None:
    """Дописать свежие бары. None — дыра длиннее лимита биржи, нужен полный ряд."""
    from ws_server.cache import merge_kline_candles

    if not cached:
        return None
    last_ts = int((cached[-1] or {}).get("timestamp") or 0)
    bar_ms = config.kline_bar_ms(interval)
    gap = 8 if bar_ms <= 0 else max(8, int((now_ms - last_ts) / bar_ms) + 3)
    if gap > config.BYBIT_KLINE_MAX_LIMIT:
        return None
    rest = await _bybit_rest()
    message = await rest.fetch_klines(symbol, interval, limit=gap)
    incoming = (message.get("data") or {}).get("candles") or [] if message else []
    if not incoming:
        return list(cached)
    merged = merge_kline_candles(cached, incoming)
    return merged


@app.get("/api/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = "1",
    refresh: bool = False,
    days: int = 0,
    bars: int = 0,
    tail: bool = False,
    pivots: bool = False,
) -> dict[str, Any]:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    if interval not in {"1", "5", "15", "30", "60", "240", "D"}:
        raise HTTPException(status_code=400, detail="Некорректный интервал")
    bar_cap = max(0, min(int(bars or 0), 1000))
    window_days = 0 if bar_cap else (days if days > 0 else config.PUMP_SCAN_CHART_FETCH_DAYS)
    hub: Hub = app.state.hub
    key = (symbol, interval)
    min_bars = (
        bar_cap
        if bar_cap
        else config.kline_bars_for_days(interval, window_days)
        if days > 0
        else max(100, config.KLINE_FETCH_LIMIT // 2)
    )
    now_ms = int(time.time() * 1000)
    cached = list(hub.cache.klines.get(key) or [])
    last_ts = int((cached[-1] or {}).get("timestamp") or 0) if cached else 0
    oldest = int((cached[0] or {}).get("timestamp") or 0) if cached else 0
    full_enough = len(cached) >= min_bars
    tail_fresh = config.kline_tail_fresh(last_ts, interval, now_ms)
    did_full = False
    fetched_ok = False
    candles: list[dict[str, Any]]
    if refresh:
        candles = []
    elif pivots or tail:
        if full_enough and tail_fresh:
            candles = cached
        elif full_enough:
            merged = await _refresh_kline_tail(symbol, interval, cached, now_ms)
            candles = merged if merged is not None else []
            if merged is None:
                did_full = True
        else:
            candles = []
            did_full = True
    elif full_enough and tail_fresh:
        candles = cached
    elif full_enough:
        merged = await _refresh_kline_tail(symbol, interval, cached, now_ms)
        candles = merged if merged is not None else []
        if merged is None:
            did_full = True
    elif config.kline_cache_servable(len(cached), last_ts, interval, min_bars, now_ms):
        candles = cached
    else:
        candles = []
        did_full = True
    if did_full or (refresh and not candles):
        rest = await _bybit_rest()
        if bar_cap:
            message = await rest.fetch_klines(symbol, interval, limit=bar_cap)
        elif days > 0 or refresh or pivots or tail:
            message = await rest.fetch_klines_for_days(symbol, interval, window_days)
        else:
            message = await rest.fetch_klines(symbol, interval)
        fetched = (message.get("data") or {}).get("candles") or [] if message else []
        if fetched:
            candles = list(fetched)
            fetched_ok = True
            hub.cache.market_dirty = True
        elif cached and not candles:
            candles = cached
    if candles and candles is not cached:
        hub.cache.klines[key] = list(candles)
    if bar_cap and len(candles) > bar_cap:
        candles = candles[-bar_cap:]
    oldest_out = int((candles[0] or {}).get("timestamp") or 0) if candles else oldest
    history_complete = bool(bar_cap and len(candles) >= bar_cap) or config.kline_history_complete(
        oldest_out, interval, window_days, now_ms
    ) or (fetched_ok and len(candles) < min_bars)
    klines_bundle = None
    if pivots and interval in config.VACUUM_LH_CONFLUENCE_INTERVALS:
        klines_bundle = hub.cache._vacuum_klines_bundle(symbol, interval)
        klines_bundle[interval] = list(candles)
    return _kline_reply(
        symbol,
        interval,
        window_days,
        candles,
        history_complete=history_complete,
        pivots=pivots,
        now_ms=now_ms,
        klines_bundle=klines_bundle,
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    hub: Hub = websocket.app.state.hub
    client = Client(websocket)
    hub.clients.add(client)
    try:
        await websocket.send_json(hub.snapshot(client))
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                hub.on_client(client, message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(client)


def bybit_trade_url(symbol: str) -> str:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    return config.BYBIT_TRADE_URL.format(symbol=symbol)
