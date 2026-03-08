"""Stage 1: Idea Discovery — from theme to Idea Cards."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from control.event_bus import EventBus
from control.models import CrowdDirection, Event, HackathonBrief, SessionConfig, SessionResult, SessionStatus
from control.session_manager import PROJECT_ROOT, SessionManager

logger = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "stage1"
WORKSPACE_DIR = PROJECT_ROOT / "workspace" / "stage1"


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    """Simple mustache-like template rendering.

    Supports {{var}} replacement and {{#var}}...{{/var}} conditional blocks.
    """
    # Handle conditional blocks first
    for key, value in kwargs.items():
        # If value is truthy, keep the block content; otherwise remove it
        open_tag = "{{#" + key + "}}"
        close_tag = "{{/" + key + "}}"
        pattern = re.escape(open_tag) + r"(.*?)" + re.escape(close_tag)
        if value:
            template = re.sub(pattern, r"\1", template, flags=re.DOTALL)
        else:
            template = re.sub(pattern, "", template, flags=re.DOTALL)

    # Then replace simple variables
    for key, value in kwargs.items():
        template = template.replace("{{" + key + "}}", str(value))

    return template


def _extract_text_from_stream_json(raw_output: str) -> str:
    """Extract the full assistant text from stream-json output.

    Tries two approaches:
    1. Look for the 'result' event which contains the complete text
    2. Accumulate text from content_block_delta events
    """
    result_text = ""
    accumulated_text = ""

    for line in raw_output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "result":
            r = event.get("result", "")
            if isinstance(r, str):
                result_text = r

        elif etype == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                accumulated_text += delta.get("text", "")

    return result_text or accumulated_text


def _extract_json_array(text: str) -> list[dict] | None:
    """Extract a JSON array from text, handling markdown fences and nested brackets."""
    # Strip markdown code fences if present
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()

    # Find the outermost [...] using bracket balancing
    start = text.find('[')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    data = json.loads(candidate)
                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                        return data
                except json.JSONDecodeError:
                    return None
    return None


def _parse_directions(result: SessionResult) -> list[CrowdDirection]:
    """Parse crowd directions JSON from the main agent output."""
    raw = result.output

    # Strategy 1: extract text from stream-json, then parse JSON
    text = _extract_text_from_stream_json(raw)
    if text:
        data = _extract_json_array(text)
        if data and "slug" in data[0]:
            return _build_directions(data)

    # Strategy 2: try parsing raw output directly (in case output is plain text)
    data = _extract_json_array(raw)
    if data and "slug" in data[0]:
        return _build_directions(data)

    raise ValueError(f"Could not parse crowd directions from output. Output length: {len(raw)}")


def _build_directions(data: list[dict]) -> list[CrowdDirection]:
    """Convert parsed JSON dicts into CrowdDirection objects."""
    directions = []
    for item in data:
        directions.append(CrowdDirection(
            slug=item["slug"],
            persona=item["persona"],
            relevance=item.get("relevance", "medium"),
            pain_areas=item.get("pain_areas", []),
        ))
    return directions


def _collect_idea_cards(results: list[SessionResult]) -> list[Path]:
    """Collect all idea-card-*.md files from research session working dirs."""
    cards = []
    for r in results:
        if r.status != SessionStatus.COMPLETED or not r.working_dir:
            continue
        work_dir = Path(r.working_dir)
        for f in work_dir.rglob("idea-card-*.md"):
            cards.append(f)
    return cards


async def run_stage1(
    theme: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    interests: str | None = None,
    max_directions: int | None = None,
    brief: HackathonBrief | None = None,
) -> list[Path]:
    """Execute Stage 1: Idea Discovery. Returns paths to final Idea Cards."""

    await event_bus.emit(Event(type="stage_started", data={"stage": 1, "theme": theme}))

    # Ensure workspace dirs exist
    main_dir = WORKSPACE_DIR / "main"
    dedup_input_dir = WORKSPACE_DIR / "dedup" / "input"
    output_dir = WORKSPACE_DIR / "output"
    main_dir.mkdir(parents=True, exist_ok=True)
    dedup_input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build hackathon context block from brief (empty if simple --theme)
    hackathon_context = brief.render_context_block() if brief else ""

    # ------------------------------------------------------------------
    # Step 1: Main Agent — expand theme into crowd directions
    # ------------------------------------------------------------------
    logger.info("Stage 1 Step 1: Expanding theme into crowd directions")
    main_prompt = _render(
        _read_prompt("main.md"),
        theme=theme,
        interests=interests or "",
        hackathon_context=hackathon_context,
    )

    main_result = await session_mgr.run_session(SessionConfig(
        session_id="main-agent",
        prompt=main_prompt,
        working_dir=str(main_dir),
        allowed_tools=["Read", "Write"],
        model="sonnet",
        timeout_seconds=120,
        max_budget_usd=1.0,
    ))

    if main_result.status != SessionStatus.COMPLETED:
        raise RuntimeError(f"Main agent failed: {main_result.error}")

    directions = _parse_directions(main_result)
    logger.info("Got %d crowd directions", len(directions))

    # Apply max_directions limit (prioritize high relevance)
    if max_directions and max_directions < len(directions):
        directions.sort(key=lambda d: (d.relevance != "high", d.slug))
        directions = directions[:max_directions]
        logger.info("Limited to %d directions (max_directions=%d)", len(directions), max_directions)

    await event_bus.emit(Event(
        type="directions_found",
        data={"count": len(directions), "directions": [d.slug for d in directions]},
    ))

    # ------------------------------------------------------------------
    # Step 2: Research sessions — one per direction
    # ------------------------------------------------------------------
    logger.info("Stage 1 Step 2: Launching %d research sessions", len(directions))

    research_configs = []
    for d in directions:
        research_prompt = _render(
            _read_prompt("research.md"),
            theme=theme,
            persona=d.persona,
            pain_areas="\n".join(f"- {pa}" for pa in d.pain_areas),
            hackathon_context=hackathon_context,
        )
        research_configs.append(SessionConfig(
            session_id=f"research-{d.slug}",
            prompt=research_prompt,
            working_dir=str(WORKSPACE_DIR / f"research-{d.slug}"),
            allowed_tools=["WebSearch", "WebFetch", "Agent", "Read", "Write", "Glob", "Grep"],
            model="sonnet",
            max_budget_usd=5.0,
            timeout_seconds=900,
        ))

    research_results = await session_mgr.run_many(research_configs)

    completed = sum(1 for r in research_results if r.status == SessionStatus.COMPLETED)
    failed = sum(1 for r in research_results if r.status == SessionStatus.FAILED)
    logger.info("Research done: %d completed, %d failed", completed, failed)

    # ------------------------------------------------------------------
    # Step 3: Collect Idea Cards
    # ------------------------------------------------------------------
    all_cards = _collect_idea_cards(research_results)
    logger.info("Collected %d raw idea cards", len(all_cards))

    if not all_cards:
        logger.warning("No idea cards produced! Stage 1 ending with empty result.")
        await event_bus.emit(Event(type="stage_completed", data={"stage": 1, "cards": 0}))
        return []

    # Skip dedup when few cards (saves tokens in single/lite modes)
    if len(all_cards) <= 3:
        logger.info("Only %d cards — skipping dedup, copying directly to output", len(all_cards))
        for card in all_cards:
            dest = output_dir / card.name
            if dest.exists():
                prefix = card.parent.name
                dest = output_dir / f"{prefix}-{card.name}"
            shutil.copy2(card, dest)
    else:
        # Copy all cards to dedup input directory
        for card in all_cards:
            dest = dedup_input_dir / card.name
            # Avoid name collisions by prefixing with parent dir name
            if dest.exists():
                prefix = card.parent.name
                dest = dedup_input_dir / f"{prefix}-{card.name}"
            shutil.copy2(card, dest)

        # ------------------------------------------------------------------
        # Step 4: Dedup Agent
        # ------------------------------------------------------------------
        logger.info("Stage 1 Step 4: Running dedup agent on %d cards", len(all_cards))

        dedup_prompt = _read_prompt("dedup.md")
        dedup_result = await session_mgr.run_session(SessionConfig(
            session_id="dedup-agent",
            prompt=dedup_prompt,
            working_dir=str(WORKSPACE_DIR / "dedup"),
            allowed_tools=["Read", "Write", "Glob"],
            model="sonnet",
            timeout_seconds=300,
            max_budget_usd=1.0,
        ))

        if dedup_result.status != SessionStatus.COMPLETED:
            logger.warning("Dedup agent failed: %s — using raw cards instead", dedup_result.error)
            # Fallback: copy raw cards to output
            for card in all_cards:
                dest = output_dir / card.name
                if not dest.exists():
                    shutil.copy2(card, dest)

    # ------------------------------------------------------------------
    # Step 5: Collect final output
    # ------------------------------------------------------------------
    final_cards = sorted(output_dir.glob("idea-card-*.md"))
    logger.info("Stage 1 complete: %d final idea cards", len(final_cards))

    await event_bus.emit(Event(
        type="stage_completed",
        data={"stage": 1, "cards": len(final_cards)},
    ))

    return final_cards
