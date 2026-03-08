"""Main entry point for Hackathon Agent control plane.

Usage:
    python -m control.main --theme "AI + Education"
    python -m control.main --theme "AI + Education" --interests "学生,教师"
    python -m control.main --prompt "Build an innovative solution using generative AI..."
    python -m control.main --prompt-file hackathon-brief.txt
    python -m control.main --idea-card workspace/stage1/output/idea-card-xxx.md
    python -m control.main --prd-dir workspace/stage2/output/some-slug/
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import shutil

from control.event_bus import EventBus
from control.models import Event, HackathonBrief
from control.review_gate import ReviewGate
from control.session_manager import PROJECT_ROOT, SessionManager
from control.stages.stage0 import run_stage0
from control.stages.stage1 import run_stage1
from control.stages.stage2 import run_stage2
from control.stages.stage2_5 import run_config_gate
from control.stages.stage3 import run_stage3
from control.stages.stage4 import run_stage4
from control.stages.stage5 import run_stage5, WORKSPACE_DIR as STAGE5_WORKSPACE
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
        "--prd-dir",
        help="Path to a PRD directory (containing concept.md, logic.md, technical.md) — skip Stages 0-2, run Stage 3 directly",
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
    parser.add_argument("--clean", action="store_true", help="Remove workspace/ before running (clear stale data)")
    parser.add_argument("--skip-publish", action="store_true", help="Skip Stage 4 (GitHub publishing)")
    parser.add_argument("--private", action="store_true", help="Create private GitHub repos instead of public")
    parser.add_argument(
        "--publish-mode",
        choices=["test", "use"],
        default="test",
        help="test: repo name prefixed with hg-, README mentions AI. use: clean repo name, no AI attribution.",
    )
    parser.add_argument("--skip-config", action="store_true", help="Skip ConfigGate credential collection (use persistent store only)")
    parser.add_argument("--skip-pitch", action="store_true", help="Skip Stage 5 (pitch deck generation)")
    parser.add_argument("--no-archive", action="store_true", help="Skip archiving workspace after run")
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

    # Archive stale workspace from previous run (if any)
    # This handles the case where a previous run was killed before reaching finally.
    workspace_dir = PROJECT_ROOT / "workspace"
    if workspace_dir.exists() and any(workspace_dir.iterdir()):
        if args.clean:
            logger.info("Cleaning workspace: %s", workspace_dir)
            shutil.rmtree(workspace_dir)
        else:
            logger.info("Found stale workspace from previous run, archiving first")
            _archive_workspace()

    try:
        # ----------------------------------------------------------
        # Direct PRD directory mode: skip Stages 0-2, run Stage 3 only
        # ----------------------------------------------------------
        if args.prd_dir:
            prd_dir = Path(args.prd_dir)
            if not prd_dir.is_dir():
                logger.error("PRD directory not found: %s", args.prd_dir)
                sys.exit(1)

            # Validate required files exist
            required_files = ["concept.md", "logic.md", "technical.md"]
            missing = [f for f in required_files if not (prd_dir / f).exists()]
            if missing:
                logger.error("PRD directory missing files: %s", ", ".join(missing))
                sys.exit(1)

            theme = _extract_theme_from_concept(prd_dir / "concept.md")
            logger.info("Running Stage 3 directly on: %s (theme: %s)", prd_dir.name, theme)

            # ConfigGate: collect credentials before Stage 3
            approved_dirs, _ = await run_config_gate(
                prd_dirs=[prd_dir],
                event_bus=event_bus,
                skip=args.skip_config,
                no_dashboard=args.no_dashboard,
                ws_server=ws_server,
            )

            if not approved_dirs:
                logger.error("ConfigGate blocked all projects — cannot proceed")
                sys.exit(1)

            project_dirs = await run_stage3(
                prd_dirs=approved_dirs,
                theme=theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("=" * 60)
            logger.info("Stage 3 complete! %d projects built:", len(project_dirs))
            for d in project_dirs:
                logger.info("  - %s", d)
            logger.info("=" * 60)

            # Stage 5 → copy into demo/ → Stage 4
            if project_dirs:
                # Stage 5: Pitch Deck generation
                if not args.skip_pitch:
                    pitch_dirs = await run_stage5(
                        project_dirs, theme=theme, session_mgr=session_mgr,
                        event_bus=event_bus,
                        prd_dirs=[prd_dir] * len(project_dirs),
                    )
                    copied = _copy_pitch_to_projects(project_dirs)
                    logger.info("=" * 60)
                    logger.info("Generated %d pitch decks, copied to %d projects:", len(pitch_dirs), copied)
                    for d in pitch_dirs:
                        logger.info("  - %s", d)
                    logger.info("=" * 60)

                # Stage 4: Publish to GitHub (pitch files already in demo/)
                if not args.skip_publish:
                    repo_urls = await run_stage4(
                        project_dirs, event_bus, private=args.private,
                        prd_dirs=[prd_dir] * len(project_dirs),
                        publish_mode=args.publish_mode,
                    )
                    logger.info("=" * 60)
                    logger.info("Published %d repos:", len(repo_urls))
                    for url in repo_urls:
                        logger.info("  - %s", url)
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
            prd_dirs = await run_stage2(
                idea_cards=idea_cards,
                theme=theme,
                session_mgr=session_mgr,
                event_bus=event_bus,
            )

            logger.info("=" * 60)
            logger.info("Stage 2 complete! %d PRD directories produced:", len(prd_dirs))
            for d in prd_dirs:
                logger.info("  - %s", d)
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
        # Phased Pipeline: ReviewGate → Stage 2 → ConfigGate → Stage 3
        # Stage 2 runs all cards in parallel, then ConfigGate collects
        # credentials once, then Stage 3 runs approved projects in parallel.
        # ----------------------------------------------------------

        # In single mode, limit to 1 card
        if args.mode == "single" and len(idea_cards) > 1:
            idea_cards = idea_cards[:1]
            logger.info("Single mode: limited to 1 card")

        if not idea_cards:
            logger.info("No Idea Cards to process — pipeline ending after Stage 1")
            logger.info("=" * 60)
            return

        # ReviewGate: filter cards
        approved_cards: list[Path] = []
        if args.skip_review:
            approved_cards = list(idea_cards)
            logger.info("Review skipped, proceeding with %d cards", len(approved_cards))
        else:
            logger.info("Starting review for %d cards", len(idea_cards))
            review_gate = ReviewGate(event_bus, ws_server=ws_server)
            async for card in review_gate.stream_approved_cards(idea_cards):
                logger.info("Card approved: %s", card.name)
                approved_cards.append(card)

        if not approved_cards:
            logger.info("No cards approved — pipeline ending after review")
            logger.info("=" * 60)
            return

        # Stage 2: PRD generation (parallel across cards)
        prd_dirs = await run_stage2(
            idea_cards=approved_cards,
            theme=brief.theme,
            session_mgr=session_mgr,
            event_bus=event_bus,
        )

        if not prd_dirs:
            logger.info("No PRDs produced — pipeline ending after Stage 2")
            logger.info("=" * 60)
            return

        logger.info("Stage 2 produced %d PRD directories", len(prd_dirs))

        # Stage 2.5: ConfigGate — collect credentials, generate env plans
        approved_dirs, _ = await run_config_gate(
            prd_dirs=prd_dirs,
            event_bus=event_bus,
            skip=args.skip_config,
            no_dashboard=args.no_dashboard,
            ws_server=ws_server,
        )

        if not approved_dirs:
            logger.info("ConfigGate blocked all projects — pipeline ending")
            logger.info("=" * 60)
            return

        # Stage 3: Demo development (parallel across projects)
        project_dirs = await run_stage3(
            prd_dirs=approved_dirs,
            theme=brief.theme,
            session_mgr=session_mgr,
            event_bus=event_bus,
        )

        logger.info("=" * 60)
        logger.info("Pipeline complete! %d projects built:", len(project_dirs))
        for d in project_dirs:
            logger.info("  - %s", d)
        logger.info("=" * 60)

        # Stage 5 → copy into demo/ → Stage 4
        if project_dirs:
            # Stage 5: Pitch Deck generation
            if not args.skip_pitch:
                pitch_dirs = await run_stage5(
                    project_dirs, theme=brief.theme, session_mgr=session_mgr,
                    event_bus=event_bus,
                )
                copied = _copy_pitch_to_projects(project_dirs)
                logger.info("=" * 60)
                logger.info("Generated %d pitch decks, copied to %d projects:", len(pitch_dirs), copied)
                for d in pitch_dirs:
                    logger.info("  - %s", d)
                logger.info("=" * 60)

            # Stage 4: Publish to GitHub (pitch files already in demo/)
            if not args.skip_publish:
                repo_urls = await run_stage4(
                    project_dirs, event_bus, private=args.private,
                    publish_mode=args.publish_mode,
                )
                logger.info("=" * 60)
                logger.info("Published %d repos:", len(repo_urls))
                for url in repo_urls:
                    logger.info("  - %s", url)
                logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
    finally:
        # Archive workspace
        if not args.no_archive:
            _archive_workspace()

        if ws_server:
            # Keep WS alive briefly so dashboard can show final state
            await asyncio.sleep(2)
            await ws_server.stop()


def _copy_pitch_to_projects(project_dirs: list[Path]) -> int:
    """Copy Stage 5 pitch outputs into corresponding project demo/ dirs.

    Returns the number of projects that received pitch files.
    """
    copied = 0
    for project_dir in project_dirs:
        # Derive slug the same way stage5 does: demo/ -> dev/ -> {slug}/
        slug = project_dir.parent.parent.name
        pitch_output = STAGE5_WORKSPACE / "output" / slug
        if not pitch_output.is_dir():
            continue
        for fname in ("pitch-script.md", "pitch-deck.html"):
            src = pitch_output / fname
            if src.exists():
                shutil.copy2(src, project_dir / fname)
        copied += 1
        logger.info("Copied pitch files into %s", project_dir)
    return copied


def _archive_workspace() -> Path | None:
    """Move workspace/ to archive/{timestamp}/.

    Returns the archive path, or None if there was nothing to archive.
    """
    workspace_dir = PROJECT_ROOT / "workspace"
    if not workspace_dir.exists():
        return None

    archive_dir = PROJECT_ROOT / "archive"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = archive_dir / timestamp

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(workspace_dir), str(dest))
    logger.info("Archived workspace to: %s", dest)
    return dest


def _extract_theme_from_concept(concept_path: Path) -> str:
    """Best-effort theme extraction from a concept.md file for --prd-dir mode."""
    import re
    text = concept_path.read_text(encoding="utf-8")
    # Look for theme mention in the concept content
    theme_match = re.search(r"Hackathon Theme[:\s]*(.+)", text, re.IGNORECASE)
    if theme_match:
        return theme_match.group(1).strip()
    # Fallback: use the concept title
    title_match = re.search(r"^#\s+(?:Product Concept:\s*)?(.+)$", text, re.MULTILINE)
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
