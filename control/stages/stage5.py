"""Stage 5: Pitch Deck Generation — 2-session serial pipeline per project.

Each project runs through: storyteller → deck builder.
Different projects run in parallel, bounded by SessionManager semaphore.
Runs concurrently with Stage 4 after Stage 3 completes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, SessionConfig, SessionStatus
from control.session_manager import PROJECT_ROOT, SessionManager

logger = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "stage5"
WORKSPACE_DIR = PROJECT_ROOT / "workspace" / "stage5"
STAGE2_OUTPUT_DIR = PROJECT_ROOT / "workspace" / "stage2" / "output"


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    """Simple mustache-like template rendering.

    Supports {{var}} replacement and {{#var}}...{{/var}} conditional blocks.
    """
    for key, value in kwargs.items():
        open_tag = "{{#" + key + "}}"
        close_tag = "{{/" + key + "}}"
        pattern = re.escape(open_tag) + r"(.*?)" + re.escape(close_tag)
        if value:
            template = re.sub(pattern, r"\1", template, flags=re.DOTALL)
        else:
            template = re.sub(pattern, "", template, flags=re.DOTALL)

    for key, value in kwargs.items():
        template = template.replace("{{" + key + "}}", str(value))

    return template


def _find_prd_dir_for_project(project_dir: Path) -> Path | None:
    """Find the corresponding Stage 2 output directory for a project.

    project_dir is typically workspace/stage3/{slug}/dev/demo/.
    The slug should match the Stage 2 output directory name.
    """
    # Walk up from demo/ -> dev/ -> {slug}/
    slug_dir = project_dir.parent.parent  # demo -> dev -> {slug}
    slug = slug_dir.name

    prd_dir = STAGE2_OUTPUT_DIR / slug
    if prd_dir.is_dir() and (prd_dir / "concept.md").exists():
        return prd_dir

    # Fallback: scan stage2/output for matching slug
    if STAGE2_OUTPUT_DIR.is_dir():
        for d in STAGE2_OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name == slug and (d / "concept.md").exists():
                return d

    return None


def _slug_from_project(project_dir: Path) -> str:
    """Derive slug from a project directory path."""
    # project_dir is typically workspace/stage3/{slug}/dev/demo/
    slug_dir = project_dir.parent.parent  # demo -> dev -> {slug}
    return slug_dir.name


async def _run_pitch_pipeline(
    prd_dir: Path,
    project_dir: Path,
    slug: str,
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    model: str = "sonnet",
) -> Path | None:
    """Run the 2-session pitch pipeline for a single project.

    Returns the output directory path on success, or None if failed.
    """
    base_work_dir = WORKSPACE_DIR / slug
    output_dir = WORKSPACE_DIR / "output" / slug

    # Clean stale data from previous runs
    if base_work_dir.exists():
        shutil.rmtree(base_work_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read PRD documents
    concept_content = (prd_dir / "concept.md").read_text(encoding="utf-8")
    logic_content = (prd_dir / "logic.md").read_text(encoding="utf-8")
    technical_content = (prd_dir / "technical.md").read_text(encoding="utf-8")

    # Load prompt templates
    storyteller_template = _read_prompt("storyteller.md")
    deck_builder_template = _read_prompt("deck-builder.md")

    # ------------------------------------------------------------------
    # Session 1: Storyteller
    # ------------------------------------------------------------------
    storyteller_work_dir = base_work_dir / "storyteller"
    storyteller_work_dir.mkdir(parents=True, exist_ok=True)

    # Symlink demo/ into storyteller working dir so it can read the source code
    demo_link = storyteller_work_dir / "demo"
    if demo_link.is_symlink():
        demo_link.unlink()
    if not demo_link.exists():
        os.symlink(str(Path(project_dir).resolve()), str(demo_link))

    storyteller_prompt = _render(
        storyteller_template,
        theme=theme,
        concept_content=concept_content,
        logic_content=logic_content,
        technical_content=technical_content,
    )

    await event_bus.emit(Event(
        type="pitch_started",
        data={"session_id": f"storyteller-{slug}", "slug": slug},
    ))

    storyteller_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"storyteller-{slug}",
        prompt=storyteller_prompt,
        working_dir=str(storyteller_work_dir),
        allowed_tools=["Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
        model=model,
        timeout_seconds=1200,
        max_budget_usd=3.0,
    ))

    if storyteller_result.status != SessionStatus.COMPLETED:
        logger.warning("Storyteller session for %s failed: %s", slug, storyteller_result.error)
        await event_bus.emit(Event(
            type="pitch_deck_failed",
            data={"session_id": f"storyteller-{slug}", "error": storyteller_result.error or "unknown"},
        ))
        return None

    # Check for pitch-script.md
    script_file = storyteller_work_dir / "pitch-script.md"
    if not script_file.exists():
        logger.warning("Storyteller session for %s completed but no pitch-script.md found", slug)
        await event_bus.emit(Event(
            type="pitch_deck_failed",
            data={"session_id": f"storyteller-{slug}", "error": "no pitch-script.md produced"},
        ))
        return None

    pitch_script_content = script_file.read_text(encoding="utf-8")

    await event_bus.emit(Event(
        type="pitch_script_completed",
        data={
            "session_id": f"storyteller-{slug}",
            "slug": slug,
            "script_path": str(script_file),
        },
    ))

    # ------------------------------------------------------------------
    # Session 2: Deck Builder
    # ------------------------------------------------------------------
    deck_work_dir = base_work_dir / "deck"
    deck_work_dir.mkdir(parents=True, exist_ok=True)

    # Copy pitch-script.md into deck working dir for reference
    shutil.copy2(script_file, deck_work_dir / "pitch-script.md")

    deck_prompt = _render(
        deck_builder_template,
        theme=theme,
        concept_content=concept_content,
        technical_content=technical_content,
        pitch_script_content=pitch_script_content,
    )

    deck_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"deck-builder-{slug}",
        prompt=deck_prompt,
        working_dir=str(deck_work_dir),
        allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
        model=model,
        timeout_seconds=1200,
        max_budget_usd=3.0,
    ))

    if deck_result.status != SessionStatus.COMPLETED:
        logger.warning("Deck builder session for %s failed: %s", slug, deck_result.error)
        await event_bus.emit(Event(
            type="pitch_deck_failed",
            data={"session_id": f"deck-builder-{slug}", "error": deck_result.error or "unknown"},
        ))
        # Still copy the script even if deck fails
        shutil.copy2(script_file, output_dir / "pitch-script.md")
        return None

    # Check for pitch-deck.html
    deck_file = deck_work_dir / "pitch-deck.html"
    if not deck_file.exists():
        logger.warning("Deck builder session for %s completed but no pitch-deck.html found", slug)
        await event_bus.emit(Event(
            type="pitch_deck_failed",
            data={"session_id": f"deck-builder-{slug}", "error": "no pitch-deck.html produced"},
        ))
        shutil.copy2(script_file, output_dir / "pitch-script.md")
        return None

    # ------------------------------------------------------------------
    # Collect outputs
    # ------------------------------------------------------------------
    shutil.copy2(script_file, output_dir / "pitch-script.md")
    shutil.copy2(deck_file, output_dir / "pitch-deck.html")

    logger.info("Pitch pipeline for %s completed successfully", slug)
    await event_bus.emit(Event(
        type="pitch_deck_completed",
        data={
            "session_id": f"deck-builder-{slug}",
            "slug": slug,
            "deck_path": str(output_dir / "pitch-deck.html"),
            "script_path": str(output_dir / "pitch-script.md"),
        },
    ))

    return output_dir


async def run_stage5(
    project_dirs: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    prd_dirs: list[Path] | None = None,
    model: str = "sonnet",
) -> list[Path]:
    """Execute Stage 5: Pitch Deck Generation.

    Args:
        project_dirs: List of successful demo/ project directories from Stage 3.
        theme: Hackathon theme string.
        session_mgr: Session manager for running Claude CLI sessions.
        event_bus: Event bus for publishing progress events.
        prd_dirs: Optional explicit list of PRD directories (parallel to project_dirs).
                  When provided, used directly for document reading.
                  When None, auto-discovers from workspace/stage2/output/.

    Returns:
        List of output directory paths (each containing pitch-script.md + pitch-deck.html).
    """
    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 5, "projects": len(project_dirs)},
    ))

    # Ensure workspace dirs exist
    (WORKSPACE_DIR / "output").mkdir(parents=True, exist_ok=True)

    # Launch pitch pipelines in parallel
    tasks = []
    for i, project_dir in enumerate(project_dirs):
        if prd_dirs and i < len(prd_dirs):
            prd_dir = prd_dirs[i]
        else:
            prd_dir = _find_prd_dir_for_project(project_dir)

        if not prd_dir or not (prd_dir / "concept.md").exists():
            logger.warning("No PRD directory found for project %s, skipping pitch", project_dir)
            continue

        slug = _slug_from_project(project_dir)
        tasks.append(_run_pitch_pipeline(
            prd_dir, project_dir, slug, theme, session_mgr, event_bus,
            model=model,
        ))

    logger.info("Stage 5: Launching %d pitch pipelines (2 sessions each)", len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful output directories
    output_dirs: list[Path] = []
    failed_count = 0
    for r in results:
        if isinstance(r, BaseException):
            logger.error("Pitch pipeline raised exception: %s", r, exc_info=r)
            failed_count += 1
        elif r is None:
            failed_count += 1
        else:
            output_dirs.append(r)

    logger.info(
        "Stage 5 complete: %d pitch decks generated, %d failed",
        len(output_dirs), failed_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 5,
            "successful": len(output_dirs),
            "failed": failed_count,
        },
    ))

    return output_dirs
