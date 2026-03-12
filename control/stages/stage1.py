"""Stage 1: Idea Discovery — from theme to Idea Cards."""

from __future__ import annotations

import asyncio
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


def _extract_json_array(text: str, require_dicts: bool = True) -> list | None:
    """Extract a JSON array from text, handling markdown fences and nested brackets.

    Args:
        require_dicts: If True (default), only return arrays of dicts.
            If False, return any valid JSON array (including arrays of strings).
    """
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
                    if isinstance(data, list) and len(data) > 0:
                        if not require_dicts or isinstance(data[0], dict):
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
            scope=item.get("scope", "broad"),
            likely_product_types=item.get("likely_product_types", []),
            pain_areas=item.get("pain_areas", []),
        ))
    return directions


def _card_title_summary(card_path: Path) -> str:
    """Extract title and first meaningful paragraph from an idea card for dedup comparison."""
    text = card_path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    title = ""
    summary_lines = []
    in_scenario = False
    for line in lines:
        if line.startswith("# Idea Card:"):
            title = line.replace("# Idea Card:", "").strip()
        elif line.strip() == "## Specific Scenario":
            in_scenario = True
        elif in_scenario and line.startswith("## "):
            break
        elif in_scenario and line.strip():
            summary_lines.append(line.strip())
    summary = " ".join(summary_lines[:3])  # First 3 non-empty lines of scenario
    return f"**{title}**: {summary}" if title else summary


async def _stream_dedup_compare(
    new_cards: list[Path],
    existing_pool: list[Path],
    session_mgr: SessionManager,
) -> list[Path]:
    """Compare new cards against existing pool for obvious duplicates.

    Uses a lightweight claude -p call. Returns cards to keep (non-duplicates).
    """
    if not existing_pool:
        return new_cards

    # Build context: new card full text + existing card title/summaries
    new_texts = []
    for card in new_cards:
        new_texts.append(f"--- NEW CARD: {card.name} ---\n{card.read_text(encoding='utf-8')}\n")

    existing_summaries = []
    for card in existing_pool:
        existing_summaries.append(f"- {card.name}: {_card_title_summary(card)}")

    prompt = f"""You are a dedup checker. Compare these NEW cards against the EXISTING card pool.

## Existing Cards (title + summary only)

{chr(10).join(existing_summaries)}

## New Cards (full text)

{chr(10).join(new_texts)}

## Task

For each new card, determine if it is an obvious duplicate of any existing card.
Two cards are duplicates if they address essentially the same pain point for essentially the same persona.
Be CONSERVATIVE — only flag obvious duplicates. If in doubt, keep both.

Output a JSON array of new card filenames to KEEP (non-duplicates):
["card-a.md", "card-b.md"]

If all new cards should be kept, output all their filenames.
If a new card is a duplicate, omit its filename from the array.
Output ONLY the JSON array, nothing else."""

    dedup_dir = WORKSPACE_DIR / "stream-dedup"
    dedup_dir.mkdir(parents=True, exist_ok=True)

    result = await session_mgr.run_session(SessionConfig(
        session_id=f"stream-dedup-{len(existing_pool)}",
        prompt=prompt,
        working_dir=str(dedup_dir),
        allowed_tools=["Read"],
        model="sonnet",
        timeout_seconds=120,
        max_budget_usd=0.5,
        max_retries=0,
    ))

    if result.status != SessionStatus.COMPLETED:
        logger.warning("Stream dedup failed, keeping all new cards: %s", result.error)
        return new_cards

    # Parse the response to get list of filenames to keep
    text = _extract_text_from_stream_json(result.output) or result.output
    keep_names: set[str] = set()

    # Extract JSON array of filenames (strings, not dicts)
    data = _extract_json_array(text, require_dicts=False)

    if data and isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                keep_names.add(item)
            elif isinstance(item, dict) and "name" in item:
                keep_names.add(item["name"])

    if not keep_names:
        # Couldn't parse response, keep all cards to be safe
        logger.warning("Could not parse stream dedup response, keeping all new cards")
        return new_cards

    kept = [c for c in new_cards if c.name in keep_names]

    # Safety: if LLM returned filenames that don't match any actual card names,
    # kept could be empty even though keep_names isn't. Fall back to keeping all.
    if not kept and new_cards:
        logger.warning(
            "Stream dedup returned filenames that don't match actual cards "
            "(expected: %s, got: %s) — keeping all new cards",
            [c.name for c in new_cards], keep_names,
        )
        return new_cards

    dropped = len(new_cards) - len(kept)
    if dropped > 0:
        logger.info("Stream dedup dropped %d duplicate cards", dropped)

    return kept


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
        allowed_tools=["Read", "Write", "WebSearch"],
        model="sonnet",
        timeout_seconds=360,
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
    # Step 2: Research sessions — one per direction, with streaming dedup
    # ------------------------------------------------------------------
    logger.info("Stage 1 Step 2: Launching %d research sessions", len(directions))

    # Build research configs
    research_template = _read_prompt("research.md")
    research_tasks: list[tuple[CrowdDirection, SessionConfig]] = []

    for d in directions:
        # Determine scope-based conditional blocks
        scope_broad = "true" if d.scope == "broad" else ""
        scope_focused = "true" if d.scope != "broad" else ""

        research_prompt = _render(
            research_template,
            theme=theme,
            persona=d.persona,
            pain_areas="\n".join(f"- {pa}" for pa in d.pain_areas),
            hackathon_context=hackathon_context,
            scope=d.scope,
            scope_broad=scope_broad,
            scope_focused=scope_focused,
        )
        config = SessionConfig(
            session_id=f"research-{d.slug}",
            prompt=research_prompt,
            working_dir=str(WORKSPACE_DIR / f"research-{d.slug}"),
            allowed_tools=["WebSearch", "WebFetch", "Agent", "Read", "Write", "Glob", "Grep"],
            model="sonnet",
            max_budget_usd=5.0,
            timeout_seconds=1800,
        )
        research_tasks.append((d, config))

    # Launch research sessions and process results as they complete (streaming dedup)
    card_pool: list[Path] = []
    card_pool_lock = asyncio.Lock()

    async def run_and_dedup(direction: CrowdDirection, config: SessionConfig) -> SessionResult:
        """Run a research session and stream-dedup its cards into the pool."""
        result = await session_mgr.run_session(config)

        if result.status != SessionStatus.COMPLETED or not result.working_dir:
            return result

        # Collect cards from this session
        work_dir = Path(result.working_dir)
        new_cards = list(work_dir.rglob("idea-card-*.md"))

        if not new_cards:
            return result

        # Read existing pool under lock, then release before running dedup session
        async with card_pool_lock:
            existing_pool = list(card_pool) if card_pool else []

        if not existing_pool:
            # First batch — no dedup needed
            async with card_pool_lock:
                card_pool.extend(new_cards)
            logger.info("Added %d initial cards to pool from %s", len(new_cards), config.session_id)
        else:
            # Compare against existing pool (outside lock to avoid blocking)
            kept = await _stream_dedup_compare(new_cards, existing_pool, session_mgr)
            async with card_pool_lock:
                card_pool.extend(kept)
            logger.info(
                "Added %d/%d cards to pool from %s (after stream dedup)",
                len(kept), len(new_cards), config.session_id,
            )

        return result

    # Use asyncio.gather with semaphore handled by SessionManager
    research_coros = [run_and_dedup(d, cfg) for d, cfg in research_tasks]
    research_results = await asyncio.gather(*research_coros, return_exceptions=True)

    # Log research results
    completed = sum(1 for r in research_results if isinstance(r, SessionResult) and r.status == SessionStatus.COMPLETED)
    failed = sum(1 for r in research_results if isinstance(r, Exception) or (isinstance(r, SessionResult) and r.status == SessionStatus.FAILED))
    logger.info("Research done: %d completed, %d failed", completed, failed)

    # ------------------------------------------------------------------
    # Step 3: Final review (replaces old batch Dedup)
    # ------------------------------------------------------------------
    logger.info("Card pool has %d cards after streaming dedup", len(card_pool))

    if not card_pool:
        logger.warning("No idea cards produced! Stage 1 ending with empty result.")
        await event_bus.emit(Event(type="stage_completed", data={"stage": 1, "cards": 0}))
        return []

    # Skip final review when few cards
    if len(card_pool) <= 3:
        logger.info("Only %d cards — skipping final review, copying directly to output", len(card_pool))
        for card in card_pool:
            dest = output_dir / card.name
            if dest.exists():
                prefix = card.parent.name
                dest = output_dir / f"{prefix}-{card.name}"
            shutil.copy2(card, dest)
    else:
        # Copy all cards to dedup input directory for final review
        for card in card_pool:
            dest = dedup_input_dir / card.name
            if dest.exists():
                prefix = card.parent.name
                dest = dedup_input_dir / f"{prefix}-{card.name}"
            shutil.copy2(card, dest)

        # ------------------------------------------------------------------
        # Final Review Agent (lightweight pass on pre-deduplicated pool)
        # ------------------------------------------------------------------
        logger.info("Stage 1 Step 3: Running final review on %d cards", len(card_pool))

        dedup_prompt = _read_prompt("dedup.md")
        dedup_result = await session_mgr.run_session(SessionConfig(
            session_id="final-review-agent",
            prompt=dedup_prompt,
            working_dir=str(WORKSPACE_DIR / "dedup"),
            allowed_tools=["Read", "Write", "Glob"],
            model="sonnet",
            timeout_seconds=600,
            max_budget_usd=1.0,
        ))

        if dedup_result.status != SessionStatus.COMPLETED:
            logger.warning("Final review agent failed: %s — using stream-deduplicated cards instead", dedup_result.error)
            # Fallback: copy pool cards to output
            for card in card_pool:
                dest = output_dir / card.name
                if not dest.exists():
                    shutil.copy2(card, dest)

    # ------------------------------------------------------------------
    # Step 4: Collect final output
    # ------------------------------------------------------------------
    final_cards = sorted(output_dir.glob("idea-card-*.md"))
    logger.info("Stage 1 complete: %d final idea cards", len(final_cards))

    await event_bus.emit(Event(
        type="stage_completed",
        data={"stage": 1, "cards": len(final_cards)},
    ))

    return final_cards
