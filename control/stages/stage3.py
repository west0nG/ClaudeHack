"""Stage 3: Demo Development — 3-session serial pipeline per PRD directory.

Each project runs through: plan → dev → review (with optional bounce-back).
Different projects run in parallel, bounded by SessionManager semaphore.
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

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "stage3"
WORKSPACE_DIR = PROJECT_ROOT / "workspace" / "stage3"


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


def _slugify_prd_dir(prd_dir: Path) -> str:
    """Derive a short slug from a PRD directory path."""
    name = prd_dir.name  # e.g. "freelancer-burnout"
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:40] or "project"


def _check_project_success(work_dir: Path) -> dict:
    """Check a project's working dir for outputs.

    Returns a dict with keys:
      - "project_dir": Path to demo/ directory (or None)
      - "has_readme": bool
      - "build_failed": Path to BUILD_FAILED.md (or None)
    """
    outputs: dict = {"project_dir": None, "has_readme": False, "build_failed": None}

    # Check for build failure sentinel in the working dir (not inside demo/)
    build_failed = work_dir / "BUILD_FAILED.md"
    if build_failed.exists():
        outputs["build_failed"] = build_failed
        return outputs

    # Check for a successful project (package.json inside demo/)
    demo_dir = work_dir / "demo"
    package_json = demo_dir / "package.json"
    if package_json.exists():
        outputs["project_dir"] = demo_dir
        outputs["has_readme"] = (demo_dir / "README.md").exists()

    return outputs


async def _run_project_pipeline(
    prd_dir: Path,
    slug: str,
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> Path | None:
    """Run the 3-session pipeline for a single project.

    Returns the demo/ directory path on success, or None if failed.
    """
    # Read the 3 PRD documents
    concept_content = (prd_dir / "concept.md").read_text(encoding="utf-8")
    logic_content = (prd_dir / "logic.md").read_text(encoding="utf-8")
    technical_content = (prd_dir / "technical.md").read_text(encoding="utf-8")

    # Working directories: plan gets its own, dev and review share one
    project_work_dir = WORKSPACE_DIR / slug
    plan_work_dir = project_work_dir / "plan"
    dev_work_dir = project_work_dir / "dev"

    # Clean stale data from previous runs to prevent false
    # BUILD_FAILED.md / demo/ detection from old sessions
    if project_work_dir.exists():
        shutil.rmtree(project_work_dir)
    plan_work_dir.mkdir(parents=True, exist_ok=True)
    dev_work_dir.mkdir(parents=True, exist_ok=True)

    # Load prompt templates
    plan_template = _read_prompt("plan.md")
    dev_template = _read_prompt("dev.md")
    review_template = _read_prompt("review.md")

    # ------------------------------------------------------------------
    # Session A: Plan
    # ------------------------------------------------------------------
    plan_prompt = _render(
        plan_template,
        theme=theme,
        concept_content=concept_content,
        logic_content=logic_content,
        technical_content=technical_content,
    )

    plan_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"plan-{slug}",
        prompt=plan_prompt,
        working_dir=str(plan_work_dir),
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        model="sonnet",
        timeout_seconds=300,
        max_budget_usd=2.0,
    ))

    if plan_result.status != SessionStatus.COMPLETED:
        logger.warning("Plan session for %s failed: %s", slug, plan_result.error)
        await event_bus.emit(Event(
            type="dev_failed",
            data={"session_id": f"plan-{slug}", "error": plan_result.error or "unknown"},
        ))
        return None

    # Read dev-plan.md
    dev_plan_file = plan_work_dir / "dev-plan.md"
    if not dev_plan_file.exists():
        logger.warning("Plan session for %s completed but no dev-plan.md found", slug)
        await event_bus.emit(Event(
            type="dev_failed",
            data={"session_id": f"plan-{slug}", "error": "no dev-plan.md produced"},
        ))
        return None

    dev_plan_content = dev_plan_file.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Session B: Dev
    # ------------------------------------------------------------------
    dev_prompt = _render(
        dev_template,
        theme=theme,
        concept_content=concept_content,
        logic_content=logic_content,
        technical_content=technical_content,
        dev_plan_content=dev_plan_content,
    )

    dev_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"dev-{slug}",
        prompt=dev_prompt,
        working_dir=str(dev_work_dir),
        allowed_tools=["Bash", "Agent", "Read", "Write", "Glob", "Grep"],
        model="sonnet",
        timeout_seconds=2400,
        max_budget_usd=8.0,
    ))

    if dev_result.status != SessionStatus.COMPLETED:
        logger.warning("Dev session for %s failed: %s", slug, dev_result.error)
        await event_bus.emit(Event(
            type="dev_failed",
            data={"session_id": f"dev-{slug}", "error": dev_result.error or "unknown"},
        ))
        return None

    # ------------------------------------------------------------------
    # Session C: Review (shares working directory with dev)
    # ------------------------------------------------------------------
    review_prompt = _render(
        review_template,
        theme=theme,
        concept_content=concept_content,
        dev_plan_content=dev_plan_content,
    )

    review_result = await session_mgr.run_session_bounded(SessionConfig(
        session_id=f"review-{slug}",
        prompt=review_prompt,
        working_dir=str(dev_work_dir),
        allowed_tools=["Bash", "Agent", "Read", "Write", "Glob", "Grep"],
        model="sonnet",
        timeout_seconds=1200,
        max_budget_usd=5.0,
    ))

    if review_result.status != SessionStatus.COMPLETED:
        logger.warning("Review session for %s failed: %s", slug, review_result.error)
        # Don't return None yet — check if the project was built before review failed

    # ------------------------------------------------------------------
    # Bounce-back: if BUILD_FAILED, retry dev + review (max 1x)
    # ------------------------------------------------------------------
    outputs = _check_project_success(dev_work_dir)

    if outputs["build_failed"] and review_result.status == SessionStatus.COMPLETED:
        logger.info("Project %s: build failed after review, attempting bounce-back", slug)

        # Read failure context
        failure_context = outputs["build_failed"].read_text(encoding="utf-8")

        # Re-run dev with failure context appended
        bounce_prompt = dev_prompt + (
            "\n\n---\n\n"
            "## IMPORTANT: Previous Attempt Failed\n\n"
            "The previous build attempt failed. Here is the failure report:\n\n"
            f"{failure_context}\n\n"
            "Fix the issues described above. Pay special attention to build errors."
        )

        # Remove BUILD_FAILED.md so fresh attempt starts clean
        outputs["build_failed"].unlink()

        bounce_dev_result = await session_mgr.run_session_bounded(SessionConfig(
            session_id=f"dev-{slug}-fix",
            prompt=bounce_prompt,
            working_dir=str(dev_work_dir),
            allowed_tools=["Bash", "Agent", "Read", "Write", "Glob", "Grep"],
            model="sonnet",
            timeout_seconds=2400,
            max_budget_usd=8.0,
        ))

        if bounce_dev_result.status == SessionStatus.COMPLETED:
            # Re-run review
            bounce_review_result = await session_mgr.run_session_bounded(SessionConfig(
                session_id=f"review-{slug}-fix",
                prompt=review_prompt,
                working_dir=str(dev_work_dir),
                allowed_tools=["Bash", "Agent", "Read", "Write", "Glob", "Grep"],
                model="sonnet",
                timeout_seconds=1200,
                max_budget_usd=5.0,
            ))

            if bounce_review_result.status != SessionStatus.COMPLETED:
                logger.warning("Bounce review for %s failed: %s", slug, bounce_review_result.error)

        # Re-check outputs after bounce
        outputs = _check_project_success(dev_work_dir)

    # ------------------------------------------------------------------
    # Final result
    # ------------------------------------------------------------------
    if outputs["build_failed"]:
        reason = outputs["build_failed"].read_text(encoding="utf-8")[:200]
        logger.info("Project %s: BUILD FAILED — %s", slug, reason)
        await event_bus.emit(Event(
            type="dev_failed",
            data={"session_id": f"dev-{slug}", "error": f"Build failed: {reason}"},
        ))
        return None

    if outputs["project_dir"]:
        logger.info(
            "Project %s: built successfully (README: %s)",
            slug, outputs["has_readme"],
        )
        await event_bus.emit(Event(
            type="dev_completed",
            data={
                "session_id": f"dev-{slug}",
                "project_dir": str(outputs["project_dir"]),
                "has_readme": outputs["has_readme"],
            },
        ))
        return outputs["project_dir"]

    logger.warning("Project %s: no demo/ directory found after pipeline", slug)
    await event_bus.emit(Event(
        type="dev_failed",
        data={"session_id": f"dev-{slug}", "error": "no project produced"},
    ))
    return None


async def run_stage3(
    prd_dirs: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> list[Path]:
    """Execute Stage 3: Demo Development.

    Args:
        prd_dirs: List of directories, each containing concept.md, logic.md, technical.md.
        theme: Hackathon theme string.
        session_mgr: Session manager for running Claude CLI sessions.
        event_bus: Event bus for publishing progress events.

    Returns:
        List of paths to successful demo/ project directories.
    """
    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 3, "theme": theme, "projects": len(prd_dirs)},
    ))

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Launch project pipelines in parallel (SessionManager semaphore bounds concurrency)
    tasks = []
    for prd_dir in prd_dirs:
        slug = _slugify_prd_dir(prd_dir)
        tasks.append(_run_project_pipeline(prd_dir, slug, theme, session_mgr, event_bus))

    logger.info("Stage 3: Launching %d project pipelines (3 sessions each)", len(tasks))
    results = await asyncio.gather(*tasks)

    # Collect successful project directories
    project_dirs = [r for r in results if r is not None]
    failed_count = len(results) - len(project_dirs)

    logger.info(
        "Stage 3 complete: %d projects built, %d failed",
        len(project_dirs), failed_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 3,
            "projects": len(project_dirs),
            "failed": failed_count,
        },
    ))

    return project_dirs
