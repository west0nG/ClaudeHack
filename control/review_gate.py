"""ReviewGate: pause pipeline for human card selection between stages."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event

logger = logging.getLogger(__name__)

# Timeout for waiting on user selection (10 minutes)
REVIEW_TIMEOUT_SECONDS = 600


def _parse_card(path: Path) -> dict:
    """Extract summary info from an idea card markdown file."""
    text = path.read_text(encoding="utf-8")
    result: dict = {"file": path.name, "path": str(path)}

    # Title: first H1
    title_match = re.search(r"^#\s+(?:Idea Card:\s*)?(.+)$", text, re.MULTILINE)
    result["title"] = title_match.group(1).strip() if title_match else path.stem

    # Scenario excerpt: first 150 chars of the Specific Scenario section
    scenario_match = re.search(
        r"##\s+Specific Scenario\s*\n+([\s\S]*?)(?=\n##\s|\Z)", text
    )
    if scenario_match:
        scenario_text = scenario_match.group(1).strip()
        # Remove HTML comments
        scenario_text = re.sub(r"<!--.*?-->", "", scenario_text, flags=re.DOTALL).strip()
        result["scenario_excerpt"] = scenario_text[:150] + ("..." if len(scenario_text) > 150 else "")
    else:
        result["scenario_excerpt"] = ""

    # Evidence count: number of bullet items under Evidence section
    evidence_match = re.search(
        r"##\s+Evidence\s*\n+([\s\S]*?)(?=\n##\s|\Z)", text
    )
    if evidence_match:
        evidence_text = evidence_match.group(1).strip()
        evidence_text = re.sub(r"<!--.*?-->", "", evidence_text, flags=re.DOTALL).strip()
        result["evidence_count"] = len(re.findall(r"^\s*-\s+", evidence_text, re.MULTILINE))
    else:
        result["evidence_count"] = 0

    # Solution direction names
    directions = re.findall(r"###\s+Direction\s+\d+:\s*(.+)$", text, re.MULTILINE)
    result["solution_directions"] = [d.strip() for d in directions]

    return result


class ReviewGate:
    """Pause pipeline to let a human review and filter idea cards."""

    def __init__(self, event_bus: EventBus, ws_server: "WebSocketServer | None" = None) -> None:
        self._event_bus = event_bus
        self._ws_server = ws_server
        self._selection_future: asyncio.Future[list[int]] | None = None
        # Per-card streaming state
        self._card_response_queue: asyncio.Queue[dict] | None = None

    def handle_review_selection(self, message: dict) -> None:
        """Called by WebSocket server when dashboard sends a batch selection."""
        if self._selection_future and not self._selection_future.done():
            indices = message.get("selected_indices", [])
            self._selection_future.set_result(indices)

    def handle_card_review_response(self, message: dict) -> None:
        """Called by WebSocket server when dashboard sends a per-card decision."""
        if self._card_response_queue is not None:
            self._card_response_queue.put_nowait(message)

    async def wait_for_selection(self, cards: list[Path]) -> list[Path]:
        """Present cards to user and wait for selection. Returns filtered list."""
        if not cards:
            return cards

        card_summaries = []
        for i, card_path in enumerate(cards):
            try:
                summary = _parse_card(card_path)
                summary["index"] = i
                card_summaries.append(summary)
            except Exception:
                logger.warning("Failed to parse card: %s", card_path, exc_info=True)
                card_summaries.append({
                    "index": i,
                    "file": card_path.name,
                    "title": card_path.stem,
                    "scenario_excerpt": "(parse error)",
                    "evidence_count": 0,
                    "solution_directions": [],
                })

        # Emit review_requested event
        await self._event_bus.emit(Event(
            type="review_requested",
            data={"cards": card_summaries},
        ))

        if self._ws_server:
            selected = await self._wait_dashboard_selection(cards, card_summaries)
        else:
            selected = await self._wait_cli_selection(cards, card_summaries)

        await self._event_bus.emit(Event(
            type="review_completed",
            data={"selected": len(selected), "total": len(cards)},
        ))

        return selected

    async def stream_approved_cards(self, cards: list[Path]) -> AsyncIterator[Path]:
        """Yield cards one at a time as the user approves them.

        For each card the user can: approve (yielded), reject (skipped),
        or approve-all (yield all remaining). Works via dashboard WebSocket
        or CLI fallback.
        """
        if not cards:
            return

        # Build summaries for all cards
        card_summaries = []
        for i, card_path in enumerate(cards):
            try:
                summary = _parse_card(card_path)
                summary["index"] = i
                card_summaries.append(summary)
            except Exception:
                logger.warning("Failed to parse card: %s", card_path, exc_info=True)
                card_summaries.append({
                    "index": i,
                    "file": card_path.name,
                    "title": card_path.stem,
                    "scenario_excerpt": "(parse error)",
                    "evidence_count": 0,
                    "solution_directions": [],
                })

        # Emit queue start so dashboard can render the full list
        await self._event_bus.emit(Event(
            type="review_queue_started",
            data={"cards": card_summaries, "total": len(cards)},
        ))

        approved_count = 0
        rejected_count = 0

        try:
            if self._ws_server:
                yield_from = self._stream_dashboard_review(cards, card_summaries)
            else:
                yield_from = self._stream_cli_review(cards, card_summaries)

            async for card_path, action in yield_from:
                if action == "approved":
                    approved_count += 1
                    yield card_path
                else:
                    rejected_count += 1
        finally:
            # Always emit completion, even if the caller closes the generator early
            await self._event_bus.emit(Event(
                type="review_queue_completed",
                data={
                    "approved": approved_count,
                    "rejected": rejected_count,
                    "total": len(cards),
                },
            ))
            logger.info(
                "Streaming review complete: %d approved, %d rejected out of %d",
                approved_count, rejected_count, len(cards),
            )

    async def _stream_dashboard_review(
        self,
        cards: list[Path],
        card_summaries: list[dict],
    ) -> AsyncIterator[tuple[Path, str]]:
        """Yield (card_path, action) pairs from dashboard WebSocket interaction."""
        self._card_response_queue = asyncio.Queue()
        self._ws_server.register_handler(
            "card_review_response", self.handle_card_review_response
        )
        try:
            for i, card_path in enumerate(cards):
                await self._event_bus.emit(Event(
                    type="card_review_requested",
                    data={"card": card_summaries[i], "index": i, "total": len(cards)},
                ))

                try:
                    response = await asyncio.wait_for(
                        self._card_response_queue.get(),
                        timeout=REVIEW_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Per-card review timeout at card %d — auto-approving remaining", i
                    )
                    for j in range(i, len(cards)):
                        await self._event_bus.emit(Event(
                            type="card_reviewed",
                            data={"index": j, "action": "approved"},
                        ))
                        yield cards[j], "approved"
                    return

                action = response.get("action", "approve")

                if action == "approve":
                    await self._event_bus.emit(Event(
                        type="card_reviewed",
                        data={"index": i, "action": "approved"},
                    ))
                    yield card_path, "approved"
                elif action == "reject":
                    await self._event_bus.emit(Event(
                        type="card_reviewed",
                        data={"index": i, "action": "rejected"},
                    ))
                    yield card_path, "rejected"
                elif action == "approve_all":
                    for j in range(i, len(cards)):
                        await self._event_bus.emit(Event(
                            type="card_reviewed",
                            data={"index": j, "action": "approved"},
                        ))
                        yield cards[j], "approved"
                    return
                else:
                    # Unrecognized action — default to approve
                    logger.warning("Unknown review action '%s' for card %d, defaulting to approve", action, i)
                    await self._event_bus.emit(Event(
                        type="card_reviewed",
                        data={"index": i, "action": "approved"},
                    ))
                    yield card_path, "approved"
        finally:
            self._ws_server.unregister_handler("card_review_response")
            self._card_response_queue = None

    async def _stream_cli_review(
        self,
        cards: list[Path],
        card_summaries: list[dict],
    ) -> AsyncIterator[tuple[Path, str]]:
        """Yield (card_path, action) pairs from CLI interaction."""
        loop = asyncio.get_running_loop()
        for i, card_path in enumerate(cards):
            summary = card_summaries[i]
            # Intentional print() for interactive CLI UX
            print(f"\n--- Card {i + 1}/{len(cards)} ---")
            print(f"  Title: {summary['title']}")
            if summary.get("scenario_excerpt"):
                print(f"  {summary['scenario_excerpt']}")
            print(
                f"  Evidence: {summary['evidence_count']} sources | "
                f"Directions: {', '.join(summary.get('solution_directions', []))}"
            )
            print("  [y]es / [n]o / [a]pprove all remaining >", end=" ", flush=True)

            try:
                raw = await asyncio.wait_for(
                    loop.run_in_executor(None, input, ""),
                    timeout=REVIEW_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("CLI review timeout — approving remaining cards")
                for j in range(i, len(cards)):
                    yield cards[j], "approved"
                return

            choice = raw.strip().lower()
            if choice in ("a", "approve", "approve all"):
                for j in range(i, len(cards)):
                    yield cards[j], "approved"
                return
            elif choice in ("n", "no"):
                yield card_path, "rejected"
            else:
                # Default: approve (y, yes, or empty)
                yield card_path, "approved"

    async def _wait_dashboard_selection(
        self, cards: list[Path], summaries: list[dict]
    ) -> list[Path]:
        """Wait for user selection via dashboard WebSocket."""
        loop = asyncio.get_running_loop()
        self._selection_future = loop.create_future()

        # Register handler on the ws_server
        assert self._ws_server is not None
        self._ws_server.register_handler("review_selection", self.handle_review_selection)

        logger.info(
            "Waiting for manual review in dashboard (%d cards, %ds timeout)...",
            len(cards), REVIEW_TIMEOUT_SECONDS,
        )

        try:
            indices = await asyncio.wait_for(
                self._selection_future, timeout=REVIEW_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning("Review timeout — keeping all cards")
            return list(cards)
        finally:
            self._ws_server.unregister_handler("review_selection")
            self._selection_future = None

        # Filter cards by selected indices
        selected = [cards[i] for i in indices if 0 <= i < len(cards)]
        logger.info("User selected %d / %d cards", len(selected), len(cards))
        return selected

    async def _wait_cli_selection(
        self, cards: list[Path], summaries: list[dict]
    ) -> list[Path]:
        """CLI fallback: print summaries and read user input."""
        print("\n" + "=" * 60)
        print("REVIEW GATE: Select idea cards to keep")
        print("=" * 60)

        for s in summaries:
            print(f"\n  [{s['index']}] {s['title']}")
            if s.get("scenario_excerpt"):
                print(f"      {s['scenario_excerpt']}")
            print(f"      Evidence: {s['evidence_count']} sources | Directions: {', '.join(s.get('solution_directions', []))}")

        print(f"\nEnter indices to KEEP (comma-separated), or 'all' to keep all.")
        print(f"Example: 0,1,3")
        print(f"Timeout: {REVIEW_TIMEOUT_SECONDS}s (defaults to 'all')\n")

        loop = asyncio.get_running_loop()
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(None, input, "> "),
                timeout=REVIEW_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("CLI review timeout — keeping all cards")
            return list(cards)

        raw = raw.strip()
        if raw.lower() == "all" or not raw:
            return list(cards)

        try:
            indices = [int(x.strip()) for x in raw.split(",")]
            selected = [cards[i] for i in indices if 0 <= i < len(cards)]
            logger.info("User selected %d / %d cards", len(selected), len(cards))
            return selected
        except ValueError:
            logger.warning("Invalid input '%s' — keeping all cards", raw)
            return list(cards)
