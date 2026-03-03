"""Stage 2: PRD Generation — from Idea Cards to complete PRDs with wireframes."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, SessionConfig, SessionResult, SessionStatus
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
    # Strip the "idea-card-" prefix if present
    slug = re.sub(r"^idea-card-", "", stem)
    # Ensure URL-safe
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:40] or "card"


def _collect_prd_outputs(result: SessionResult) -> dict:
    """Check a session's working dir for PRD outputs.

    Returns a dict with keys:
      - "prd": Path to prd.md (or None)
      - "wireframe": Path to wireframe.html (or None)
      - "eliminated": Path to ELIMINATED.md (or None)
    """
    outputs: dict = {"prd": None, "wireframe": None, "eliminated": None}
    if result.status != SessionStatus.COMPLETED or not result.working_dir:
        return outputs

    work_dir = Path(result.working_dir)

    eliminated = work_dir / "ELIMINATED.md"
    if eliminated.exists():
        outputs["eliminated"] = eliminated
        return outputs

    prd = work_dir / "prd.md"
    if prd.exists():
        outputs["prd"] = prd

    wireframe = work_dir / "wireframe.html"
    if wireframe.exists():
        outputs["wireframe"] = wireframe

    return outputs


async def run_stage2(
    idea_cards: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> list[Path]:
    """Execute Stage 2: PRD Generation. Returns paths to final PRD files."""

    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 2, "theme": theme, "cards": len(idea_cards)},
    ))

    # Ensure workspace dirs exist
    output_dir = WORKSPACE_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read the master prompt template
    prompt_template = _read_prompt("prd.md")

    # Build session configs — one session per Idea Card
    configs: list[SessionConfig] = []
    slug_map: dict[str, Path] = {}  # session_id -> card path

    for card_path in idea_cards:
        slug = _slugify(card_path)
        session_id = f"prd-{slug}"

        # Read the idea card content
        card_content = card_path.read_text(encoding="utf-8")

        # Render the prompt with idea card content and theme
        prompt = _render(
            prompt_template,
            idea_card_content=card_content,
            theme=theme,
        )

        work_dir = str(WORKSPACE_DIR / slug)

        configs.append(SessionConfig(
            session_id=session_id,
            prompt=prompt,
            working_dir=work_dir,
            allowed_tools=["Agent", "Read", "Write", "Glob", "Grep"],
            model="sonnet",
            timeout_seconds=1800,
            max_budget_usd=5.0,
        ))
        slug_map[session_id] = card_path

    logger.info("Stage 2: Launching %d PRD sessions", len(configs))

    # Run all sessions (parallel, bounded by SessionManager semaphore)
    results = await session_mgr.run_many(configs)

    # Collect outputs
    prd_files: list[Path] = []
    eliminated_count = 0
    failed_count = 0

    for result in results:
        slug = result.session_id.removeprefix("prd-")
        card_path = slug_map.get(result.session_id)

        if result.status != SessionStatus.COMPLETED:
            failed_count += 1
            logger.warning(
                "PRD session %s failed: %s", result.session_id, result.error
            )
            await event_bus.emit(Event(
                type="prd_failed",
                data={"session_id": result.session_id, "error": result.error or "unknown"},
            ))
            continue

        outputs = _collect_prd_outputs(result)

        if outputs["eliminated"]:
            eliminated_count += 1
            reason = outputs["eliminated"].read_text(encoding="utf-8")[:200]
            logger.info("PRD session %s: ELIMINATED — %s", result.session_id, reason)
            await event_bus.emit(Event(
                type="prd_eliminated",
                data={"session_id": result.session_id, "reason": reason},
            ))
            continue

        if outputs["prd"]:
            # Copy PRD to output directory
            dest_prd = output_dir / f"prd-{slug}.md"
            shutil.copy2(outputs["prd"], dest_prd)
            prd_files.append(dest_prd)

            # Copy wireframe if present
            if outputs["wireframe"]:
                dest_wf = output_dir / f"prd-{slug}-wireframe.html"
                shutil.copy2(outputs["wireframe"], dest_wf)

            logger.info("PRD session %s: produced PRD", result.session_id)
            await event_bus.emit(Event(
                type="prd_completed",
                data={
                    "session_id": result.session_id,
                    "prd_file": str(dest_prd),
                    "has_wireframe": outputs["wireframe"] is not None,
                },
            ))
        else:
            failed_count += 1
            logger.warning("PRD session %s completed but no prd.md found", result.session_id)
            await event_bus.emit(Event(
                type="prd_failed",
                data={"session_id": result.session_id, "error": "no prd.md produced"},
            ))

    logger.info(
        "Stage 2 complete: %d PRDs, %d eliminated, %d failed",
        len(prd_files), eliminated_count, failed_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 2,
            "prds": len(prd_files),
            "eliminated": eliminated_count,
            "failed": failed_count,
        },
    ))

    return prd_files
