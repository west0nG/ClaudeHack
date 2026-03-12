"""Stage 2: PRD Generation — 3-session serial pipeline per Idea Card.

Each card runs through: concept → logic → technical.
Different cards run in parallel, bounded by SessionManager semaphore.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, SessionConfig, SessionStatus
from control.session_manager import PROJECT_ROOT, SessionManager

logger = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "stage2"
WORKSPACE_DIR = PROJECT_ROOT / "workspace" / "stage2"


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


def _slugify(card_path: Path) -> str:
    """Derive a short slug from an idea card file path."""
    stem = card_path.stem  # e.g. "idea-card-freelancer-burnout"
    slug = re.sub(r"^idea-card-", "", stem)
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:40] or "card"


def _find_output_file(work_dir: Path, filename: str) -> Path | None:
    """Find an output file in the working directory."""
    target = work_dir / filename
    return target if target.exists() else None


async def _run_card_pipeline(
    card_path: Path,
    slug: str,
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> Path | None:
    """Run the 3-session pipeline for a single Idea Card.

    Returns the output directory path on success, or None if eliminated/failed.
    """
    card_content = card_path.read_text(encoding="utf-8")
    base_work_dir = WORKSPACE_DIR / slug
    output_dir = WORKSPACE_DIR / "output" / slug

    # Clean stale data from previous runs to prevent false
    # ELIMINATED.md / concept.md detection from old sessions
    if base_work_dir.exists():
        shutil.rmtree(base_work_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load prompt templates
    concept_template = _read_prompt("concept.md")
    logic_template = _read_prompt("logic.md")
    technical_template = _read_prompt("technical.md")

    # ------------------------------------------------------------------
    # Session 1: Concept
    # ------------------------------------------------------------------
    concept_work_dir = base_work_dir / "concept"
    concept_work_dir.mkdir(parents=True, exist_ok=True)

    concept_prompt = _render(
        concept_template,
        theme=theme,
        idea_card_content=card_content,
    )

    concept_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"concept-{slug}",
        prompt=concept_prompt,
        working_dir=str(concept_work_dir),
        allowed_tools=["Agent", "Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
        model="sonnet",
        timeout_seconds=1200,
        max_budget_usd=3.0,
    ))

    if concept_result.status != SessionStatus.COMPLETED:
        logger.warning("Concept session for %s failed: %s", slug, concept_result.error)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"concept-{slug}", "error": concept_result.error or "unknown"},
        ))
        return None

    # Check for elimination
    eliminated = _find_output_file(concept_work_dir, "ELIMINATED.md")
    if eliminated:
        reason = eliminated.read_text(encoding="utf-8")[:200]
        logger.info("Card %s ELIMINATED at concept phase: %s", slug, reason)
        # Copy ELIMINATED.md to output
        shutil.copy2(eliminated, output_dir / "ELIMINATED.md")
        await event_bus.emit(Event(
            type="prd_eliminated",
            data={"session_id": f"concept-{slug}", "reason": reason},
        ))
        return None

    # Check for concept.md
    concept_file = _find_output_file(concept_work_dir, "concept.md")
    if not concept_file:
        logger.warning("Concept session for %s completed but no concept.md found", slug)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"concept-{slug}", "error": "no concept.md produced"},
        ))
        return None

    concept_content = concept_file.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Session 2: Logic
    # ------------------------------------------------------------------
    logic_work_dir = base_work_dir / "logic"
    logic_work_dir.mkdir(parents=True, exist_ok=True)

    logic_prompt = _render(
        logic_template,
        theme=theme,
        idea_card_content=card_content,
        concept_content=concept_content,
    )

    logic_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"logic-{slug}",
        prompt=logic_prompt,
        working_dir=str(logic_work_dir),
        allowed_tools=["Agent", "Read", "Write", "Glob", "Grep"],
        model="sonnet",
        timeout_seconds=1200,
        max_budget_usd=3.0,
    ))

    if logic_result.status != SessionStatus.COMPLETED:
        logger.warning("Logic session for %s failed: %s", slug, logic_result.error)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"logic-{slug}", "error": logic_result.error or "unknown"},
        ))
        return None

    logic_file = _find_output_file(logic_work_dir, "logic.md")
    if not logic_file:
        logger.warning("Logic session for %s completed but no logic.md found", slug)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"logic-{slug}", "error": "no logic.md produced"},
        ))
        return None

    logic_content = logic_file.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Session 3: Technical
    # ------------------------------------------------------------------
    tech_work_dir = base_work_dir / "technical"
    tech_work_dir.mkdir(parents=True, exist_ok=True)

    technical_prompt = _render(
        technical_template,
        theme=theme,
        concept_content=concept_content,
        logic_content=logic_content,
    )

    tech_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"tech-{slug}",
        prompt=technical_prompt,
        working_dir=str(tech_work_dir),
        allowed_tools=["Agent", "Read", "Write", "Glob", "Grep"],
        model="sonnet",
        timeout_seconds=1200,
        max_budget_usd=3.0,
    ))

    if tech_result.status != SessionStatus.COMPLETED:
        logger.warning("Technical session for %s failed: %s", slug, tech_result.error)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"tech-{slug}", "error": tech_result.error or "unknown"},
        ))
        return None

    tech_file = _find_output_file(tech_work_dir, "technical.md")
    if not tech_file:
        logger.warning("Technical session for %s completed but no technical.md found", slug)
        await event_bus.emit(Event(
            type="prd_failed",
            data={"session_id": f"tech-{slug}", "error": "no technical.md produced"},
        ))
        return None

    # ------------------------------------------------------------------
    # Collect all outputs to output directory
    # ------------------------------------------------------------------
    shutil.copy2(concept_file, output_dir / "concept.md")
    shutil.copy2(logic_file, output_dir / "logic.md")
    shutil.copy2(tech_file, output_dir / "technical.md")

    logger.info("Card %s: all 3 sessions completed successfully", slug)
    await event_bus.emit(Event(
        type="prd_completed",
        data={
            "session_id": f"prd-{slug}",
            "output_dir": str(output_dir),
            "docs": ["concept.md", "logic.md", "technical.md"],
        },
    ))

    return output_dir


async def run_stage2(
    idea_cards: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> list[Path]:
    """Execute Stage 2: PRD Generation.

    Returns paths to output directories (each containing concept.md, logic.md, technical.md).
    """
    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 2, "theme": theme, "cards": len(idea_cards)},
    ))

    # Ensure workspace dirs exist
    (WORKSPACE_DIR / "output").mkdir(parents=True, exist_ok=True)

    # Launch card pipelines in parallel (SessionManager semaphore bounds concurrency)
    tasks = []
    for card_path in idea_cards:
        slug = _slugify(card_path)
        tasks.append(_run_card_pipeline(card_path, slug, theme, session_mgr, event_bus))

    logger.info("Stage 2: Launching %d card pipelines (3 sessions each)", len(tasks))
    results = await asyncio.gather(*tasks)

    # Collect successful output directories
    output_dirs = [r for r in results if r is not None]
    eliminated_or_failed = len(results) - len(output_dirs)

    logger.info(
        "Stage 2 complete: %d successful, %d eliminated/failed",
        len(output_dirs), eliminated_or_failed,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 2,
            "successful": len(output_dirs),
            "eliminated_or_failed": eliminated_or_failed,
        },
    ))

    return output_dirs
