"""Resume Stage 3 for incomplete projects only.

Skips the expensive archive copytree — uses workspace/ as-is.
"""

import asyncio
import json
import logging
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, HackathonBrief
from control.config import PROJECT_ROOT
from control.session_manager import SessionManager
from control.stages.stage3 import run_stage3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("resume-stage3")


async def main() -> None:
    workspace = PROJECT_ROOT / "workspace"

    # Load metadata
    meta = json.loads((workspace / "run-metadata.json").read_text())
    theme = meta["theme"]
    model = meta.get("model", "sonnet")
    logger.info("Theme: %s, Model: %s", theme, model)

    # Collect ALL PRD dirs (stage3 skip logic handles already-done ones)
    stage2_output = workspace / "stage2" / "output"
    prd_dirs = sorted([
        d for d in stage2_output.iterdir()
        if d.is_dir() and (d / "concept.md").exists()
    ])
    logger.info("Total PRD dirs: %d", len(prd_dirs))

    event_bus = EventBus()

    async def log_events(event: Event) -> None:
        logger.info("[EVENT] %s: %s", event.type, event.data)

    event_bus.subscribe(log_events)

    session_mgr = SessionManager(max_concurrent=5, event_bus=event_bus)

    project_dirs = await run_stage3(
        prd_dirs=prd_dirs,
        theme=theme,
        session_mgr=session_mgr,
        event_bus=event_bus,
        model=model,
    )

    logger.info("=" * 60)
    logger.info("Stage 3 resume complete! %d projects built:", len(project_dirs))
    for d in project_dirs:
        logger.info("  - %s", d)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
