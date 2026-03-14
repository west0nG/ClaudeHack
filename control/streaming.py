"""Streaming pipeline: each card flows independently through all stages.

Instead of stage-by-stage batch execution:
    [All Stage 2] → ConfigGate → [All Stage 3] → [All Stage 5] → [Stage 4]

Each card flows end-to-end:
    Card A: Stage 2 → ConfigCheck → Stage 3 → Stage 5 → Stage 4
    Card B: Stage 2 ────→ ConfigCheck → Stage 3 ────→ Stage 5 → Stage 4

Concurrency is still bounded by SessionManager's semaphore.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from control.credential_barrier import CredentialBarrier
from control.event_bus import EventBus
from control.models import Event
from control.session_manager import SessionManager

# Import internal pipeline functions from stage modules
from control.stages.stage2 import _run_card_pipeline, _slugify
from control.stages.stage3 import _run_project_pipeline, _slugify_prd_dir
from control.stages.stage4 import (
    _publish_project,
    _slugify_project_name,
    _extract_project_name,
)
from control.stages.stage5 import _run_pitch_pipeline

logger = logging.getLogger(__name__)


async def run_streaming_pipeline(
    idea_cards: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    barrier: CredentialBarrier,
    model: str = "sonnet",
    skip_pitch: bool = False,
    skip_publish: bool = False,
    private: bool = False,
    publish_mode: str = "test",
) -> list[Path]:
    """Run the full pipeline with per-card streaming.

    Each card flows independently: Stage 2 → ConfigCheck → Stage 3 → Stage 5 → Stage 4.
    Concurrency bounded by SessionManager semaphore.

    Returns list of successful project directories.
    """
    await event_bus.emit(Event(
        type="streaming_pipeline_started",
        data={"cards": len(idea_cards), "theme": theme},
    ))

    # Shared repo name registry to avoid GitHub naming collisions
    repo_name_lock = asyncio.Lock()
    used_repo_names: dict[str, int] = {}

    tasks = []
    for card_path in idea_cards:
        slug = _slugify(card_path)
        tasks.append(_run_card_end_to_end(
            card_path=card_path,
            slug=slug,
            theme=theme,
            session_mgr=session_mgr,
            event_bus=event_bus,
            barrier=barrier,
            model=model,
            skip_pitch=skip_pitch,
            skip_publish=skip_publish,
            private=private,
            publish_mode=publish_mode,
            repo_name_lock=repo_name_lock,
            used_repo_names=used_repo_names,
        ))

    logger.info(
        "Streaming pipeline: launching %d card pipelines (Stage 2→3→5→4 per card)",
        len(tasks),
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    project_dirs: list[Path] = []
    repo_urls: list[str] = []
    failed = 0

    for r in results:
        if isinstance(r, BaseException):
            logger.error("Card pipeline raised exception: %s", r, exc_info=r)
            failed += 1
        elif r is None:
            failed += 1
        else:
            proj_dir, repo_url = r
            project_dirs.append(proj_dir)
            if repo_url:
                repo_urls.append(repo_url)

    await event_bus.emit(Event(
        type="streaming_pipeline_completed",
        data={
            "projects_built": len(project_dirs),
            "projects_published": len(repo_urls),
            "failed": failed,
            "repo_urls": repo_urls,
        },
    ))

    return project_dirs


async def _run_card_end_to_end(
    card_path: Path,
    slug: str,
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    barrier: CredentialBarrier,
    model: str,
    skip_pitch: bool,
    skip_publish: bool,
    private: bool,
    publish_mode: str,
    repo_name_lock: asyncio.Lock,
    used_repo_names: dict[str, int],
) -> tuple[Path, str | None] | None:
    """Run one card through the complete pipeline: Stage 2 → Config → Stage 3 → Stage 5 → Stage 4.

    Returns (project_dir, repo_url) on success, or None on failure.
    """
    logger.info("Card %s: starting end-to-end pipeline", slug)

    # ------------------------------------------------------------------
    # Stage 2: PRD generation (concept → logic → technical)
    # ------------------------------------------------------------------
    prd_dir = await _run_card_pipeline(
        card_path, slug, theme, session_mgr, event_bus, model=model,
    )

    if prd_dir is None:
        logger.info("Card %s: eliminated or failed at Stage 2", slug)
        # Still notify barrier so it can count this project
        await barrier.check_and_wait(slug, None)
        return None

    # ------------------------------------------------------------------
    # ConfigGate: credential check (may block if collection needed)
    # ------------------------------------------------------------------
    project_creds, needed_vars, is_blocked = await barrier.check_and_wait(
        slug, prd_dir,
    )

    if is_blocked:
        logger.info("Card %s: blocked by ConfigGate (missing carrier deps)", slug)
        return None

    # ------------------------------------------------------------------
    # Stage 3: Demo development (plan → dev → review)
    # ------------------------------------------------------------------
    project_dir = await _run_project_pipeline(
        prd_dir, slug, theme, session_mgr, event_bus,
        credentials=project_creds,
        model=model,
    )

    if project_dir is None:
        logger.info("Card %s: failed at Stage 3", slug)
        return None

    # ------------------------------------------------------------------
    # Stage 5: Pitch deck generation (storyteller → deck builder)
    # ------------------------------------------------------------------
    if not skip_pitch:
        pitch_dir = await _run_pitch_pipeline(
            prd_dir, project_dir, slug, theme, session_mgr, event_bus,
            model=model,
        )
        if pitch_dir:
            _copy_pitch_to_project(pitch_dir, project_dir)

    # ------------------------------------------------------------------
    # Stage 4: Publish to GitHub
    # ------------------------------------------------------------------
    repo_url: str | None = None
    if not skip_publish:
        repo_slug = await _allocate_repo_name(
            prd_dir, project_dir, repo_name_lock, used_repo_names,
        )
        repo_url = await _publish_project(
            project_dir, prd_dir, event_bus,
            private=private,
            repo_slug_override=repo_slug,
            publish_mode=publish_mode,
        )

    logger.info("Card %s: pipeline complete (project=%s)", slug, project_dir.name)
    return project_dir, repo_url


def _copy_pitch_to_project(pitch_dir: Path, project_dir: Path) -> None:
    """Copy pitch outputs into the project's demo/ directory."""
    for fname in ("pitch-script.md", "pitch-deck.html"):
        src = pitch_dir / fname
        if src.exists():
            shutil.copy2(src, project_dir / fname)
    logger.info("Copied pitch files into %s", project_dir)


async def _allocate_repo_name(
    prd_dir: Path,
    project_dir: Path,
    lock: asyncio.Lock,
    used_names: dict[str, int],
) -> str:
    """Allocate a unique repo slug, avoiding collisions across concurrent cards."""
    if prd_dir and (prd_dir / "concept.md").exists():
        name = _extract_project_name(prd_dir / "concept.md")
    else:
        name = project_dir.parent.parent.name.replace("-", " ").title()

    base_slug = _slugify_project_name(name)

    async with lock:
        if base_slug in used_names:
            used_names[base_slug] += 1
            return f"{base_slug}-{used_names[base_slug]}"
        else:
            used_names[base_slug] = 0
            return base_slug
