"""Persistent credential store and prerequisites parser.

Two-layer credential architecture:
  Layer 1: Persistent store at project root (credentials.env) — accumulates across runs
  Layer 2: Per-run credentials at workspace/stage2.5/credentials.env — subset for this run
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def load_persistent(path: Path) -> dict[str, str]:
    """Load KEY=VALUE pairs from persistent credentials.env.

    Skips blank lines and comments (lines starting with #).
    Returns empty dict if file does not exist.
    """
    if not path.exists():
        return {}

    creds: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes (KEY="value" or KEY='value')
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key:
                creds[key] = value
    return creds


def save_persistent(path: Path, new_creds: dict[str, str]) -> None:
    """Append new credentials to the persistent store.

    Only appends keys that don't already exist in the file.
    Creates the file if it doesn't exist.
    """
    existing = load_persistent(path)
    to_add = {k: v for k, v in new_creds.items() if k not in existing and v}

    if not to_add:
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    is_new_file = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8") as f:
        if is_new_file:
            f.write("# Persistent credential store (auto-managed by ConfigGate)\n")
        for key, value in sorted(to_add.items()):
            f.write(f"{key}={value}\n")

    logger.info("Saved %d new credentials to persistent store", len(to_add))


def parse_prerequisites(technical_md: str) -> dict:
    """Extract Prerequisites Checklist from technical.md content.

    Parses the structured markdown format produced by the Technical Architect Agent.

    Returns:
        {
            "carrier": [{"name": "SLACK_BOT_TOKEN", "description": "...", "obtain": "..."}],
            "functional": [{"name": "OPENAI_API_KEY", "description": "...", "skip_module": "..."}],
            "dev": [{"name": "ngrok", "description": "..."}],
        }
    """
    result: dict[str, list[dict]] = {"carrier": [], "functional": [], "dev": []}

    # Find the Prerequisites Checklist section
    checklist_match = re.search(
        r"##\s*Prerequisites\s+Checklist(.*?)(?=\n##\s[^#]|\Z)",
        technical_md,
        re.DOTALL | re.IGNORECASE,
    )
    if not checklist_match:
        return result

    checklist_text = checklist_match.group(1)

    # Split into subsections by ### headers
    sections = re.split(r"###\s+", checklist_text)

    for section in sections:
        if not section.strip():
            continue

        # Determine category from section header
        header_lower = section.split("\n", 1)[0].lower()
        if "carrier" in header_lower:
            category = "carrier"
        elif "functional" in header_lower:
            category = "functional"
        elif "development" in header_lower or "dev" in header_lower:
            category = "dev"
        else:
            continue

        # Parse individual items: lines starting with "- [ ]" or "- [x]"
        items = re.findall(
            r"-\s*\[[ x]\]\s*\*\*(.+?)\*\*:\s*(.+?)(?=\n-\s*\[|\n###|\Z)",
            section,
            re.DOTALL,
        )

        for item_name, item_body in items:
            dep: dict[str, str] = {
                "name": item_name.strip(),
                "description": item_body.strip().split("\n")[0].strip(),
            }

            # Extract env var name from `VARIABLE_NAME` pattern
            env_match = re.search(r"Env\s*var:\s*`([^`]+)`", item_body)
            if env_match:
                dep["env_var"] = env_match.group(1).strip()

            # Extract obtain/install instructions
            obtain_match = re.search(r"Obtain:\s*(.+?)(?:\n|$)", item_body)
            if obtain_match:
                dep["obtain"] = obtain_match.group(1).strip()

            install_match = re.search(r"Install:\s*(.+?)(?:\n|$)", item_body)
            if install_match:
                dep["obtain"] = install_match.group(1).strip()

            # Extract skip info for functional deps
            skip_match = re.search(r"If\s+missing:\s*(.+?)(?:\n|$)", item_body)
            if skip_match:
                dep["skip_module"] = skip_match.group(1).strip()

            result[category].append(dep)

    return result


def diff_credentials(
    needed: dict[str, list[dict]], have: dict[str, str]
) -> dict:
    """Compare needed deps against what we have.

    Args:
        needed: Output from parse_prerequisites()
        have: Dict of env var name -> value from persistent store

    Returns:
        {
            "satisfied": [{"name": ..., "env_var": ..., "category": ...}],
            "missing_carrier": [{"name": ..., "env_var": ..., ...}],
            "missing_functional": [{"name": ..., "env_var": ..., ...}],
        }
    """
    result: dict[str, list[dict]] = {
        "satisfied": [],
        "missing_carrier": [],
        "missing_functional": [],
    }

    for category in ("carrier", "functional"):
        for dep in needed.get(category, []):
            env_var = dep.get("env_var", "")

            if not env_var:
                # No env var extracted — can't check or collect.
                # Carrier deps without env_var are still blockers (parser couldn't
                # extract the variable name, so we can't satisfy it).
                if category == "carrier":
                    logger.warning(
                        "Carrier dep '%s' has no env_var — treating as missing",
                        dep.get("name", "unknown"),
                    )
                    result["missing_carrier"].append(dep)
                # Functional deps without env_var are silently skipped (no way to
                # collect them, and they're optional anyway).
                continue

            if env_var in have and have[env_var]:
                result["satisfied"].append({**dep, "category": category})
            elif category == "carrier":
                result["missing_carrier"].append(dep)
            else:
                result["missing_functional"].append(dep)

    return result


def generate_env_plan(
    slug: str,
    diff_result: dict,
    blocked: bool = False,
) -> str:
    """Generate environment-plan.md content from diff results.

    Args:
        slug: Project slug
        diff_result: Output from diff_credentials()
        blocked: Whether the project is blocked due to missing carrier deps

    Returns:
        Markdown content for environment-plan.md
    """
    lines = [
        f"# Environment Plan: {slug}",
        "",
    ]

    if blocked:
        lines.append("**Status: BLOCKED** — missing required carrier dependencies")
        lines.append("")

    # Satisfied credentials
    if diff_result["satisfied"]:
        lines.append("## Satisfied Dependencies")
        lines.append("")
        for dep in diff_result["satisfied"]:
            lines.append(
                f"- ✅ `{dep.get('env_var', 'N/A')}` — {dep['name']} ({dep['category']})"
            )
        lines.append("")

    # Missing carrier (blockers)
    if diff_result["missing_carrier"]:
        lines.append("## Missing Carrier Dependencies (REQUIRED)")
        lines.append("")
        for dep in diff_result["missing_carrier"]:
            status = "❌" if blocked else "✅"
            lines.append(
                f"- {status} `{dep.get('env_var', 'N/A')}` — {dep['name']}"
            )
            if dep.get("obtain"):
                lines.append(f"  - Obtain: {dep['obtain']}")
        lines.append("")

    # Missing functional (skippable)
    if diff_result["missing_functional"]:
        lines.append("## Missing Functional Dependencies (skipped)")
        lines.append("")
        for dep in diff_result["missing_functional"]:
            lines.append(
                f"- ⏭️ `{dep.get('env_var', 'N/A')}` — {dep['name']}"
            )
            if dep.get("skip_module"):
                lines.append(f"  - Skipped module: {dep['skip_module']}")
        lines.append("")

    return "\n".join(lines)
