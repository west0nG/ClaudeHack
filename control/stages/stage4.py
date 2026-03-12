"""Stage 4: Publish — push demo projects to GitHub as individual repos.

Purely deterministic git/gh operations, no AI session needed.
Each successful project gets: standardized README, git init, gh repo create + push.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event
from control.session_manager import PROJECT_ROOT

logger = logging.getLogger(__name__)

STAGE2_OUTPUT_DIR = PROJECT_ROOT / "workspace" / "stage2" / "output"


def _extract_project_name(concept_path: Path) -> str:
    """Extract project name from concept.md title line."""
    text = concept_path.read_text(encoding="utf-8")
    match = re.search(r"^#\s+(?:Product Concept:\s*)?(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return concept_path.parent.name.replace("-", " ").title()


def _extract_section(text: str, heading: str) -> str:
    """Extract content under a markdown heading (## level)."""
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _slugify_project_name(name: str) -> str:
    """Convert a project name to a GitHub-friendly slug."""
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "project"


def _find_prd_dir_for_project(project_dir: Path) -> Path | None:
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


def _generate_readme(project_name: str, concept_text: str, technical_text: str, publish_mode: str = "test") -> str:
    """Generate a standardized README.md from PRD documents."""
    # Extract sections from concept.md
    problem = _extract_section(concept_text, "Pain Point")
    if not problem:
        problem = _extract_section(concept_text, "Problem")
    if not problem:
        problem = _extract_section(concept_text, "Core Pain Point")

    solution = _extract_section(concept_text, "Value Proposition")
    if not solution:
        solution = _extract_section(concept_text, "Solution")
    if not solution:
        solution = _extract_section(concept_text, "Core Value Proposition")

    product_def = _extract_section(concept_text, "Product Definition")
    if not product_def:
        product_def = _extract_section(concept_text, "Product Concept")

    # One-liner: first sentence of product definition or solution
    one_liner = ""
    source = product_def or solution
    if source:
        first_line = source.split("\n")[0].strip().lstrip("- ")
        one_liner = first_line[:200]

    # Extract tech stack from technical.md
    tech_stack = _extract_section(technical_text, "Tech Stack")
    if not tech_stack:
        tech_stack = _extract_section(technical_text, "Technology Stack")
    if not tech_stack:
        tech_stack = _extract_section(technical_text, "Technology")

    # Extract project structure
    project_structure = _extract_section(technical_text, "Project Architecture")
    if not project_structure:
        project_structure = _extract_section(technical_text, "Project Structure")

    lines = [f"# {project_name}", ""]

    if publish_mode == "test":
        lines += ["> Built by Hackathon Agents", ""]

    if one_liner:
        lines += ["## What is this?", "", one_liner, ""]

    if problem:
        lines += ["## The Problem", "", problem, ""]

    if solution:
        lines += ["## Solution", "", solution, ""]

    if tech_stack:
        lines += ["## Tech Stack", "", tech_stack, ""]

    lines += [
        "## Getting Started",
        "",
        "```bash",
        "npm install",
        "npm run dev",
        "```",
        "",
    ]

    if project_structure:
        lines += ["## Project Structure", "", project_structure, ""]

    if publish_mode == "test":
        lines += [
            "---",
            "",
            "*This project was built autonomously by Hackathon Agents — "
            "an AI system that discovers problems, designs products, and builds demos "
            "without human intervention.*",
            "",
        ]

    return "\n".join(lines)


async def _run_cmd(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr).

    Uses create_subprocess_exec (not shell) to avoid injection.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


def _ensure_gitignore(project_dir: Path) -> None:
    """Ensure a .gitignore exists that excludes node_modules and common build artifacts."""
    gitignore_path = project_dir / ".gitignore"
    needed_entries = {"node_modules/", "dist/", ".env", ".DS_Store"}

    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        existing_lines = {line.strip() for line in existing.splitlines()}
        missing = needed_entries - existing_lines
        if missing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n")
                for entry in sorted(missing):
                    f.write(f"{entry}\n")
    else:
        gitignore_path.write_text(
            "\n".join(sorted(needed_entries)) + "\n",
            encoding="utf-8",
        )


async def _publish_project(
    project_dir: Path,
    prd_dir: Path | None,
    event_bus: EventBus,
    private: bool = False,
    repo_slug_override: str | None = None,
    publish_mode: str = "test",
) -> str | None:
    """Publish a single project to GitHub.

    Returns the repo URL on success, or None on failure.
    """
    # Determine project name
    if prd_dir and (prd_dir / "concept.md").exists():
        project_name = _extract_project_name(prd_dir / "concept.md")
    else:
        project_name = project_dir.parent.parent.name.replace("-", " ").title()

    slug = repo_slug_override or _slugify_project_name(project_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    repo_name = f"hg-{slug}-{timestamp}" if publish_mode == "test" else slug

    await event_bus.emit(Event(
        type="publish_started",
        data={"project_dir": str(project_dir), "repo_name": repo_name},
    ))

    # Generate standardized README
    if prd_dir:
        concept_text = ""
        technical_text = ""
        concept_file = prd_dir / "concept.md"
        technical_file = prd_dir / "technical.md"
        if concept_file.exists():
            concept_text = concept_file.read_text(encoding="utf-8")
        if technical_file.exists():
            technical_text = technical_file.read_text(encoding="utf-8")

        readme_content = _generate_readme(project_name, concept_text, technical_text, publish_mode=publish_mode)
    else:
        if publish_mode == "test":
            readme_content = (
                f"# {project_name}\n\n"
                "> Built by Hackathon Agents\n\n"
                "## Getting Started\n\n"
                "```bash\nnpm install\nnpm run dev\n```\n\n"
                "---\n\n"
                "*This project was built autonomously by Hackathon Agents.*\n"
            )
        else:
            readme_content = (
                f"# {project_name}\n\n"
                "## Getting Started\n\n"
                "```bash\nnpm install\nnpm run dev\n```\n"
            )

    # Write README.md
    readme_path = project_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")

    # Remove node_modules/ before git operations — it's reproducible via npm install
    # and can contain 100k+ files that slow down git add even when gitignored.
    node_modules = project_dir / "node_modules"
    if node_modules.is_dir():
        shutil.rmtree(node_modules)

    # Ensure .gitignore exists before committing (prevents build artifacts in repo)
    _ensure_gitignore(project_dir)

    # Git init + commit
    rc, _, err = await _run_cmd(["git", "init"], cwd=project_dir)
    if rc != 0:
        logger.error("git init failed for %s: %s", repo_name, err)
        await event_bus.emit(Event(
            type="publish_failed",
            data={"repo_name": repo_name, "error": f"git init failed: {err}"},
        ))
        return None

    # Ensure git identity is set (local to this repo, won't affect global config)
    rc_name, _, _ = await _run_cmd(["git", "config", "user.name"], cwd=project_dir)
    if rc_name != 0:
        # In use mode, query gh for the authenticated user's identity
        fallback_name = "Hackathon Agent"
        fallback_email = "hackathon-agent@noreply.github.com"
        if publish_mode == "use":
            rc_gh, gh_out, _ = await _run_cmd(
                ["gh", "api", "user", "-q", ".login"],
            )
            if rc_gh == 0 and gh_out.strip():
                gh_login = gh_out.strip()
                fallback_name = gh_login
                fallback_email = f"{gh_login}@users.noreply.github.com"
        await _run_cmd(
            ["git", "config", "user.name", fallback_name], cwd=project_dir
        )
        await _run_cmd(
            ["git", "config", "user.email", fallback_email], cwd=project_dir,
        )

    rc, _, err = await _run_cmd(["git", "add", "-A"], cwd=project_dir)
    if rc != 0:
        logger.error("git add failed for %s: %s", repo_name, err)
        await event_bus.emit(Event(
            type="publish_failed",
            data={"repo_name": repo_name, "error": f"git add failed: {err}"},
        ))
        return None

    rc, _, err = await _run_cmd(
        ["git", "commit", "-m", f"Initial commit: {project_name}"],
        cwd=project_dir,
    )
    if rc != 0:
        logger.error("git commit failed for %s: %s", repo_name, err)
        await event_bus.emit(Event(
            type="publish_failed",
            data={"repo_name": repo_name, "error": f"git commit failed: {err}"},
        ))
        return None

    # Create GitHub repo + push
    visibility = "--private" if private else "--public"
    rc, stdout, err = await _run_cmd(
        ["gh", "repo", "create", repo_name, visibility, "--source", ".", "--push"],
        cwd=project_dir,
    )
    if rc != 0:
        logger.error("gh repo create failed for %s: %s", repo_name, err)
        await event_bus.emit(Event(
            type="publish_failed",
            data={"repo_name": repo_name, "error": f"gh repo create failed: {err}"},
        ))
        return None

    # Extract repo URL from gh output
    repo_url = stdout.strip()
    if not repo_url.startswith("http"):
        # Fallback: query gh for the actual repo URL
        rc2, url_out, _ = await _run_cmd(
            ["gh", "repo", "view", repo_name, "--json", "url", "-q", ".url"],
            cwd=project_dir,
        )
        repo_url = url_out.strip() if rc2 == 0 and url_out.strip() else f"https://github.com/{repo_name}"

    logger.info("Published %s -> %s", project_name, repo_url)
    await event_bus.emit(Event(
        type="publish_completed",
        data={"repo_name": repo_name, "repo_url": repo_url, "project_dir": str(project_dir)},
    ))
    return repo_url


async def run_stage4(
    project_dirs: list[Path],
    event_bus: EventBus,
    private: bool = False,
    prd_dirs: list[Path] | None = None,
    publish_mode: str = "test",
) -> list[str]:
    """Execute Stage 4: Publish demo projects to GitHub.

    Args:
        project_dirs: List of successful demo/ project directories from Stage 3.
        event_bus: Event bus for publishing progress events.
        private: If True, create private repos instead of public.
        prd_dirs: Optional explicit list of PRD directories (parallel to project_dirs).
                  When provided, used directly for README generation.
                  When None, auto-discovers from workspace/stage2/output/.

    Returns:
        List of published repo URLs.
    """
    await event_bus.emit(Event(
        type="stage_started",
        data={"stage": 4, "projects": len(project_dirs)},
    ))

    # Deduplicate repo names to avoid collision
    used_names: dict[str, int] = {}

    # Publish all projects in parallel
    tasks = []
    for i, project_dir in enumerate(project_dirs):
        if prd_dirs and i < len(prd_dirs):
            prd_dir = prd_dirs[i]
        else:
            prd_dir = _find_prd_dir_for_project(project_dir)

        # Pre-compute repo name to detect collisions
        if prd_dir and (prd_dir / "concept.md").exists():
            name = _extract_project_name(prd_dir / "concept.md")
        else:
            name = project_dir.parent.parent.name.replace("-", " ").title()
        slug = _slugify_project_name(name)
        if slug in used_names:
            used_names[slug] += 1
            slug = f"{slug}-{used_names[slug]}"
        else:
            used_names[slug] = 0

        tasks.append(_publish_project(
            project_dir, prd_dir, event_bus, private=private,
            repo_slug_override=slug, publish_mode=publish_mode,
        ))

    logger.info("Stage 4: Publishing %d projects to GitHub", len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    repo_urls: list[str] = []
    failed_count = 0
    for r in results:
        if isinstance(r, BaseException):
            logger.error("Publish raised exception: %s", r, exc_info=r)
            failed_count += 1
        elif r is None:
            failed_count += 1
        else:
            repo_urls.append(r)

    logger.info(
        "Stage 4 complete: %d published, %d failed",
        len(repo_urls), failed_count,
    )

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 4,
            "published": len(repo_urls),
            "failed": failed_count,
            "repos": repo_urls,
        },
    ))

    return repo_urls
