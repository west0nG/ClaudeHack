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

import asyncio
import logging
import time
from pathlib import Path

from control.credential_store import (
    diff_credentials,
    generate_env_plan,
    load_persistent,
    parse_prerequisites,
    save_persistent,
    validate_credential,
)
from control.event_bus import EventBus
from control.models import Event
from control.session_manager import PROJECT_ROOT

logger = logging.getLogger(__name__)

STAGE2_5_DIR = PROJECT_ROOT / "workspace" / "stage2.5"
PERSISTENT_CREDS_PATH = PROJECT_ROOT / "credentials.env"

# Timeout for waiting on user credential input (10 minutes)
CONFIG_TIMEOUT_SECONDS = 600


async def run_config_gate(
    prd_dirs: list[Path],
    event_bus: EventBus,
    persistent_creds_path: Path | None = None,
    skip: bool = False,
    no_dashboard: bool = True,
    ws_server: "WebSocketServer | None" = None,
) -> tuple[list[Path], dict[str, str]]:
    """Run ConfigGate: parse prerequisites, collect credentials, generate env plans.

    Args:
        prd_dirs: List of PRD directories (each with concept.md, logic.md, technical.md).
        event_bus: Event bus for publishing progress events.
        persistent_creds_path: Path to persistent credentials.env (default: project root).
        skip: If True, skip interactive collection — use only what's in persistent store.
        no_dashboard: If True, use CLI mode for credential collection.
        ws_server: WebSocket server for dashboard interaction (None = CLI mode).

    Returns:
        Tuple of (approved_prd_dirs, merged_credentials).
        approved_prd_dirs excludes projects blocked by missing carrier deps.
        merged_credentials contains all credentials (persistent + newly collected).
    """
    creds_path = persistent_creds_path or PERSISTENT_CREDS_PATH

    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": "2.5-config", "projects": len(prd_dirs)},
    ))

    # Step 1: Parse all technical.md prerequisites
    all_prerequisites: dict[str, dict] = {}  # slug -> parsed prerequisites
    all_needed_vars: set[str] = set()

    for prd_dir in prd_dirs:
        technical_path = prd_dir / "technical.md"
        if not technical_path.exists():
            logger.warning("ConfigGate: no technical.md in %s, skipping", prd_dir.name)
            continue

        technical_content = technical_path.read_text(encoding="utf-8")
        prereqs = parse_prerequisites(technical_content)
        slug = prd_dir.name
        all_prerequisites[slug] = prereqs

        # Collect all unique env var names
        for category in ("carrier", "functional"):
            for dep in prereqs.get(category, []):
                env_var = dep.get("env_var", "")
                if env_var:
                    all_needed_vars.add(env_var)

    if not all_prerequisites:
        logger.info("ConfigGate: no prerequisites found in any project")
        await event_bus.emit(Event(
            type="stage_completed",
            data={"stage": "2.5-config", "projects": len(prd_dirs), "skipped": True},
        ))
        return prd_dirs, {}

    logger.info(
        "ConfigGate: found prerequisites in %d projects, %d unique env vars needed",
        len(all_prerequisites),
        len(all_needed_vars),
    )

    # Step 2: Diff against persistent store
    persistent_creds = load_persistent(creds_path)
    already_have = {k for k in all_needed_vars if k in persistent_creds and persistent_creds[k]}
    still_need = all_needed_vars - already_have

    logger.info(
        "ConfigGate: %d credentials already in store, %d still needed",
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
            new_creds = await _collect_credentials_dashboard(
                needed_details, already_have, event_bus, ws_server,
            )
        else:
            new_creds = await _collect_credentials_cli(
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
    _write_run_credentials(run_creds_path, merged_creds, all_needed_vars)

    # Step 5: Generate environment-plan.md per project and determine blocking
    approved_dirs: list[Path] = []
    blocked_count = 0

    for prd_dir in prd_dirs:
        slug = prd_dir.name
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

    return approved_dirs, merged_creds


# ---------------------------------------------------------------------------
# Dashboard mode: WebSocket-based credential collection
# ---------------------------------------------------------------------------

async def _collect_credentials_dashboard(
    needed_details: dict[str, dict],
    already_have: set[str],
    event_bus: EventBus,
    ws_server: "WebSocketServer",
) -> dict[str, str]:
    """Collect missing credentials via Dashboard WebSocket UI.

    Emits config_requested event, waits for config_response message from
    the dashboard containing filled-in credential values.
    """
    # Build serializable payload for the dashboard
    satisfied = [{"env_var": v} for v in sorted(already_have)]

    carrier_list = []
    functional_list = []
    for env_var, detail in sorted(needed_details.items()):
        entry = {
            "env_var": env_var,
            "name": detail["name"],
            "obtain": detail.get("obtain", ""),
            "projects": detail["projects"],
        }
        if detail["category"] == "carrier":
            carrier_list.append(entry)
        else:
            functional_list.append(entry)

    await event_bus.emit(Event(
        type="config_requested",
        data={
            "satisfied": satisfied,
            "carrier": carrier_list,
            "functional": functional_list,
        },
    ))

    logger.info(
        "Waiting for credential input from dashboard (%d carrier, %d functional, %ds timeout)...",
        len(carrier_list), len(functional_list), CONFIG_TIMEOUT_SECONDS,
    )

    # Register validation handler so dashboard can validate individual keys.
    # NOTE: ws_server._dispatch_message calls handlers synchronously, so this
    # must be a regular function that schedules async work via create_task.
    def handle_validate_request(message: dict) -> None:
        env_var = message.get("env_var", "")
        value = message.get("value", "")

        async def _do_validate() -> None:
            result = await validate_credential(env_var, value)
            await event_bus.emit(Event(
                type="config_validate_response",
                data={"env_var": env_var, **result},
            ))

        asyncio.create_task(_do_validate())

    ws_server.register_handler("config_validate_request", handle_validate_request)

    # Wait for dashboard response
    loop = asyncio.get_running_loop()
    response_future: asyncio.Future[dict] = loop.create_future()

    def handle_config_response(message: dict) -> None:
        if not response_future.done():
            response_future.set_result(message)

    ws_server.register_handler("config_response", handle_config_response)

    try:
        response = await asyncio.wait_for(
            response_future, timeout=CONFIG_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("ConfigGate dashboard timeout — proceeding with no new credentials")
        return {}
    finally:
        ws_server.unregister_handler("config_response")
        ws_server.unregister_handler("config_validate_request")

    # Extract credentials from response: {credentials: {ENV_VAR: "value", ...}}
    new_creds: dict[str, str] = {}
    raw_creds = response.get("credentials", {})
    for env_var, value in raw_creds.items():
        value = str(value).strip()
        if value:
            new_creds[env_var] = value

    logger.info("Dashboard provided %d credentials", len(new_creds))

    await event_bus.emit(Event(
        type="config_collected",
        data={"count": len(new_creds)},
    ))

    return new_creds


# ---------------------------------------------------------------------------
# CLI mode: interactive terminal-based credential collection
# ---------------------------------------------------------------------------

async def _collect_credentials_cli(
    needed_details: dict[str, dict],
    already_have: set[str],
) -> dict[str, str]:
    """Collect missing credentials via CLI interactive prompt."""
    new_creds: dict[str, str] = {}

    print("\n" + "=" * 60)
    print("ConfigGate: Credential Collection")
    print("=" * 60)

    if already_have:
        print(f"\nAlready satisfied ({len(already_have)}):")
        for var in sorted(already_have):
            print(f"  ✅ {var}")

    # Separate carrier and functional
    carrier_vars = {k: v for k, v in needed_details.items() if v["category"] == "carrier"}
    functional_vars = {k: v for k, v in needed_details.items() if v["category"] == "functional"}

    if carrier_vars:
        print(f"\nRequired credentials ({len(carrier_vars)}) — projects will be BLOCKED without these:")
        for env_var, detail in sorted(carrier_vars.items()):
            print(f"\n  🔑 {env_var} — {detail['name']}")
            if detail["obtain"]:
                print(f"     Obtain: {detail['obtain']}")
            print(f"     Used by: {', '.join(detail['projects'])}")

            value = await _prompt_and_validate(env_var, required=True)
            if value:
                new_creds[env_var] = value

    if functional_vars:
        print(f"\nOptional credentials ({len(functional_vars)}) — features will be skipped if missing:")
        for env_var, detail in sorted(functional_vars.items()):
            print(f"\n  🔧 {env_var} — {detail['name']}")
            if detail["obtain"]:
                print(f"     Obtain: {detail['obtain']}")
            print(f"     Used by: {', '.join(detail['projects'])}")

            value = await _prompt_and_validate(env_var, required=False)
            if value:
                new_creds[env_var] = value

    print(f"\nCollected {len(new_creds)} new credentials.")
    print("=" * 60 + "\n")

    return new_creds


def _prompt_credential(env_var: str, required: bool = True) -> str:
    """Prompt user for a single credential value.

    Returns the value, or empty string if skipped.
    """
    label = "(required)" if required else "(optional, Enter to skip)"
    try:
        value = input(f"     Enter value {label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return value


async def _prompt_and_validate(
    env_var: str,
    required: bool,
    max_attempts: int = 3,
) -> str:
    """Prompt for a credential and validate it, with retries on failure.

    Returns the accepted value, or empty string if skipped.
    """
    loop = asyncio.get_running_loop()
    for attempt in range(1, max_attempts + 1):
        value = await loop.run_in_executor(
            None, _prompt_credential, env_var, required,
        )
        if not value:
            return ""

        # Validate
        print("     Validating...", end="", flush=True)
        result = await validate_credential(env_var, value)

        if result["skipped"]:
            print(" skipped (no validator for this key type)")
            return value

        if result["valid"]:
            if result["warning"]:
                print(f" ⚠️  {result['warning']}")
            else:
                print(" ✅ valid")
            return value

        # Validation failed
        print(f" ❌ {result['error']}")
        if attempt < max_attempts:
            print(f"     Please try again ({max_attempts - attempt} attempts remaining)")
        else:
            print("     Max attempts reached — accepting value with warning")
            return value

    return ""


def _write_run_credentials(
    path: Path, all_creds: dict[str, str], needed_vars: set[str]
) -> None:
    """Write per-run credentials.env containing only keys relevant to this run."""
    lines = ["# Per-run credentials (auto-generated by ConfigGate)"]
    for var in sorted(needed_vars):
        value = all_creds.get(var, "")
        if value:
            lines.append(f"{var}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote per-run credentials to %s (%d keys)", path, sum(1 for v in needed_vars if all_creds.get(v)))
