"""WebSocket server: bridges EventBus to the browser dashboard."""

from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.server import serve

from control.event_bus import EventBus
from control.models import Event

logger = logging.getLogger(__name__)


class WebSocketServer:
    def __init__(self, event_bus: EventBus, host: str = "localhost", port: int = 8765) -> None:
        self._event_bus = event_bus
        self._host = host
        self._port = port
        self._clients: set[websockets.WebSocketServerProtocol] = set()
        self._server = None

        # Subscribe to all events
        event_bus.subscribe(self._on_event)

    async def start(self) -> None:
        self._server = await serve(self._handler, self._host, self._port)
        logger.info("WebSocket server listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, websocket: websockets.WebSocketServerProtocol) -> None:
        self._clients.add(websocket)
        logger.info("Dashboard connected (%d clients)", len(self._clients))

        # Send event history to new client
        for event in self._event_bus.history:
            try:
                await websocket.send(json.dumps(event.to_dict(), ensure_ascii=False))
            except websockets.ConnectionClosed:
                break

        try:
            async for _ in websocket:
                pass  # We don't expect messages from the dashboard
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Dashboard disconnected (%d clients)", len(self._clients))

    async def _on_event(self, event: Event) -> None:
        if not self._clients:
            return
        message = json.dumps(event.to_dict(), ensure_ascii=False)
        # Broadcast to all connected clients
        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except websockets.ConnectionClosed:
                disconnected.add(client)
        self._clients -= disconnected
