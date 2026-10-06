"""Страница сигналов и WebSocket в браузер. Ордера отсюда не отправляются."""

from __future__ import annotations

import asyncio
import re
import webbrowser
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
        return {"closed": 0, "wins": 0, "losses": 0, "win_rate": 0, "by_grade": {}, "factors_wins": {}, "factors_losses": {}}
    return data.get("analytics") or {}


@app.get("/api/tooltips")
async def tooltips() -> FileResponse:
    return FileResponse(STATIC_DIR / "tooltips.json", media_type="application/json")


@app.post("/api/open-bybit/{symbol}")
async def open_bybit(symbol: str) -> dict[str, str]:
    """Открывает график только на Bybit, на машине, где запущен сервер."""
    url = bybit_trade_url(symbol)
    await asyncio.to_thread(webbrowser.open, url)
    return {"url": url}


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
