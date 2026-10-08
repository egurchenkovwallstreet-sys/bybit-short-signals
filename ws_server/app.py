"""Страница сигналов и WebSocket в браузер. Ордера отсюда не отправляются."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import config
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    return app.state.hub.stats()


@app.get("/api/paper/snapshot")
async def paper_snapshot() -> dict[str, Any]:
    data = app.state.hub.paper.view()
    if data:
        return data
    return await asyncio.to_thread(paper_db.snapshot_from_db)


@app.get("/api/paper/trades")
async def paper_trades(status: str = "closed", limit: int = 300, variant: str | None = None) -> dict[str, Any]:
    if status not in {"open", "closed"}:
        raise HTTPException(status_code=400, detail="status: open или closed")
    if variant is not None and variant not in config.PAPER_VARIANTS:
        raise HTTPException(status_code=400, detail="неизвестный вариант")
    rows = await asyncio.to_thread(paper_db.trades, status, max(1, min(limit, 2000)), variant)
    return {"rows": rows}


@app.get("/api/paper/candidates")
async def paper_candidates(limit: int = 300) -> dict[str, Any]:
    rows = await asyncio.to_thread(paper_db.candidates, max(1, min(limit, 2000)))
    return {"rows": rows}


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


@app.post("/api/watch/dismiss")
async def dismiss_board_watch(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Снять монету с доски памп-скан или 2× откат (липкий список)."""
    board = str(body.get("board") or "").strip()
    symbol = str(body.get("symbol") or "").strip().upper()
    if board not in {"pump_scan", "x2_retrace", "pump_strategy"}:
        raise HTTPException(status_code=400, detail="board: pump_scan, x2_retrace или pump_strategy")
    if not _SYMBOL.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    from signal_engine.watch_store import WatchStore

    store = WatchStore(config.SQLITE_PATH)
    store.open()
    try:
        store.dismiss(board, symbol)
    finally:
        store.close()
    return {"ok": True, "board": board, "symbol": symbol}


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


@app.get("/api/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = "1",
    refresh: bool = False,
    days: int = 0,
) -> dict[str, Any]:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    if interval not in {"1", "5", "15", "30", "60", "240", "D"}:
        raise HTTPException(status_code=400, detail="Некорректный интервал")
    window_days = days if days > 0 else config.PUMP_SCAN_CHART_FETCH_DAYS
    hub: Hub = app.state.hub
    key = (symbol, interval)
    min_bars = (
        config.kline_bars_for_days(interval, window_days)
        if days > 0
        else max(100, config.KLINE_FETCH_LIMIT // 2)
    )
    cached = hub.cache.klines.get(key)
    if cached and len(cached) >= min_bars and not refresh and days <= 0:
        return {"symbol": symbol, "interval": interval, "window_days": window_days, "candles": cached}
    from collector.rest_client import BybitRest

    rest: BybitRest | None = getattr(app.state, "bybit_rest", None)
    if rest is None:
        rest = BybitRest()
        await rest.open()
        app.state.bybit_rest = rest
    if days > 0 or refresh:
        message = await rest.fetch_klines_for_days(symbol, interval, window_days)
    else:
        message = await rest.fetch_klines(symbol, interval)
    candles = (message.get("data") or {}).get("candles") or [] if message else []
    if candles:
        hub.cache.klines[key] = list(candles)
        hub.cache.market_dirty = True
    elif cached:
        candles = cached
    return {"symbol": symbol, "interval": interval, "window_days": window_days, "candles": candles}


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
