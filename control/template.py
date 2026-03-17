"""Shared template rendering, prompt loading, and stream parsing utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path


def read_prompt(prompts_dir: Path, name: str) -> str:
    """Read a prompt file from the given directory."""
    return (prompts_dir / name).read_text(encoding="utf-8")


def render(template: str, **kwargs: str) -> str:
    """Simple mustache-like template rendering.

    Supports {{var}} replacement and {{#var}}...{{/var}} conditional blocks.
    If value is truthy, the block content is kept; otherwise the block is removed.
    """
    # Handle conditional blocks first
    for key, value in kwargs.items():
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


def extract_text_from_stream_json(raw_output: str) -> str:
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
