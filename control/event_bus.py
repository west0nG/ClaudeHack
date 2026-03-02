"""Simple async event pub/sub system."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from control.models import Event

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], Any]] = []
        self._history: list[Event] = []

    def subscribe(self, callback: Callable) -> None:
        self._subscribers.append(callback)

    async def emit(self, event: Event) -> None:
        self._history.append(event)
        for callback in self._subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in event subscriber")

    @property
    def history(self) -> list[Event]:
        return list(self._history)
