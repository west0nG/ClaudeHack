"""Data models for Hackathon Agent control plane."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class StageStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class SessionConfig:
    session_id: str
    prompt: str
    system_prompt: str | None = None
    working_dir: str | None = None
    allowed_tools: list[str] | None = None
    max_budget_usd: float | None = None
    model: str = "sonnet"
    timeout_seconds: int = 600
    max_retries: int = 1


@dataclass
class SessionResult:
    session_id: str
    status: SessionStatus
    output: str = ""
    working_dir: str | None = None
    output_files: list[str] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class Event:
    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class CrowdDirection:
    slug: str
    persona: str
    relevance: str
    pain_areas: list[str]
