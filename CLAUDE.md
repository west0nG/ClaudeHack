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
| Phase 2: Stage 2 PRD 生成 | ⬜ 未开始 | |
| Phase 3: Stage 3 Demo 开发 | ⬜ 未开始 | |
| Phase 4: Polish | ⬜ 未开始 | |

---

## 3. Architecture

### 三阶段流水线

```
用户输入 (主题 + 方向)
    ↓
[Stage 1: 需求发现] → 10-20 Idea Cards
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
    ├── stages/ — 各阶段编排逻辑
    ├── 收集 session 产出 (文件系统)
    └── WebSocketServer — 广播状态 → dashboard.html (实时渲染)
```

### 关键原则

- **中控是确定性编排脚本，不是 AI**——流程编排是 if/then 逻辑，不需要 AI 判断
- **Session 间不共享上下文**——每个 Claude Code session 完全独立，避免信息污染
- **阶段间通过文件系统传递数据**——Idea Card / PRD 是 Markdown 文件，不是内存对象
- **混合编排**——阶段级由中控脚本驱动，角色级由 Claude Code 的 Agent tool 在 session 内部处理

### Stage 1 数据流

```
用户输入 (theme + optional interests)
    │
    ▼
[Main Agent Session] ── claude -p → 输出 JSON: 5-10 个人群方向
    │
    ▼
中控解析 JSON，为每个方向启动 session (最多5个并行)
    │
    ▼
[Research Session × N] ── 每个 session 内部用 Agent tool spawn:
    │  ├─ 模板搜索 sub-agent
    │  ├─ 自由搜索 sub-agent
    │  └─ Critic sub-agent
    │ 输出: 1-3 个 idea-card-*.md 文件/session
    ▼
中控收集所有 Idea Card 文件 → 复制到 dedup/input/
    │
    ▼
[Dedup Session] ── claude -p → 去重、质量过滤、排名
    │ 输出: workspace/stage1/output/idea-card-*.md
    ▼
最终产出: 10-20 个标准 Idea Card
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
│   ├── models.py                # 数据模型 (SessionConfig, SessionResult, Event, ...)
│   ├── event_bus.py             # 异步事件 pub/sub
│   ├── session_manager.py       # 核心：管理 claude CLI 子进程
│   ├── ws_server.py             # WebSocket 服务端
│   └── stages/
│       ├── __init__.py
│       └── stage1.py            # 阶段一完整逻辑
│
├── dashboard.html               # 单文件监控页面 (vanilla JS + WebSocket)
│
├── prompts/                     # ⭐ 核心资产：各角色 Prompt
│   └── stage1/
│       ├── main.md              # 主 Agent: 人群展开 → JSON 输出
│       ├── research.md          # Research Session (内部用 Agent tool 管理3个 sub-agent)
│       └── dedup.md             # 去重 + 质量过滤 Agent
│
├── templates/
│   └── idea-card.md             # Idea Card 模板
│
├── workspace/                   # ⚠️ 运行时产物，不进 git
│   └── stage1/
│       ├── main/                # 主 Agent 工作目录
│       ├── research-{slug}/     # 各 Research Session 工作目录
│       ├── dedup/input/         # 去重输入 (所有 raw idea cards)
│       ├── dedup/               # 去重 Agent 工作目录
│       └── output/              # 最终产出
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

# 运行 Stage 1
.venv/bin/python -m control.main --theme "AI + Education"

# 带兴趣方向
.venv/bin/python -m control.main --theme "AI + Education" --interests "学生,教师"

# 自定义参数
.venv/bin/python -m control.main --theme "Developer Tools" --max-concurrent 3 --ws-port 9000

# 不启动 Dashboard
.venv/bin/python -m control.main --theme "AI + Education" --no-dashboard
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

---

## 8. Event System

### 事件类型

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `stage_started` | 阶段开始 | stage, theme |
| `stage_completed` | 阶段结束 | stage, cards |
| `directions_found` | 人群方向解析完成 | count, directions[] |
| `session_started` | Session 启动 | session_id, model |
| `session_progress` | Session 进度更新 | session_id, activity |
| `session_completed` | Session 完成 | session_id, duration, files[] |
| `session_failed` | Session 失败 | session_id, error |
| `session_retrying` | Session 重试 | session_id, attempt |

### WebSocket 协议

```json
{"type": "session_started", "data": {"session_id": "research-students", "model": "sonnet"}, "timestamp": 1234567890.0}
{"type": "session_progress", "data": {"session_id": "research-students", "activity": "搜索: remote work pain points reddit"}, "timestamp": 1234567891.0}
```

Dashboard 通过 `ws://localhost:8765` 消费事件，新连接自动接收历史事件。

---

## 9. Prompt Engineering

### 文件组织 (Stage 1)

```
prompts/stage1/
├── main.md       # 输入: theme + interests → 输出: JSON 人群方向数组
├── research.md   # 输入: persona + pain_areas → 内部 spawn 3 sub-agents → 输出: idea-card-*.md
└── dedup.md      # 输入: 读取 input/*.md → 输出: 去重后写入 ../output/
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

模板渲染由 `control/stages/stage1.py:_render()` 处理。

---

## 10. Development Roadmap

### Phase 0: Vertical Slice ✅
中控能启动 1 个 Claude CLI session，发送 prompt，接收输出，Dashboard 显示 session 状态。

### Phase 1: Stage 1 — 需求发现 ✅
- 主 Agent 人群展开 → JSON 输出
- 并行 Research Sessions (内部 Agent tool 管理 sub-agents)
- Idea Card 收集 + 去重
- WebSocket Dashboard 实时监控

### Phase 2: Stage 2 — PRD 生成 ⬜
- 5 角色 PRD 生成流水线（Product → Technical → Critic → Pitch → Wireframe）
- 角色间循环与淘汰机制

### Phase 3: Stage 3 — Demo 开发 ⬜
- 并行项目开发 sessions
- 三层循环机制（自修复 → 屏幕级 Review → 集成检查）

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
| Dashboard | 纯观察，无干预 | 先验证核心命题 |
| 中控语言 | Python (asyncio) | 异步原生支持，subprocess 管理方便 |
| CLI 调用方式 | subprocess (`claude -p`) | 最简单直接，无需额外 SDK |
| Dashboard 实现 | 单文件 HTML + vanilla JS | 无构建工具，直接浏览器打开 |
| 编排方式 | 混合：阶段级中控 + 角色级 Agent tool | 兼顾可控性和灵活性 |
| 并发限制 | 最多 5 个并行 session | 保守策略，避免 rate limit |
| 权限模式 | `--dangerously-skip-permissions` | 自动化必须 |
| 输出格式 | `--output-format stream-json` | 支持实时推送 dashboard |

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
