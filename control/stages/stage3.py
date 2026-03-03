"""Stage 3: Demo Development — from PRDs to working, runnable demo projects."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, SessionConfig, SessionResult, SessionStatus
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


def _slugify(prd_path: Path) -> str:
    """Derive a short slug from a PRD file path."""
    stem = prd_path.stem  # e.g. "prd-freelancer-burnout"
    # Strip the "prd-" prefix if present
    slug = re.sub(r"^prd-", "", stem)
    # Ensure URL-safe
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:40] or "project"


def _collect_project_outputs(result: SessionResult) -> dict:
    """Check a session's working dir for project outputs.

    Avoids rglob to prevent scanning node_modules/.

    Returns a dict with keys:
      - "project_dir": Path to demo/ directory (or None)
      - "has_readme": bool
      - "build_failed": Path to BUILD_FAILED.md (or None)
    """
    outputs: dict = {"project_dir": None, "has_readme": False, "build_failed": None}
    if result.status != SessionStatus.COMPLETED or not result.working_dir:
        return outputs

    work_dir = Path(result.working_dir)

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


async def run_stage3(
    prd_files: list[Path],
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
) -> list[Path]:
    """Execute Stage 3: Demo Development. Returns paths to project directories."""

    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 3, "theme": theme, "prds": len(prd_files)},
    ))

    # Ensure workspace dir exists
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Read the master prompt template
    prompt_template = _read_prompt("dev.md")

    # Build session configs — one session per PRD
    configs: list[SessionConfig] = []
    slug_map: dict[str, Path] = {}  # session_id -> prd path

    for prd_path in prd_files:
        slug = _slugify(prd_path)
        session_id = f"dev-{slug}"

        # Read the PRD content
        prd_content = prd_path.read_text(encoding="utf-8")

        # Render the prompt with PRD content and theme
        prompt = _render(
            prompt_template,
            prd_content=prd_content,
            theme=theme,
        )

        work_dir = str(WORKSPACE_DIR / slug)

        configs.append(SessionConfig(
            session_id=session_id,
            prompt=prompt,
            working_dir=work_dir,
            allowed_tools=["Bash", "Agent", "Read", "Write", "Glob", "Grep"],
            model="sonnet",
            timeout_seconds=3600,  # 1 hour — demos take time to build
            max_budget_usd=10.0,
        ))
        slug_map[session_id] = prd_path

    logger.info("Stage 3: Launching %d dev sessions", len(configs))

    # Run all sessions (parallel, bounded by SessionManager semaphore)
    results = await session_mgr.run_many(configs)

    # Collect outputs
    project_dirs: list[Path] = []
    build_failed_count = 0
    failed_count = 0

    for result in results:
        slug = result.session_id.removeprefix("dev-")

        if result.status != SessionStatus.COMPLETED:
            failed_count += 1
            logger.warning(
                "Dev session %s failed: %s", result.session_id, result.error
            )
            await event_bus.emit(Event(
                type="dev_failed",
                data={"session_id": result.session_id, "error": result.error or "unknown"},
            ))
            continue

        outputs = _collect_project_outputs(result)

        if outputs["build_failed"]:
            build_failed_count += 1
            reason = outputs["build_failed"].read_text(encoding="utf-8")[:200]
            logger.info("Dev session %s: BUILD FAILED — %s", result.session_id, reason)
            await event_bus.emit(Event(
                type="dev_failed",
                data={"session_id": result.session_id, "error": f"Build failed: {reason}"},
            ))
            continue

        if outputs["project_dir"]:
            project_dirs.append(outputs["project_dir"])
            logger.info(
                "Dev session %s: project built (README: %s)",
                result.session_id, outputs["has_readme"],
            )
            await event_bus.emit(Event(
                type="dev_completed",
                data={
                    "session_id": result.session_id,
                    "project_dir": str(outputs["project_dir"]),
                    "has_readme": outputs["has_readme"],
                },
            ))
        else:
            failed_count += 1
            logger.warning("Dev session %s completed but no project found", result.session_id)
            await event_bus.emit(Event(
                type="dev_failed",
                data={"session_id": result.session_id, "error": "no project produced"},
            ))

    logger.info(
        "Stage 3 complete: %d projects, %d build failures, %d session failures",
        len(project_dirs), build_failed_count, failed_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 3,
            "projects": len(project_dirs),
            "build_failed": build_failed_count,
            "failed": failed_count,
        },
    ))

    return project_dirs
