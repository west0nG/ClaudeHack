# Hackathon Agent

**A fully autonomous AI hackathon contestant** — from idea discovery to working demos to GitHub publishing, entirely driven by AI agents with zero human intervention.

## What is this?

Hackathon Agent is an experiment in end-to-end AI automation. Instead of _assisting_ a human participant, the agent **is** the participant: it discovers real-world pain points, writes product specs, builds runnable demos, and publishes them to GitHub — producing 5-7 independent projects from a single theme input.

The user provides a hackathon theme (or a full hackathon brief) and optionally a few interest areas. Everything else is handled by the agent pipeline.

## Pipeline

```
User Input (--theme / --prompt / --prompt-file)
        │
        ▼
┌──────────────────────────┐
│  Stage 0: Brief Parsing  │  Parse complex hackathon prompts (optional)
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│  Stage 1: Discovery      │  Research real pain points → 10-20 Idea Cards
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│  ReviewGate              │  Human review (Dashboard UI / CLI, skippable)
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│  Stage 2: PRD Gen        │  3-session pipeline → concept + logic + technical docs
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│  Stage 3: Demo Dev       │  plan → dev → review → 5-7 runnable projects
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│  Stage 4: Publish        │  README gen + git init + GitHub repo creation
└──────────────────────────┘
```

## Architecture

```
Python Control Script (asyncio)
    ├── SessionManager ─── spawns Claude Code CLI sessions (subprocess)
    ├── EventBus ────────── async pub/sub for all components
    ├── ReviewGate ──────── human-in-the-loop card selection
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
# 1. Clone & setup
git clone https://github.com/your-username/hackathon-agent.git
cd hackathon-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Simple theme
.venv/bin/python -m control.main --theme "AI + Education"

# 3. Full hackathon brief (triggers Stage 0 parsing)
.venv/bin/python -m control.main --prompt-file hackathon-brief.txt

# 4. With options
.venv/bin/python -m control.main --theme "AI + Education" \
  --interests "students,teachers" \
  --max-directions 10 \
  --max-concurrent 10 \
  --skip-review
```

> **Prerequisite:** [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) and [GitHub CLI](https://cli.github.com/) (`gh`) must be installed and authenticated.

## CLI Options

| Flag | Description |
|------|-------------|
| `--theme` | Simple theme string (skips Stage 0) |
| `--prompt` / `--prompt-file` | Complex hackathon brief (triggers Stage 0 parsing) |
| `--idea-card` | Skip to Stage 2 with a specific Idea Card |
| `--prd-dir` | Skip to Stage 3 with a PRD directory |
| `--interests` | Comma-separated interest hints |
| `--mode full\|single\|lite` | `full` (parallel), `single` (1 direction), `lite` (sequential) |
| `--max-directions N` | Limit number of research directions |
| `--max-concurrent N` | Max parallel sessions (default: 5) |
| `--skip-review` | Skip manual ReviewGate, auto-approve all cards |
| `--skip-publish` | Skip Stage 4 (GitHub publishing) |
| `--publish-mode test\|use` | `test`: repo prefixed `hg-`, README mentions AI. `use`: clean names, no AI attribution |
| `--private` | Create private GitHub repos |
| `--clean` | Remove workspace/ before running |
| `--no-archive` | Don't archive workspace after run |
| `--no-dashboard` | Disable WebSocket server |
| `--ws-port N` | WebSocket port (default: 8765) |

## Dashboard

Open `dashboard.html` in a browser after starting the control script. It connects to `ws://localhost:8765` and displays:

- **Global view** — current stage, session counts, idea card tally
- **Session cards** — per-session status with live activity
- **ReviewGate UI** — approve/reject cards one by one
- **Event timeline** — chronological log of all system events (including publish status)

No build tools required — it's a single vanilla JS + WebSocket file.

## Project Structure

```
hackathon-agent/
├── control/                # Python control script (asyncio)
│   ├── main.py             # CLI entry point + pipeline orchestration
│   ├── session_manager.py  # Claude Code CLI subprocess management
│   ├── event_bus.py        # Async pub/sub
│   ├── models.py           # Data models
│   ├── review_gate.py      # Human-in-the-loop card selection
│   ├── ws_server.py        # WebSocket server
│   └── stages/
│       ├── stage0.py       # Prompt interpretation
│       ├── stage1.py       # Idea discovery
│       ├── stage2.py       # PRD generation
│       ├── stage3.py       # Demo development
│       └── stage4.py       # GitHub publishing
├── prompts/                # Prompt templates (core asset)
│   ├── stage0/ stage1/ stage2/ stage3/
├── templates/              # Output templates (Idea Card, etc.)
├── dashboard.html          # Real-time monitoring UI
├── workspace/              # Runtime artifacts (gitignored)
├── archive/                # Archived runs (gitignored)
├── requirements.txt
├── CLAUDE.md               # Agent development guide
└── Hackathon Agent Design.md
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Control script | Python 3.11+, asyncio, subprocess |
| Agent runtime | Claude Code CLI (`claude -p`) |
| Dashboard | Single-file HTML, vanilla JS, WebSocket |
| WebSocket server | `websockets` (Python) |
| Publishing | `git`, `gh` CLI |

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0: Vertical Slice | Done | Control script + SessionManager + Dashboard + WebSocket |
| Phase 1: Idea Discovery | Done | Population expansion, parallel research, dedup |
| Phase 1.5: Enhancements | Done | Run modes, Stage 0 prompt interpreter, ReviewGate |
| Phase 2: PRD Generation | Done | 3-session pipeline (concept, logic, technical), elimination |
| Phase 3: Demo Development | Done | plan, dev, review with bounce-back on failure |
| Phase 4: Publishing | Done | Auto README, git init, GitHub repo creation |
| Phase 5: Polish | Planned | End-to-end testing, error handling, dashboard improvements |

## License

MIT
