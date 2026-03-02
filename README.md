# Hackathon Agent

**A fully autonomous AI hackathon contestant** — from idea discovery to working demos, entirely driven by AI agents with zero human intervention.

## What is this?

Hackathon Agent is an experiment in end-to-end AI automation. Instead of _assisting_ a human participant, the agent **is** the participant: it discovers real-world pain points, writes product specs, and builds runnable demos — producing 5-7 independent projects from a single theme input.

The user provides a hackathon theme (e.g. "AI + Education") and optionally a few interest areas. Everything else is handled by the agent pipeline.

## Pipeline

```
User Input (theme + optional interests)
        │
        ▼
┌──────────────────────┐
│  Stage 1: Discovery  │  Research real pain points → 10-20 Idea Cards
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Stage 2: PRD Gen    │  Multi-role pipeline → 5-7 PRDs + wireframes
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Stage 3: Demo Dev   │  Parallel builds → 5-7 runnable projects
└──────────────────────┘
```

## Architecture

```
Python Control Script (asyncio)
    ├── SessionManager ─── spawns Claude Code CLI sessions (subprocess)
    ├── EventBus ────────── async pub/sub for all components
    ├── stages/ ─────────── orchestration logic per stage
    └── WebSocketServer ──► dashboard.html (real-time monitoring)
```

Key design choices:

- **Control script is deterministic, not AI** — orchestration is `if/then` logic, no LLM in the loop
- **Sessions are fully isolated** — no shared context between parallel Claude Code sessions
- **File-system as interface** — stages communicate via Markdown files (Idea Cards, PRDs), not memory objects
- **Hybrid orchestration** — stage-level flow controlled by Python; role-level collaboration handled by Claude Code's Agent tool inside each session

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-username/hackathon-agent.git
cd hackathon-agent

# 2. Create virtual environment & install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run Stage 1 (Idea Discovery)
.venv/bin/python -m control.main --theme "AI + Education"

# Optional: specify interest areas
.venv/bin/python -m control.main --theme "AI + Education" --interests "students,teachers"

# Optional: tune concurrency and WebSocket port
.venv/bin/python -m control.main --theme "Developer Tools" --max-concurrent 3 --ws-port 9000
```

> **Prerequisite:** [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) must be installed and authenticated.

## Dashboard

Open `dashboard.html` in a browser after starting the control script. It connects to `ws://localhost:8765` and displays:

- **Global view** — current stage, session counts, idea card tally
- **Session cards** — per-session status (pending / running / completed / failed) with live activity
- **Event timeline** — chronological log of all system events

No build tools required — it's a single vanilla JS + WebSocket file.

## Project Structure

```
hackathon-agent/
├── control/              # Python control script (asyncio)
│   ├── main.py           # CLI entry point
│   ├── session_manager.py
│   ├── event_bus.py
│   ├── models.py
│   ├── ws_server.py
│   └── stages/
│       └── stage1.py     # Stage 1 orchestration
├── prompts/              # Prompt templates (core asset)
│   └── stage1/
├── templates/            # Output templates (Idea Card, etc.)
├── dashboard.html        # Real-time monitoring UI
├── workspace/            # Runtime artifacts (gitignored)
├── requirements.txt
├── CLAUDE.md             # Agent development guide
└── Hackathon Agent Design.md
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Control script | Python 3.11+, asyncio, subprocess |
| Agent runtime | Claude Code CLI (`claude -p`) |
| Dashboard | Single-file HTML, vanilla JS, WebSocket |
| WebSocket server | `websockets` (Python) |
| Dependencies | `websockets`, `aiofiles` |

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0: Vertical Slice | Done | Control script + SessionManager + Dashboard + WebSocket |
| Phase 1: Idea Discovery | Done | Population expansion → parallel research → dedup |
| Phase 2: PRD Generation | Planned | 5-role pipeline (Product → Technical → Critic → Pitch → Wireframe) |
| Phase 3: Demo Development | Planned | Parallel project builds with self-repair loops |
| Phase 4: Polish | Planned | End-to-end testing, error handling, dashboard improvements |

## License

MIT
