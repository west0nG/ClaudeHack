"""Stage 2.5: ConfigGate — credential collection and environment planning.

Sits between Stage 2 (PRD generation) and Stage 3 (Demo development).
Parses Prerequisites Checklists from technical.md, diffs against the persistent
credential store, prompts for missing credentials, and generates per-project
environment plans.

Supports two collection modes:
  - Dashboard: emits config_requested event, renders form in browser, waits for
    config_response WebSocket message.
  - CLI: interactive input() prompts in the terminal.
"""

from __future__ import annotations

import logging
from pathlib import Path

from control.config import PERSISTENT_CREDS_PATH, STAGE2_5_DIR
from control.credential_store import (
    diff_credentials,
    generate_env_plan,
    load_all_credentials,
    load_persistent,
    parse_prerequisites,
    save_persistent,
)
from control.credential_ui import (
    collect_credentials_cli,
    collect_credentials_dashboard,
    write_run_credentials,
)
from control.event_bus import EventBus
from control.models import Event, slugify_name

logger = logging.getLogger(__name__)


async def run_config_gate(
    prd_dirs: list[Path],
    event_bus: EventBus,
    persistent_creds_path: Path | None = None,
    skip: bool = False,
    no_dashboard: bool = True,
    ws_server: "WebSocketServer | None" = None,
) -> tuple[list[Path], dict[str, str], dict[str, set[str]]]:
    """Run ConfigGate: parse prerequisites, collect credentials, generate env plans.

    Args:
        prd_dirs: List of PRD directories (each with concept.md, logic.md, technical.md).
        event_bus: Event bus for publishing progress events.
        persistent_creds_path: Path to persistent credentials.env (default: project root).
        skip: If True, skip interactive collection — use only what's in persistent store.
        no_dashboard: If True, use CLI mode for credential collection.
        ws_server: WebSocket server for dashboard interaction (None = CLI mode).

    Returns:
        Tuple of (approved_prd_dirs, merged_credentials, project_needed_vars).
        approved_prd_dirs excludes projects blocked by missing carrier deps.
        merged_credentials contains all credentials (persistent + newly collected).
        project_needed_vars maps slug -> set of env var names the project needs.
    """
    creds_path = persistent_creds_path or PERSISTENT_CREDS_PATH

    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": "2.5-config", "projects": len(prd_dirs)},
    ))

    # Step 1: Parse all technical.md prerequisites
    all_prerequisites: dict[str, dict] = {}  # slug -> parsed prerequisites
    all_needed_vars: set[str] = set()
    # Per-project env var names (slug -> set of var names)
    project_needed_vars: dict[str, set[str]] = {}

    for prd_dir in prd_dirs:
        technical_path = prd_dir / "technical.md"
        if not technical_path.exists():
            logger.warning("ConfigGate: no technical.md in %s, skipping", prd_dir.name)
            continue

        technical_content = technical_path.read_text(encoding="utf-8")
        prereqs = parse_prerequisites(technical_content)
        slug = slugify_name(prd_dir.name, fallback="project")
        all_prerequisites[slug] = prereqs

        # Collect env var names (global + per-project)
        project_vars: set[str] = set()
        for category in ("carrier", "functional"):
            for dep in prereqs.get(category, []):
                env_var = dep.get("env_var", "")
                if env_var:
                    all_needed_vars.add(env_var)
                    project_vars.add(env_var)
        project_needed_vars[slug] = project_vars

    if not all_prerequisites:
        logger.info("ConfigGate: no prerequisites found in any project")
        await event_bus.emit(Event(
            type="stage_completed",
            data={"stage": "2.5-config", "projects": len(prd_dirs), "skipped": True},
        ))
        return prd_dirs, {}, project_needed_vars

    logger.info(
        "ConfigGate: found prerequisites in %d projects, %d unique env vars needed",
        len(all_prerequisites),
        len(all_needed_vars),
    )

    # Step 2: Diff against persistent store + system environment
    persistent_creds = load_all_credentials(creds_path, needed_vars=all_needed_vars)
    already_have = {k for k in all_needed_vars if k in persistent_creds and persistent_creds[k]}
    still_need = all_needed_vars - already_have

    logger.info(
        "ConfigGate: %d credentials already available (store + env), %d still needed",
        len(already_have),
        len(still_need),
    )

    # Step 3: Collect missing credentials
    new_creds: dict[str, str] = {}

    if still_need and not skip:
        # Build a display-friendly list of what's needed.
        # If the same env var is carrier in one project and functional in
        # another, promote it to carrier (the stricter classification wins).
        needed_details: dict[str, dict] = {}  # env_var -> {name, category, obtain, projects}
        for slug, prereqs in all_prerequisites.items():
            for category in ("carrier", "functional"):
                for dep in prereqs.get(category, []):
                    env_var = dep.get("env_var", "")
                    if env_var in still_need:
                        if env_var not in needed_details:
                            needed_details[env_var] = {
                                "name": dep["name"],
                                "category": category,
                                "obtain": dep.get("obtain", ""),
                                "projects": [],
                            }
                        else:
                            # Promote to carrier if any project treats it as carrier
                            if category == "carrier":
                                needed_details[env_var]["category"] = "carrier"
                        needed_details[env_var]["projects"].append(slug)

        if ws_server and not no_dashboard:
            new_creds = await collect_credentials_dashboard(
                needed_details, already_have, event_bus, ws_server,
            )
        else:
            new_creds = await collect_credentials_cli(
                needed_details, already_have,
            )

    elif still_need and skip:
        logger.info("ConfigGate: --skip-config active, using only persistent store (%d keys)", len(persistent_creds))

    # Step 4: Persist new credentials and generate per-run files
    if new_creds:
        save_persistent(creds_path, new_creds)

    # Merge all credentials
    merged_creds = {**persistent_creds, **new_creds}

    # Write per-run credentials.env (only keys relevant to this run)
    STAGE2_5_DIR.mkdir(parents=True, exist_ok=True)
    run_creds_path = STAGE2_5_DIR / "credentials.env"
    write_run_credentials(run_creds_path, merged_creds, all_needed_vars)

    # Step 5: Generate environment-plan.md per project and determine blocking
    approved_dirs: list[Path] = []
    blocked_count = 0

    for prd_dir in prd_dirs:
        slug = slugify_name(prd_dir.name, fallback="project")
        prereqs = all_prerequisites.get(slug)

        if prereqs is None:
            # No technical.md — let it through (no deps to check)
            approved_dirs.append(prd_dir)
            continue

        diff = diff_credentials(prereqs, merged_creds)

        # Block if missing carrier deps (but not in skip mode — user chose
        # to skip collection, so let everything through with best-effort creds)
        is_blocked = len(diff["missing_carrier"]) > 0 and not skip
        env_plan = generate_env_plan(slug, diff, blocked=is_blocked)

        # Write environment-plan.md
        plan_dir = STAGE2_5_DIR / slug
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "environment-plan.md").write_text(env_plan, encoding="utf-8")

        if is_blocked:
            missing_names = [d.get("env_var", d["name"]) for d in diff["missing_carrier"]]
            logger.warning(
                "ConfigGate: BLOCKED %s — missing carrier deps: %s",
                slug,
                ", ".join(missing_names),
            )
            await event_bus.emit(Event(
                type="config_blocked",
                data={"slug": slug, "missing": missing_names},
            ))
            blocked_count += 1
        else:
            approved_dirs.append(prd_dir)

    logger.info(
        "ConfigGate complete: %d approved, %d blocked",
        len(approved_dirs),
        blocked_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": "2.5-config",
            "approved": len(approved_dirs),
            "blocked": blocked_count,
            "credentials_collected": len(new_creds),
        },
    ))

    return approved_dirs, merged_creds, project_needed_vars
