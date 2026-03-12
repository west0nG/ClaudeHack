"""WebSocket server: bridges EventBus to the browser dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

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
        self._handlers: dict[str, list[Callable]] = {}

        # Subscribe to all events
        event_bus.subscribe(self._on_event)

    async def start(self) -> None:
        self._server = await serve(self._handler, self._host, self._port)
        logger.info("WebSocket server listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def register_handler(self, message_type: str, handler: callable) -> None:
        """Register a handler for incoming WebSocket messages of a given type."""
        self._handlers.setdefault(message_type, []).append(handler)

    def unregister_handler(self, message_type: str, handler: callable | None = None) -> None:
        """Remove handler(s) for a message type. If handler is None, remove all."""
        if handler is None:
            self._handlers.pop(message_type, None)
        elif message_type in self._handlers:
            self._handlers[message_type] = [
                h for h in self._handlers[message_type] if h is not handler
            ]

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
            async for raw_message in websocket:
                self._dispatch_message(raw_message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Dashboard disconnected (%d clients)", len(self._clients))

    def _dispatch_message(self, raw_message: str) -> None:
        """Parse incoming JSON message and dispatch to registered handlers."""
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from dashboard: %s", raw_message[:100])
            return

        msg_type = message.get("type", "")
        handlers = self._handlers.get(msg_type, [])
        if not handlers:
            logger.debug("No handler for message type: %s", msg_type)
            return

        for handler in handlers:
            try:
                handler(message)
            except Exception:
                logger.exception("Error in message handler for type=%s", msg_type)

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
