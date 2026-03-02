"""Session manager: launches and monitors Claude Code CLI subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from control.event_bus import EventBus
from control.models import Event, SessionConfig, SessionResult, SessionStatus

logger = logging.getLogger(__name__)

# Project root — used to resolve relative working dirs
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SessionManager:
    def __init__(self, max_concurrent: int = 5, event_bus: EventBus | None = None) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._event_bus = event_bus or EventBus()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_session(self, config: SessionConfig) -> SessionResult:
        """Run a single Claude Code CLI session with retry."""
        last_error: str | None = None
        for attempt in range(config.max_retries + 1):
            if attempt > 0:
                await self._emit(
                    "session_retrying",
                    {"session_id": config.session_id, "attempt": attempt + 1},
                )
            result = await self._run_once(config)
            if result.status == SessionStatus.COMPLETED:
                return result
            last_error = result.error

        # All retries exhausted
        return SessionResult(
            session_id=config.session_id,
            status=SessionStatus.FAILED,
            error=last_error or "All retries exhausted",
        )

    async def run_many(self, configs: list[SessionConfig]) -> list[SessionResult]:
        """Run multiple sessions with concurrency control."""
        tasks = [self._run_with_semaphore(cfg) for cfg in configs]
        return await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_with_semaphore(self, config: SessionConfig) -> SessionResult:
        async with self._semaphore:
            return await self.run_session(config)

    async def _run_once(self, config: SessionConfig) -> SessionResult:
        work_dir = self._resolve_working_dir(config.working_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(config)
        logger.info("[%s] Starting: %s", config.session_id, " ".join(cmd))

        await self._emit(
            "session_started",
            {"session_id": config.session_id, "model": config.model},
        )

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
            )
            try:
                stdout_lines = await asyncio.wait_for(
                    self._stream_output(proc, config.session_id),
                    timeout=config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.monotonic() - t0
                await self._emit(
                    "session_failed",
                    {"session_id": config.session_id, "error": "timeout"},
                )
                return SessionResult(
                    session_id=config.session_id,
                    status=SessionStatus.FAILED,
                    error=f"Timeout after {config.timeout_seconds}s",
                    duration_seconds=duration,
                )

            await proc.wait()
            duration = time.monotonic() - t0

            if proc.returncode != 0:
                stderr_bytes = await proc.stderr.read() if proc.stderr else b""
                err_msg = stderr_bytes.decode(errors="replace").strip()
                await self._emit(
                    "session_failed",
                    {"session_id": config.session_id, "error": err_msg[:200]},
                )
                return SessionResult(
                    session_id=config.session_id,
                    status=SessionStatus.FAILED,
                    error=err_msg or f"Exit code {proc.returncode}",
                    duration_seconds=duration,
                )

            # Collect output files
            output_files = self._collect_output_files(work_dir)
            full_output = "\n".join(stdout_lines)

            await self._emit(
                "session_completed",
                {
                    "session_id": config.session_id,
                    "duration": round(duration, 1),
                    "files": [str(f) for f in output_files],
                },
            )
            return SessionResult(
                session_id=config.session_id,
                status=SessionStatus.COMPLETED,
                output=full_output,
                working_dir=str(work_dir),
                output_files=[str(f) for f in output_files],
                duration_seconds=duration,
            )

        except Exception as exc:
            duration = time.monotonic() - t0
            await self._emit(
                "session_failed",
                {"session_id": config.session_id, "error": str(exc)[:200]},
            )
            return SessionResult(
                session_id=config.session_id,
                status=SessionStatus.FAILED,
                error=str(exc),
                duration_seconds=duration,
            )

    async def _stream_output(
        self, proc: asyncio.subprocess.Process, session_id: str
    ) -> list[str]:
        """Read stream-json lines from stdout, extract progress events."""
        lines: list[str] = []
        assert proc.stdout is not None

        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue
            lines.append(line)

            # Try to parse stream-json event
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            await self._process_stream_event(session_id, event)

        return lines

    async def _process_stream_event(self, session_id: str, event: dict) -> None:
        """Extract human-readable progress from a stream-json event."""
        etype = event.get("type", "")

        # Tool use events — extract activity summaries
        if etype == "content_block_start":
            cb = event.get("content_block", {})
            if cb.get("type") == "tool_use":
                tool_name = cb.get("name", "")
                await self._emit_tool_activity(session_id, tool_name, cb)

        # Result message — contains the final assistant text
        if etype == "result":
            result_text = ""
            # result events contain a "result" field with the text
            result_obj = event.get("result", "")
            if isinstance(result_obj, str):
                result_text = result_obj[:300]
            await self._emit(
                "session_progress",
                {"session_id": session_id, "activity": "处理完成", "detail": result_text},
            )

    async def _emit_tool_activity(self, session_id: str, tool_name: str, content_block: dict) -> None:
        """Emit a progress event based on tool usage."""
        input_data = content_block.get("input", {})
        activity = ""

        if tool_name == "WebSearch":
            query = input_data.get("query", "")
            activity = f"搜索: {query}" if query else "正在搜索..."
        elif tool_name == "WebFetch":
            url = input_data.get("url", "")
            activity = f"阅读: {url[:60]}" if url else "正在阅读网页..."
        elif tool_name == "Write":
            path = input_data.get("file_path", "")
            fname = Path(path).name if path else "?"
            activity = f"写入: {fname}"
        elif tool_name == "Agent":
            desc = input_data.get("description", "")
            activity = f"启动子代理: {desc}" if desc else "启动子代理..."
        elif tool_name == "Read":
            path = input_data.get("file_path", "")
            fname = Path(path).name if path else "?"
            activity = f"读取: {fname}"
        else:
            activity = f"工具: {tool_name}"

        if activity:
            await self._emit(
                "session_progress",
                {"session_id": session_id, "activity": activity},
            )

    def _build_command(self, config: SessionConfig) -> list[str]:
        """Build the claude CLI command."""
        cmd = ["claude", "-p", config.prompt, "--output-format", "stream-json", "--verbose"]

        if config.system_prompt:
            cmd.extend(["--system-prompt", config.system_prompt])

        cmd.extend(["--model", config.model])

        if config.max_budget_usd is not None:
            cmd.extend(["--max-budget-usd", str(config.max_budget_usd)])

        if config.allowed_tools:
            cmd.extend(["--allowedTools", " ".join(config.allowed_tools)])

        cmd.append("--dangerously-skip-permissions")

        return cmd

    def _resolve_working_dir(self, working_dir: str | None) -> Path:
        if working_dir is None:
            return PROJECT_ROOT / "workspace"
        p = Path(working_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def _collect_output_files(self, work_dir: Path) -> list[Path]:
        """Collect markdown files produced in the working directory."""
        files = []
        if work_dir.exists():
            for f in work_dir.rglob("*.md"):
                files.append(f)
        return sorted(files)

    async def _emit(self, event_type: str, data: dict) -> None:
        await self._event_bus.emit(Event(type=event_type, data=data))
