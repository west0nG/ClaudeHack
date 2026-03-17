"""Centralized path constants for the Hackathon Agent control plane."""

from pathlib import Path

# Project root — single source of truth for all modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Workspace directories
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
STAGE2_OUTPUT_DIR = WORKSPACE_DIR / "stage2" / "output"
STAGE2_5_DIR = WORKSPACE_DIR / "stage2.5"

# Persistent credential store
PERSISTENT_CREDS_PATH = PROJECT_ROOT / "credentials.env"

# Logs
LOGS_DIR = WORKSPACE_DIR / "logs"


def find_prd_dir_for_project(project_dir: Path) -> Path | None:
    """Find the corresponding Stage 2 output directory for a project.

    project_dir is typically workspace/stage3/{slug}/dev/demo/.
    The slug should match the Stage 2 output directory name.
    """
    # Walk up from demo/ -> dev/ -> {slug}/
    slug_dir = project_dir.parent.parent  # demo -> dev -> {slug}
    slug = slug_dir.name

    prd_dir = STAGE2_OUTPUT_DIR / slug
    if prd_dir.is_dir() and (prd_dir / "concept.md").exists():
        return prd_dir

    # Fallback: scan stage2/output for matching slug
    if STAGE2_OUTPUT_DIR.is_dir():
        for d in STAGE2_OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name == slug and (d / "concept.md").exists():
                return d

    return None
