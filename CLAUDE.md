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
| Phase 1: Stage 1 需求发现 | ✅ 已完成 | 完整流程：人群展开 → 并行 Research → 去重 |
| Phase 1.5: Enhancements | ✅ 已完成 | Run modes, Stage 0 prompt interpreter, ReviewGate |
| Phase 2: Stage 2 PRD 生成 | ✅ 已完成 | 单 coordinator prompt 管理 5 sub-agents，淘汰机制 |
| Phase 3: Stage 3 Demo 开发 | ✅ 已完成 | 单 coordinator prompt，7 步流水线，Vite + React 脚手架 |
| Phase 4: Polish | ⬜ 未开始 | |

---

## 3. Architecture

### 流水线

```
用户输入 (--theme / --prompt / --prompt-file)
    ↓
[Stage 0: 赛题解析] → HackathonBrief (--theme 时跳过)
    ↓
[Stage 1: 需求发现] → 10-20 Idea Cards
    ↓
[ReviewGate: 人工筛选] → 用户选择保留的 Cards (--skip-review 时跳过)
    ↓
[Stage 2: PRD 生成] → 5-7 份完整 PRD + HTML 线框图
    ↓
[Stage 3: Demo 开发] → 5-7 个可运行项目
```

### 组件关系

```
Python 中控脚本 (asyncio)
    ├── SessionManager — 启动/管理 Claude Code CLI sessions (subprocess)
    ├── EventBus — 异步事件发布/订阅
    ├── ReviewGate — 阶段间人工筛选 (Dashboard UI / CLI)
    ├── stages/ — 各阶段编排逻辑 (stage0, stage1, ...)
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
[Main Agent Session] ── claude -p → 输出 JSON: 5-10 个人群方向
    │
    ▼
中控解析 JSON → [可选] 按 max_directions 裁剪 (--mode single = 1)
    │
    ▼
[Research Session × N] ── 每个 session 内部用 Agent tool spawn:
    │  ├─ 模板搜索 sub-agent
    │  ├─ 自由搜索 sub-agent
    │  └─ Critic sub-agent
    │ 输出: 1-3 个 idea-card-*.md 文件/session
    ▼
中控收集所有 Idea Card 文件
    │
    ▼ (卡片 ≤ 3: 跳过 Dedup)
[Dedup Session] ── claude -p → 去重、质量过滤、排名
    │ 输出: workspace/stage1/output/idea-card-*.md
    ▼
[ReviewGate] → Dashboard UI / CLI → 用户筛选
    │ (--skip-review 时跳过)
    ▼
最终产出: 筛选后的 Idea Cards
```

### Stage 2 数据流

```
Idea Cards (from Stage 1 output or --idea-card)
    │
    ▼
中控为每张 Idea Card 启动 1 个 PRD Session (最多5个并行)
    │
    ▼
[PRD Session × N] ── 每个 session 内部用 Agent tool spawn 5 sub-agents:
    │  ├─ Product Agent → 选方向、设计 Demo Path (3层描述)
    │  ├─ Technical Agent → 验证可行性、定义技术栈 (↔ Product, max 2轮)
    │  ├─ Critic Agent → 验证是否解决原始痛点 (max 2次拒绝 → 淘汰)
    │  ├─ Pitch Agent → 优化叙事、Demo脚本
    │  └─ Wireframe Agent → 生成 HTML 线框图
    │ 输出: prd.md + wireframe.html (或 ELIMINATED.md)
    ▼
中控收集所有 PRD 文件 → 复制到 workspace/stage2/output/
    │
    ▼
最终产出: 5-7 个完整 PRD + HTML 线框图
```

### Stage 3 数据流

```
PRD files (from Stage 2 output or --prd)
    │
    ▼
中控为每份 PRD 启动 1 个 Dev Session (最多5个并行)
    │
    ▼
[Dev Session × N] ── 每个 session 内部执行 7 步流水线:
    │  ├─ Step 1: Planner Agent (sub-agent) → dev-plan.md
    │  ├─ Step 2: Scaffold (coordinator 直接执行) → npm create vite, install deps
    │  ├─ Step 3: Coding Agents (sub-agents, 按 wave 并行) → 每屏幕 1 个
    │  ├─ Step 4: Designer Agent (sub-agent) → 视觉一致性 + polish
    │  ├─ Step 5: Reviewer Agent (sub-agent) → review.md (PASS / ISSUES_FOUND)
    │  ├─ Step 6: Fix Issues (条件触发, max 2 cycles)
    │  └─ Step 7: Final Verification → README.md 或 BUILD_FAILED.md
    │ 输出: demo/ 目录 (含 package.json) 或 BUILD_FAILED.md
    ▼
中控收集所有项目目录
    │
    ▼
最终产出: 5-7 个可运行的 Demo 项目
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
│   └── stages/
│       ├── __init__.py
│       ├── stage0.py            # 阶段零：Prompt 解析器
│       ├── stage1.py            # 阶段一完整逻辑
│       ├── stage2.py            # 阶段二：PRD 生成编排
│       └── stage3.py            # 阶段三：Demo 开发编排
│
├── dashboard.html               # 单文件监控页面 (vanilla JS + WebSocket + ReviewGate UI)
│
├── prompts/                     # ⭐ 核心资产：各角色 Prompt
│   ├── stage0/
│   │   └── interpreter.md       # Prompt 解析 Agent
│   ├── stage1/
│   │   ├── main.md              # 主 Agent: 人群展开 → JSON 输出
│   │   ├── research.md          # Research Session (内部用 Agent tool 管理3个 sub-agent)
│   │   └── dedup.md             # 去重 + 质量过滤 Agent
│   ├── stage2/
│   │   └── prd.md               # PRD Session (内部用 Agent tool 管理5个 sub-agent)
│   └── stage3/
│       └── dev.md               # Dev Session (7步流水线: Planner→Scaffold→Coding→Designer→Reviewer→Fix→Final)
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
│   │   ├── {card-slug}/         # 各 PRD Session 工作目录
│   │   └── output/              # 最终产出 (prd-*.md + prd-*-wireframe.html)
│   └── stage3/
│       └── {prd-slug}/          # 各 Dev Session 工作目录
│           └── demo/            # 产出项目 (含 package.json, src/, README.md)
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

# Debug: skip to Stage 3 with a single PRD file
.venv/bin/python -m control.main --prd workspace/stage2/output/prd-xxx.md
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
| `prd_completed` | PRD 生成完成 | session_id, prd_file, has_wireframe |
| `prd_eliminated` | Idea Card 被淘汰 | session_id, reason |
| `prd_failed` | PRD 生成失败 | session_id, error |
| `dev_completed` | Demo 项目构建成功 | session_id, project_dir, has_readme |
| `dev_failed` | Demo 构建失败或 session 失败 | session_id, error |

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
│   ├── research.md       # 输入: persona + pain_areas + hackathon_context → 内部 spawn 3 sub-agents → 输出: idea-card-*.md
│   └── dedup.md          # 输入: 读取 input/*.md → 输出: 去重后写入 ../output/
├── stage2/
│   └── prd.md            # 输入: idea_card_content + theme → 内部 spawn 5 sub-agents → 输出: prd.md + wireframe.html
└── stage3/
    └── dev.md            # 输入: prd_content + theme → 7步流水线 → 输出: demo/ 项目 或 BUILD_FAILED.md
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
- `{{raw_prompt}}` — 原始赛题文本（Stage 0）
- `{{hackathon_context}}` — 约束/评审标准/限制文本块（Stage 1，由 `HackathonBrief.render_context_block()` 生成）
- `{{idea_card_content}}` — Idea Card 全文（Stage 2）
- `{{prd_content}}` — PRD 全文（Stage 3）

条件块 `{{#hackathon_context}}...{{/hackathon_context}}`：当 `hackathon_context` 非空时展开，为空时整个块被移除。

模板渲染由各 stage 模块的 `_render()` 函数处理（`stage0.py`、`stage1.py`、`stage2.py`、`stage3.py` 均包含相同的渲染逻辑）。

---

## 10. Development Roadmap

### Phase 0: Vertical Slice ✅
中控能启动 1 个 Claude CLI session，发送 prompt，接收输出，Dashboard 显示 session 状态。

### Phase 1: Stage 1 — 需求发现 ✅
- 主 Agent 人群展开 → JSON 输出
- 并行 Research Sessions (内部 Agent tool 管理 sub-agents)
- Idea Card 收集 + 去重
- WebSocket Dashboard 实时监控

### Phase 1.5: Enhancements ✅
- **Run Mode Selection**: `--mode full/single/lite` + `--max-directions` 控制研究方向数量，方向裁剪优先 high relevance，卡片 ≤3 跳过 Dedup
- **Stage 0 Prompt Interpreter**: `--prompt`/`--prompt-file` 解析复杂赛题为 `HackathonBrief`，约束通过 `{{#hackathon_context}}` 条件块注入 Stage 1 prompts
- **ReviewGate**: 阶段间人工筛选，Dashboard UI（卡片网格+勾选+确认）+ CLI 回退，10分钟超时安全，`--skip-review` 跳过

### Phase 2: Stage 2 — PRD 生成 ✅
- 单 coordinator prompt (`prd.md`) 内部用 Agent tool 管理 5 sub-agents
- 5 角色 PRD 生成流水线（Product → Technical → Critic → Pitch → Wireframe）
- Product ↔ Technical 反馈循环 (max 2 轮)，Critic 淘汰机制 (max 2 次拒绝 → ELIMINATED.md)
- `--idea-card` 调试入口跳过 Stage 0+1

### Phase 3: Stage 3 — Demo 开发 ✅
- 单 coordinator prompt (`dev.md`) 内部执行 7 步流水线
- Planner → Scaffold (Vite+React+Tailwind) → Coding Agents (按 wave 并行) → Designer → Reviewer → Fix → Final
- Coding Agent 自修复循环 (build + fix, max 5x)，Reviewer 集成检查 (max 2 cycles)
- 成功标志: `package.json`；失败标志: `BUILD_FAILED.md`
- `--prd` 调试入口跳过 Stage 0+1+2
- Session 参数: timeout 1h, budget $10, allowed_tools 含 Bash

### Phase 4: Polish ⬜
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
| Stage 2 prompt 模式 | 单 coordinator prompt (`prd.md`) | 与 Stage 1 research.md 模式一致，session 内部管理 sub-agents |
| Stage 3 prompt 模式 | 单 coordinator prompt (`dev.md`) | 同上，7步流水线在 session 内部编排 |
| Stage 3 scaffold 工具 | coordinator 直接用 Bash，不 spawn sub-agent | 脚手架是确定性操作，不需要 AI 判断 |
| Stage 3 超时 | 3600s (1 小时) | Demo 开发含多轮 build+fix，需要更长时间 |
| Stage 3 预算 | $10/session | 开发任务 token 消耗显著高于 PRD |
| Stage 3 构建验证 | `npm run build` (非 `npm run dev`) | build 退出干净，dev 启动持久服务器会卡住 session |
| Stage 3 失败标志 | `BUILD_FAILED.md` | 类比 Stage 2 的 `ELIMINATED.md`，中控据此判断成败 |
| Stage 3 成功标志 | `demo/package.json` 存在 | 避免 rglob 扫描 node_modules/，只检查特定路径 |
| `--prd` 调试入口 | 跳过 Stage 0+1+2，直接运行 Stage 3 | 同 `--idea-card` 模式，便于单独测试 |

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
