"""Страница сигналов и WebSocket в браузер. Ордера отсюда не отправляются."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import config
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ws_server.hub import Client, Hub


STATIC_DIR = Path(__file__).resolve().parent / "static"
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}$")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    hub = Hub()
    app.state.hub = hub
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


app = FastAPI(title="Сигналы шорт", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    return app.state.hub.stats()


@app.get("/api/btc-test/analytics")
async def btc_analytics() -> dict[str, Any]:
    data = app.state.hub.btc.view()
    if not data:
        from ws_server.btc_hydrate import btc_snapshot_from_db

        data = btc_snapshot_from_db()
    if not data:
        return {"closed": 0, "wins": 0, "losses": 0, "win_rate": 0, "by_grade": {}, "factors_wins": {}, "factors_losses": {}}
    return data.get("analytics") or {}


@app.get("/api/btc-test/snapshot")
async def btc_snapshot() -> dict[str, Any]:
    data = app.state.hub.btc.view()
    if data:
        return data
    from ws_server.btc_hydrate import btc_snapshot_from_db

    snap = btc_snapshot_from_db()
    if snap:
        return snap
    return {"signals": [], "markers": [], "analytics": {}, "candles_by_tf": {}}


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


@app.get("/api/klines/{symbol}")
async def klines(symbol: str, interval: str = "1", refresh: bool = False) -> dict[str, Any]:
    if not _SYMBOL.fullmatch(symbol or ""):
        raise HTTPException(status_code=400, detail="Некорректный тикер")
    if interval not in {"1", "5", "15", "60", "240", "D"}:
        raise HTTPException(status_code=400, detail="Некорректный интервал")
    hub: Hub = app.state.hub
    key = (symbol, interval)
    min_bars = max(100, config.KLINE_FETCH_LIMIT // 2)
    cached = hub.cache.klines.get(key)
    if cached and len(cached) >= min_bars and not refresh:
        return {"symbol": symbol, "interval": interval, "candles": cached}
    from collector.rest_client import BybitRest

    rest: BybitRest | None = getattr(app.state, "bybit_rest", None)
    if rest is None:
        rest = BybitRest()
        await rest.open()
        app.state.bybit_rest = rest
    message = await rest.fetch_klines(symbol, interval)
    candles = (message.get("data") or {}).get("candles") or [] if message else []
    if candles:
        hub.cache.klines[key] = list(candles)
        hub.cache.market_dirty = True
    elif cached:
        candles = cached
    return {"symbol": symbol, "interval": interval, "candles": candles}


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
