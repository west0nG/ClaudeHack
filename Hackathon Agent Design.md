# Hackathon Agent — System Design Document

## 1. 项目概述

### 1.1 核心理念

Hackathon Agent 是一个完全自主的 AI 黑客松参赛系统。它不是辅助人类参赛的工具，而是**独立参赛的选手**——从发现需求、定义问题、编写产品方案，到完成 Demo 开发，全程由 Agent 主导，用户仅作为观察者在关键节点进行 proof。

### 1.2 核心命题

验证纯 Agent 自动化能否端到端跑通一个复杂度较高的黑客松项目流程，最终同时产出 5-7 个可运行的独立项目。

### 1.3 用户输入

支持两种输入模式：

**简单模式**（`--theme`）：
- **Hackathon 主题约束**（必填）：如 "AI + Climate"、"Crypto"、"Developer Tools" 等
- **用户感兴趣的方向**（可选）：如 "教育"、"医疗"、"生产力工具" 等。不提供时由 Agent 自主发散

**完整模式**（`--prompt` / `--prompt-file`）：
- **原始 Hackathon 赛题**：多段落的完整赛题文本，包含规则、约束、评审标准、赞助商奖项等
- 由 Stage 0（Prompt Interpreter）自动解析为结构化的 `HackathonBrief`，提取主题、约束、限制、评审标准等

### 1.4 最终产出

5-7 个独立的 GitHub 仓库，每个仓库包含：

- 可运行的项目 Demo 代码
- 产品方案文档（concept.md + logic.md + technical.md）

各项目之间完全独立，无任何关联，可分别参加不同的黑客松。

---

## 2. 整体架构

### 2.1 四阶段流水线

```
用户输入 → [阶段零：赛题解析] → [阶段一：需求发现] → [人工筛选] → [阶段二：PRD 生成] → [阶段三：Demo 开发] → 5-7 个 GitHub 仓库
```

- **阶段零**（可选）：解析复杂赛题为结构化 Brief（简单 `--theme` 模式跳过此阶段）
- **阶段一**：产出 10-20 个 Idea Card
- **人工筛选**（ReviewGate）：用户在 Dashboard 或 CLI 中选择要保留的 Idea Card
- **阶段二**：通过 3 层递进 session 深化为 5-7 套产品方案文档（concept + logic + technical）
- **阶段三**：并行开发 5-7 个可运行 Demo

### 2.2 中控架构

整个系统由一个**Python 中控脚本**（asyncio）驱动，而非 AI Agent。

中控脚本负责：

- **Session 管理** (`SessionManager`)：启动、监控、收集各阶段的 Claude Code CLI session
- **阶段流转** (`stages/`)：阶段零赛题解析 → 阶段一需求发现 → 人工筛选 → 阶段二 PRD → 阶段三开发
- **人工筛选** (`ReviewGate`)：阶段间暂停等待用户确认，支持 Dashboard UI 和 CLI 两种模式
- **事件系统** (`EventBus`)：异步事件发布/订阅，解耦组件
- **状态广播** (`WebSocketServer`)：双向 WebSocket 通信——向 Dashboard 推送状态，接收用户操作（如 ReviewGate 选择）

**编排方式：混合模式**
- **阶段级编排**由中控脚本驱动（确定性 if/then 逻辑）
- **角色级协作**由 Claude Code session 内部通过 Agent tool 自行管理（如 Research session 内部 spawn 模板搜索、自由搜索、Critic 三个 sub-agent）

选择脚本而非 Agent 做中控的原因：流程编排是完全确定性的逻辑（if/then），不需要 AI 判断，用 Agent 做既浪费 token 又不可靠。

### 2.3 并行策略

- 所有并行任务使用**独立的 Claude Code session**
- 并行任务之间**不共享上下文**，避免信息污染
- 阶段一：10-20 个并行 research session
- 阶段二：每张 Idea Card 3 个串行 session，不同 Card 间并行（Semaphore 控制）
- 阶段三：每份 PRD 3 个串行 session（Plan → Dev → Review），不同项目间并行（Semaphore 控制）

### 2.4 Dashboard ✅ 已实现

同时具备**监控**和**交互**能力的单页面。

展示三个层面的信息：

- **全局视角**：当前阶段、Session 数量、完成/失败计数、Idea Card 数量
- **Session 视角**：每个 session 的状态卡片（pending / running / completed / failed / retrying），显示实时活动摘要
- **关键事件流**：右侧时间线形式展示所有事件

交互能力：

- **ReviewGate 面板**：阶段一完成后自动弹出，展示 Idea Card 摘要（标题、场景片段、证据数量、解决方向），支持勾选/取消勾选，全选/全不选，确认后通过 WebSocket 回传选择结果

技术实现：单文件 `dashboard.html`（vanilla JS + WebSocket），无构建工具，直接浏览器打开。双向 WebSocket 通信（`ws://localhost:8765`），支持断线自动重连，新连接自动接收历史事件。

---

## 3. 阶段零：赛题解析（Stage 0）✅ 已实现

### 3.1 目标

将复杂的 Hackathon 赛题文本解析为结构化的 `HackathonBrief`，供后续阶段使用。

### 3.2 触发条件

- 使用 `--prompt` 或 `--prompt-file` 输入时触发
- 使用 `--theme` 简单模式时**跳过**，直接生成最小 `HackathonBrief`（只含 theme 字段）

### 3.3 数据模型：HackathonBrief

```python
@dataclass
class HackathonBrief:
    theme: str                       # "AI + Education"
    theme_description: str           # 2-3 句描述
    constraints: list[str]           # 硬性约束（"必须使用 X API"）
    evaluation_criteria: list[str]   # 评审标准及权重
    restrictions: list[str]          # 明确禁止项
    special_requirements: list[str]  # 赞助商奖项、特殊赛道
    suggested_directions: list[str]  # 赛题建议的探索方向
    raw_prompt: str                  # 原始赛题文本
    time_limit: str | None           # 比赛时长
    team_size: str | None            # 团队规模
    target_audience: str | None      # 目标受众
```

### 3.4 流程

```
原始赛题文本 (--prompt / --prompt-file)
    ↓
[Interpreter Session] ── claude -p → 输出 JSON: HackathonBrief
    ↓
中控解析 JSON → 构建 HackathonBrief 对象
    ↓
Brief 的 constraints/criteria/restrictions 渲染为文本块
    ↓
注入阶段一的 main.md 和 research.md（通过 {{#hackathon_context}} 条件块）
```

### 3.5 约束传递

`HackathonBrief.render_context_block()` 将约束、评审标准、限制渲染为人类可读的文本块，通过模板条件块 `{{#hackathon_context}}...{{/hackathon_context}}` 注入阶段一的 Prompt。当使用简单 `--theme` 模式时，`hackathon_context` 为空字符串，条件块被移除。

---

## 4. 阶段一：需求发现

### 4.1 目标

从 hackathon 主题出发，自主发现真实用户痛点，产出 10-20 个有证据支撑的 Idea Card。

### 4.2 核心设计原则

- Agent 没有"身体性"和生活经验，因此必须先**选人群**（模拟谁的视角），再找痛点
- 聚焦**真实用户痛点**路线，不走"做有趣的东西"路线
- 寻找的是"痛点假设"而非"已验证的痛点"——有证据支撑即可，不需要百分百确认
- 只做筛选（淘汰明显不行的），不做挑选（不主观排序）

### 4.3 Agent 编排

#### 4.3.1 主 Agent

由一个 Claude Code session 完成以下工作：

- **人群展开**：根据主题列出相关角色和人群（5-10 个方向）
- **粗筛**：排除明显不适合 hackathon 的方向

粗筛标准：

- **可理解性**：评委能否在 30 秒内理解这个痛点
- **痛感共鸣度**：是否能引起广泛共鸣
- **排除项**：需要法律合规、银行合作、硬件依赖等 hackathon 明显做不了的方向

此步骤不需要搜索，靠 Agent 自身知识完成。

#### 4.3.2 Research Sessions（每个人群方向 × 1）✅ 已实现

**实现决策变更**：原设计为中控分别启动 2 research + 1 critic 共 3 个 session。实际实现改为每个方向启动 **1 个 Research session**，session 内部通过 Claude Code 的 **Agent tool** 自行 spawn 3 个 sub-agent：

**Sub-Agent 1: 模板搜索**（通过 Agent tool）
- 使用结构化关键词组合搜索
- Reddit、HackerNews、Twitter/X 等平台
- 查找投诉、变通方法、"I wish..." 帖子、统计数据

**Sub-Agent 2: 自由搜索**（通过 Agent tool）
- 开放式探索，不限于假设的痛点
- 寻找模板搜索可能遗漏的意外方向

**Sub-Agent 3: Critic**（通过 Agent tool）
- 读取前两个 sub-agent 的产出
- 质疑证据真实性和时效性
- 评估严重性、频率、现有方案
- 建议最强的痛点和更好的框定方式

> **变更理由**：让 Claude Code session 自己管理 sub-agent 的生命周期更自然——它能在内部协调循环、共享文件上下文，减少中控脚本的复杂度。

每个 Research session 产出 1-3 个 `idea-card-*.md` 文件。

#### 4.3.3 去重 Agent ✅ 已实现

独立的 Dedup session（`prompts/stage1/dedup.md`）：

- 读取所有 Research session 产出的 Idea Card（中控复制到 `dedup/input/`）
- 合并重复、淘汰证据不足的
- 如果 Dedup session 失败，中控会 fallback 使用 raw cards

### 4.4 运行模式 ✅ 已实现

支持三种运行模式，通过 `--mode` 控制：

| 模式 | 行为 | 用途 |
|------|------|------|
| `full`（默认）| 所有方向并行研究 | 生产环境 |
| `single` | 只取 1 个方向 | 开发测试，节省约 80% tokens |
| `lite` | 所有方向串行执行 | 调试 |

另外支持 `--max-directions N` 精确控制方向数量。

**方向裁剪逻辑**：
- 优先保留 `relevance: "high"` 的方向
- 同优先级按 slug 字母序排序
- 裁剪后方向数 <= 3 时，跳过 Dedup Agent（卡片太少没必要去重）

### 4.5 Session 规模（实际）

假设 7 个人群方向：
- 1 个主 Agent session
- 7 个 Research sessions（每个内部 spawn 3 个 sub-agent）
- 1 个 Dedup session
- 共 9 个 Claude Code sessions（最多 5 个并行，由 Semaphore 控制）

### 4.6 阶段一产出

10-20 个标准格式的 Idea Card 文件，存放于汇总目录。

---

## 5. 人工筛选：ReviewGate ✅ 已实现

### 5.1 目标

阶段一完成后暂停流水线，让人类审查 Idea Card 并决定哪些进入阶段二。

### 5.2 设计理由

AI 可能高估某些想法的可行性——人类一眼就能看出的不靠谱点，AI 往往信心满满地通过。增加人工筛选可以在早期阶段避免浪费后续大量 token。

### 5.3 两种交互模式

**Dashboard 模式**（默认）：
- 阶段一完成后，中控发送 `review_requested` 事件
- Dashboard 自动展示 Review 面板：卡片网格，每张卡显示标题、场景摘要（150 字）、证据数量、解决方向
- 每张卡默认勾选，用户取消勾选不需要的卡片
- 点击 "Confirm Selection" → 通过 WebSocket 回传 `{type: "review_selection", selected_indices: [0,1,3]}`
- 中控收到选择后恢复流水线

**CLI 模式**（`--no-dashboard` 时）：
- 在终端打印卡片编号和摘要
- 用户输入逗号分隔的编号（如 `0,1,3`）或 `all`
- 超时 10 分钟自动保留全部卡片

### 5.4 跳过筛选

`--skip-review` 跳过 ReviewGate，自动保留所有卡片（用于全自动运行）。

### 5.5 事件

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `review_requested` | 卡片就绪等待审查 | `{cards: [{index, title, scenario_excerpt, evidence_count, solution_directions}]}` |
| `review_completed` | 用户确认选择 | `{selected: int, total: int}` |

---

## 6. 中间产物：Idea Card 格式

```markdown
# Idea Card: [简短标题]

## 具体场景

[一个真实的、有画面感的用户故事。谁、在什么情境下、遇到什么具体的困难、现在怎么凑合解决的。来自搜索到的真实抱怨，由 Agent 加工成连贯叙事。]

## 证据

- [来源1]：[平台名称 + 链接 + 简要描述]
- [来源2]：[平台名称 + 链接 + 简要描述]
- ...

## 现有方案及不足

[市面上有什么解决方案、做得怎么样、用户评价如何、明显缺陷在哪里。如果没有现有方案则说明原因。]

## 解决方向

### 方向一：[名称]
[一两句话描述] ⭐ 推荐度：高/中/低
推荐理由：[为什么 Agent 认为这个方向最有潜力]

### 方向二：[名称]
[一两句话描述] ⭐ 推荐度：高/中/低

### 方向三：[名称]（可选）
[一两句话描述] ⭐ 推荐度：高/中/低

> 注意：以上推荐排序仅为初步判断，不是定论。PRD 阶段应重新评估所有方向。
```

---

## 7. 阶段二：PRD 生成 ⬜ Redesigned (not yet implemented)

### 7.1 目标

对筛选后的 Idea Card 并行深入，通过 3 个递进层次的独立 session 完成产品定义，淘汰不可行的，为存活的 5-7 个各自生成完整的产品方案文档。

### 7.2 核心设计原则

- **产品导向**：先把问题想清楚、把产品设计好，Pitch 是后续包装的事（不再在 PRD 阶段考虑演示效果）
- **按功能模块组织**：不再按页面/屏幕拆分，而是按功能模块组织产品定义
- **按抽象层次递进**：概念层 → 逻辑层 → 物理层，从粗到细，每一层产出自包含文档
- **Demo 呈现真实效果**：产品本身设计好了，Demo 自然能展示价值，不需要刻意编排演示路径

> **原方案问题**：原方案本质上是"倒着写 PRD"——从演示效果倒推产品设计。PRD 按屏幕/页面组织，实际是在写 demo 脚本；Pitch Agent 参与产品设计阶段，演示效果的考量侵入了产品决策；产出偏向"怎么展示"而非"解决什么问题"。

### 7.3 Agent 架构：3 个串行独立 Session

每张 Idea Card 由 3 个**串行的独立 Claude Code session** 处理（替代原来的单 session + 5 sub-agent 模式）：

```/
Session 1（产品定义）
  输入：Idea Card
  步骤：
    1. 验证痛点 — 基于 Idea Card 的场景和证据，判断痛点是否成立
    2. 找产品 Idea — 从 Idea Card 的 2-3 个解决方向中选择/组合/改进
    3. 概念层定义 — 产品是什么、为谁、核心价值主张、边界
    4. 自审 — 概念层是否真正解决痛点、边界是否合理
  产出：concept.md（或 ELIMINATED.md 淘汰）
      ↓ 中控传递 concept.md
Session 2（产品设计）
  输入：concept.md + 原始 Idea Card
  步骤：
    1. 功能模块划分 — 每个模块解决什么子问题
    2. 模块间关系与数据流
    3. 用户流程 — 从进入到完成核心任务的路径
  产出：logic.md
      ↓ 中控传递 concept.md + logic.md
Session 3（技术方案）
  输入：concept.md + logic.md
  步骤：
    1. 技术栈选择
    2. 每个功能模块的实现方案
    3. API 设计、数据结构
    4. 项目架构
  产出：technical.md
```

### 7.4 角色变更对照

| 原角色 | 新方案处理 | 理由 |
|--------|-----------|------|
| Product Agent | → Session 1 + Session 2 | 拆为概念层和逻辑层两个阶段 |
| Technical Agent | → Session 3 | 独立 session，专注技术方案 |
| Critic Agent | → Session 1 内部自审步骤 | 不再独立角色，概念层定完后自审 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示，产品导向 |
| Wireframe Agent | **删除** | PRD 阶段不做线框图，交给 Stage 3 |

### 7.5 Session 切分理由

按三个原则切分 session 边界：

1. **信息耦合度**：步骤 1-3（验证痛点 → 找 Idea → 概念层）思维高度连贯，必须在同一 session
2. **任务性质变化**：概念层（产品定义）→ 逻辑层（产品设计）→ 物理层（技术方案），每次切换都是思维模式的转变
3. **天然切分点**：每个 session 的产出都是结构化的自包含文档，可以作为下一个 session 的独立输入

### 7.6 淘汰机制

- **Session 1 自审不通过** → 写 `ELIMINATED.md`，中控跳过后续 session
  - 痛点不成立（证据不足、场景不真实）
  - 找不到合理的产品方案
  - 已有成熟方案完全解决了该痛点
- Session 2、Session 3 的淘汰/自审机制 → **待定**（见 7.10 待讨论事项）

### 7.7 阶段二产出

每个存活的 Idea 产出 3 份按抽象层次组织的独立文档：

| 文档 | 内容 | 主要消费者 |
|------|------|-----------|
| `concept.md` | 产品定义、核心价值、目标用户、边界 | Stage 3 所有 agent（作为背景参考） |
| `logic.md` | 功能模块、数据流、用户流程 | Stage 3 Session A (Planner) / Session B (Dev) |
| `technical.md` | 技术栈、实现方案、项目架构 | Stage 3 技术类 agent（主要 context） |

### 7.8 中控编排

每张 Idea Card → 3 个串行 Claude Code session（中控依次调度）。不同 Idea Card 之间仍然可以并行（Semaphore 控制），但同一张卡的 3 个 session 必须串行。

```python
# 伪代码
for card in idea_cards:
    # Session 1: 产品定义
    result1 = await session_mgr.run(concept_session_config(card))
    if is_eliminated(result1):
        emit("prd_eliminated", card)
        continue

    # Session 2: 产品设计
    result2 = await session_mgr.run(logic_session_config(card, concept_md))

    # Session 3: 技术方案
    result3 = await session_mgr.run(technical_session_config(card, concept_md, logic_md))

    # 收集三份文档
    collect_outputs(card, concept_md, logic_md, technical_md)
```

### 7.9 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| Session 1（产品定义）| 600s (10min) | $3 | 验证痛点 + 找 Idea + 概念层 + 自审 |
| Session 2（产品设计）| 600s (10min) | $3 | 功能模块 + 数据流 + 用户流程 |
| Session 3（技术方案）| 600s (10min) | $3 | 技术栈 + 实现方案 + 架构 |
| **单卡总计** | **1800s** | **$9** | 原方案 1800s / $5 |


### 7.10 待讨论事项

以下事项在本次设计改造中暂未确定，需后续补充：

1. **Session 2 和 Session 3 是否带内部自审**
2. **三份文档的具体格式模板**（concept.md / logic.md / technical.md 各包含哪些字段）
3. **Prompt 文件组织**（是 3 个独立 prompt 文件还是其他形式）
4. **失败处理与重试策略**（单个 session 失败时是否重试、如何重试）

---

## 8. 中间产物：产品方案文档格式 ⬜ Redesigned

阶段二产出 3 份按抽象层次组织的独立文档（替代原来的单一 PRD + HTML 线框图）。

> **注意**：以下为文档结构框架。各文档的详细字段模板待定（见 Section 7.10 待讨论事项 #2）。

### 8.1 concept.md — 产品定义（概念层）

```markdown
# Concept: [产品名称]

## 痛点验证
[痛点是什么、证据是否成立、场景是否真实]

## 产品定义
[一句话描述：这个产品是什么、解决谁的什么问题]

## 核心价值主张
[用户为什么要用这个产品、与现有方案的关键差异]

## 目标用户
[具体用户画像、使用场景]

## 产品边界
[做什么、不做什么、MVP 范围]

## 选择的解决方向
[从 Idea Card 的 2-3 个方向中选择/组合/改进的结果及理由]
```

### 8.2 logic.md — 产品设计（逻辑层）

```markdown
# Logic: [产品名称]

## 功能模块
### 模块一：[名称]
[解决什么子问题、核心功能点]

### 模块二：[名称]
[解决什么子问题、核心功能点]

...

## 模块关系与数据流
[模块间如何协作、数据如何流转]

## 用户流程
[从进入产品到完成核心任务的完整路径]
```

### 8.3 technical.md — 技术方案（物理层）

```markdown
# Technical: [产品名称]

## 技术栈
- 框架：[如 React + Vite]
- UI 库：[如 Tailwind CSS]
- 关键依赖：[如 OpenAI API、Supabase 等]

## 功能模块实现方案
### 模块一：[名称]
[实现方式、关键技术点]

### 模块二：[名称]
[实现方式、关键技术点]

...

## API 设计与数据结构
[接口定义、数据模型]

## 项目架构
[目录结构、文件组织]
```

---

## 9. 阶段三：Demo 开发 ⬜ Redesigned (not yet implemented)

### 9.1 目标

将 5-7 套产品方案文档（concept.md + logic.md + technical.md）并行开发为可运行的 Demo，每个项目产出一个完整的、核心功能能跑通的应用。

### 9.2 核心设计原则

- **Demo 优先原则**：能用 mock 数据就不接真实 API；能硬编码就不做配置化；不做边界情况处理；不做用户体系；只实现核心功能路径上的功能
- 核心功能必须真正 work，纯静态页面不够
- 5-7 个项目完全独立，不同项目间可并行，不需要任何协调

### 9.3 Agent 架构：3 个串行独立 Session

每份 PRD（三文档）由 3 个**串行的独立 Claude Code session** 处理（替代原来的单 session + 7 步流水线模式）：

```
Session A（规划）
  输入：concept.md + logic.md + technical.md
  步骤：
    Planner — 读三份文档，产出开发计划
      - 功能模块 → 页面的映射关系
      - 页面列表及每个页面的职责描述
      - 页面间的依赖关系（决定并行/串行）
      - 共享层定义（公共组件、全局状态、工具函数等）
  产出：dev-plan.md

      ↓ 中控传递 dev-plan.md

Session B（开发）
  输入：dev-plan.md + concept.md + logic.md + technical.md
  步骤：
    1. Scaffold — 脚手架初始化（npm create vite 等确定性操作）
    2. Shared Layer Agent — 公共组件、全局状态、API 层、工具函数
    3. Page Coding Agents — 按页面分配，按依赖关系并行/串行
       每个 Coding Agent 内部自修复循环（build + fix，上限 5 次）
  产出：可构建的完整项目代码

      ↓ 中控传递项目代码

Session C（审查）
  输入：项目代码 + dev-plan.md + concept.md
  步骤：
    1. Designer Agent — 视觉一致性检查
    2. Reviewer Agent — 功能检查 + 端到端验证
    3. Fix Issues — 发现问题则在 Session C 内部修复（上限 2 次）
    4. Final Verification — 最终构建验证
  产出：通过验证的项目（或 BUILD_FAILED.md）

  如果 Session C 内部修不好 → 打回 Session B 针对性修复 → 再跑 Session C（最多打回 1 次）
```

### 9.4 关键设计决策

**Planner 的任务拆分方式：混合模式**
- PRD 按功能模块组织（产品逻辑），但最终开发产出是有页面的应用（工程实现）
- Planner 负责做桥接：功能模块 → 页面映射
- Coding Agent 按页面分配，但每个 agent 拿到的上下文包含"这个页面涉及哪些功能模块"

**共享层由独立 Coding Agent 先做**
- 全局状态、公共组件、API 层等跨页面复用的部分
- 先于所有 Page Agent 完成，确保依赖关系清晰
- Page Agent 基于共享层开发

**Scaffold 放在 Session B**
- Session A 纯规划不碰代码
- Session B 从脚手架初始化开始，完整负责所有代码产出

**Review 保留 Designer + Reviewer 两个角色**
- Designer 关注视觉一致性
- Reviewer 关注功能正确性 + 端到端验证
- 关注点不同，分开更清晰

### 9.5 三层循环机制

| 循环层级 | 位置 | 上限 | 触发条件 |
|----------|------|------|----------|
| Coding Agent 自修复 | Session B 内部 | 5 次 | build 失败 |
| Session C 内部修复 | Session C 内部 | 2 次 | Designer/Reviewer 发现问题 |
| Session C → B 打回 | 中控编排 | 1 次 | Session C 内部修不好 |

**关键原则：循环范围尽量小。** Session B 内部的 build 错误不需要打回 Session A；Session C 能修的不打回 Session B。

失败处理：打回 1 次后仍修不好 → 写 `BUILD_FAILED.md`

### 9.6 执行顺序

```
Session A: Planner → dev-plan.md
    ↓
Session B:
  Scaffold 初始化
    ↓
  Shared Layer Agent → 公共组件、全局状态、API 层
    ↓
  Page Coding Agents（按依赖关系并行/串行）
    - 每个 Agent 内部自修复循环 (build + fix, 上限 5 次)
    ↓
Session C:
  Designer Agent → 视觉一致性检查
    ↓
  Reviewer Agent → 功能检查 + 端到端验证
    ↓
  [条件] 发现问题 → Fix Issues (上限 2 次)
    ↓
  Final Verification → 通过 / BUILD_FAILED.md
    ↓
  [条件] 修不好 → 打回 Session B (最多 1 次) → 再跑 Session C
```

### 9.7 中控编排

每份 PRD → 3 个串行 Claude Code session（中控依次调度）。不同项目之间仍然可以并行（Semaphore 控制），但同一个项目的 3 个 session 必须串行。

```python
# 伪代码
for prd in prd_docs:
    # Session A: 规划
    result_a = await session_mgr.run(plan_session_config(prd))
    dev_plan_md = find_output(result_a, "dev-plan.md")

    # Session B: 开发
    result_b = await session_mgr.run(dev_session_config(prd, dev_plan_md))

    # Session C: 审查
    result_c = await session_mgr.run(review_session_config(prd, dev_plan_md))

    if needs_bounceback(result_c):
        # 打回 Session B 针对性修复
        result_b2 = await session_mgr.run(dev_fix_session_config(prd, result_c))
        result_c2 = await session_mgr.run(review_session_config(prd, dev_plan_md))

    collect_project_outputs(prd, work_dir)
```

### 9.8 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| A（规划）| 300s (5min) | $2 | 纯文本规划，不写代码 |
| B（开发）| 2400s (40min) | $8 | scaffold + 共享层 + 多页面开发 + 自修复 |
| C（审查）| 1200s (20min) | $5 | review + 可能的修复 |
| **单项目总计** | **3900s** | **$15** | 原方案 3600s / $10 |
| **最坏情况（含 1 次打回）** | **~7500s** | **~$28** | 额外 B + C |

*注：先按此分配，跑起来再调。*

### 9.9 实现说明

> **⚠️ 待实现**：以下为设计方案，尚未编码实现。

**Prompt 文件**：3 个独立 prompt 文件（替代原来的单一 `dev.md`）

| Prompt 文件 | Session | 职责 |
|------------|---------|------|
| `prompts/stage3/plan.md` | Session A | Planner：读三份文档，产出 dev-plan.md |
| `prompts/stage3/dev.md` | Session B | Scaffold + Shared Layer Agent + Page Coding Agents |
| `prompts/stage3/review.md` | Session C | Designer + Reviewer + Fix + Final Verification |

**⚠️ 待适配**：
- `prompts/stage3/dev.md` 需要从原来的单 coordinator 7 步流水线 prompt 重构为仅负责 Session B 的开发 prompt
- 新增 `prompts/stage3/plan.md` 和 `prompts/stage3/review.md`
- 中控编排 `stage3.py` 需要改为 3 session 串行调度 + bounce-back 逻辑

**Session 配置参数**：

| 参数 | Session A | Session B | Session C |
|------|-----------|-----------|-----------|
| `timeout_seconds` | 300 | 2400 | 1200 |
| `max_budget_usd` | 2.0 | 8.0 | 5.0 |
| `allowed_tools` | Read, Glob, Grep, Agent | Bash, Agent, Read, Write, Glob, Grep | Bash, Agent, Read, Write, Glob, Grep |
| `model` | sonnet | sonnet | sonnet |

**成功判定逻辑**：
- 检查 `{work_dir}/BUILD_FAILED.md` → 存在则视为构建失败
- 检查 `{work_dir}/demo/package.json` → 存在则视为项目构建成功
- 只检查特定路径，不使用 rglob，避免扫描 `node_modules/`

**Dashboard 事件**：`dev_completed`（构建成功）和 `dev_failed`（构建失败或 session 失败）

**`--prd` CLI 调试入口**：跳过 Stage 0+1+2，直接对单份 PRD 文档运行 Stage 3（同 `--idea-card` 模式）

---

## 10. 技术实现方案

### 10.1 技术栈选择 ✅ 已确定

- **中控脚本**：Python 3.11+ (asyncio)
- **Dashboard**：单文件 `dashboard.html`（vanilla JS + WebSocket，无构建工具）
- **Agent 运行时**：Claude Code CLI (`claude -p`)
- **通信**：中控 EventBus → WebSocketServer → Dashboard
- **依赖**：websockets, aiofiles
- **Python 环境**：`.venv/` (venv)

### 10.2 中控脚本职责

```
1. 解析 CLI 参数（--theme / --prompt / --prompt-file + --mode 等）
2. 启动 EventBus + WebSocketServer
3. [可选] Stage 0: 解析复杂赛题 → 构建 HackathonBrief
4. Stage 1: 启动主 Agent session → 获取人群方向 JSON
5. [可选] 按 max_directions 裁剪方向
6. 为每个方向启动 Research session（内部 spawn sub-agents）
7. 收集 Idea Card → 卡片数 <= 3 跳过去重，否则启动 Dedup session
8. [可选] ReviewGate: 暂停等待用户筛选（Dashboard UI 或 CLI）
9. 收集筛选后的最终产出 → workspace/stage1/output/
10. Stage 2: 为每张 Idea Card 串行启动 3 个 session（concept → logic → technical）→ 收集文档到 workspace/stage2/output/
11. Stage 3: 为每份 PRD 串行启动 3 个 session（Plan → Dev → Review），含条件性 C→B 打回 → 收集项目目录 (检查 package.json 或 BUILD_FAILED.md)
12. 全程通过 EventBus → WebSocket 双向通信 Dashboard
```

### 10.3 Session 管理 ✅ 已实现

- 每个 session 有独立的工作目录 (`workspace/stage1/research-{slug}/`)
- `SessionManager` 用 `asyncio.Semaphore(5)` 控制并发
- 逐行解析 `stream-json` 输出，提取工具使用事件推送 Dashboard
- Session 完成判定：进程退出码 + 扫描工作目录中的 `*.md` 文件
- Session 异常处理：超时 kill + 最多重试 1 次
- 失败 fallback：Dedup 失败时使用 raw cards

### 10.4 文件系统结构 ✅ 已实现

```
hackathon-agent/
├── control/                     # Python 中控
│   ├── __init__.py
│   ├── __main__.py              # python -m control 入口
│   ├── main.py                  # CLI 入口 + 组件编排
│   ├── models.py                # 数据模型 (SessionConfig, SessionResult, Event, HackathonBrief, ...)
│   ├── event_bus.py             # 异步事件 pub/sub
│   ├── session_manager.py       # 核心：管理 claude CLI 子进程
│   ├── ws_server.py             # WebSocket 服务端（双向通信）
│   ├── review_gate.py           # ReviewGate: 阶段间人工筛选
│   └── stages/
│       ├── __init__.py
│       ├── stage0.py            # 阶段零：赛题解析
│       ├── stage1.py            # 阶段一完整逻辑
│       ├── stage2.py            # ✅ 阶段二：PRD 生成编排
│       └── stage3.py            # ⚠️ 阶段三：Demo 开发编排（需适配 3 session 模式）
│
├── dashboard.html               # 单文件监控 + 交互页面（含 ReviewGate UI）
│
├── prompts/                     # 各角色 Agent 的 Prompt
│   ├── stage0/                  # ✅ 已实现
│   │   └── interpreter.md       # 赛题解析 Agent
│   ├── stage1/                  # ✅ 已实现
│   │   ├── main.md              # 主 Agent: 人群展开 → JSON（含 hackathon_context 条件块）
│   │   ├── research.md          # Research: 内部 Agent tool 管理 3 sub-agents（含 hackathon_context 条件块）
│   │   └── dedup.md             # 去重 + 质量过滤
│   ├── stage2/                  # ⬜ Redesigned (3 serial session model)
│   │   # Redesign: 3 independent prompts (concept, logic, technical) — TBD
│   │   # 原实现: prd.md (单 coordinator prompt 内嵌 5 角色)
│   │   # 新设计: 每张 Idea Card → 3 个串行独立 session
│   └── stage3/                  # ⬜ Redesigned (3 serial session model)
│       # Redesign: 3 independent prompts (plan, dev, review) — TBD
│       # 原实现: dev.md (单 coordinator prompt 内嵌 7 步流水线)
│       # 新设计: 每份 PRD → 3 个串行独立 session
│       ├── plan.md              # Session A: Planner（功能→页面映射 + 开发计划）
│       ├── dev.md               # Session B: Scaffold + Shared Layer + Page Coding
│       └── review.md            # Session C: Designer + Reviewer + Fix + Final Verification
│
├── templates/
│   └── idea-card.md             # ✅ Idea Card 模板
│
├── workspace/                   # 运行时工作空间 (gitignored)
│   ├── stage0/
│   │   └── interpreter/         # Stage 0 工作目录
│   ├── stage1/
│   │   ├── main/                # 主 Agent 工作目录
│   │   ├── research-{slug}/     # 各 Research Session 工作目录
│   │   ├── dedup/input/         # 去重输入
│   │   └── output/              # 最终产出
│   ├── stage2/                  # ⬜ Redesigned
│   │   ├── {card-slug}/         # 各 Session 工作目录 (concept, logic, technical)
│   │   └── output/              # 最终产出 (concept-*.md + logic-*.md + technical-*.md)
│   └── stage3/                  # ⬜ Redesigned
│       └── {prd-slug}/          # 各项目工作目录 (Session A/B/C 共享)
│           ├── dev-plan.md      # Session A 产出
│           └── demo/            # Session B/C 产出 (package.json, src/, README.md)
│
├── .venv/                       # Python 虚拟环境
├── requirements.txt
├── .gitignore
├── CLAUDE.md
└── Hackathon Agent Design.md
```

---

## 11. Agent 角色总览

| 阶段 | 角色 | 数量 | 职责 | 形式 |
|------|------|------|------|------|
| 零 | Interpreter | 0-1 | 解析复杂赛题为结构化 Brief | Claude Code session |
| 一 | 主 Agent | 1 | 人群展开、粗筛 → JSON 输出 | Claude Code session |
| 一 | Research | 每人群 1 个 | 内部管理模板搜索+自由搜索+Critic sub-agents | Claude Code session |
| 一 | ├ 模板搜索 | (内部) | 结构化关键词搜索痛点 | Agent tool sub-agent |
| 一 | ├ 自由搜索 | (内部) | 开放式探索发现痛点 | Agent tool sub-agent |
| 一 | └ Critic | (内部) | 质疑痛点真实性、评估证据 | Agent tool sub-agent |
| 一 | Dedup Agent | 0-1 | 去重、质量过滤、排名（卡片 ≤3 时跳过）| Claude Code session |
| — | ReviewGate | — | 人工筛选 Idea Card（非 Agent，中控组件）| Dashboard UI / CLI |
| 二 | Session 1: 产品定义 | 每 Idea 1 个 | 验证痛点、找产品 Idea、概念层定义、自审 | Claude Code session |
| 二 | Session 2: 产品设计 | 每 Idea 1 个 | 功能模块划分、模块关系、用户流程 | Claude Code session |
| 二 | Session 3: 技术方案 | 每 Idea 1 个 | 技术栈、实现方案、API、项目架构 | Claude Code session |
| 三 | Session A: Planner | 每项目 1 个 | 读三份文档，产出 dev-plan.md（功能→页面映射、依赖关系、共享层定义）| Claude Code session |
| 三 | Session B: Dev | 每项目 1 个 | Scaffold + Shared Layer Agent + Page Coding Agents（内部 Agent tool 管理 sub-agents）| Claude Code session |
| 三 | ├ Shared Layer Agent | (内部) | 公共组件、全局状态、API 层、工具函数 | Agent tool sub-agent |
| 三 | └ Page Coding Agents | (内部, 每页面 1 个) | 按页面分配的代码实现 + 自修复循环 | Agent tool sub-agent |
| 三 | Session C: Review | 每项目 1 个 | Designer + Reviewer + Fix + Final Verification（内部 Agent tool 管理 sub-agents）| Claude Code session |
| 三 | ├ Designer | (内部) | 视觉一致性检查 | Agent tool sub-agent |
| 三 | └ Reviewer | (内部) | 功能检查 + 端到端验证 | Agent tool sub-agent |

**实现说明**：
- **阶段二**（redesigned）：每张 Idea Card 对应 3 个串行的独立 Claude Code session（产品定义 → 产品设计 → 技术方案），不再使用 sub-agent 模式。Session 间通过文件系统传递文档（concept.md → logic.md → technical.md）。
- **阶段三**（redesigned）：每份 PRD 对应 3 个串行的独立 Claude Code session（Plan → Dev → Review）。Session B 和 C 内部通过 Agent tool 管理 sub-agent。Session C 修不好可打回 Session B（中控编排，最多 1 次）。

---

## 12. 循环与容错机制总览

### 12.1 阶段一

| 循环 | 参与角色 | 轮次上限 | 触发条件 |
|------|----------|----------|----------|
| Research ↔ Critic | Research + Critic | 1-2 轮 | Critic 质疑痛点 |

失败处理：Critic 质疑后 Research 无法有效回应 → 该 Idea Card 自然淘汰

### 12.2 阶段二 ⬜ Redesigned

| 机制 | 位置 | 说明 |
|------|------|------|
| Session 1 内部自审 | Session 1 末尾 | 概念层定义完成后自审：痛点是否成立、边界是否合理。不通过 → `ELIMINATED.md` |
| Session 2 自审 | 待定 | 是否需要内部自审机制待讨论（见 Section 7.10） |
| Session 3 自审 | 待定 | 是否需要内部自审机制待讨论（见 Section 7.10） |

失败处理：Session 1 自审不通过 → 写 `ELIMINATED.md`，中控跳过后续 Session 2 和 Session 3

> **变更说明**：原方案的 3 个反馈循环（Product↔Technical、Critic→Product、Pitch→Product）已被移除。新方案中不存在跨 session 循环——每个 session 独立运行，通过文件系统单向传递数据。

### 12.3 阶段三 ⬜ Redesigned

| 循环层级 | 位置 | 轮次上限 | 触发条件 | 处理范围 |
|----------|------|----------|----------|----------|
| Coding Agent 自修复 | Session B 内部 | 5 次 | build 失败 | 语法错误、import、简单 bug |
| Session C 内部修复 | Session C 内部 | 2 次 | Designer/Reviewer 发现问题 | 视觉不一致、功能不符 PRD |
| Session C → B 打回 | 中控编排 | 1 次 | Session C 内部修不好 | 需要重新开发的结构性问题 |

失败处理：打回 1 次后仍修不好 → 写 `BUILD_FAILED.md`

> **变更说明**：原方案的三层循环（自修复、屏幕级 Review、集成级）全部在单 session 内部完成。新方案将循环分布在不同 session 中——Session B 内部处理 build 级错误，Session C 内部处理 review 级问题，跨 session 打回由中控编排。

---

## 13. Token 消耗预估

### 13.1 阶段零
- Interpreter：0-1 session，轻量级，约 5K-10K tokens（简单 `--theme` 模式跳过）

### 13.2 阶段一
- 主 Agent：1 session，轻量级，约 10K-20K tokens
- Research sessions：约 14 个，每个含搜索和内容分析，约 50K-100K tokens/session
- Critic sessions：约 7 个，每个约 20K-30K tokens/session
- **阶段一预估总计**：约 1M-2M tokens

### 13.3 阶段二 ⬜ Updated estimate
- 每张 Idea Card 3 个串行 session（无 sub-agent 开销），每个 session 约 30K-80K tokens
- 假设 5-7 张存活卡片：3 sessions × 5-7 cards = 15-21 个 session
- **阶段二预估总计**：约 0.5M-1.7M tokens（低于原方案，因取消了 sub-agent 多轮交互开销）

### 13.4 阶段三 ⬜ Updated estimate
- 每份 PRD 3 个串行 session：Session A (规划, ~20K-50K) + Session B (开发, ~400K-800K) + Session C (审查, ~100K-300K)
- 假设 5-7 个项目：3 sessions × 5-7 projects = 15-21 个 session
- 最坏情况含打回：额外 B + C session，约 500K-1.1M tokens/项目
- **阶段三预估总计**：约 3M-8M tokens（预算从 $10/项目提升至 $15/项目，最坏 $28）

### 13.5 总计
- **整体预估**：约 4.5M-12M tokens（Stage 2+3 redesign 后整体变化不大，Stage 2 降低但 Stage 3 略增）
- 以上为粗略估算，实际消耗取决于项目复杂度、循环次数、打回频率等因素

---

## 14. 待定与后续迭代项

### 14.1 第一版不做，后续迭代

- ~~用户干预机制（暂停、提问、修改方向）~~ → **已部分实现**（ReviewGate 提供阶段间人工筛选）
- Presentation / Pitch Deck 自动生成（原计划的第四阶段）
- 智能 token 预算管理

### 14.2 需要在实现中验证和调整

- 各角色 Agent 的 Prompt 具体内容
- 循环次数上限的最优值
- 搜索深度的最优平衡点
- 两层半策略中 Coding Agent 自行拆分的判断标准
- 中控脚本判定 Session 完成的具体机制

### 14.3 Stage 2 Redesign 待讨论事项

以下事项来自 Stage 2 架构改造，需在实现前确定：

1. **Session 2 和 Session 3 是否带内部自审**——当前仅 Session 1 有自审步骤
2. **三份文档的具体格式模板**——concept.md / logic.md / technical.md 各包含哪些字段（当前为框架，见 Section 8）
3. **Prompt 文件组织**——是 3 个独立 prompt 文件（`concept.md`, `logic.md`, `technical.md`）还是其他形式
4. **失败处理与重试策略**——单个 session 失败时是否重试、如何重试（Session 1 失败 vs Session 2/3 失败的不同处理）

### 14.4 Stage 3 Redesign 待讨论事项

以下事项来自 Stage 3 架构改造，需在实现前确定：

1. **dev-plan.md 的具体格式**——功能→页面映射怎么表达、共享层定义的结构
2. **超时与预算的实际调优**——当前值为初始估计，需根据实际运行调整
3. **Dashboard 事件适配**——新增 session 类型（plan/dev/review）的事件定义
4. **各 Session 的 allowed_tools 区分**——Session A 是否需要 Bash（当前设计不需要）
5. **打回机制的触发条件**——Session C 的 review.md 如何判定"修不好需要打回"，以及中控如何检测
6. **打回时 Session B 的上下文**——打回重跑时 Session B 需要额外接收 Session C 的问题描述

---

## 15. 设计决策记录

### 原始设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 角色定位 | 独立参赛者，非辅助工具 | 差异化，验证纯自动化可行性 |
| 需求发现路线 | 真实痛点，非"有趣的东西" | Agent 缺乏创意直觉，痛点路线更结构化 |
| 痛点验证标准 | 痛点假设（有证据即可） | Hackathon 不需要百分百验证 |
| 筛选原则 | 只淘汰不挑选 | 保留最大可能性空间 |
| 并行策略 | 独立 session，不用 Agent Teams | 项目间无依赖，不需要协调 |
| 项目内编排 | Sub-agents，两层半策略 | 平衡拆分粒度和集成复杂度 |
| 中控实现 | 脚本，非 Agent | 流程编排是确定性逻辑，不需要 AI |
| Dashboard 第一版 | 纯观察，无干预 | 先验证核心命题，降低复杂度 |
| 解决方向数量 | Idea Card 含 2-3 个方向 | 避免锁死方向，保留 PRD 阶段灵活性 |
| PRD 演示路径 | ~~三层描述（表面+产品逻辑+技术逻辑）~~ → 三文档递进（concept+logic+technical） | 原方案按屏幕组织偏向演示脚本；新方案按抽象层次递进，产品导向 |

### 实现阶段新增决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 中控语言 | Python (asyncio) | 异步原生支持，subprocess 管理方便 |
| CLI 调用方式 | subprocess (`claude -p`) | 最简单直接，无需额外 SDK |
| Dashboard 实现 | 单文件 HTML + vanilla JS | 无构建工具依赖，直接浏览器打开 |
| Stage 1 编排 | 混合：中控管 session，session 内用 Agent tool 管 sub-agent | 减少中控复杂度，利用 Claude Code 原生能力 |
| 并发控制 | Semaphore(5) | 保守策略，避免 rate limit |
| 权限模式 | `--dangerously-skip-permissions` | 全自动化场景必须 |
| 输出格式 | `--output-format stream-json` | 实时解析进度推送 Dashboard |
| 超时策略 | 主 Agent 120s / Research 900s / Dedup 300s | 按任务复杂度分配 |
| 重试策略 | 最多 1 次重试 | 简单可靠，避免浪费 token |
| Dedup 失败 fallback | 使用 raw cards | 宁可多不可少 |

### Phase 1.5 增强决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 运行模式 | `--mode full/single/lite` + `--max-directions` | 开发测试时节省 token，生产环境全量运行 |
| 方向裁剪策略 | 优先保留 high relevance | 确保测试时选到最有价值的方向 |
| 少量卡片跳过 Dedup | 卡片 ≤3 时直接跳过 | 没必要为 1-3 张卡启动额外 session |
| 赛题解析 | 独立 Stage 0 session | 结构化提取约束/评审标准，避免信息丢失 |
| 简单模式跳过 Stage 0 | `--theme` 直接创建最小 Brief | 向后兼容，无需额外开销 |
| 约束注入方式 | `{{#hackathon_context}}` 条件块 | 简单模式时块被移除，零侵入 |
| 人工筛选位置 | 阶段一和阶段二之间 | 最早介入点，避免为不靠谱的 Idea 浪费 PRD token |
| ReviewGate 交互 | Dashboard 优先 + CLI 回退 | 有 Dashboard 时体验好，CLI 作为兜底 |
| ReviewGate 默认行为 | 所有卡片默认勾选 | 符合"只淘汰不挑选"原则，用户减法操作 |
| ReviewGate 超时 | 10 分钟超时保留全部 | 安全兜底，避免无人值守时管道卡住 |
| WebSocket 双向通信 | `register_handler()` 消息分发 | 最小改动支持回传，不引入额外依赖 |

### Stage 2 Redesign 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 设计理念 | 产品导向（非 Pitch 导向） | 原方案从演示效果倒推产品设计，本末倒置 |
| 产品组织方式 | 按功能模块（非按屏幕/页面） | 按屏幕组织本质是写 demo 脚本，不是做产品设计 |
| Agent 架构 | 3 个串行独立 session（非单 session + 5 sub-agent） | 按抽象层次递进，每次思维模式转变作为 session 边界 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示效果，产品设计好了 demo 自然能展示价值 |
| Wireframe Agent | **删除** | 线框图推迟到 Stage 3，PRD 阶段专注产品定义 |
| Critic Agent | 合并为 Session 1 内部自审 | 不再独立角色，概念层定义后立即自审 |
| 产出格式 | 3 份独立文档（concept/logic/technical） | 按抽象层次组织，替代原来的单一按屏幕组织的 PRD |
| 淘汰判定 | Session 1 自审不通过 → ELIMINATED.md | 最早阶段淘汰，节省后续 session token |

### Stage 3 Redesign 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 架构 | 3 个串行独立 session（Plan → Dev → Review） | 与 Stage 2 同理：按任务性质切分 session 边界，规划/开发/审查是三种不同思维模式 |
| Session 切分点 | A 纯规划 / B 全部代码 / C 审查+修复 | A 不碰代码降低复杂度；B 完整负责所有代码产出；C 独立视角审查 |
| Planner 任务拆分 | 混合模式（功能模块→页面映射） | PRD 按功能模块组织，但工程实现需要按页面分配，Planner 做桥接 |
| 共享层处理 | 独立 Coding Agent 先于 Page Agent | 确保跨页面复用的部分先完成，Page Agent 基于共享层开发 |
| Scaffold 位置 | Session B（非 Session A） | Session A 纯规划不碰代码，Session B 从脚手架开始完整负责代码产出 |
| Review 角色保留 | Designer + Reviewer 两个角色 | 关注点不同：视觉一致性 vs 功能正确性，分开更清晰 |
| 打回机制 | Session C → B，中控编排，最多 1 次 | Session C 修不好的结构性问题需要回到开发阶段；限制 1 次避免无限循环 |
| Stage 3 超时 | A: 300s / B: 2400s / C: 1200s | 按任务复杂度分配，总计 3900s（原方案 3600s） |
| Stage 3 预算 | A: $2 / B: $8 / C: $5 | 总计 $15/项目（原方案 $10），开发复杂度需要更多预算 |
| 构建验证命令 | `npm run build` (非 `npm run dev`) | build 退出干净，dev 启动持久服务器会卡住 session |
| 失败标志 | `BUILD_FAILED.md` | 类比 Stage 2 的 `ELIMINATED.md`，中控据此判断成败 |
| 成功判定 | 检查 `demo/package.json` 存在 | 避免 rglob 扫描 node_modules/，只检查特定路径 |
| `--prd` 调试入口 | 跳过 Stage 0+1+2 | 同 `--idea-card` 模式，便于单独测试 Stage 3 |

