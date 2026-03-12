"""Stage 0: Prompt Interpreter — parse raw hackathon prompt into structured brief."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, HackathonBrief, SessionConfig, SessionStatus
from control.session_manager import PROJECT_ROOT, SessionManager

logger = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "stage0"
WORKSPACE_DIR = PROJECT_ROOT / "workspace" / "stage0"


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    """Simple variable replacement for stage0 prompts."""
    for key, value in kwargs.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def _extract_text_from_stream_json(raw_output: str) -> str:
    """Extract assistant text from stream-json output."""
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


def _extract_json_object(text: str) -> dict | None:
    """Extract a JSON object from text, handling markdown fences."""
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()

    start = text.find('{')
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
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict) and "theme" in data:
                        return data
                except json.JSONDecodeError:
                    return None
    return None


async def run_stage0(
    raw_prompt: str,
    session_mgr: SessionManager,
    event_bus: EventBus,
    model: str = "sonnet",
) -> HackathonBrief:
    """Execute Stage 0: Parse raw hackathon prompt into structured brief."""

    await event_bus.emit(Event(type="stage_started", data={"stage": 0, "theme": "(interpreting prompt)"}))

    work_dir = WORKSPACE_DIR / "interpreter"
    work_dir.mkdir(parents=True, exist_ok=True)

    prompt = _render(_read_prompt("interpreter.md"), raw_prompt=raw_prompt)

    result = await session_mgr.run_session(SessionConfig(
        session_id="prompt-interpreter",
        prompt=prompt,
        working_dir=str(work_dir),
        allowed_tools=["Read", "Write"],
        model=model,
        timeout_seconds=240,
        max_budget_usd=0.5,
    ))

    if result.status != SessionStatus.COMPLETED:
        raise RuntimeError(f"Prompt interpreter failed: {result.error}")

    # Parse JSON output
    text = _extract_text_from_stream_json(result.output)
    data = _extract_json_object(text) if text else None

    if not data:
        data = _extract_json_object(result.output)

    if not data:
        raise ValueError(
            f"Could not parse structured brief from interpreter output. "
            f"Output length: {len(result.output)}"
        )

    # Preserve the original raw prompt
    data["raw_prompt"] = raw_prompt

    brief = HackathonBrief.from_dict(data)

    logger.info("Interpreted hackathon brief: theme=%s", brief.theme)
    if brief.constraints:
        logger.info("  Constraints: %s", brief.constraints)
    if brief.restrictions:
        logger.info("  Restrictions: %s", brief.restrictions)

    await event_bus.emit(Event(
        type="stage_completed",
        data={
            "stage": 0,
            "theme": brief.theme,
            "constraints_count": len(brief.constraints),
            "criteria_count": len(brief.evaluation_criteria),
        },
    ))

    return brief
