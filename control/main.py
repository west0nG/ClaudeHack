"""Main entry point for Hackathon Agent control plane.

Usage:
    python -m control.main --theme "AI + Education"
    python -m control.main --theme "AI + Education" --interests "学生,教师"
    python -m control.main --prompt "Build an innovative solution using generative AI..."
    python -m control.main --prompt-file hackathon-brief.txt
    python -m control.main --idea-card workspace/stage1/output/idea-card-xxx.md
    python -m control.main --prd workspace/stage2/output/prd-xxx.md
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, HackathonBrief
from control.review_gate import ReviewGate
from control.session_manager import SessionManager
from control.stages.stage0 import run_stage0
from control.stages.stage1 import run_stage1
from control.stages.stage2 import run_stage2
from control.stages.stage3 import run_stage3
from control.ws_server import WebSocketServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hackathon-agent")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hackathon Agent — autonomous ideation system")

    # Input modes (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--theme", help="Simple theme (e.g. 'AI + Education'), skips Stage 0")
    input_group.add_argument("--prompt", help="Raw hackathon prompt text (triggers Stage 0 interpreter)")
    input_group.add_argument("--prompt-file", help="Path to hackathon prompt file (triggers Stage 0)")
    input_group.add_argument(
        "--idea-card",
        help="Path to a specific Idea Card file — skip Stage 1, run Stage 2 directly",
    )
    input_group.add_argument(
        "--prd",
        help="Path to a specific PRD file — skip Stages 0-2, run Stage 3 directly",
    )

    parser.add_argument("--interests", default=None, help="Comma-separated interest hints (optional)")
    parser.add_argument("--max-concurrent", type=int, default=5, help="Max parallel sessions")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket port for dashboard")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable WebSocket server")
    parser.add_argument(
        "--mode",
        choices=["full", "single", "lite"],
        default="full",
        help="Run mode: full (all parallel), single (1 direction), lite (all sequential)",
    )
    parser.add_argument(
        "--max-directions",
        type=int,
        default=None,
        help="Max number of research directions (overrides --mode)",
    )
    parser.add_argument("--skip-review", action="store_true", help="Skip manual review gate after Stage 1")
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

    # Resolve max_directions from --mode / --max-directions
    max_directions: int | None = args.max_directions
    if max_directions is None and args.mode == "single":
        max_directions = 1

    # In lite mode, run sessions sequentially (max_concurrent=1)
    effective_concurrent = 1 if args.mode == "lite" else args.max_concurrent
    session_mgr = SessionManager(max_concurrent=effective_concurrent, event_bus=event_bus)

    try:
        # ----------------------------------------------------------
        # Direct PRD mode: skip Stages 0-2, run Stage 3 only
        # ----------------------------------------------------------
        if args.prd:
            prd_path = Path(args.prd)
            if not prd_path.exists():
                logger.error("PRD file not found: %s", args.prd)
                sys.exit(1)

            theme = _extract_theme_from_prd(prd_path)
            logger.info("Running Stage 3 directly on: %s (theme: %s)", prd_path.name, theme)

            project_dirs = await run_stage3(
                prd_files=[prd_path],
                theme=theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("=" * 60)
            logger.info("Stage 3 complete! %d projects built:", len(project_dirs))
            for d in project_dirs:
                logger.info("  - %s", d)
            logger.info("=" * 60)
            return

        # ----------------------------------------------------------
        # Direct Idea Card mode: skip Stage 0 + Stage 1, run Stage 2 only
        # ----------------------------------------------------------
        if args.idea_card:
            card_path = Path(args.idea_card)
            if not card_path.exists():
                logger.error("Idea card file not found: %s", args.idea_card)
                sys.exit(1)

            # --idea-card requires a theme for context (infer from card or require --theme fallback)
            # Since --idea-card and --theme are mutually exclusive in argparse,
            # we extract the theme from the card title or use a generic default.
            theme = _extract_theme_from_card(card_path)
            logger.info("Running Stage 2 directly on: %s (theme: %s)", card_path.name, theme)

            idea_cards = [card_path]
            prd_files = await run_stage2(
                idea_cards=idea_cards,
                theme=theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("=" * 60)
            logger.info("Stage 2 complete! %d PRDs produced:", len(prd_files))
            for prd in prd_files:
                logger.info("  - %s", prd.name)
            logger.info("=" * 60)
            return

        # ----------------------------------------------------------
        # Resolve input: --theme (skip Stage 0) vs --prompt/--prompt-file (run Stage 0)
        # ----------------------------------------------------------
        brief: HackathonBrief
        if args.theme:
            brief = HackathonBrief.from_theme(args.theme)
            logger.info("Using simple theme (Stage 0 skipped): %s", brief.theme)
        else:
            raw_prompt: str
            if args.prompt:
                raw_prompt = args.prompt
            else:
                prompt_path = Path(args.prompt_file)
                if not prompt_path.exists():
                    logger.error("Prompt file not found: %s", args.prompt_file)
                    sys.exit(1)
                raw_prompt = prompt_path.read_text(encoding="utf-8")
            logger.info("Running Stage 0: Interpreting hackathon prompt (%d chars)", len(raw_prompt))
            brief = await run_stage0(raw_prompt, session_mgr, event_bus)
            logger.info("Interpreted theme: %s", brief.theme)

        # ----------------------------------------------------------
        # Stage 1: Idea Discovery
        # ----------------------------------------------------------
        logger.info("Starting Stage 1: Idea Discovery (mode=%s)", args.mode)
        logger.info("Theme: %s", brief.theme)
        if args.interests:
            logger.info("Interests: %s", args.interests)
        if max_directions:
            logger.info("Max directions: %d", max_directions)

        idea_cards = await run_stage1(
            theme=brief.theme,
            session_mgr=session_mgr,
            event_bus=event_bus,
            interests=args.interests,
            max_directions=max_directions,
            brief=brief,
        )

        logger.info("Stage 1 produced %d Idea Cards", len(idea_cards))

        # ----------------------------------------------------------
        # Review Gate: manual filtering between Stage 1 and Stage 2
        # ----------------------------------------------------------
        if not args.skip_review and idea_cards:
            review_gate = ReviewGate(event_bus, ws_server=ws_server)
            idea_cards = await review_gate.wait_for_selection(idea_cards)
            logger.info("After review: %d cards selected", len(idea_cards))

        # In single mode, limit to 1 card for Stage 2
        if args.mode == "single" and len(idea_cards) > 1:
            idea_cards = idea_cards[:1]
            logger.info("Single mode: limited to 1 card for Stage 2")

        # ----------------------------------------------------------
        # Stage 2: PRD Generation
        # ----------------------------------------------------------
        if idea_cards:
            logger.info("Starting Stage 2: PRD Generation (%d cards)", len(idea_cards))
            prd_files = await run_stage2(
                idea_cards=idea_cards,
                theme=brief.theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("Stage 2 complete: %d PRDs produced", len(prd_files))
            for prd in prd_files:
                logger.info("  - %s", prd.name)
        else:
            logger.info("No Idea Cards to process — pipeline ending after Stage 1")
            prd_files = []

        # ----------------------------------------------------------
        # Stage 3: Demo Development
        # ----------------------------------------------------------
        if prd_files:
            logger.info("Starting Stage 3: Demo Development (%d PRDs)", len(prd_files))
            project_dirs = await run_stage3(
                prd_files=prd_files,
                theme=brief.theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("=" * 60)
            logger.info("Pipeline complete! %d projects built:", len(project_dirs))
            for d in project_dirs:
                logger.info("  - %s", d)
            logger.info("=" * 60)
        else:
            logger.info("=" * 60)
            logger.info("No PRDs to build — pipeline ending after Stage 2")
            logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
    finally:
        if ws_server:
            # Keep WS alive briefly so dashboard can show final state
            await asyncio.sleep(2)
            await ws_server.stop()


def _extract_theme_from_prd(prd_path: Path) -> str:
    """Best-effort theme extraction from a PRD file for --prd mode."""
    import re
    text = prd_path.read_text(encoding="utf-8")
    # Look for theme mention in the PRD content
    theme_match = re.search(r"Hackathon Theme[:\s]*(.+)", text, re.IGNORECASE)
    if theme_match:
        return theme_match.group(1).strip()
    # Fallback: use the PRD title
    title_match = re.search(r"^#\s+(?:PRD:\s*)?(.+)$", text, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()
    return "General"


def _extract_theme_from_card(card_path: Path) -> str:
    """Best-effort theme extraction from an idea card for --idea-card mode."""
    import re
    text = card_path.read_text(encoding="utf-8")
    # Look for theme mention in the card content
    theme_match = re.search(r"Hackathon Theme[:\s]*(.+)", text, re.IGNORECASE)
    if theme_match:
        return theme_match.group(1).strip()
    # Fallback: use the card title
    title_match = re.search(r"^#\s+(?:Idea Card:\s*)?(.+)$", text, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()
    return "General"


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
