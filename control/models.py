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


@dataclass
class HackathonBrief:
    """Structured representation of a hackathon prompt."""

    theme: str
    theme_description: str = ""
    constraints: list[str] = field(default_factory=list)
    evaluation_criteria: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    special_requirements: list[str] = field(default_factory=list)
    suggested_directions: list[str] = field(default_factory=list)
    raw_prompt: str = ""
    time_limit: str | None = None
    team_size: str | None = None
    target_audience: str | None = None

    @classmethod
    def from_theme(cls, theme: str) -> "HackathonBrief":
        """Create a minimal brief from a simple --theme string."""
        return cls(theme=theme)

    @classmethod
    def from_dict(cls, data: dict) -> "HackathonBrief":
        """Parse from JSON dict returned by the interpreter session."""
        return cls(
            theme=data.get("theme", ""),
            theme_description=data.get("theme_description", ""),
            constraints=data.get("constraints", []),
            evaluation_criteria=data.get("evaluation_criteria", []),
            restrictions=data.get("restrictions", []),
            special_requirements=data.get("special_requirements", []),
            suggested_directions=data.get("suggested_directions", []),
            raw_prompt=data.get("raw_prompt", ""),
            time_limit=data.get("time_limit"),
            team_size=data.get("team_size"),
            target_audience=data.get("target_audience"),
        )

    def render_context_block(self) -> str:
        """Render constraints/criteria/restrictions as a text block for prompts."""
        lines: list[str] = []
        if self.constraints:
            lines.append("### Hard Constraints")
            for c in self.constraints:
                lines.append(f"- {c}")
            lines.append("")
        if self.evaluation_criteria:
            lines.append("### Evaluation Criteria")
            for c in self.evaluation_criteria:
                lines.append(f"- {c}")
            lines.append("")
        if self.restrictions:
            lines.append("### Restrictions")
            for r in self.restrictions:
                lines.append(f"- {r}")
            lines.append("")
        if self.special_requirements:
            lines.append("### Special Requirements / Bonus Prizes")
            for s in self.special_requirements:
                lines.append(f"- {s}")
            lines.append("")
        if self.suggested_directions:
            lines.append("### Suggested Directions (from hackathon organizers)")
            for d in self.suggested_directions:
                lines.append(f"- {d}")
            lines.append("")
        if self.time_limit:
            lines.append(f"**Time Limit**: {self.time_limit}")
        if self.team_size:
            lines.append(f"**Team Size**: {self.team_size}")
        if self.target_audience:
            lines.append(f"**Target Audience**: {self.target_audience}")
        return "\n".join(lines)
