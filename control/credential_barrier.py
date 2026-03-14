"""Streaming-friendly credential check and collection barrier.

Projects call check_and_wait() after their Stage 2 completes.
- If all credentials are in the persistent store → return immediately.
- If any credentials are missing → wait for interactive collection.
- Interactive collection triggers once, after all projects have checked in.

This replaces the stage-by-stage ConfigGate synchronization barrier
with a per-project barrier that only blocks projects that need it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from control.credential_store import (
    diff_credentials,
    generate_env_plan,
    parse_prerequisites,
    resolve_credential,
    save_persistent,
)
from control.event_bus import EventBus
from control.models import Event, slugify_name
from control.session_manager import PROJECT_ROOT

logger = logging.getLogger(__name__)

STAGE2_5_DIR = PROJECT_ROOT / "workspace" / "stage2.5"
PERSISTENT_CREDS_PATH = PROJECT_ROOT / "credentials.env"

# Safety timeout: don't block forever if some Stage 2 sessions hang
_BARRIER_TIMEOUT = 600  # 10 minutes


class CredentialBarrier:
    """One-shot credential collection barrier for streaming pipelines.

    Thread-safe for concurrent asyncio coroutines. Collection runs at most once.
    """

    def __init__(
        self,
        persistent_creds: dict[str, str],
        total_projects: int,
        event_bus: EventBus,
        skip: bool = False,
        no_dashboard: bool = True,
        ws_server: object | None = None,
    ) -> None:
        self._persistent = dict(persistent_creds)
        self._merged = dict(persistent_creds)
        self._total = total_projects
        self._event_bus = event_bus
        self._skip = skip
        self._no_dashboard = no_dashboard
        self._ws_server = ws_server

        self._lock = asyncio.Lock()
        self._collection_done = asyncio.Event()
        self._checked = 0
        self._all_prereqs: dict[str, dict] = {}
        self._project_needed: dict[str, set[str]] = {}
        self._all_needed: set[str] = set()
        self._needs_interactive = False

        # If skip mode or nothing to check, barrier starts open
        if skip or total_projects == 0:
            self._collection_done.set()

    # -- Public accessors (for resume support) --

    @property
    def merged_credentials(self) -> dict[str, str]:
        return dict(self._merged)

    @property
    def project_needed_vars(self) -> dict[str, set[str]]:
        return dict(self._project_needed)

    # -- Main API --

    async def check_and_wait(
        self, slug: str, prd_dir: Path | None,
    ) -> tuple[dict[str, str] | None, set[str], bool]:
        """Check credentials for a project after its Stage 2 completes.

        Args:
            slug: Project slug (must match across stages).
            prd_dir: PRD output directory, or None if Stage 2 failed.

        Returns:
            (project_creds, needed_vars, is_blocked)
            project_creds is None if blocked or failed.
        """
        if prd_dir is None:
            # Stage 2 failed — increment counter, don't register needs
            await self._increment_and_maybe_finalize()
            return None, set(), True

        # Parse prerequisites
        prereqs, needed = self._parse_prereqs(prd_dir)

        # Enrich from system environment for newly discovered vars
        self._fill_from_env(needed)

        # Check for missing deps against persistent store + env
        has_missing_carrier = False
        has_any_missing = False
        if prereqs and not self._skip:
            diff = diff_credentials(prereqs, self._merged)
            has_missing_carrier = len(diff["missing_carrier"]) > 0
            has_any_missing = (
                has_missing_carrier or len(diff["missing_functional"]) > 0
            )

        should_wait = False

        async with self._lock:
            self._all_prereqs[slug] = prereqs
            self._project_needed[slug] = needed
            self._all_needed |= needed
            self._checked += 1

            if has_missing_carrier:
                self._needs_interactive = True

            # Projects with missing deps wait (they benefit from collection)
            if has_any_missing and not self._skip:
                should_wait = True

            if self._checked >= self._total and not self._collection_done.is_set():
                await self._finalize()

        # Wait for collection if this project has missing deps
        if should_wait and not self._collection_done.is_set():
            try:
                await asyncio.wait_for(
                    self._wait_for_collection(), timeout=_BARRIER_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "CredentialBarrier: timeout waiting for collection for %s, "
                    "proceeding with available creds",
                    slug,
                )

        # Write environment-plan.md (uses merged creds, available after collection)
        diff = diff_credentials(prereqs, self._merged)
        is_blocked = bool(diff["missing_carrier"]) and not self._skip
        self._write_env_plan(slug, diff, is_blocked)

        if is_blocked:
            missing_names = [
                d.get("env_var", d["name"]) for d in diff["missing_carrier"]
            ]
            logger.warning(
                "CredentialBarrier: BLOCKED %s — missing carrier deps: %s",
                slug, ", ".join(missing_names),
            )
            await self._event_bus.emit(Event(
                type="config_blocked",
                data={"slug": slug, "missing": missing_names},
            ))
            return None, needed, True

        # Filter credentials for this project only
        project_creds = {k: v for k, v in self._merged.items() if k in needed}
        return project_creds or None, needed, False

    # -- Internal --

    async def _increment_and_maybe_finalize(self) -> None:
        async with self._lock:
            self._checked += 1
            if self._checked >= self._total and not self._collection_done.is_set():
                await self._finalize()

    async def _finalize(self) -> None:
        """Called (under lock) when all projects have checked in."""
        if self._needs_interactive:
            await self._run_collection()
        self._write_run_creds_file()
        self._collection_done.set()

    async def _wait_for_collection(self) -> None:
        """Await the collection_done event (wrappable with wait_for)."""
        await self._collection_done.wait()

    async def _run_collection(self) -> None:
        """Run interactive credential collection. Called at most once."""
        # Enrich from env one final time (covers vars from late-checking projects)
        self._fill_from_env(self._all_needed)

        still_need = self._all_needed - {
            k for k in self._merged if self._merged[k]
        }
        already_have = self._all_needed - still_need

        if not still_need:
            return

        # Build needed_details (same format as stage2_5 collection functions)
        needed_details: dict[str, dict] = {}
        for slug, prereqs in self._all_prereqs.items():
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
                        elif category == "carrier":
                            needed_details[env_var]["category"] = "carrier"
                        needed_details[env_var]["projects"].append(slug)

        await self._event_bus.emit(Event(
            type="stage_started",
            data={"stage": "2.5-config", "projects": self._total},
        ))

        # Reuse collection functions from stage2_5
        from control.stages.stage2_5 import (
            _collect_credentials_cli,
            _collect_credentials_dashboard,
        )

        if self._ws_server and not self._no_dashboard:
            new_creds = await _collect_credentials_dashboard(
                needed_details, already_have, self._event_bus, self._ws_server,
            )
        else:
            new_creds = await _collect_credentials_cli(
                needed_details, already_have,
            )

        if new_creds:
            save_persistent(PERSISTENT_CREDS_PATH, new_creds)
            self._merged.update(new_creds)

        logger.info(
            "CredentialBarrier: collected %d new credentials",
            len(new_creds) if new_creds else 0,
        )

        await self._event_bus.emit(Event(
            type="stage_completed",
            data={
                "stage": "2.5-config",
                "credentials_collected": len(new_creds) if new_creds else 0,
            },
        ))

    def _fill_from_env(self, needed: set[str]) -> None:
        """Fill gaps in self._merged from aliases + os.environ for the given var names."""
        for var in needed:
            if var in self._merged and self._merged[var]:
                continue

            # Try alias resolution against what we already have
            value = resolve_credential(var, self._merged)
            if value:
                logger.info("Credential %s: resolved via alias", var)
                self._merged[var] = value
                continue

            # Try exact name in system environment
            env_value = os.environ.get(var, "")
            if env_value:
                logger.info("Credential %s: found in system environment", var)
                self._merged[var] = env_value
                continue

            # Try alias resolution against system environment
            env_value = resolve_credential(var, dict(os.environ))
            if env_value:
                logger.info("Credential %s: resolved via alias from system environment", var)
                self._merged[var] = env_value

    def _write_run_creds_file(self) -> None:
        """Write per-run credentials.env for resume support."""
        STAGE2_5_DIR.mkdir(parents=True, exist_ok=True)
        creds_path = STAGE2_5_DIR / "credentials.env"
        lines = ["# Per-run credentials (auto-generated by CredentialBarrier)"]
        for var in sorted(self._all_needed):
            value = self._merged.get(var, "")
            if value:
                lines.append(f"{var}={value}")
        creds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_env_plan(self, slug: str, diff: dict, blocked: bool) -> None:
        """Write environment-plan.md for a single project."""
        env_plan = generate_env_plan(slug, diff, blocked=blocked)
        plan_dir = STAGE2_5_DIR / slug
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "environment-plan.md").write_text(env_plan, encoding="utf-8")

    @staticmethod
    def _parse_prereqs(prd_dir: Path) -> tuple[dict, set[str]]:
        """Parse prerequisites from technical.md. Returns (prereqs, needed_vars)."""
        technical_path = prd_dir / "technical.md"
        if not technical_path.exists():
            return {}, set()

        prereqs = parse_prerequisites(
            technical_path.read_text(encoding="utf-8")
        )
        needed: set[str] = set()
        for cat in ("carrier", "functional"):
            for dep in prereqs.get(cat, []):
                env_var = dep.get("env_var", "")
                if env_var:
                    needed.add(env_var)
        return prereqs, needed
