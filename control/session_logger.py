"""Session logger: detailed per-session logging for debugging and diagnostics.

Each session gets:
1. A raw JSONL log file with every stream-json event + timestamps
2. A human-readable summary (.md) written on session completion

Logs are stored in workspace/logs/{session_id}/
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ToolCall:
    """Track a single tool invocation."""
    name: str
    description: str  # human-readable summary
    started_at: float  # monotonic time
    ended_at: float | None = None
    input_summary: str = ""
    output_summary: str = ""
    error: str | None = None


@dataclass
class SessionLogger:
    """Captures detailed logs for a single Claude CLI session."""

    session_id: str
    log_dir: Path
    started_at: float = field(default_factory=time.monotonic)
    started_wall: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Internal state
    _jsonl_path: Path = field(init=False)
    _tool_calls: list[ToolCall] = field(default_factory=list)
    _current_tool: ToolCall | None = field(default=None)
    _text_chunks: list[str] = field(default_factory=list)
    _event_count: int = field(default=0)
    _last_event_time: float = field(default=0.0)
    _last_event_type: str = field(default="")
    _longest_gap: tuple[float, str, str] = field(default=(0.0, "", ""))  # (gap_seconds, before_event, after_event)
    _sub_agents: list[str] = field(default_factory=list)
    _errors: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self.log_dir / f"{self.session_id}.jsonl"
        self._last_event_time = self.started_at
        # Write header
        self._write_jsonl({
            "log_event": "session_start",
            "session_id": self.session_id,
            "wall_time": self.started_wall,
        })

    def record_event(self, raw_line: str, parsed: dict | None) -> None:
        """Record a single stream-json event."""
        now = time.monotonic()
        self._event_count += 1

        # Track gaps between events
        gap = now - self._last_event_time
        etype = parsed.get("type", "unknown") if parsed else "unparseable"
        if gap > self._longest_gap[0]:
            self._longest_gap = (gap, self._last_event_type, etype)
        self._last_event_time = now
        self._last_event_type = etype

        # Write raw event to JSONL
        self._write_jsonl({
            "t": round(now - self.started_at, 2),
            "type": etype,
            "raw": raw_line[:2000],  # cap line length
        })

        if not parsed:
            return

        # Process specific event types
        if etype == "content_block_start":
            self._handle_block_start(parsed, now)
        elif etype == "content_block_stop":
            self._handle_block_stop(now)
        elif etype == "content_block_delta":
            self._handle_delta(parsed)
        elif etype == "result":
            self._handle_result(parsed)
        elif etype == "error":
            self._handle_error(parsed, now)

    def record_timeout(self, timeout_seconds: int) -> None:
        """Record that the session timed out."""
        now = time.monotonic()
        elapsed = now - self.started_at

        context = {
            "log_event": "timeout",
            "elapsed_seconds": round(elapsed, 1),
            "timeout_limit": timeout_seconds,
            "total_events": self._event_count,
            "last_event_type": self._last_event_type,
            "seconds_since_last_event": round(now - self._last_event_time, 1),
        }

        # What was the session doing when it timed out?
        if self._current_tool:
            context["stuck_on_tool"] = self._current_tool.name
            context["stuck_tool_description"] = self._current_tool.description
            context["stuck_tool_duration"] = round(now - self._current_tool.started_at, 1)
        elif self._text_chunks:
            context["was_generating_text"] = True
            context["last_text_snippet"] = "".join(self._text_chunks[-5:])[:200]

        self._write_jsonl(context)

    def record_exit(self, status: str, error: str | None = None, duration: float = 0.0) -> None:
        """Record session exit and write the summary."""
        self._write_jsonl({
            "log_event": "session_exit",
            "status": status,
            "error": error,
            "duration_seconds": round(duration, 1),
            "total_events": self._event_count,
        })

    def write_summary(self, status: str, error: str | None = None, duration: float = 0.0) -> Path:
        """Write a human-readable summary markdown file. Returns the path."""
        summary_path = self.log_dir / f"{self.session_id}-summary.md"

        lines = [
            f"# Session Log: {self.session_id}",
            "",
            f"- **Status**: {status}",
            f"- **Started**: {self.started_wall}",
            f"- **Duration**: {duration:.1f}s",
            f"- **Total Events**: {self._event_count}",
            "",
        ]

        if error:
            lines.extend([
                "## Error",
                "",
                f"```\n{error}\n```",
                "",
            ])

        # Timeout diagnosis
        if status == "TIMEOUT":
            gap_sec, before, after = self._longest_gap
            lines.extend([
                "## Timeout Diagnosis",
                "",
            ])
            if self._current_tool:
                lines.append(
                    f"- **Stuck on tool**: `{self._current_tool.name}` "
                    f"(running for {duration - (self._current_tool.started_at - self.started_at):.0f}s)"
                )
                if self._current_tool.input_summary:
                    lines.append(f"- **Tool input**: {self._current_tool.input_summary}")
            lines.extend([
                f"- **Longest gap between events**: {gap_sec:.1f}s (between `{before}` → `{after}`)",
                f"- **Seconds since last event at timeout**: {duration - (self._last_event_time - self.started_at):.1f}s",
                "",
            ])

        # Tool call timeline
        if self._tool_calls:
            lines.extend([
                "## Tool Call Timeline",
                "",
                "| # | Tool | Description | Duration | Status |",
                "|---|------|-------------|----------|--------|",
            ])
            for i, tc in enumerate(self._tool_calls, 1):
                dur = ""
                if tc.ended_at is not None:
                    dur = f"{tc.ended_at - tc.started_at:.1f}s"
                elif status == "TIMEOUT":
                    dur = f"{duration - (tc.started_at - self.started_at):.1f}s (running)"
                tc_status = "error" if tc.error else ("running" if tc.ended_at is None else "ok")
                desc = tc.description[:60]
                lines.append(f"| {i} | `{tc.name}` | {desc} | {dur} | {tc_status} |")
            lines.append("")

        # Sub-agents
        if self._sub_agents:
            lines.extend([
                "## Sub-agents Spawned",
                "",
            ])
            for desc in self._sub_agents:
                lines.append(f"- {desc}")
            lines.append("")

        # Errors
        if self._errors:
            lines.extend([
                "## Errors Encountered",
                "",
            ])
            for err in self._errors:
                t = err.get("t", "?")
                msg = err.get("message", "unknown")
                lines.append(f"- **t={t}s**: {msg}")
            lines.append("")

        # Stats
        tool_names: dict[str, int] = {}
        for tc in self._tool_calls:
            tool_names[tc.name] = tool_names.get(tc.name, 0) + 1
        if tool_names:
            lines.extend([
                "## Tool Usage Summary",
                "",
            ])
            for name, count in sorted(tool_names.items(), key=lambda x: -x[1]):
                lines.append(f"- `{name}`: {count} calls")
            lines.append("")

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        return summary_path

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _handle_block_start(self, event: dict, now: float) -> None:
        cb = event.get("content_block", {})
        if cb.get("type") == "tool_use":
            tool_name = cb.get("name", "unknown")
            input_data = cb.get("input", {})
            desc = self._describe_tool(tool_name, input_data)
            input_summary = self._summarize_input(tool_name, input_data)

            tc = ToolCall(
                name=tool_name,
                description=desc,
                started_at=now,
                input_summary=input_summary,
            )
            self._tool_calls.append(tc)
            self._current_tool = tc

            if tool_name == "Agent":
                self._sub_agents.append(desc)
        elif cb.get("type") == "text":
            self._text_chunks = []

    def _handle_block_stop(self, now: float) -> None:
        if self._current_tool and self._current_tool.ended_at is None:
            self._current_tool.ended_at = now
            self._current_tool = None

    def _handle_delta(self, event: dict) -> None:
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            self._text_chunks.append(text)

    def _handle_result(self, event: dict) -> None:
        # Close any open tool
        if self._current_tool and self._current_tool.ended_at is None:
            self._current_tool.ended_at = time.monotonic()
            self._current_tool = None

    def _handle_error(self, event: dict, now: float) -> None:
        error_info = event.get("error", {})
        msg = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
        self._errors.append({
            "t": round(now - self.started_at, 1),
            "message": msg[:500],
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _describe_tool(self, name: str, input_data: dict) -> str:
        """Human-readable one-liner for a tool call."""
        if name == "WebSearch":
            return f"Search: {input_data.get('query', '?')}"
        elif name == "WebFetch":
            url = input_data.get("url", "?")
            return f"Fetch: {url[:80]}"
        elif name == "Write":
            path = input_data.get("file_path", "?")
            return f"Write: {Path(path).name}"
        elif name == "Read":
            path = input_data.get("file_path", "?")
            return f"Read: {Path(path).name}"
        elif name == "Agent":
            return f"Agent: {input_data.get('description', '?')}"
        elif name == "Bash":
            cmd = input_data.get("command", "?")
            return f"Bash: {cmd[:80]}"
        elif name == "Glob":
            return f"Glob: {input_data.get('pattern', '?')}"
        elif name == "Grep":
            return f"Grep: {input_data.get('pattern', '?')}"
        elif name == "Edit":
            path = input_data.get("file_path", "?")
            return f"Edit: {Path(path).name}"
        return f"{name}"

    def _summarize_input(self, name: str, input_data: dict) -> str:
        """Short summary of tool input for diagnosis."""
        if name == "WebSearch":
            return input_data.get("query", "")
        elif name == "WebFetch":
            return input_data.get("url", "")[:100]
        elif name in ("Write", "Read", "Edit"):
            return input_data.get("file_path", "")
        elif name == "Agent":
            return input_data.get("description", "")
        elif name == "Bash":
            return input_data.get("command", "")[:100]
        return json.dumps(input_data, ensure_ascii=False)[:100]

    def _write_jsonl(self, data: dict) -> None:
        """Append a line to the JSONL log file."""
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
