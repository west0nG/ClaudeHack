# CLAUDE.md — Hackathon Agent

## 1. Project Overview

Hackathon Agent 是一个**全自主 AI 黑客松参赛系统**——从需求发现到 Demo 开发，全程由 Agent 主导，用户仅作为观察者。

**核心命题**：验证纯 Agent 自动化能否端到端跑通一个黑客松项目流程，最终同时产出 5-7 个可运行的独立项目。

> 完整设计详见 `Hackathon Agent Design.md`

---

## 2. Implementation Status

| Phase | 状态 | 说明 |
|-------|------|------|
| Phase 0: Vertical Slice | ✅ 已完成 | 中控 + SessionManager + Dashboard + WebSocket |
| Phase 1: Stage 1 需求发现 | ✅ 已完成 | 灵感搜索 + 人群展开 → 并行 Research (2 sub-agents) → 流式去重 + 最终审查 |
| Phase 1.5: Enhancements | ✅ 已完成 | Run modes, Stage 0 prompt interpreter, ReviewGate |
| Phase 2: Stage 2 PRD 生成 | ✅ 已完成 | 3-session 串行流水线 (concept → logic → technical)，淘汰机制 |
| Phase 3: Stage 3 Demo 开发 | ✅ 已完成 | 3-session 串行流水线 (plan → dev → review)，bounce-back 机制 |
| Phase 3.5: Stage 2.5 ConfigGate | ✅ 已完成 | 3-layer credential resolution (persistent + env + interactive) + alias table + per-project filtering |
| Phase 4: Stage 4 GitHub 发布 | ✅ 已完成 | 自动 README 生成 + git init + gh repo create + push |
| Phase 5: Stage 5 Pitch Deck | ✅ 已完成 | 2-session pipeline (storyteller → deck builder), parallel with Stage 4 |
| Phase 6: Streaming Pipeline | ✅ 已完成 | Per-card end-to-end streaming (Stage 2→Config→3→5→4), CredentialBarrier, zero-barrier when creds satisfied |
| Phase 7: Polish | ⬜ 未开始 | |

---

## 3. Architecture

### 流水线 (Streaming Architecture)

```
用户输入 (--theme / --prompt / --prompt-file)
    ↓
[Stage 0: 赛题解析] → HackathonBrief (--theme 时跳过)
    ↓
[Stage 1: 需求发现] → 5-15 Idea Cards
    ↓
[ReviewGate: 人工筛选] → 用户选择保留的 Cards (--skip-review 时跳过)
    ↓
┌─── Per-Card Streaming Pipeline (cards flow independently) ───┐
│                                                               │
│  Card A: [Stage 2] → [ConfigCheck] → [Stage 3] → [Stage 5] → [Stage 4]
│  Card B: [Stage 2] ────→ [ConfigCheck] → [Stage 3] ────→ [Stage 5] → [Stage 4]
│  Card C: [Stage 2] ──→ [ConfigCheck] → [Stage 3] ──→ [Stage 5] → [Stage 4]
│                                                               │
│  ConfigCheck: instant if creds satisfied (persistent store +  │
│  system env + alias resolution). Only blocks if interactive   │
│  collection needed (CredentialBarrier).                       │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 组件关系

```
Python 中控脚本 (asyncio)
    ├── SessionManager — 启动/管理 Claude Code CLI sessions (subprocess)
    ├── EventBus — 异步事件发布/订阅
    ├── ReviewGate — 阶段间人工筛选 (Dashboard UI / CLI)
    ├── CredentialBarrier — 流式凭证检查 + 一次性交互收集
    ├── streaming.py — Per-card 端到端流水线编排
    ├── credential_store.py — 3-layer 凭证查找 + alias 解析
    ├── stages/ — 各阶段内部逻辑 (stage0, stage1, ...)
    ├── 收集 session 产出 (文件系统)
    └── WebSocketServer — 双向 WebSocket (推送状态 + 接收用户操作)
```

### 关键原则

- **中控是确定性编排脚本，不是 AI**——流程编排是 if/then 逻辑，不需要 AI 判断
- **Session 间不共享上下文**——每个 Claude Code session 完全独立，避免信息污染
- **阶段间通过文件系统传递数据**——Idea Card / PRD 是 Markdown 文件，不是内存对象
- **混合编排**——阶段级由中控脚本驱动，角色级由 Claude Code 的 Agent tool 在 session 内部处理

### Stage 0 数据流 (可选)

```
原始赛题文本 (--prompt / --prompt-file)
    │
    ▼
[Interpreter Session] ── claude -p → 输出 JSON: HackathonBrief
    │ (constraints, evaluation_criteria, restrictions, ...)
    ▼
HackathonBrief.render_context_block() → 注入 Stage 1 prompts
```

使用 `--theme` 时跳过，直接创建最小 `HackathonBrief(theme=...)`。

### Stage 1 数据流

```
HackathonBrief + optional interests
    │
    ▼
[Main Agent Session] ── claude -p (with WebSearch for inspiration)
    │ → 输出 JSON: 8-12 个人群方向 (含 scope + likely_product_types)
    ▼
中控解析 JSON → [可选] 按 max_directions 裁剪 (--mode single = 1)
    │
    ▼
[Research Session × N] ── 每个 session 内部用 Agent tool spawn:
    │  ├─ Search sub-agent (按 pain area 可并行，scope=broad 时拆分)
    │  └─ Synthesis sub-agent (独立上下文，内含 self-review)
    │ 输出: 1-5 个 idea-card-*.md 文件/session (受 scope 控制)
    ▼
中控流式去重 (每个 Research session 完成后立即与卡片池比较)
    │ 轻量 claude -p 调用，只处理明显重复
    ▼
[Final Review Agent] ── 最终轻量审查 (卡片池 > 3 时)
    │ 检查遗漏重复 + 格式标准化 + 质量排序
    │ 输出: workspace/stage1/output/idea-card-*.md
    ▼
[ReviewGate] → Dashboard UI / CLI → 用户筛选
    │ (--skip-review 时跳过)
    ▼
最终产出: 5-15 张筛选后的 Idea Cards
```

### Stage 2 数据流

```
Idea Cards (from Stage 1 output or --idea-card)
    │
    ▼
中控为每张 Idea Card 启动 3 个串行 Session (不同卡片并行)
    │
    ▼
[Session 1: Concept] ── idea_card → concept.md | ELIMINATED.md
    │ (淘汰时终止流水线)
    ▼
[Session 2: Logic] ── concept.md + idea_card → logic.md
    │
    ▼
[Session 3: Technical] ── concept.md + logic.md → technical.md
    │
    ▼
中控收集所有输出 → 复制到 workspace/stage2/output/{slug}/
    │
    ▼
最终产出: 5-7 组产品文档目录 (concept.md + logic.md + technical.md)
```

### Stage 2.5 数据流 (CredentialBarrier / ConfigGate)

**Streaming mode** (full pipeline — uses `CredentialBarrier`):
```
Each card finishes Stage 2 → technical.md with Prerequisites Checklist
    │
    ▼
CredentialBarrier.check_and_wait(slug, prd_dir):
    │
    ├─ Step 1: Parse Prerequisites Checklist from technical.md
    │   → Extract: {carrier: [...], functional: [...], dev: [...]}
    │
    ├─ Step 2: 3-layer credential resolution (per var)
    │   1. Persistent store (credentials.env at project root)
    │   2. Alias resolution (e.g. GOOGLE_MAPS_API_KEY → GOOGLE_API_KEY)
    │   3. System environment (os.environ)
    │
    ├─ All satisfied? → return immediately, proceed to Stage 3 (zero blocking)
    │
    └─ Missing carrier deps? → wait for interactive collection
        → Collection triggers ONCE after all cards have checked in
        → CLI or Dashboard prompt for missing creds only
        → Persist new creds → all waiting cards resume
    │
    ▼
Per-project outputs:
    → environment-plan.md (✅/⏭️/❌ status for prompt injection)
    → Filtered credentials dict (only keys this project needs)
    → BLOCK if carrier deps still missing after collection
```

**Batch mode** (--prd-dir, --resume — uses `run_config_gate`):
Same 3-layer resolution, but processes all projects synchronously before Stage 3.

**Credential alias table** (`credential_store._CANONICAL_ALIASES`):
Maps common naming variants to a canonical name. Example:
- `GOOGLE_MAPS_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLOUD_API_KEY` → all resolve to `GOOGLE_API_KEY`
- `OPENAI_KEY`, `OPEN_AI_KEY` → `OPENAI_API_KEY`
- `SLACK_TOKEN`, `SLACK_API_TOKEN` → `SLACK_BOT_TOKEN`

User only needs to set one key (in `credentials.env` or shell env), all project variants auto-resolve.

### Stage 3 数据流

```
PRD directory (from Stage 2 output or --prd-dir)
    │  (含 concept.md + logic.md + technical.md)
    │  + credentials (passed directly from CredentialBarrier, per-project filtered)
    │  + environment-plan.md (injected into prompts via {{env_plan_content}})
    ▼
3 个串行 Session per project:
    │
    ▼
[Session A: Plan] ── concept + logic + technical + env_plan → dev-plan.md
    │ (纯规划，不写代码)
    ▼
[Session B: Dev] ── dev-plan + 3 docs → demo/ 项目
    │ (Scaffold → Shared Layer → Page Coding)
    │ (credentials written to .env in working dir via SessionManager)
    ▼
[Session C: Review] ── demo/ + dev-plan + concept → verified project
    │ (Designer → Reviewer → Fix → Final)
    │
    ├─ 如果 BUILD_FAILED → bounce back: 重跑 B + C (max 1次)
    │
    ▼
最终产出: 可运行的 Demo 项目 (demo/package.json 为成功标志)
```

In streaming mode, each card enters Stage 3 independently as soon as its Stage 2 + ConfigCheck completes. No waiting for other cards.

### Stage 4 数据流

```
Demo project directories (from Stage 3)
    │
    ▼
中控为每个成功项目并行执行 (确定性 git/gh 操作，无 AI session)
    │
    ├─ 查找对应 Stage 2 output → 读取 concept.md + technical.md
    ├─ 生成标准化 README.md (项目名、问题、方案、技术栈、启动指令)
    ├─ git init + git add -A + git commit
    └─ gh repo create hackathon-agent-{slug} --public --source . --push
    │
    ▼
最终产出: 5-7 个 GitHub 仓库 URL
```

### Stage 5 数据流 (runs before Stage 4)

```
Demo project directories + PRD directories (from Stage 2/3)
    │
    ▼
中控为每个成功项目启动 2 个串行 Session (不同项目并行)
    │
    ▼
[Session 1: Storyteller] ── concept + logic + technical + demo/ → pitch-script.md
    │ (Hook + Problem + Solution + Our Demo + Closing)
    ▼
[Session 2: Deck Builder] ── pitch-script + concept + technical → pitch-deck.html
    │ (Self-contained HTML slides, CSS-only, keyboard nav)
    ▼
中控收集输出 → workspace/stage5/output/{slug}/
    │
    ▼
中控复制 pitch-script.md + pitch-deck.html → 各项目 demo/ 目录
    │ (Stage 4 git add -A 时自动包含)
    ▼
Stage 4 发布到 GitHub（含 pitch 产出）
```

---

## 4. Tech Stack

| 层 | 技术 |
|---|---|
| 中控脚本 | Python 3.11+, asyncio, subprocess |
| Dashboard | 单文件 `dashboard.html` (vanilla JS + WebSocket，无构建工具) |
| Agent Runtime | Claude Code CLI (`claude -p`) |
| WebSocket | `websockets` (Python) |
| 依赖 | websockets, aiofiles |
| Python 环境 | `.venv/` (venv) |

---

## 5. Directory Layout (实际结构)

```
hackathon-agent/
├── control/                     # Python 中控
│   ├── __init__.py
│   ├── __main__.py              # python -m control 入口
│   ├── main.py                  # CLI 入口 + 组件编排
│   ├── models.py                # 数据模型 (SessionConfig, SessionResult, Event, HackathonBrief, ...)
│   ├── event_bus.py             # 异步事件 pub/sub
│   ├── session_manager.py       # 核心：管理 claude CLI 子进程
│   ├── ws_server.py             # WebSocket 服务端 (双向通信)
│   ├── review_gate.py           # ReviewGate: 阶段间人工筛选
│   ├── credential_store.py      # 3-layer credential resolution + alias table + prerequisites parser
│   ├── credential_barrier.py    # Streaming-friendly credential barrier (CredentialBarrier)
│   ├── streaming.py             # Per-card end-to-end streaming pipeline
│   └── stages/
│       ├── __init__.py
│       ├── stage0.py            # 阶段零：Prompt 解析器
│       ├── stage1.py            # 阶段一完整逻辑
│       ├── stage2.py            # 阶段二：PRD 生成编排
│       ├── stage2_5.py           # 阶段 2.5：ConfigGate 凭证收集编排
│       ├── stage3.py            # 阶段三：Demo 开发编排
│       ├── stage4.py            # 阶段四：GitHub 发布 (git/gh, 无 AI session)
│       └── stage5.py            # 阶段五：Pitch Deck 生成编排
│
├── dashboard.html               # 单文件监控页面 (vanilla JS + WebSocket + ReviewGate UI)
│
├── prompts/                     # ⭐ 核心资产：各角色 Prompt
│   ├── stage0/
│   │   └── interpreter.md       # Prompt 解析 Agent
│   ├── stage1/
│   │   ├── main.md              # 主 Agent: WebSearch 灵感搜索 + 人群展开 → JSON (含 scope + likely_product_types)
│   │   ├── research.md          # Research Session (内部用 Agent tool 管理2个 sub-agent: Search + Synthesis)
│   │   └── dedup.md             # Final Review Agent: 去重检查 + 格式标准化 + 质量排序
│   ├── stage2/
│   │   ├── concept.md           # Session 1: 痛点验证 + 产品概念定义
│   │   ├── logic.md             # Session 2: 功能模块 + 用户流程
│   │   ├── technical.md         # Session 3: 技术栈 + 实现计划
│   │   └── prd.md.bak           # (旧版单 session prompt，仅供参考)
│   ├── stage3/
│   │   ├── plan.md              # Session A: 模块→页面映射 + 开发计划
│   │   ├── dev.md               # Session B: 脚手架 + Shared Layer + 页面编码
│   │   └── review.md            # Session C: 设计审查 + 功能审查 + 修复 + 最终验证
│   └── stage5/
│       ├── storyteller.md       # Session 1: Pitch 叙事脚本
│       └── deck-builder.md      # Session 2: HTML slide deck
│
├── templates/
│   └── idea-card.md             # Idea Card 模板
│
├── workspace/                   # ⚠️ 运行时产物，不进 git
│   ├── stage1/
│   │   ├── main/                # 主 Agent 工作目录
│   │   ├── research-{slug}/     # 各 Research Session 工作目录
│   │   ├── dedup/input/         # 去重输入 (所有 raw idea cards)
│   │   ├── dedup/               # 去重 Agent 工作目录
│   │   └── output/              # 最终产出
│   ├── stage2/
│   │   ├── {card-slug}/
│   │   │   ├── concept/         # Session 1 工作目录
│   │   │   ├── logic/           # Session 2 工作目录
│   │   │   └── technical/       # Session 3 工作目录
│   │   └── output/{card-slug}/  # 最终产出 (concept.md + logic.md + technical.md)
│   ├── stage3/
│   │   └── {prd-slug}/
│   │       ├── plan/            # Session A 工作目录 (dev-plan.md)
│   │       └── dev/             # Session B+C 共享工作目录
│   │           └── demo/        # 产出项目 (含 package.json, src/, README.md)
│   └── stage5/
│       ├── {slug}/
│       │   ├── storyteller/     # Session 1 工作目录
│       │   │   ├── demo -> symlink  # Points to Stage 3 demo/
│       │   │   └── pitch-script.md
│       │   └── deck/            # Session 2 工作目录
│       │       └── pitch-deck.html
│       └── output/{slug}/       # 最终产出
│           ├── pitch-script.md
│           └── pitch-deck.html
│
├── tests/                       # 测试
├── .venv/                       # Python 虚拟环境
├── requirements.txt             # websockets, aiofiles
├── .gitignore
├── CLAUDE.md
└── Hackathon Agent Design.md
```

**注意**：
- `prompts/` 和 `templates/` 是核心资产，修改需谨慎
- `workspace/` 是运行时产物，体积可能很大，已在 `.gitignore` 中排除
- 不要全量读取 `workspace/` 目录内容

---

## 6. Running the System

```bash
# 安装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Simple theme (skips Stage 0 interpreter)
.venv/bin/python -m control.main --theme "AI + Education"

# With interest hints
.venv/bin/python -m control.main --theme "AI + Education" --interests "学生,教师"

# Complex hackathon prompt (triggers Stage 0 interpreter)
.venv/bin/python -m control.main --prompt "Build an innovative solution using generative AI..."
.venv/bin/python -m control.main --prompt-file hackathon-brief.txt

# Run modes: single (1 direction, saves ~80% tokens), lite (all sequential), full (default)
.venv/bin/python -m control.main --theme "AI + Education" --mode single
.venv/bin/python -m control.main --theme "AI + Education" --mode lite
.venv/bin/python -m control.main --theme "AI + Education" --max-directions 3

# Skip manual review gate (auto-keep all cards)
.venv/bin/python -m control.main --theme "AI + Education" --skip-review

# Custom concurrency and WS port
.venv/bin/python -m control.main --theme "Developer Tools" --max-concurrent 3 --ws-port 9000

# No dashboard (CLI-only review gate)
.venv/bin/python -m control.main --theme "AI + Education" --no-dashboard

# Debug: skip to Stage 3 with a PRD directory
.venv/bin/python -m control.main --prd-dir workspace/stage2/output/some-slug/

# Skip ConfigGate credential collection (use persistent store only)
.venv/bin/python -m control.main --theme "AI + Education" --skip-config

# Skip GitHub publishing (Stage 4)
.venv/bin/python -m control.main --theme "AI + Education" --skip-publish

# Skip pitch deck generation (Stage 5)
.venv/bin/python -m control.main --theme "AI + Education" --skip-pitch

# Create private repos instead of public
.venv/bin/python -m control.main --theme "AI + Education" --private
```

Dashboard: 启动后在浏览器打开 `dashboard.html`，会自动连接 `ws://localhost:8765`。

---

## 7. Core Components

### SessionManager (`control/session_manager.py`)

管理 Claude Code CLI 子进程的完整生命周期。

```python
# 核心接口
session_mgr = SessionManager(max_concurrent=5, event_bus=event_bus)
result = await session_mgr.run_session(SessionConfig(...))
results = await session_mgr.run_many([config1, config2, ...])
```

**关键行为：**
- `asyncio.Semaphore(5)` 控制并发
- 逐行读取 stdout 的 stream-json，解析并提取进度事件
- 超时处理：`asyncio.wait_for` + process.kill()
- 失败重试：默认最多重试 1 次
- 结果收集：session 完成后扫描 working_dir 中的 `*.md` 文件

**CLI 命令构建：**
```
claude -p "{prompt}" \
  --output-format stream-json \
  --model sonnet \
  --allowedTools "WebSearch WebFetch Agent Read Write Glob Grep" \
  --max-budget-usd 2.0 \
  --dangerously-skip-permissions
```

### EventBus (`control/event_bus.py`)

```python
event_bus = EventBus()
event_bus.subscribe(callback)       # 订阅（支持 sync 和 async callback）
await event_bus.emit(Event(...))    # 发布
event_bus.history                   # 历史事件列表
```

### SessionConfig / SessionResult (`control/models.py`)

```python
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
    extra_env: dict[str, str] | None = None  # Credentials injected as .env + process env

@dataclass
class SessionResult:
    session_id: str
    status: SessionStatus  # PENDING | RUNNING | COMPLETED | FAILED | RETRYING
    output: str = ""
    working_dir: str | None = None
    output_files: list[str] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0
```

### HackathonBrief (`control/models.py`)

Structured representation of a hackathon prompt, parsed by Stage 0 or created minimally from `--theme`.

```python
brief = HackathonBrief.from_theme("AI + Education")     # Minimal, skips Stage 0
brief = HackathonBrief.from_dict(parsed_json)            # Full, from interpreter
brief.render_context_block()                              # → text block for prompt injection
```

Key fields: `theme`, `constraints`, `evaluation_criteria`, `restrictions`, `special_requirements`, `suggested_directions`.

### ReviewGate (`control/review_gate.py`)

Pauses pipeline between stages for human card selection.

```python
review_gate = ReviewGate(event_bus, ws_server=ws_server)
filtered = await review_gate.wait_for_selection(cards)  # Returns filtered list[Path]
```

**Dashboard mode**: emits `review_requested` → dashboard renders card grid with checkboxes → user confirms → WebSocket message `review_selection` → pipeline resumes.

**CLI mode** (`--no-dashboard`): prints numbered summaries → user types indices → pipeline resumes.

10-minute timeout safety — defaults to keeping all cards.

### CredentialBarrier (`control/credential_barrier.py`)

Streaming-friendly credential check for per-card pipelines. Replaces batch ConfigGate in the full pipeline path.

```python
barrier = CredentialBarrier(
    persistent_creds=load_all_credentials(PERSISTENT_CREDS_PATH),
    total_projects=len(cards),
    event_bus=event_bus,
    skip=args.skip_config,
)

# Called by each card after its Stage 2 completes
project_creds, needed_vars, is_blocked = await barrier.check_and_wait(slug, prd_dir)
```

**Key behaviors:**
- Projects with all creds satisfied → return immediately (zero blocking)
- Projects with missing creds → wait until all projects have checked in
- Interactive collection triggers at most once (after all check-ins)
- Per-project credential filtering (each project only gets the keys it needs)
- Writes `environment-plan.md` per project for Stage 3 prompt injection
- 10-minute safety timeout on barrier wait

### Credential Store (`control/credential_store.py`)

3-layer credential resolution with alias table:

```python
# Load from all sources
creds = load_all_credentials(path, needed_vars={"OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY"})

# Alias resolution: one key satisfies all variants
resolve_credential("GOOGLE_MAPS_API_KEY", {"GOOGLE_API_KEY": "AIza..."})  # → "AIza..."
resolve_credential("GEMINI_API_KEY", {"GOOGLE_API_KEY": "AIza..."})       # → "AIza..."
```

**Lookup order per variable:**
1. Persistent store (`credentials.env`) — exact name
2. Persistent store — alias variants
3. System environment (`os.environ`) — exact name
4. System environment — alias variants
5. Interactive collection (only if still missing after all above)

### Streaming Pipeline (`control/streaming.py`)

Per-card end-to-end pipeline that replaces batch stage execution in the full flow:

```python
project_dirs = await run_streaming_pipeline(
    idea_cards=cards, theme=theme, session_mgr=session_mgr,
    event_bus=event_bus, barrier=barrier, model=model,
    skip_pitch=False, skip_publish=False,
)
```

Each card flows: Stage 2 → ConfigCheck → Stage 3 → Stage 5 → Stage 4.
Concurrency bounded by SessionManager semaphore. Shared repo name registry prevents GitHub naming collisions.

### WebSocketServer (`control/ws_server.py`)

Bidirectional WebSocket server. Broadcasts events to dashboard, receives user actions.

```python
ws_server.register_handler("review_selection", callback)   # Register incoming message handler
ws_server.unregister_handler("review_selection")            # Clean up
```

---

## 8. Event System

### 事件类型

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `stage_started` | 阶段开始 | stage, theme |
| `stage_completed` | 阶段结束 | stage, cards (或 theme, constraints_count) |
| `directions_found` | 人群方向解析完成 | count, directions[] |
| `session_started` | Session 启动 | session_id, model |
| `session_progress` | Session 进度更新 | session_id, activity |
| `session_completed` | Session 完成 | session_id, duration, files[] |
| `session_failed` | Session 失败 | session_id, error |
| `session_retrying` | Session 重试 | session_id, attempt |
| `review_requested` | Idea Cards 就绪等待审查 | cards: [{index, title, scenario_excerpt, evidence_count, solution_directions}] |
| `review_completed` | 用户确认筛选 | selected, total |
| `prd_completed` | PRD 生成完成 | session_id, output_dir, docs[] |
| `prd_eliminated` | Idea Card 被淘汰 | session_id, reason |
| `prd_failed` | PRD 生成失败 | session_id, error |
| `dev_completed` | Demo 项目构建成功 | session_id, project_dir, has_readme |
| `dev_failed` | Demo 构建失败或 session 失败 | session_id, error |
| `publish_started` | 项目开始发布到 GitHub | project_dir, repo_name |
| `publish_completed` | 项目发布成功 | repo_name, repo_url, project_dir |
| `config_blocked` | ConfigGate 阻止项目 (缺少 carrier 依赖) | slug, missing |
| `publish_failed` | 项目发布失败 | repo_name, error |
| `pitch_started` | Pitch 生成开始 | session_id, slug |
| `pitch_script_completed` | Pitch 脚本生成完成 | session_id, slug, script_path |
| `pitch_deck_completed` | Pitch 幻灯片生成完成 | session_id, slug, deck_path, script_path |
| `pitch_deck_failed` | Pitch 生成失败 | session_id, error |
| `streaming_pipeline_started` | Streaming pipeline 启动 | cards, theme |
| `streaming_pipeline_completed` | Streaming pipeline 完成 | projects_built, projects_published, failed, repo_urls |

### WebSocket 协议

```json
{"type": "session_started", "data": {"session_id": "research-students", "model": "sonnet"}, "timestamp": 1234567890.0}
{"type": "session_progress", "data": {"session_id": "research-students", "activity": "搜索: remote work pain points reddit"}, "timestamp": 1234567891.0}
```

Dashboard 通过 `ws://localhost:8765` 消费事件，新连接自动接收历史事件。

---

## 9. Prompt Engineering

### 文件组织

```
prompts/
├── stage0/
│   └── interpreter.md   # 输入: raw_prompt → 输出: JSON HackathonBrief
├── stage1/
│   ├── main.md           # 输入: theme + interests + hackathon_context → 输出: JSON 人群方向数组
│   ├── research.md       # 输入: persona + pain_areas + scope + hackathon_context → 2 sub-agents (Search + Synthesis) → 输出: idea-card-*.md
│   └── dedup.md          # Final Review Agent: 读取 input/*.md → 去重检查 + 格式标准化 + 质量排序 → 写入 ../output/
├── stage2/
│   ├── concept.md        # Session 1: theme + idea_card_content → concept.md 或 ELIMINATED.md
│   ├── logic.md          # Session 2: theme + idea_card_content + concept_content → logic.md
│   └── technical.md      # Session 3: theme + concept_content + logic_content → technical.md
├── stage3/
│   ├── plan.md            # Session A: theme + concept + logic + technical → dev-plan.md
│   ├── dev.md             # Session B: theme + concept + logic + technical + dev_plan → demo/ 项目
│   └── review.md          # Session C: theme + concept + dev_plan → verified project 或 BUILD_FAILED.md
└── stage5/
    ├── storyteller.md     # Session 1: theme + concept + logic + technical + demo/ → pitch-script.md
    └── deck-builder.md    # Session 2: theme + concept + technical + pitch_script → pitch-deck.html
```

### Prompt 格式规范

每个 prompt 文件按以下结构组织：
1. **角色定义** — 你是谁，职责是什么
2. **输入说明** — 你会收到什么数据
3. **过程说明** — 怎么做（特别是 Agent tool 使用指令）
4. **输出格式** — 你必须产出什么格式的内容
5. **约束条件** — 限制和边界

### 变量占位符

使用双花括号 `{{var}}`，支持条件块 `{{#var}}...{{/var}}`：

- `{{theme}}` — Hackathon 主题
- `{{interests}}` — 兴趣方向（可选）
- `{{persona}}` — 目标人群
- `{{pain_areas}}` — 痛点列表
- `{{scope}}` — 方向规模: `"broad"` 或 `"focused"`（Stage 1 Research）
- `{{scope_broad}}` — 条件块: scope 为 broad 时展开（Stage 1 Research）
- `{{scope_focused}}` — 条件块: scope 为 focused 时展开（Stage 1 Research）
- `{{raw_prompt}}` — 原始赛题文本（Stage 0）
- `{{hackathon_context}}` — 约束/评审标准/限制文本块（Stage 1，由 `HackathonBrief.render_context_block()` 生成）
- `{{idea_card_content}}` — Idea Card 全文（Stage 2 Session 1-2）
- `{{concept_content}}` — concept.md 全文（Stage 2 Session 2-3, Stage 3）
- `{{logic_content}}` — logic.md 全文（Stage 2 Session 3, Stage 3）
- `{{technical_content}}` — technical.md 全文（Stage 3）
- `{{dev_plan_content}}` — dev-plan.md 全文（Stage 3 Session B-C）
- `{{pitch_script_content}}` — pitch-script.md 全文（Stage 5 Session 2）

条件块 `{{#hackathon_context}}...{{/hackathon_context}}`：当 `hackathon_context` 非空时展开，为空时整个块被移除。

模板渲染由各 stage 模块的 `_render()` 函数处理（`stage0.py`、`stage1.py`、`stage2.py`、`stage3.py` 均包含相同的渲染逻辑）。

---

## 10. Development Roadmap

### Phase 0: Vertical Slice ✅
中控能启动 1 个 Claude CLI session，发送 prompt，接收输出，Dashboard 显示 session 状态。

### Phase 1: Stage 1 — 需求发现 ✅
- 主 Agent 灵感搜索 (WebSearch) + 人群展开 → JSON 输出 (含 scope + likely_product_types)
- 并行 Research Sessions (2 sub-agents: Search + Synthesis, 取消独立 Critic)
- 流式去重 (Research 完成后立即与卡片池比较) + Final Review Agent
- 简化证据格式 (描述性证据, 不要求完整 URL/日期/互动数据)
- Idea Card 新增外部依赖评估 section
- WebSocket Dashboard 实时监控

### Phase 1.5: Enhancements ✅
- **Run Mode Selection**: `--mode full/single/lite` + `--max-directions` 控制研究方向数量，方向裁剪优先 high relevance，卡片 ≤3 跳过 Dedup
- **Stage 0 Prompt Interpreter**: `--prompt`/`--prompt-file` 解析复杂赛题为 `HackathonBrief`，约束通过 `{{#hackathon_context}}` 条件块注入 Stage 1 prompts
- **ReviewGate**: 阶段间人工筛选，Dashboard UI（卡片网格+勾选+确认）+ CLI 回退，10分钟超时安全，`--skip-review` 跳过

### Phase 2: Stage 2 — PRD 生成 ✅
- 3-session 串行流水线 per card: concept → logic → technical
- Session 1 (Concept): 痛点验证 + 产品概念定义，可淘汰 (ELIMINATED.md)
- Session 2 (Logic): 功能模块分解 + 用户流程设计
- Session 3 (Technical): 技术栈 + 实现计划 + 设计 tokens
- 不同卡片并行，同一卡片3个 session 串行
- `--idea-card` 调试入口跳过 Stage 0+1

### Phase 3: Stage 3 — Demo 开发 ✅
- 3-session 串行流水线 per project: plan → dev → review
- Session A (Plan): 模块→页面映射 + Mock 数据定义 + 执行顺序 (不写代码)
- Session B (Dev): Scaffold → Shared Layer Agent → Page Coding Agents (按 wave 并行)
- Session C (Review): Designer Agent → Reviewer Agent → Fix → Final Verification
- Bounce-back: BUILD_FAILED 时重跑 B+C (max 1次)
- 成功标志: `demo/package.json`；失败标志: `BUILD_FAILED.md`
- `--prd-dir` 调试入口跳过 Stage 0+1+2
- Session B+C 共享工作目录；Session A 独立

### Phase 4: Stage 4 — GitHub 发布 ✅
- 纯确定性操作：README 生成 + git init + gh repo create + push
- 从 Stage 2 output 中读取 concept.md + technical.md 生成标准化 README
- 仓库命名: `hackathon-agent-{slug}`
- `--skip-publish` 跳过 Stage 4；`--private` 创建私有仓库
- 项目并行发布；单个失败不影响其他

### Phase 5: Stage 5 — Pitch Deck ✅
- 2-session serial pipeline per project: storyteller → deck builder
- Session 1 (Storyteller): reads PRD docs + demo source code, uses WebSearch for hook, writes pitch-script.md
- Session 2 (Deck Builder): converts pitch script to self-contained HTML slide deck (pitch-deck.html)
- Different projects parallel, same project 2 sessions serial
- Runs in parallel with Stage 4 via `asyncio.gather`
- `--skip-pitch` skips Stage 5

### Phase 6: Streaming Pipeline + Credential Overhaul ✅
- **Streaming pipeline**: per-card end-to-end flow (Stage 2→ConfigCheck→3→5→4) replaces batch stage execution
- **CredentialBarrier**: streaming-friendly credential check; satisfied projects proceed immediately, missing-cred projects wait for one-shot collection
- **3-layer credential resolution**: persistent store → system environment (os.environ) → interactive collection
- **Credential alias table**: maps AI-generated naming variants (GOOGLE_MAPS_API_KEY, GEMINI_API_KEY, etc.) to canonical names
- **Per-project credential filtering**: each project's .env only contains its own keys (least-privilege)
- **Shared slug generation**: `slugify_name()` in models.py prevents slug mismatch between ConfigGate and Stage 3
- **Direct credential passing**: main.py passes creds dict directly to Stage 3 (no file re-read)
- **Resume mode fix**: resume path reloads credentials from per-run file + system environment

### Phase 7: Polish ⬜
- 全流程端到端测试
- Dashboard 完善
- 错误处理与边界情况

---

## 11. Key Design Decisions

| 决策 | 选择 | 理由 |
|---|---|---|
| Agent 定位 | 独立参赛者 | 验证纯自动化可行性 |
| 需求发现路线 | 真实痛点 | Agent 缺乏创意直觉，痛点路线更结构化 |
| 筛选原则 | 只淘汰不挑选 | 保留最大可能性空间 |
| 并行策略 | 独立 session | 项目间无依赖，不需要协调 |
| 中控实现 | 脚本，非 Agent | 编排是确定性逻辑 |
| Dashboard | 监控+交互 (ReviewGate) | 观察为主，关键节点可干预 |
| 中控语言 | Python (asyncio) | 异步原生支持，subprocess 管理方便 |
| CLI 调用方式 | subprocess (`claude -p`) | 最简单直接，无需额外 SDK |
| Dashboard 实现 | 单文件 HTML + vanilla JS | 无构建工具，直接浏览器打开 |
| 编排方式 | 混合：阶段级中控 + 角色级 Agent tool | 兼顾可控性和灵活性 |
| 并发限制 | 最多 5 个并行 session | 保守策略，避免 rate limit |
| 权限模式 | `--dangerously-skip-permissions` | 自动化必须 |
| 输出格式 | `--output-format stream-json` | 支持实时推送 dashboard |
| 运行模式 | `full/single/lite` + `--max-directions` | 开发测试节省 token |
| 赛题解析 | 独立 Stage 0 + `HackathonBrief` | 结构化提取约束，不丢信息 |
| 人工筛选 | ReviewGate (Dashboard + CLI fallback) | 最早介入点，避免 token 浪费 |
| WebSocket 通信 | 双向 (`register_handler`) | 最小改动支持回传 |
| Stage 2 架构 | 3-session 串行流水线 (concept → logic → technical) | 产品导向: 问题→产品→技术，层间清晰分离 |
| Stage 2 淘汰点 | Session 1 (Concept) 的 self-review | 最早淘汰，避免浪费后续 session |
| Stage 3 架构 | 3-session 串行流水线 (plan → dev → review) | 规划与执行分离，review 独立 session 保证客观性 |
| Stage 3 bounce-back | BUILD_FAILED 时重跑 dev + review (max 1次) | 中控驱动重试，不依赖 session 内部循环 |
| Stage 3 工作目录 | Session B+C 共享，Session A 独立 | Review 需要访问 dev 产出的 demo/ 目录 |
| Stage 3 scaffold 工具 | coordinator 直接用 Bash，不 spawn sub-agent | 脚手架是确定性操作，不需要 AI 判断 |
| Stage 3 构建验证 | `npm run build` (非 `npm run dev`) | build 退出干净，dev 启动持久服务器会卡住 session |
| Stage 3 失败标志 | `BUILD_FAILED.md` | 类比 Stage 2 的 `ELIMINATED.md`，中控据此判断成败 |
| Stage 3 成功标志 | `demo/package.json` 存在 | 避免 rglob 扫描 node_modules/，只检查特定路径 |
| `--prd-dir` 调试入口 | 跳过 Stage 0+1+2，直接运行 Stage 3 | 接受目录 (含 concept/logic/technical.md)，便于单独测试 |
| Stage 4 实现 | 纯 shell 操作 (git/gh)，不用 AI session | 发布是确定性操作，不需要 AI 判断 |
| Stage 4 仓库命名 | `hackathon-agent-{slug}` | 统一前缀标注来源 |
| Stage 4 README | 从 Stage 2 concept.md + technical.md 生成 | 复用已有文档，保证一致性 |
| `--skip-publish` | 跳过 Stage 4 | 开发测试时不需要发布 |
| ConfigGate 实现 | 纯 Python 确定性逻辑，不用 AI session | 解析 markdown + diff 凭证 + CLI 提示，不需要 AI 判断 |
| 两层凭证架构 | 持久层 (project root) + 运行层 (workspace) | 持久层跨 run 积累，运行层只含当前 run 所需 |
| `--skip-config` | 跳过交互收集，只用持久层 | 自动化测试/CI 场景 |
| ConfigGate 阻止机制 | 缺少 carrier 依赖时阻止项目 | 避免浪费 Stage 3 token |
| Stage 5 pipeline position | Before Stage 4 | Pitch files copied into demo/ so Stage 4 includes them in GitHub repos |
| Stage 5 architecture | 2-session serial (storyteller → deck builder) | Narrative craft separate from visual design |
| Stage 5 demo access | Symlink demo/ into storyteller working dir | Session can read source code without copying |
| Pitch deck format | Self-contained HTML, no JS frameworks | Opens directly in browser, no build step |
| `--skip-pitch` | Skip Stage 5 | Dev/test mode doesn't need pitch decks |
| Streaming pipeline | Per-card end-to-end flow (Stage 2→3→5→4) | Eliminates stage-level synchronization barriers; faster card finishes first |
| CredentialBarrier | Replaces batch ConfigGate in full pipeline | Zero-blocking when all creds satisfied; one-shot collection when needed |
| 3-layer credential resolution | Persistent store → os.environ → interactive | Developers' existing shell env works automatically; minimal config |
| Credential alias table | Maps variant names to canonical (e.g. GEMINI_API_KEY → GOOGLE_API_KEY) | AI sessions independently pick env var names; alias prevents duplicate prompts |
| Per-project credential filtering | Each project's .env only contains its own keys | Least-privilege; avoids leaking unrelated credentials |
| Shared slugify_name | Single function in models.py used by all stages | Prevents slug mismatch between ConfigGate and Stage 3 |
| Direct credential passing | main.py passes creds dict to run_stage3, not re-read from file | Eliminates I/O dependency; single source of truth in memory |
| Batch mode preserved | --prd-dir, --resume, --idea-card still use stage-by-stage | Streaming only for full pipeline; simpler modes keep sequential logic |

---

## 12. Working Agreements & Gotchas

### 工作约定

- **All code, comments, and commit messages must be in English** — no exceptions
- **复杂功能先 plan 再实现**——用 plan mode 对齐方案后再写代码
- **Prompt 改动需要用户确认**——prompt 是核心资产，改动影响全局
- **每完成一个 Phase 做 checkpoint**——确认通过再进入下一阶段
- **CLI 行为不确定时先做 spike**——小规模验证再大规模使用

### 常见陷阱

- **中控不要用 AI 做判断**——编排逻辑必须是确定性的 if/then，不要调用 LLM 决定流程走向
- **Session 间不共享上下文**——不要尝试让一个 session 读取另一个 session 的对话历史
- **workspace/ 可能很大**——不要全量读取，只读需要的特定文件
- **注意 API rate limit**——控制并发数，用 Semaphore 限流
- **Prompt 不要假设先前上下文**——每个 session 从零开始，所有需要的信息必须在 prompt 中提供
- **不要在中控中硬编码 prompt 内容**——prompt 统一放在 `prompts/` 目录，运行时读取
- **用 .venv 运行**——系统 Python 有 PEP 668 限制，必须用 `.venv/bin/python`
