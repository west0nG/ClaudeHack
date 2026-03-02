"""Main entry point for Hackathon Agent control plane.

Usage:
    python -m control.main --theme "AI + Education"
    python -m control.main --theme "AI + Education" --interests "学生,教师"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from control.event_bus import EventBus
from control.models import Event
from control.session_manager import SessionManager
from control.stages.stage1 import run_stage1
from control.ws_server import WebSocketServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hackathon-agent")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hackathon Agent — autonomous ideation system")
    parser.add_argument("--theme", required=True, help="Hackathon theme (e.g. 'AI + Education')")
    parser.add_argument("--interests", default=None, help="Comma-separated interest hints (optional)")
    parser.add_argument("--max-concurrent", type=int, default=5, help="Max parallel sessions")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket port for dashboard")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable WebSocket server")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()

    event_bus = EventBus()

    # Console logger subscriber
    async def log_events(event: Event) -> None:
        logger.info("[EVENT] %s: %s", event.type, event.data)

    event_bus.subscribe(log_events)

    # Start WebSocket server for dashboard
    ws_server = None
    if not args.no_dashboard:
        ws_server = WebSocketServer(event_bus, port=args.ws_port)
        await ws_server.start()
        logger.info("Dashboard: open dashboard.html in your browser")

    session_mgr = SessionManager(max_concurrent=args.max_concurrent, event_bus=event_bus)

    try:
        logger.info("Starting Stage 1: Idea Discovery")
        logger.info("Theme: %s", args.theme)
        if args.interests:
            logger.info("Interests: %s", args.interests)

        idea_cards = await run_stage1(
            theme=args.theme,
            session_mgr=session_mgr,
            event_bus=event_bus,
            interests=args.interests,
        )

        logger.info("=" * 60)
        logger.info("Stage 1 complete! Produced %d Idea Cards:", len(idea_cards))
        for card in idea_cards:
            logger.info("  - %s", card.name)
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Stage 1 failed")
        sys.exit(1)
    finally:
        if ws_server:
            # Keep WS alive briefly so dashboard can show final state
            await asyncio.sleep(2)
            await ws_server.stop()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
