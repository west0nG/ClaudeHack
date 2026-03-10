# Hackathon Agent 🤖

**A fully autonomous AI hackathon contestant** — from idea discovery to working demos to GitHub publishing, entirely driven by AI agents with zero human intervention.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## 🚀 What is this?

Hackathon Agent is an **experiment in end-to-end AI automation**. Instead of _assisting_ a human participant, the agent **IS** the participant:

- 🔍 Discovers real-world pain points through research
- 📝 Writes product specs (PRDs)
- 💻 Builds runnable demos with full source code
- 🚢 Publishes to GitHub with READMEs and pitch decks
- 🎯 Produces **5-7 independent projects** from a single theme

**You provide:** A hackathon theme (e.g., "AI + Education")  
**It delivers:** Multiple working projects, each with a GitHub repo, README, and pitch deck

---

## ✨ Demo: What It Looks Like

### Input
```bash
python -m control.main --theme "AI + Healthcare"
```

### Process
1. **Stage 1 (Discovery):** Agent researches healthcare pain points → generates 15 Idea Cards
2. **ReviewGate:** Human reviews and selects 5 promising ideas (or skip with `--skip-review`)
3. **Stage 2 (PRDs):** Agent writes detailed product specs for each idea
4. **Stage 3 (Development):** Agent codes 5 working demos, each with:
   - Full source code
   - Dependencies & setup instructions
   - Test data
5. **Stage 4 (Publishing):** Auto-generates READMEs, creates GitHub repos, pushes code
6. **Stage 5 (Pitch Decks):** Creates pitch decks (HTML + Markdown scripts) for each project

### Output
```
5 GitHub repositories like:
├── ai-symptom-checker/
│   ├── app.py
│   ├── requirements.txt
│   ├── README.md
│   ├── pitch-deck.html
│   └── pitch-script.md
├── medical-record-summarizer/
├── drug-interaction-checker/
└── ...
```

Each repo includes:
- ✅ Working code (Python, JS, or other languages)
- ✅ Professional README with setup instructions
- ✅ Pitch deck (HTML presentation)
- ✅ Pitch script (Markdown)

### Dashboard
Open `dashboard.html` in your browser during the run to watch real-time progress:
- Live session status
- Idea card generation
- PRD creation progress
- GitHub publish status

---

## 📦 Installation

### Prerequisites

1. **Claude Code CLI** — [Install guide](https://docs.anthropic.com/en/docs/claude-code)
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude auth login
   ```

2. **GitHub CLI** — [Install guide](https://cli.github.com/)
   ```bash
   # macOS
   brew install gh
   
   # Linux
   sudo apt install gh
   
   # Windows
   winget install --id GitHub.cli
   
   # Authenticate
   gh auth login
   ```

3. **Python 3.11+**
   ```bash
   python3 --version  # Should be 3.11 or higher
   ```

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-username/hackathon-agent.git
cd hackathon-agent

# 2. Create virtual environment
python3 -m venv .venv

# 3. Activate virtual environment
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Verify installation
python -m control.main --help
```

---

## 🎯 Quick Start

### Example 1: Simple Theme
```bash
python -m control.main --theme "AI + Education"
```
This will:
- Research education pain points
- Generate idea cards
- Show ReviewGate (you select which ideas to develop)
- Build demos and publish to GitHub

### Example 2: Full Hackathon Brief
```bash
python -m control.main --prompt-file hackathon-brief.txt
```
For complex hackathon prompts with rules, judging criteria, etc. Stage 0 will parse it into a structured brief.

### Example 3: Skip Manual Review (Fully Autonomous)
```bash
python -m control.main --theme "AI + Healthcare" --skip-review
```
Agent auto-selects top ideas, no human intervention needed.

### Example 4: Single Direction (Fast Mode)
```bash
python -m control.main --theme "AI + Finance" --mode single
```
Develops only 1 project instead of 5-7 (faster for testing).

### Example 5: With Interests & Limits
```bash
python -m control.main \
  --theme "AI + Climate Change" \
  --interests "sustainability,carbon-tracking" \
  --max-directions 8 \
  --max-concurrent 4
```
Focuses research on specific interests, limits to 8 ideas, runs 4 sessions in parallel.

---

## 📊 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Input                                    │
│  (--theme "AI + Education" OR --prompt-file hackathon-brief.txt) │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
        ┌────────────────────────────────────┐
        │   Stage 0: Brief Parsing           │  (Optional)
        │   Parse complex hackathon prompts  │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 1: Idea Discovery          │
        │   • Population expansion           │
        │   • Parallel research (10 dirs)    │
        │   • Generate 10-20 Idea Cards      │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   ReviewGate (Human in the Loop)   │  (Skippable)
        │   Dashboard UI: Approve/Reject     │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 2: PRD Generation          │
        │   3-session pipeline:              │
        │   concept → logic → technical      │
        │   Output: 5-7 PRDs                 │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 2.5: ConfigGate            │
        │   Parse prerequisites, collect     │
        │   API keys, generate .env plans    │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 3: Demo Development        │
        │   3-session pipeline:              │
        │   plan → dev → review              │
        │   Output: 5-7 runnable projects    │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 5: Pitch Deck Creation     │  (Parallel)
        │   2-session pipeline:              │
        │   storyteller → deck-builder       │
        │   Output: HTML decks + scripts     │
        └────────────┬───────────────────────┘
                     ▼
        ┌────────────────────────────────────┐
        │   Stage 4: GitHub Publishing       │
        │   • Auto-generate READMEs          │
        │   • git init + commit              │
        │   • gh repo create + push          │
        │   Output: 5-7 GitHub repos         │
        └────────────────────────────────────┘
```

---

## 🏗️ Architecture

### System Components

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Control Script (Python)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ SessionMgr   │  │  EventBus    │  │  ReviewGate  │               │
│  │ (subprocess) │  │  (pub/sub)   │  │  (human)     │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
│  ┌──────────────────────────────────────────────────┐               │
│  │              stages/ (orchestration)              │               │
│  │  stage0.py  stage1.py  stage2.py  stage3.py ...  │               │
│  └──────────────────────────────────────────────────┘               │
│  ┌──────────────────────────────────────────────────┐               │
│  │  WebSocketServer ──► dashboard.html              │               │
│  └──────────────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────────┐
        │  Claude Code CLI Sessions (Agent)   │
        │  • Isolated subprocess per task     │
        │  • Non-interactive mode (-p)        │
        │  • File-based I/O (prompts/output)  │
        └─────────────────────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────────┐
        │       Filesystem Interface          │
        │  • Idea Cards (Markdown)            │
        │  • PRDs (Markdown)                  │
        │  • Demo Code (Python/JS/etc)        │
        │  • Git repos (local → GitHub)       │
        └─────────────────────────────────────┘
```

### Key Design Principles

1. **Control script is deterministic, not AI**
   - Orchestration is `if/then` logic, no LLM in the control loop
   - Predictable flow, easy to debug

2. **Sessions are fully isolated**
   - No shared context between parallel Claude Code sessions
   - Each session is a fresh `claude -p` subprocess
   - Prevents context pollution

3. **File-system as interface**
   - Stages communicate via Markdown files (Idea Cards, PRDs)
   - Not memory objects or databases
   - Human-readable, versionable, inspectable

4. **Hybrid orchestration**
   - Stage-level flow: Python control script
   - Role-level collaboration: Claude Code's Agent tool inside each session

5. **Real-time monitoring**
   - WebSocket server broadcasts all events
   - Dashboard UI shows live status
   - No polling, push-based updates

---

## 🎛️ CLI Reference

### Basic Usage
```bash
python -m control.main [OPTIONS]
```

### Input Options
| Flag | Description | Example |
|------|-------------|---------|
| `--theme` | Simple theme string (skips Stage 0) | `--theme "AI + Education"` |
| `--prompt` | Inline hackathon brief (triggers Stage 0) | `--prompt "Build AI tools for..."` |
| `--prompt-file` | Hackathon brief file path | `--prompt-file brief.txt` |
| `--interests` | Comma-separated interest hints | `--interests "students,teachers"` |

### Skip Options
| Flag | Description |
|------|-------------|
| `--idea-card` | Skip to Stage 2 with a specific Idea Card file |
| `--prd-dir` | Skip to Stage 3 with a PRD directory |
| `--skip-review` | Skip ReviewGate, auto-approve all idea cards |
| `--skip-publish` | Skip Stage 4 (GitHub publishing) |
| `--skip-pitch` | Skip Stage 5 (Pitch deck creation) |

### Control Options
| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `full` | `full` (parallel), `single` (1 direction), `lite` (sequential) |
| `--max-directions` | `10` | Max number of research directions in Stage 1 |
| `--max-concurrent` | `5` | Max parallel Claude Code sessions |
| `--max-cards` | `20` | Max idea cards to generate in Stage 1 |
| `--publish-mode` | `test` | `test`: repo name prefix `hg-`, README mentions AI<br>`use`: clean names, no AI attribution |
| `--private` | `false` | Create private GitHub repos |

### Utility Options
| Flag | Description |
|------|-------------|
| `--clean` | Remove `workspace/` before running |
| `--no-archive` | Don't archive workspace after run |
| `--no-dashboard` | Disable WebSocket server |
| `--ws-port` | WebSocket port (default: 8765) |

---

## 📂 Project Structure

```
hackathon-agent/
├── control/                     # Python control script (asyncio)
│   ├── main.py                  # CLI entry point + pipeline orchestration
│   ├── session_manager.py       # Claude Code CLI subprocess management
│   ├── event_bus.py             # Async pub/sub event system
│   ├── models.py                # Data models (IdeaCard, PRD, etc.)
│   ├── review_gate.py           # Human-in-the-loop card selection
│   ├── ws_server.py             # WebSocket server for dashboard
│   └── stages/
│       ├── stage0.py            # Prompt interpretation
│       ├── stage1.py            # Idea discovery
│       ├── stage2.py            # PRD generation
│       ├── stage3.py            # Demo development
│       ├── stage4.py            # GitHub publishing
│       └── stage5.py            # Pitch deck creation
├── prompts/                     # Prompt templates (core asset)
│   ├── stage0/                  # Brief parsing prompts
│   ├── stage1/                  # Research prompts
│   ├── stage2/                  # PRD generation prompts
│   ├── stage3/                  # Development prompts
│   ├── stage4/                  # Publishing prompts
│   └── stage5/                  # Pitch deck prompts
├── templates/                   # Output templates
│   ├── idea-card.md             # Idea Card template
│   ├── prd-template.md          # PRD template
│   └── readme-template.md       # GitHub README template
├── dashboard.html               # Real-time monitoring UI (single file)
├── workspace/                   # Runtime artifacts (gitignored)
│   ├── brief/                   # Stage 0 output
│   ├── ideas/                   # Stage 1 Idea Cards
│   ├── prd/                     # Stage 2 PRDs
│   ├── demos/                   # Stage 3 demo projects
│   └── pitch/                   # Stage 5 pitch decks
├── archive/                     # Archived runs (gitignored)
├── requirements.txt             # Python dependencies
├── CLAUDE.md                    # Agent development guide (Chinese)
├── Hackathon Agent Design.md    # Full system design doc
└── README.md                    # This file
```

---

## 💻 Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Control Script** | Python 3.11+, asyncio | Orchestration logic |
| **Agent Runtime** | Claude Code CLI (`claude -p`) | AI agent execution |
| **AI Model** | Anthropic Claude Opus/Sonnet | Via Claude Code CLI |
| **Dashboard** | Single-file HTML + vanilla JS + WebSocket | No build step |
| **WebSocket Server** | `websockets` (Python) | Real-time event push |
| **Publishing** | `git`, GitHub CLI (`gh`) | Auto repo creation |
| **Languages** | Python, JavaScript, Markdown | Demos can use any language |

---

## ❓ FAQ

### Q: Do I need to code anything?
**A:** No. You just provide a theme and watch the agent work. It writes all the code.

### Q: How long does it take?
**A:** 
- **Stage 1 (Discovery):** 10-15 minutes (10 parallel research sessions)
- **Stage 2 (PRDs):** 15-20 minutes (5-7 parallel PRD sessions)
- **Stage 3 (Development):** 30-60 minutes (5-7 parallel dev sessions)
- **Stage 4+5 (Publish & Pitch):** 5-10 minutes
- **Total:** ~1-2 hours for 5-7 complete projects

### Q: Can I customize the prompts?
**A:** Yes! All prompts are in `prompts/` as Markdown files. Edit them to change the agent's behavior.

### Q: What if the agent gets stuck?
**A:** The control script has retry logic and timeouts. If a session fails, it gets archived and the pipeline continues.

### Q: Can I run this without the dashboard?
**A:** Yes, use `--no-dashboard`. You'll see progress in the terminal instead.

### Q: Does it cost money?
**A:** Yes, it uses Claude API via Claude Code CLI. Cost depends on:
- Number of projects (5-7 by default)
- Model used (Opus is more expensive than Sonnet)
- Complexity of the theme

Rough estimate: **$5-20 per full run** (5-7 projects)

### Q: Can I pause and resume?
**A:** Not yet. The pipeline must run to completion. (Planned for future releases)

### Q: What if I don't have GitHub CLI?
**A:** You can skip publishing with `--skip-publish`. Projects will be saved locally in `workspace/demos/`.

### Q: Can I use this for real hackathons?
**A:** Technically yes, but check the rules! Many hackathons require human-written code. This is best used for:
- Rapid prototyping
- Idea exploration
- Learning system design
- Bootstrapping projects

### Q: What happens to failed projects?
**A:** Failed sessions are archived in `workspace/archive/`. The pipeline continues with successful ones.

### Q: Can I add my own stages?
**A:** Yes! Create a new `stageN.py` in `control/stages/` and update `main.py` to call it. See existing stages as examples.

### Q: How do I debug a failed session?
**A:** Check:
1. `workspace/session-<timestamp>/` for session logs
2. `archive/` for archived failed sessions
3. Dashboard event timeline for detailed error messages

---

## 🛠️ Troubleshooting

### `claude: command not found`
Install Claude Code CLI:
```bash
npm install -g @anthropic-ai/claude-code
claude auth login
```

### `gh: command not found`
Install GitHub CLI:
```bash
brew install gh  # macOS
gh auth login
```

### `WebSocket connection failed`
Check if port 8765 is available:
```bash
lsof -i :8765
```
Or use a different port:
```bash
python -m control.main --ws-port 9000
```

### Sessions hang forever
Check Claude Code CLI is working:
```bash
claude -p "Say hello"
```
If it fails, re-authenticate:
```bash
claude auth logout
claude auth login
```

### Out of API credits
Claude Code uses your Anthropic API key. Check your usage at: https://console.anthropic.com/

---

## 📈 Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0** | ✅ Done | Control script + SessionManager + Dashboard + WebSocket |
| **Phase 1** | ✅ Done | Idea Discovery: Population expansion, parallel research, dedup |
| **Phase 1.5** | ✅ Done | Run modes, Stage 0 prompt interpreter, ReviewGate |
| **Phase 2** | ✅ Done | PRD Generation: 3-session pipeline (concept, logic, technical) |
| **Phase 3** | ✅ Done | Demo Development: plan, dev, review with bounce-back |
| **Phase 3.5** | ✅ Done | ConfigGate: Credential collection, environment setup |
| **Phase 4** | ✅ Done | Publishing: Auto README, git init, GitHub repo creation |
| **Phase 5** | ✅ Done | Pitch Decks: Storyteller + deck builder |
| **Phase 6** | 📅 Planned | Polish: End-to-end testing, error handling improvements |

---

## 🤝 Contributing

This is an experimental research project. Contributions welcome! 

**Areas for improvement:**
- Better error handling
- Pause/resume support
- More language support in Stage 3 (currently Python/JS focused)
- Cost tracking dashboard
- More output formats (video demos, Figma designs, etc.)

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

---

## 🙏 Acknowledgments

Built with:
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) by Anthropic
- [GitHub CLI](https://cli.github.com/) by GitHub
- Inspired by [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT), [GPT-Engineer](https://github.com/gpt-engineer-org/gpt-engineer), and other autonomous agent experiments

---

**Made with 🤖 by an AI agent (mostly)**
