# Hackathon Agent — System Design Document

---

## 1. 项目概述

### 1.1 核心理念

Hackathon Agent 是一个完全自主的 AI 黑客松参赛系统。它不是辅助人类参赛的工具，而是**独立参赛的选手**——从发现需求、定义问题、编写产品方案，到完成 Demo 开发，全程由 Agent 主导，用户仅作为观察者在关键节点进行确认。

**定位转变：从 hackathon demo 到 indie developer MVP。**

时间不再是筛选标准。Agent 的时间成本会随模型能力提升持续下降，token 成本也在快速降低。真正成立的约束是 token 消耗量——而这个消耗是值得的。筛选标准从"hackathon 能不能做"换成两条核心原则：（1）**软件可解决**——排除需要硬件、物理交互、线下服务的方向；（2）**Agent 可独立完成**——排除需要人类专业判断才能推进的方向。

**核心转变：做真实的产品，不做 Mock。**

产品必须在真实环境里能跑起来。一个 Slack Bot 如果没有真实的 Slack workspace，它就不是这个产品——它只是关于这个产品的一张图纸。宁可产出 3 个真实运行的项目，也不要 7 个有一半是假的。

### 1.2 核心命题

验证纯 Agent 自动化能否端到端跑通一个复杂度较高的黑客松项目流程，最终同时产出 5-7 个可在**真实环境中运行**的独立项目。

### 1.3 用户输入

支持两种输入模式：

**简单模式**（`--theme`）：
- **Hackathon 主题约束**（必填）：如 "AI + Climate"、"Crypto"、"Developer Tools" 等
- **用户感兴趣的方向**（可选）：如 "教育"、"医疗"、"生产力工具" 等

**完整模式**（`--prompt` / `--prompt-file`）：
- **原始 Hackathon 赛题**：多段落的完整赛题文本，包含规则、约束、评审标准、赞助商奖项等
- 由 Stage 0（Prompt Interpreter）自动解析为结构化的 `HackathonBrief`

### 1.4 最终产出

5-7 个独立的 GitHub 仓库，每个仓库包含：

- **可在真实环境中运行的项目代码**（非 Mock Demo）
- 产品方案文档（concept.md + logic.md + technical.md）
- 环境配置说明（environment-plan.md + `.env.example`）
- 部署/安装说明（README.md，包含真实运行的完整步骤）
- **Pitch 演示材料**（pitch-script.md + pitch-deck.html）

各项目之间完全独立，无任何关联，可分别参加不同的黑客松。

---

## 2. 整体架构

### 2.1 七阶段流水线

```
用户输入
  → [Stage 0：赛题解析]（可选）
  → [Stage 1：需求发现]
  → [ReviewGate：人工筛选]
  → [Stage 2：产品方案]
  → [ConfigGate：凭证收集 + 可行性验证]
  → [Stage 3：真实环境开发]
  → [Stage 5：Pitch Deck]（pitch 产出复制到 demo/ 目录）
  → [Stage 4：GitHub 发布]（含 pitch 产出）
  → 5-7 个 GitHub 仓库（代码 + pitch-script.md + pitch-deck.html）
```

关键设计：
- **Stage 1** 新增外部依赖复杂度标注，Idea Card 阶段就能看到产品的环境要求
- **Stage 2** 产品定义阶段明确 `product_type` 和宿主环境，真实环境约束内嵌到所有三份文档
- **ConfigGate（Stage 2.5）** 重新定位：不是"让 demo 更好看的可选步骤"，而是"验证产品能否真实存在的必要关卡"——无法满足载体依赖的项目直接 BLOCKED，不进入 Stage 3
- **Stage 3** 开发目标从"构建成功"改为"在真实环境里跑通核心路径"
- **Stage 4** 自动 README 生成 + git init + GitHub repo 创建 + push
- **Stage 5** 为每个项目生成 pitch 演讲脚本 + HTML 幻灯片，产出复制到 demo/ 后由 Stage 4 一起发布

### 2.2 中控架构

整个系统由一个 **Python 中控脚本**（asyncio）驱动，而非 AI Agent。

中控脚本负责：
- **Session 管理** (`SessionManager`)：启动、监控、收集各阶段的 Claude Code CLI session
- **阶段流转** (`stages/`)：依次驱动各阶段逻辑
- **人工关卡** (`ReviewGate` / `ConfigGate`)：阶段间暂停等待用户操作
- **事件系统** (`EventBus`)：异步事件发布/订阅，解耦组件
- **状态广播** (`WebSocketServer`)：双向 WebSocket 通信

**编排方式：混合模式**
- **阶段级编排**由中控脚本驱动（确定性 if/then 逻辑）
- **角色级协作**由 Claude Code session 内部通过 Agent tool 自行管理（如 Research session 内部 spawn Search、Synthesis 两个 sub-agent）

选择脚本而非 Agent 做中控的原因：流程编排是完全确定性的逻辑（if/then），不需要 AI 判断，用 Agent 做既浪费 token 又不可靠。

### 2.3 并行策略

- 所有并行任务使用**独立的 Claude Code session**，不共享上下文
- Stage 1：多个 research session 并行
- Stage 2：每张 Idea Card 3 个串行 session，不同 Card 间并行（Semaphore 控制）
- Stage 3：每个项目 3 个串行 session（Plan → Dev → Review），不同项目间并行（Semaphore 控制）

### 2.4 Dashboard ✅ 已实现

同时具备监控和交互能力的单页面，支持：
- 全局视角 / Session 视角 / 关键事件流
- **ReviewGate 面板**：Idea Card 筛选
- **ConfigGate 面板**（🆕 新增）：凭证填入 + 可行性确认

技术实现：单文件 `dashboard.html`（vanilla JS + WebSocket），无构建工具，直接浏览器打开。双向 WebSocket 通信（`ws://localhost:8765`），支持断线自动重连，新连接自动接收历史事件。

---

## 3. Stage 0：赛题解析 ✅ 已实现

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

## 4. Stage 1：需求发现

### 4.1 目标

从 hackathon 主题出发，自主发现真实用户痛点，产出 5-15 个有证据支撑的 Idea Card。

**每张 Idea Card 必须包含外部依赖评估**，让用户在 ReviewGate 阶段就能根据自身资源做筛选。

### 4.2 核心设计原则

- Agent 没有"身体性"和生活经验，因此必须先**选人群**（模拟谁的视角），再找痛点
- 聚焦**真实用户痛点**路线，不走"做有趣的东西"路线
- 寻找的是"痛点假设"而非"已验证的痛点"——有证据支撑即可，不需要百分百确认
- 只做筛选（淘汰明显不行的），不做挑选（不主观排序）
- **核心筛选标准**：（1）软件可解决——排除需要硬件、物理交互、线下服务的方向；（2）Agent 可独立完成——排除需要人类专业判断才能推进的方向（如需医生验证的医疗诊断），但不排除需要较长开发时间或较多 token 的方向

### 4.3 粗筛标准（主 Agent）

- **软件可解决**：这个痛点能否用纯软件解决——排除需要硬件、物理交互、线下服务的方向
- **Agent 可独立完成**：能否由 Agent 独立完成开发——排除需要人类专业判断才能推进的方向
- **痛感共鸣度**：是否能引起广泛共鸣
- **排除项**：需要法律合规、银行合作、硬件依赖等明显做不了的方向
- **外部环境可及性**：产品所需的宿主环境（Slack workspace、VS Code、浏览器扩展商店等）是否可获取？高度依赖难以获取的平台权限的方向，降低优先级

### 4.4 Agent 编排

#### 4.4.1 主 Agent

由一个 Claude Code session 完成以下工作：

- **灵感搜索**（🆕）：在人群发散之前，先执行 3-5 次轻量级 WebSearch，拓宽 Claude 的联想空间，发现自身知识盲区里的人群和痛点角度。搜索定位是灵感补充，不是深度研究（深度研究是 Research Agent 的职责）。不需要 WebFetch 读完整页面，只看搜索结果的标题和摘要
- **人群展开**：根据主题 + 搜索灵感列出相关角色和人群（8-12 个方向）
- **粗筛**：排除不符合"软件可解决 + Agent 可独立完成"标准的方向

输出 JSON 中每个方向包含以下字段：
- `slug`：方向标识
- `persona`：目标人群描述
- `relevance`：high / medium
- `scope`（🆕）：`"broad"`（痛点空间大，Research 预期产出 2-5 张卡）或 `"focused"`（痛点集中，预期 1-2 张卡）
- `likely_product_types`（🆕）：最可能的产品形态列表（如 `["web_app", "cli_tool"]`），为 ReviewGate 和 Research Agent 提供参考，精度预期不高——Stage 2 Session 1 会正式确定
- `pain_areas`：痛点假设列表

#### 4.4.2 Research Sessions（每个人群方向 × 1）✅ 已实现

每个 Research session 内部通过 Claude Code 的 **Agent tool** 自行 spawn 2 个 sub-agent：

**Sub-Agent 1: Search**（通过 Agent tool，按 pain area 可并行拆分）
- 原则驱动的搜索（非模板驱动），核心搜索原则：
  1. 搜行为描述优于搜情绪表达（`"every week I have to"` > `"so frustrated with"`）
  2. 先确定人群在哪里讨论问题（哪些 subreddit、论坛），再定向搜
  3. 搜 workaround 和手搓方案（Zapier 自动化、Google Sheets 公式、Python 脚本）
  4. 搜对现有工具的具体不满和替代品讨论
- 对于 `scope: "broad"` 的方向，按 pain area 拆分并行（每个 pain area 一个独立 Search sub-agent），上下文隔离提高搜索质量
- 对于 `scope: "focused"` 的方向，单个 Search sub-agent 即可
- 每个 pain area 做 3-5 次搜索，总共不超过 10 次
- 每个 sub-agent 写一个 findings 文件（`findings-{pain_area}.md`）

**Sub-Agent 2: Synthesis**（通过 Agent tool，独立上下文）
- 只读 Search 产出的 findings 文件，不继承搜索过程的上下文噪音
- 将零散证据编织成有说服力的用户故事，提炼痛点，构思解决方向
- 内含自审逻辑（吸收原 Critic 角色的批判性审视功能），用 Quality Gates 作为检查清单，但不作为硬性 RECOMMEND/DROP 门槛
- 根据 `scope` 字段控制产出量：`"broad"` 产出 2-5 张卡，`"focused"` 产出 1-2 张卡

**Quality Gates**（2 条原则，替代原 5 条硬性门槛）：
1. 搜索过程中是否找到了真实的用户在描述这个痛点（不要求精确的 URL 数量，但需要有真实证据支撑）
2. 这个痛点是否能用软件解决，并且 Agent 能在合理时间内做出 MVP

> **实现说明**：原设计为 3 个串行 sub-agent（模板搜索 → 自由搜索 → Critic）。新设计简化为 2 个 sub-agent（Search + Synthesis），合并了搜索角色、取消独立 Critic（自审合并到 Synthesis）、采用原则驱动而非模板驱动的搜索策略。

每个 Research session 产出 1-5 个 `idea-card-*.md` 文件（取决于 scope）。

#### 4.4.3 去重 Agent ✅ 已实现

采用**流式去重 + 最终轻量审查**架构（替代原批处理方案）：

**流式去重**：中控维护累积的 Idea Card 池。每当一个 Research session 完成并产出卡片，中控把新卡片和池子里已有的卡片做比较（轻量 `claude -p` 调用）。流式阶段只做明显重复的合并，不做细粒度质量筛选。

**最终轻量审查**：所有 Research session 完成后，对流式去重后的卡片池做一次最终审查——检查遗漏的重复、格式标准化、按质量排序确定文件编号。去掉了原 Dedup 中的 5 因子加权排名公式，改为让 Agent 做综合判断排序。

- 筛选标准与新 Quality Gates 对齐：有真实证据支撑 + 软件可解决且 Agent 可独立完成
- 如果 Dedup 失败，中控会 fallback 使用 raw cards

### 4.5 运行模式 ✅ 已实现

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

### 4.6 Session 规模

假设 7 个人群方向：
- 1 个主 Agent session（含 3-5 次灵感搜索）
- 7 个 Research sessions（每个内部 spawn 2 个 sub-agent：Search + Synthesis）
- 流式去重（轻量 claude -p 调用，每张新卡一次）+ 1 次最终审查
- 共约 9 个 Claude Code sessions + N 次轻量去重调用（最多 5 个并行，由 Semaphore 控制）

### 4.7 阶段一产出

5-15 个标准格式的 Idea Card 文件，存放于汇总目录。

---

## 5. 中间产物：Idea Card 格式 ⬜ Updated

```markdown
# Idea Card: [简短标题]

## 具体场景

[一个真实的、有画面感的用户故事。谁、在什么情境下、遇到什么具体的困难、现在怎么凑合解决的。来自搜索到的真实抱怨，由 Agent 加工成连贯叙事。]

## 证据

[简化描述格式，一两句话描述每条发现。提到具体平台和具体内容即可，不需要完整 URL、日期、互动数据。]

- [来源1]：[一两句话描述发现]
- [来源2]：[一两句话描述发现]
- ...

## 现有方案及不足

[市面上有什么解决方案、做得怎么样、用户评价如何、明显缺陷在哪里。如果没有现有方案则说明原因。]

## 解决方向

[简化为方向提示，不做详细评估。产品设计留给 Stage 2。]

- [方向一]：[一两句话描述可能的产品方向]
- [方向二]：[一两句话描述可能的产品方向]（可选）

## 外部依赖评估（🆕）

| 依赖类型 | 具体服务 | 必要性 | 获取难度 |
|----------|----------|--------|---------|
| LLM API  | OpenAI / Claude | 核心功能 | 低（注册即得）|
| 平台宿主  | Slack workspace | 产品载体 | 中（需有账号）|
| OAuth    | GitHub Login | 可选增强 | 低 |

**综合可及性评估**：高 / 中 / 低
[一句话说明：什么样的用户能顺利部署这个产品]

> 注意：解决方向仅为初步提示，不是定论。产品设计由 Stage 2 负责。
```

---

## 6. ReviewGate：人工筛选 ✅ 已实现

### 6.1 目标

阶段一完成后暂停流水线，让人类审查 Idea Card 并决定哪些进入 Stage 2。

ReviewGate 面板需展示每张卡的外部依赖评估，让用户在筛选时就能根据自身资源做决策（"我没有 Slack workspace，这张卡跳过"）。

### 6.2 设计理由

AI 可能高估某些想法的可行性——人类一眼就能看出的不靠谱点，AI 往往信心满满地通过。增加人工筛选可以在早期阶段避免浪费后续大量 token。

### 6.3 两种交互模式

**Dashboard 模式**（默认）：
- 阶段一完成后，中控发送 `review_requested` 事件
- Dashboard 自动展示 Review 面板：卡片网格，每张卡显示标题、场景摘要（150 字）、证据数量、解决方向、**外部依赖评估**
- 每张卡默认勾选，用户取消勾选不需要的卡片
- 点击 "Confirm Selection" → 通过 WebSocket 回传 `{type: "review_selection", selected_indices: [0,1,3]}`
- 中控收到选择后恢复流水线

**CLI 模式**（`--no-dashboard`）：
- 在终端打印卡片编号和摘要
- 用户输入逗号分隔的编号（如 `0,1,3`）或 `all`
- 超时 10 分钟自动保留全部卡片

### 6.4 跳过筛选

`--skip-review` 跳过 ReviewGate，自动保留所有卡片（用于全自动运行）。

### 6.5 事件

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `review_requested` | 卡片就绪等待审查 | `{cards: [{index, title, scenario_excerpt, evidence_count, solution_directions}]}` |
| `review_completed` | 用户确认选择 | `{selected: int, total: int}` |

---

## 7. Stage 2：产品方案 ⬜ Redesigned

### 7.1 目标

对筛选后的 Idea Card 并行深入，通过 3 个递进层次的独立 session 完成产品定义，淘汰不可行的，为存活的 5-7 个各自生成完整的产品方案文档。

**核心变化**：从第一个 session 开始，产品定义就围绕真实运行环境展开。`product_type` 和宿主环境在 concept.md 阶段明确确定，成为后续所有决策的硬约束。

### 7.2 核心设计原则

- **产品导向**：先把问题想清楚、把产品设计好，Pitch 是后续包装的事
- **按功能模块组织**：不再按页面/屏幕拆分，而是按功能模块组织产品定义
- **按抽象层次递进**：概念层 → 逻辑层 → 物理层，从粗到细，每一层产出自包含文档
- **围绕真实环境**：所有模块定义使用宿主环境的真实概念，不做抽象 UI 描述

### 7.3 产品形态分类

Stage 2 Session 1 必须确定 `product_type`，这个字段贯穿 Stage 2 全部三份文档和 Stage 3 全部开发决策：

| product_type | 典型例子 | 宿主环境 | 载体依赖 |
|---|---|---|---|
| `web_app` | 独立 SaaS、工具站 | 浏览器 | 无（自托管）|
| `slack_app` | Slack Bot、Workflow | Slack workspace | Slack App 凭证 |
| `vscode_extension` | 编辑器插件 | VS Code | 无（本地安装）|
| `chrome_extension` | 浏览器插件 | Chrome | 无（本地加载）|
| `cli_tool` | 命令行工具 | 本地终端 | 无 |
| `api_service` | 后端服务、Webhook | 服务器 / 本地 | 无（自托管）|
| `notion_integration` | Notion 插件 | Notion workspace | Notion API 凭证 |
| `github_app` | GitHub Bot、Action | GitHub repo | GitHub App 凭证 |

**载体依赖**（宿主平台要求的凭证/权限）是硬约束——没有它，这个产品不存在，不是功能降级。

### 7.4 Agent 架构：3 个串行独立 Session

每张 Idea Card 由 3 个**串行的独立 Claude Code session** 处理：

```
Session 1（产品定义）
  输入：Idea Card
  步骤：
    1. 验证痛点
    2. 确定 product_type 和宿主环境
    3. 概念层定义（产品是什么、为谁、核心价值、边界）
    4. 自审（痛点是否成立、product_type 是否匹配、宿主环境是否合理）
  产出：concept.md（或 ELIMINATED.md）

      ↓ 中控传递 concept.md

Session 2（产品设计）
  输入：concept.md + 原始 Idea Card
  步骤：
    1. 功能模块划分（围绕真实宿主环境的概念，而非抽象 UI 描述）
    2. 模块间关系与数据流
    3. 用户流程（在真实环境中从进入到完成核心任务的路径）
  产出：logic.md

      ↓ 中控传递 concept.md + logic.md

Session 3（技术方案）
  输入：concept.md + logic.md
  步骤：
    1. 技术栈选择（需与 product_type 匹配）
    2. 每个功能模块的实现方案
    3. API 设计、数据结构
    4. 项目架构
    5. 生成 Prerequisites Checklist（分层：载体依赖 / 功能依赖 / 开发依赖）
  产出：technical.md（含完整 Prerequisites Checklist）
```

### 7.5 角色变更对照

| 原角色 | 新方案处理 | 理由 |
|--------|-----------|------|
| Product Agent | → Session 1 + Session 2 | 拆为概念层和逻辑层两个阶段 |
| Technical Agent | → Session 3 | 独立 session，专注技术方案 |
| Critic Agent | → Session 1 内部自审步骤 | 不再独立角色，概念层定完后自审 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示，产品导向 |
| Wireframe Agent | **删除** | PRD 阶段不做线框图，交给 Stage 3 |

### 7.6 Session 切分理由

按三个原则切分 session 边界：

1. **信息耦合度**：步骤 1-3（验证痛点 → 找 Idea → 概念层）思维高度连贯，必须在同一 session
2. **任务性质变化**：概念层（产品定义）→ 逻辑层（产品设计）→ 物理层（技术方案），每次切换都是思维模式的转变
3. **天然切分点**：每个 session 的产出都是结构化的自包含文档，可以作为下一个 session 的独立输入

### 7.7 淘汰机制

**Session 1 自审不通过** → 写 `ELIMINATED.md`，中控跳过后续 session：
- 痛点不成立（证据不足、场景不真实）
- 找不到合理的产品方案
- 已有成熟方案完全解决了该痛点
- product_type 与痛点不匹配（🆕）
- 宿主环境在 hackathon 场景下明显不可及（🆕）

### 7.8 阶段二产出

每个存活的 Idea 产出 3 份按抽象层次组织的独立文档：

| 文档 | 内容 | 主要消费者 |
|------|------|-----------|
| `concept.md` | 产品定义、核心价值、目标用户、边界、product_type | Stage 3 所有 agent（作为背景参考）|
| `logic.md` | 功能模块、数据流、用户流程 | Stage 3 Session A (Planner) / Session B (Dev) |
| `technical.md` | 技术栈、实现方案、项目架构、Prerequisites Checklist | Stage 3 技术类 agent（主要 context）|

### 7.9 中控编排

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

### 7.10 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| Session 1（产品定义）| 600s (10min) | $3 | 验证痛点 + 找 Idea + 概念层 + 自审 |
| Session 2（产品设计）| 600s (10min) | $3 | 功能模块 + 数据流 + 用户流程 |
| Session 3（技术方案）| 600s (10min) | $3 | 技术栈 + 实现方案 + 架构 + Prerequisites |
| **单卡总计** | **1800s** | **$9** | |

---

## 8. 中间产物：产品方案文档格式 ⬜ Redesigned

阶段二产出 3 份按抽象层次组织的独立文档。

### 8.1 concept.md — 产品定义（概念层）

```markdown
# Concept: [产品名称]

## 痛点验证
[痛点是什么、证据是否成立、场景是否真实]

## 产品定义
[一句话：这个产品是什么、解决谁的什么问题]

## 产品形态

- **product_type**: slack_app / web_app / vscode_extension / ...
- **宿主环境**: [产品运行所在的平台/环境，如 "Slack workspace", "Chrome 浏览器"]
- **部署方式**: [用户如何安装/使用这个产品]

## 核心价值主张
[用户为什么要用这个产品、与现有方案的关键差异]

## 目标用户
[具体用户画像、使用场景]

## 产品边界
[做什么、不做什么、MVP 范围]

## 选择的解决方向
[从 Idea Card 的方向中选择/组合/改进的结果及理由]
```

### 8.2 logic.md — 产品设计（逻辑层）

```markdown
# Logic: [产品名称]

## 功能模块

功能模块必须使用宿主环境的真实概念描述。

示例（Slack App）：
### 模块一：Slash Command 处理
[用户输入 /xxx 命令时触发，解析参数，调用核心逻辑]

### 模块二：Event Subscription
[监听 message.channels 事件，过滤相关消息]

### 模块三：Block Kit UI
[构建交互式消息卡片，展示结果并接收用户操作]

示例（Web App）：
### 模块一：[功能名称]
[解决什么子问题、核心功能点]

## 模块关系与数据流
[模块间如何协作、数据如何流转]

## 用户流程
[在真实宿主环境中，从进入产品到完成核心任务的完整路径]
```

### 8.3 technical.md — 技术方案（物理层）

```markdown
# Technical: [产品名称]

## 产品形态
- product_type: [同 concept.md]
- 宿主环境: [同 concept.md]

## 技术栈
- 框架: [如 Bolt.js (Slack) / React + Vite (Web) / VS Code Extension API]
- 关键依赖: [列出主要 npm/pip 包]

## Prerequisites Checklist

### 载体依赖（缺少则产品不存在，ConfigGate 必须满足）
- [ ] [凭证名称]：[用途说明]
  - 获取方式: [如何申请/创建]
  - 类型: API Key / OAuth Token / Webhook URL / ...

### 功能依赖（缺少则该功能不实现，不降级为 Mock）
- [ ] [凭证名称]：[用途说明，及缺少时跳过哪个功能模块]

### 开发环境依赖（本地开发必须，部署后不需要）
- [ ] [工具/配置]：[如 ngrok（Slack event subscription 回调地址）]

## 功能模块实现方案
### 模块一：[名称]
[实现方式、关键技术点、使用哪个具体的 API/SDK]

## API 设计与数据结构
[接口定义、数据模型]

## 项目架构
[目录结构、文件组织]

## 部署说明
[用户如何在真实环境中安装和运行这个产品]
```

---

## 9. ConfigGate：凭证收集 + 可行性验证 🆕 New Stage

### 9.1 定位

ConfigGate 不是"让 demo 看起来更好的可选步骤"，而是**验证每个项目能否在真实环境里被部署和运行的必要关卡**。

通过 ConfigGate 的项目才能进入 Stage 3。没有通过的项目直接 BLOCKED——不做，也不降级成 Mock。

### 9.2 流程

```
Step 1: 依赖分析（自动）
  读取所有项目的 technical.md，提取 Prerequisites Checklist
  按"载体依赖 / 功能依赖 / 开发环境依赖"分类汇总
  识别跨项目共用的凭证（如 OpenAI API Key）
  产出：每个项目的 credentials-needed.md

Step 2: 可行性评估（自动）
  对每个项目：
  - 列出所有载体依赖
  - 如果某载体依赖无法通过填写凭证满足（如需要企业审批的平台权限），
    自动标注"⚠️ 可能需要额外步骤"

Step 3: 凭证收集（人工，Dashboard UI）
  展示所有项目的依赖矩阵
  用户填入已有的凭证
  对于无法提供载体依赖的项目：
    用户可选择"BLOCK 此项目"或"替换为 web_app 实现同一痛点"
  功能依赖用户未填写 → 对应功能模块不实现（不是 Mock，是不做）

Step 4: 集成规划（自动）
  根据收集到的凭证，为每个通过的项目生成 environment-plan.md
  明确标注每个功能模块的集成状态：
    ✅ 真实集成（凭证已就绪）
    ⏭️ 本期不实现（凭证未提供，预留接口）
    ❌ BLOCKED（载体依赖缺失，不进入 Stage 3）
```

### 9.3 Dashboard ConfigGate 面板

```
┌─────────────────────────────────────────────────────┐
│  ConfigGate — 凭证配置与可行性确认                    │
│                                                     │
│  💡 载体依赖（必须满足，否则项目 BLOCK）               │
│     功能依赖（未填则该功能跳过，不做 Mock）             │
│                                                     │
│  [全局凭证] ────────────────────────────────────    │
│  OpenAI API Key: [sk-...________________]           │
│  （被 3 个项目共用，填一次自动应用）                   │
│                                                     │
│  [项目一：SlackBot for Code Review]  ✅ 可继续        │
│  载体依赖                                           │
│  ✅ Slack Bot Token: [xoxb-...________]  已填        │
│  ✅ Slack Signing Secret: [___________]  已填        │
│  功能依赖                                           │
│  ✅ OpenAI API Key: 继承全局配置                     │
│  ⚪ GitHub Token: [___________________]  (跳过→不实现 PR分析功能) │
│  开发环境                                           │
│  ⚠️ 需要 ngrok 或公网 URL 用于 Event Subscription   │
│                                                     │
│  [项目二：AI Writing Assistant]  ✅ 可继续           │
│  载体依赖: 无（独立 Web App）                        │
│  功能依赖                                           │
│  ✅ OpenAI API Key: 继承全局配置                     │
│                                                     │
│  [项目三：Notion Database Agent]  ⚠️ 待确认          │
│  载体依赖                                           │
│  ❌ Notion Integration Token: [未填]                 │
│     → 缺少载体依赖，此项目将被 BLOCK                 │
│     [填入 Token]  [确认 BLOCK]  [改为 Web App 实现]  │
│                                                     │
│  [确认配置，开始 Stage 3 →]                          │
└─────────────────────────────────────────────────────┘
```

### 9.4 凭证安全

- 所有凭证存储在 `workspace/stage2.5/credentials.env`，加入 `.gitignore`
- 凭证不出现在任何 session 的工作目录，不写入任何 `.md` 文档
- 仅在 Stage 3 Session B 启动时通过环境变量注入子进程：`env={...creds, **os.environ}`
- Session B 生成的代码使用 `process.env.SLACK_BOT_TOKEN` 读取，代码本身不含任何实际凭证值
- GitHub 仓库只提交 `.env.example`（含字段名，不含值）

### 9.5 environment-plan.md 格式

```markdown
# Environment Plan: [产品名称]

## 项目形态
- product_type: slack_app
- 宿主环境: Slack workspace

## 集成状态总览

| 模块 | 状态 | 说明 |
|------|------|------|
| Slash Command 处理 | ✅ 真实集成 | Slack Bot Token 已就绪 |
| AI 分析 | ✅ 真实集成 | OpenAI API Key 已就绪 |
| PR 差异分析 | ⏭️ 本期不实现 | GitHub Token 未提供，预留接口 |

## 环境变量清单

```env
# 载体依赖（必须）
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...

# 功能依赖（已提供）
OPENAI_API_KEY=sk-...

# 功能依赖（未提供，对应功能跳过）
# GITHUB_TOKEN=（未配置，PR 分析功能不实现）
```

## 开发环境配置步骤

1. 安装依赖：`npm install`
2. 创建 `.env` 文件，填入上述环境变量
3. 启动 ngrok：`ngrok http 3000`（获取公网回调 URL）
4. 在 Slack App 配置页填入 ngrok URL 作为 Event Subscription 地址
5. 启动服务：`npm run dev`
6. 在 Slack workspace 安装 App，测试 `/xxx` 命令
```

### 9.6 跳过 ConfigGate

`--skip-config` 跳过 ConfigGate，所有项目直接进入 Stage 3，但 Session B 将只实现无需凭证的功能模块（不 Mock，只是不实现需要凭证的功能）。

---

## 10. Stage 3：真实环境开发 ⬜ Redesigned

### 10.1 目标

将通过 ConfigGate 的项目并行开发为**可在真实环境中运行的应用**。每个项目产出一个核心功能能在真实宿主环境中跑通的应用。

**核心原则：开发目标是"在真实环境里跑通核心路径"，而不是"构建成功"。**

- `npm run build` 通过不算完
- 能在真实 Slack workspace 收到 Bot 回复、能在真实浏览器里加载插件、能真实调用 API 并返回结果，才算完
- 功能依赖缺失的模块，预留接口但不实现，**不做任何形式的 Mock**

### 10.2 Agent 架构：3 个串行独立 Session

```
Session A（规划）
  输入：concept.md + logic.md + technical.md + environment-plan.md
  步骤：
    Planner：读所有文档，产出 dev-plan.md
      - 确认 product_type，选择对应的 Scaffold 方式
      - 功能模块 → 代码模块的映射关系
      - 模块列表及每个模块的职责（基于真实宿主环境概念）
      - 模块间的依赖关系（决定实现顺序）
      - 共享层定义（公共组件、全局状态、API 客户端封装等）
      - 跳过模块列表（功能依赖未提供的模块，预留接口）
      - 验收标准（根据 product_type 确定，不是通用的"构建成功"）
  产出：dev-plan.md

      ↓ 中控传递 dev-plan.md + environment-plan.md

Session B（开发）
  输入：dev-plan.md + concept.md + logic.md + technical.md + environment-plan.md
  环境变量：中控注入来自 credentials.env 的凭证
  步骤：
    1. Scaffold：根据 product_type 选择对应脚手架
       - web_app → npm create vite + React + Tailwind
       - slack_app → Bolt.js 项目 + manifest.json + .env.example
       - vscode_extension → yo code 脚手架
       - chrome_extension → Manifest V3 标准结构
       - cli_tool → Node/Python CLI 模板
       - api_service → Express/FastAPI 模板
    2. Shared Layer：公共组件、全局状态、API 客户端封装（真实 SDK，非 Mock）
    3. Module Coding Agents（按依赖顺序，内部 Agent tool 管理）
       - 每个 Agent 基于 environment-plan.md 的集成状态决策：
         ✅ 真实集成 → 写真实 API 调用代码，读取 process.env 中的凭证
         ⏭️ 不实现 → 只写接口定义和 TODO 注释，不写 Mock 实现
       - 每个 Agent 内部自修复循环（build + fix，上限 5 次）
    4. .env.example 生成（含所有环境变量字段名，不含值）
    5. README.md 生成（包含真实运行的完整步骤）
  产出：可在真实环境中运行的完整项目代码

      ↓ 中控传递项目代码

Session C（审查）
  输入：项目代码 + dev-plan.md + environment-plan.md + concept.md
  环境变量：中控注入来自 credentials.env 的凭证
  步骤：
    1. Reviewer Agent：功能检查
       - 检查真实集成模块：API 调用是否正确、凭证读取是否规范
       - 检查跳过模块：接口是否预留、TODO 是否清晰
       - 不检查、不修复 Mock 实现（因为不应该有 Mock）
    2. 真实环境验证（根据 product_type 执行不同命令）
    3. Designer Agent：视觉一致性检查（仅适用于有 UI 的 product_type）
    4. Fix Issues：发现问题则在 Session C 内部修复（上限 2 次）
    5. Final Verification：最终验证
  产出：通过验证的项目（或 BUILD_FAILED.md）

  如果 Session C 内部修不好 → 打回 Session B 针对性修复 → 再跑 Session C（最多打回 1 次）
```

### 10.3 product_type 对应的 Scaffold 和验收标准

| product_type | Scaffold 方式 | 验收命令 | 验收条件 |
|---|---|---|---|
| `web_app` | `npm create vite@latest -- --template react` | `npm run build` | 构建产物存在 |
| `slack_app` | Bolt.js 初始化 + `manifest.json` | `npm run build` + 服务启动 | 服务启动不报错，manifest 完整 |
| `vscode_extension` | `yo code` | `npm run compile` + `vsce package` | `.vsix` 文件生成 |
| `chrome_extension` | MV3 手动搭建 | `npm run build`（若有构建步骤）| `manifest.json` 合法，background/content 完整 |
| `cli_tool` | Node/Python CLI 模板 | 直接执行主命令 | 返回预期格式输出 |
| `api_service` | Express/FastAPI 模板 | 启动服务 + `GET /health` | 200 响应 |

### 10.4 关键设计决策

**Planner 的任务拆分方式：混合模式**
- PRD 按功能模块组织（产品逻辑），但最终开发产出是有页面/模块的应用（工程实现）
- Planner 负责做桥接：功能模块 → 代码模块映射
- Module Coding Agent 按模块分配，但每个 agent 拿到的上下文包含"这个模块涉及哪些功能"

**共享层由独立 Agent 先做**
- 全局状态、公共组件、API 客户端封装等跨模块复用的部分
- 先于所有 Module Agent 完成，确保依赖关系清晰

**Scaffold 放在 Session B**
- Session A 纯规划不碰代码
- Session B 从脚手架初始化开始，完整负责所有代码产出

**Review 角色保留 Designer + Reviewer**
- Designer 关注视觉一致性（仅 UI 类 product_type）
- Reviewer 关注功能正确性 + 真实环境验证
- 关注点不同，分开更清晰

### 10.5 三层循环机制

| 循环层级 | 位置 | 上限 | 触发条件 |
|----------|------|------|----------|
| Module Agent 自修复 | Session B 内部 | 5 次 | build 失败 |
| Session C 内部修复 | Session C 内部 | 2 次 | Reviewer/Designer 发现问题 |
| Session C → B 打回 | 中控编排 | 1 次 | Session C 内部修不好 |

**关键原则：循环范围尽量小。** Session B 内部的 build 错误不需要打回 Session A；Session C 能修的不打回 Session B。

失败处理：打回 1 次后仍修不好 → 写 `BUILD_FAILED.md`

### 10.6 中控编排

```python
for prd in prd_docs:
    # 读取 environment-plan.md（含凭证状态和集成决策）
    env_plan = load_env_plan(prd)
    creds = load_credentials(env_plan)  # 从 credentials.env 加载

    # Session A: 规划
    result_a = await session_mgr.run(plan_session_config(prd, env_plan))
    dev_plan_md = find_output(result_a, "dev-plan.md")

    # Session B: 开发（注入凭证）
    result_b = await session_mgr.run(
        dev_session_config(prd, dev_plan_md, env_plan),
        env=creds  # 凭证通过环境变量注入，不写入工作目录
    )

    # Session C: 审查（注入凭证，用于真实环境验证）
    result_c = await session_mgr.run(
        review_session_config(prd, dev_plan_md, env_plan),
        env=creds
    )

    if needs_bounceback(result_c):
        result_b2 = await session_mgr.run(
            dev_fix_session_config(prd, result_c),
            env=creds
        )
        result_c2 = await session_mgr.run(
            review_session_config(prd, dev_plan_md, env_plan),
            env=creds
        )

    collect_project_outputs(prd, work_dir)
```

### 10.7 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| A（规划）| 300s (5min) | $2 | 纯文本规划，不写代码 |
| B（开发）| 2400s (40min) | $8 | Scaffold + 共享层 + 多模块开发 + 自修复 |
| C（审查）| 1200s (20min) | $5 | Review + 真实环境验证 + 可能的修复 |
| **单项目总计** | **3900s** | **$15** | |
| **最坏情况（含 1 次打回）** | **~7500s** | **~$28** | 额外 B + C |

*注：先按此分配，跑起来再调。*

### 10.8 Session 配置参数

| 参数 | Session A | Session B | Session C |
|------|-----------|-----------|-----------|
| `timeout_seconds` | 300 | 2400 | 1200 |
| `max_budget_usd` | 2.0 | 8.0 | 5.0 |
| `allowed_tools` | Read, Glob, Grep, Agent | Bash, Agent, Read, Write, Glob, Grep | Bash, Agent, Read, Write, Glob, Grep |
| `model` | sonnet | sonnet | sonnet |

### 10.9 成功判定逻辑

- 检查 `{work_dir}/BUILD_FAILED.md` → 存在则视为构建失败
- 检查 `{work_dir}/demo/package.json` → 存在则视为项目构建成功
- 只检查特定路径，不使用 rglob，避免扫描 `node_modules/`

### 10.10 Prompt 文件

| Prompt 文件 | Session | 职责 |
|------------|---------|------|
| `prompts/stage3/plan.md` | Session A | Planner：读所有文档，产出 dev-plan.md（含 product_type 感知的规划逻辑）|
| `prompts/stage3/dev.md` | Session B | Scaffold（product_type 分支）+ Shared Layer + Module Coding |
| `prompts/stage3/review.md` | Session C | Reviewer + 真实环境验证（product_type 感知）+ Designer + Fix |

---

## 11. 技术实现

### 11.1 技术栈 ✅ 已确定

- **中控脚本**：Python 3.11+ (asyncio)
- **Dashboard**：单文件 `dashboard.html`（vanilla JS + WebSocket，无构建工具）
- **Agent 运行时**：Claude Code CLI (`claude -p`)
- **通信**：中控 EventBus → WebSocketServer → Dashboard
- **依赖**：websockets, aiofiles, python-dotenv
- **Python 环境**：`.venv/` (venv)

### 11.2 中控脚本职责

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
11. [可选] ConfigGate: 依赖分析 → 凭证收集 → 环境规划（🆕）
12. Stage 3: 为每份 PRD 串行启动 3 个 session（Plan → Dev → Review），含条件性 C→B 打回 → 收集项目目录
13. Stage 5: 为每个成功项目生成 pitch-script.md + pitch-deck.html，复制到 demo/ 目录
14. Stage 4: 发布到 GitHub（含 pitch 产出）
15. 全程通过 EventBus → WebSocket 双向通信 Dashboard
```

### 11.3 Session 管理 ✅ 已实现

- 每个 session 有独立的工作目录 (`workspace/stage1/research-{slug}/`)
- `SessionManager` 用 `asyncio.Semaphore(5)` 控制并发
- 逐行解析 `stream-json` 输出，提取工具使用事件推送 Dashboard
- Session 完成判定：进程退出码 + 扫描工作目录中的 `*.md` 文件
- Session 异常处理：超时 kill + 最多重试 1 次
- 失败 fallback：Dedup 失败时使用 raw cards
- 🆕 新增 `env` 参数支持：凭证通过环境变量注入子进程

### 11.4 文件系统结构

```
hackathon-agent/
├── control/
│   ├── __init__.py
│   ├── __main__.py              # python -m control 入口
│   ├── main.py                  # CLI 入口 + 组件编排
│   ├── models.py                # 数据模型 (SessionConfig, SessionResult, Event, HackathonBrief, ProductType, EnvironmentPlan, CredentialSpec, ...)
│   ├── event_bus.py             # 异步事件 pub/sub
│   ├── session_manager.py       # 核心：管理 claude CLI 子进程（含 env 注入支持）
│   ├── ws_server.py             # WebSocket 服务端（双向通信）
│   ├── review_gate.py           # ReviewGate: 阶段间人工筛选
│   ├── config_gate.py           # 🆕 ConfigGate: 凭证收集 + 可行性验证
│   └── stages/
│       ├── __init__.py
│       ├── stage0.py            # 阶段零：赛题解析
│       ├── stage1.py            # 阶段一完整逻辑
│       ├── stage2.py            # 阶段二：PRD 生成编排
│       ├── stage2_5.py          # 🆕 ConfigGate 编排
│       ├── stage3.py            # 阶段三：Demo 开发编排（product_type 感知 + 凭证注入）
│       ├── stage4.py            # 阶段四：GitHub 发布 (git/gh, 无 AI session)
│       └── stage5.py            # 阶段五：Pitch Deck 生成编排
│
├── dashboard.html               # 单文件监控 + 交互页面（含 ReviewGate UI + ConfigGate UI）
│
├── prompts/
│   ├── stage0/
│   │   └── interpreter.md       # 赛题解析 Agent
│   ├── stage1/
│   │   ├── main.md              # 主 Agent: 人群展开 → JSON（含外部环境可及性粗筛）
│   │   ├── research.md          # Research: 内部 Agent tool 管理 3 sub-agents（Idea Card 含依赖评估）
│   │   └── dedup.md             # 去重 + 质量过滤
│   ├── stage2/
│   │   ├── concept.md           # Session 1: 痛点验证 + product_type 确定 + 概念层
│   │   ├── logic.md             # Session 2: 功能模块（宿主环境真实概念）
│   │   └── technical.md         # Session 3: 技术栈 + Prerequisites Checklist + 部署说明
│   ├── stage2_5/
│   │   └── env_planner.md       # 🆕 根据收集到的凭证生成 environment-plan.md
│   ├── stage3/
│   │   ├── plan.md              # Session A: product_type 感知的开发规划
│   │   ├── dev.md               # Session B: Scaffold 分支 + 不 Mock 原则 + Module Coding
│   │   └── review.md            # Session C: product_type 感知的验收 + Designer + Fix
│   └── stage5/
│       ├── storyteller.md       # Session 1: Pitch 叙事脚本生成
│       └── deck-builder.md      # Session 2: HTML 幻灯片构建
│
├── templates/
│   ├── idea-card.md             # Idea Card 模板（含外部依赖评估）
│   └── scaffolds/               # 🆕 各 product_type 的脚手架模板
│       ├── slack_app/
│       │   ├── manifest.json.template
│       │   └── .env.example
│       ├── chrome_extension/
│       │   └── manifest.json.template
│       └── vscode_extension/
│           └── .vscodeignore.template
│
├── workspace/                   # 运行时工作空间 (gitignored)
│   ├── stage0/
│   │   └── interpreter/         # Stage 0 工作目录
│   ├── stage1/
│   │   ├── main/                # 主 Agent 工作目录
│   │   ├── research-{slug}/     # 各 Research Session 工作目录
│   │   ├── dedup/input/         # 去重输入
│   │   └── output/              # 最终产出
│   ├── stage2/
│   │   ├── {card-slug}/
│   │   │   ├── concept/         # Session 1 工作目录
│   │   │   ├── logic/           # Session 2 工作目录
│   │   │   └── technical/       # Session 3 工作目录
│   │   └── output/{card-slug}/  # 最终产出 (concept.md + logic.md + technical.md)
│   ├── stage2.5/                # 🆕
│   │   ├── credentials.env      # gitignored
│   │   └── {card-slug}/
│   │       ├── credentials-needed.md
│   │       └── environment-plan.md
│   ├── stage3/
│   │   └── {prd-slug}/
│   │       ├── plan/            # Session A 工作目录 (dev-plan.md)
│   │       └── dev/             # Session B+C 共享工作目录
│   │           └── demo/        # 产出项目
│   │               ├── .env.example  # 字段名，不含值
│   │               ├── README.md     # 含真实运行步骤
│   │               └── [项目代码]
│   └── stage5/                  # 🆕
│       ├── {slug}/
│       │   ├── storyteller/     # Session 1 工作目录
│       │   │   ├── demo -> symlink  # 指向 Stage 3 demo/
│       │   │   └── pitch-script.md
│       │   └── deck/            # Session 2 工作目录
│       │       └── pitch-deck.html
│       └── output/{slug}/       # 最终产出
│           ├── pitch-script.md
│           └── pitch-deck.html
│
├── .venv/                       # Python 虚拟环境
├── requirements.txt             # websockets, aiofiles, python-dotenv
├── .gitignore                   # 确保 credentials.env 和 .env 被忽略
├── CLAUDE.md
└── Hackathon Agent Design.md
```

---

## 12. Agent 角色总览

| 阶段 | 角色 | 数量 | 职责 | 形式 |
|------|------|------|------|------|
| 零 | Interpreter | 0-1 | 解析复杂赛题为结构化 Brief | Claude Code session |
| 一 | 主 Agent | 1 | 灵感搜索 + 人群展开、粗筛（软件可解决 + Agent 可独立完成）→ JSON（含 scope、likely_product_types）| Claude Code session |
| 一 | Research | 每人群 1 个 | 内部管理 2 sub-agents，产出 Idea Card（含依赖评估）| Claude Code session |
| 一 | ├ Search | (内部, 按 pain area 可并行) | 原则驱动搜索痛点，写 findings 文件 | Agent tool sub-agent |
| 一 | └ Synthesis | (内部) | 独立上下文合成 Idea Card，含自审（吸收原 Critic 功能）| Agent tool sub-agent |
| 一 | Dedup | 流式 + 最终审查 | 流式去重（每张新卡轻量比较）+ 最终轻量审查（卡片 ≤3 时跳过）| claude -p 调用 |
| — | ReviewGate | — | 人工筛选 Idea Card（展示依赖评估）| Dashboard UI / CLI |
| 二 | Session 1: 产品定义 | 每 Idea 1 个 | 验证痛点、确定 product_type、概念层定义、自审 | Claude Code session |
| 二 | Session 2: 产品设计 | 每 Idea 1 个 | 功能模块（宿主环境真实概念）、模块关系、用户流程 | Claude Code session |
| 二 | Session 3: 技术方案 | 每 Idea 1 个 | 技术栈、实现方案、API、项目架构、Prerequisites Checklist | Claude Code session |
| — | ConfigGate | — | 凭证收集 + 可行性验证 + environment-plan.md 生成 | Dashboard / CLI |
| 二.五 | Env Planner | 每项目 1 个 | 根据已收集凭证生成 environment-plan.md | Claude Code session |
| 三 | Session A: Planner | 每项目 1 个 | product_type 感知的开发规划 | Claude Code session |
| 三 | Session B: Dev | 每项目 1 个 | product_type Scaffold + 真实集成开发 | Claude Code session |
| 三 | ├ Shared Layer Agent | (内部) | 公共层，真实 SDK 封装 | Agent tool sub-agent |
| 三 | └ Module Coding Agents | (内部, 每模块 1 个) | 按模块开发，无 Mock | Agent tool sub-agent |
| 三 | Session C: Review | 每项目 1 个 | 真实环境验证 + Review + Fix | Claude Code session |
| 三 | ├ Reviewer Agent | (内部) | 功能检查 + 真实环境验证 | Agent tool sub-agent |
| 三 | └ Designer Agent | (内部) | 视觉一致性（有 UI 的 product_type）| Agent tool sub-agent |
| 四 | — | — | 确定性操作：README + git + gh（无 AI session）| Shell commands |
| 五 | Storyteller | 每项目 1 个 | 读 PRD + demo 源码，搜索 hook，写 pitch-script.md | Claude Code session |
| 五 | Deck Builder | 每项目 1 个 | 将 pitch script 转为自包含 HTML 幻灯片 | Claude Code session |

**实现说明**：
- **阶段二**：每张 Idea Card 对应 3 个串行的独立 Claude Code session（产品定义 → 产品设计 → 技术方案），不再使用 sub-agent 模式。Session 间通过文件系统传递文档。
- **阶段三**：每份 PRD 对应 3 个串行的独立 Claude Code session（Plan → Dev → Review）。Session B 和 C 内部通过 Agent tool 管理 sub-agent。Session C 修不好可打回 Session B（中控编排，最多 1 次）。
- **阶段四**：纯确定性 shell 操作，不需要 AI session。

---

## 13. 循环与容错机制总览

### 13.1 Stage 1

| 机制 | 参与角色 | 说明 |
|------|----------|------|
| Synthesis 自审 | Synthesis sub-agent | 合成 Idea Card 时用 Quality Gates 做自审检查，证据不足的发现不产出卡片 |
| 流式去重 | 中控 + 轻量 claude -p | 每张新卡与已有池比较，明显重复时合并 |
| 最终审查 | 中控 + claude -p | 检查遗漏重复、格式标准化、质量排序 |

失败处理：Synthesis 自审认为证据不足 → 不产出该 Idea Card（自然淘汰，非硬性门槛）

### 13.2 Stage 2

| 机制 | 位置 | 说明 |
|------|------|------|
| Session 1 内部自审 | Session 1 末尾 | 概念层定义完成后自审：痛点是否成立、product_type 是否匹配。不通过 → `ELIMINATED.md` |

失败处理：Session 1 自审不通过 → 写 `ELIMINATED.md`，中控跳过后续 Session 2 和 Session 3

### 13.3 ConfigGate

| 机制 | 说明 |
|------|------|
| 载体依赖缺失 → BLOCKED | 不进入 Stage 3，不降级 Mock |
| 功能依赖缺失 → 跳过对应模块 | 不实现，不 Mock，预留接口 |

### 13.4 Stage 3

| 循环层级 | 位置 | 上限 | 触发条件 | 处理范围 |
|----------|------|------|----------|----------|
| Module Agent 自修复 | Session B 内部 | 5 次 | build 失败 | 语法错误、import、简单 bug |
| Session C 内部修复 | Session C 内部 | 2 次 | Reviewer/Designer 发现问题 | 视觉不一致、功能不符 PRD |
| Session C → B 打回 | 中控编排 | 1 次 | Session C 内部修不好 | 需要重新开发的结构性问题 |

失败处理：打回 1 次后仍修不好 → 写 `BUILD_FAILED.md`

---

## 14. Token 消耗预估

### 14.1 各阶段预估

| 阶段 | 预估 token | 说明 |
|------|-----------|------|
| Stage 0 | 5K-10K | 简单模式跳过 |
| Stage 1 | 1M-2M | Research × N + Dedup |
| Stage 2 | 0.5M-1.7M | 3 sessions × 5-7 cards |
| Stage 2.5 | 50K-150K | Env Planner × 5-7 |
| Stage 3 | 3M-8M | 3 sessions × 5-7 projects |
| Stage 4 | ~0 | 纯 shell 操作，无 AI session |
| Stage 5 | 0.5M-1.5M | 2 sessions × 5-7 projects |
| **总计** | **~5M-13.5M** | |

以上为粗略估算，实际消耗取决于项目复杂度、循环次数、打回频率等因素。

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
| 中控实现 | 脚本，非 Agent | 流程编排是确定性逻辑，不需要 AI |
| 解决方向数量 | Idea Card 含 2-3 个方向 | 避免锁死方向，保留 PRD 阶段灵活性 |
| PRD 组织方式 | 三文档递进（concept+logic+technical） | 按抽象层次递进，产品导向（替代按屏幕组织的演示脚本模式） |

### 实现阶段决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 中控语言 | Python (asyncio) | 异步原生支持，subprocess 管理方便 |
| CLI 调用方式 | subprocess (`claude -p`) | 最简单直接，无需额外 SDK |
| Dashboard 实现 | 单文件 HTML + vanilla JS | 无构建工具依赖，直接浏览器打开 |
| Stage 1 编排 | 混合：中控管 session，session 内用 Agent tool 管 sub-agent | 减少中控复杂度，利用 Claude Code 原生能力 |
| 并发控制 | Semaphore(5) | 保守策略，避免 rate limit |
| 权限模式 | `--dangerously-skip-permissions` | 全自动化场景必须 |
| 输出格式 | `--output-format stream-json` | 实时解析进度推送 Dashboard |
| 超时策略 | 按任务复杂度分配（主 Agent 120s / Research 900s / Dedup 300s） | 不同任务不同时长 |
| 重试策略 | 最多 1 次重试 | 简单可靠，避免浪费 token |
| Dedup 失败 fallback | 使用 raw cards | 宁可多不可少 |

### Phase 1.5 增强决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 运行模式 | `--mode full/single/lite` + `--max-directions` | 开发测试时节省 token，生产环境全量运行 |
| 方向裁剪策略 | 优先保留 high relevance | 确保测试时选到最有价值的方向 |
| 少量卡片跳过 Dedup | 卡片 ≤3 时直接跳过 | 没必要为 1-3 张卡启动额外 session |
| 赛题解析 | 独立 Stage 0 session | 结构化提取约束/评审标准，避免信息丢失 |
| 约束注入方式 | `{{#hackathon_context}}` 条件块 | 简单模式时块被移除，零侵入 |
| 人工筛选位置 | 阶段一和阶段二之间 | 最早介入点，避免为不靠谱的 Idea 浪费 PRD token |
| ReviewGate 默认行为 | 所有卡片默认勾选 | 符合"只淘汰不挑选"原则，用户减法操作 |
| ReviewGate 超时 | 10 分钟超时保留全部 | 安全兜底，避免无人值守时管道卡住 |
| WebSocket 双向通信 | `register_handler()` 消息分发 | 最小改动支持回传，不引入额外依赖 |

### Stage 2 Redesign 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 设计理念 | 产品导向（非 Pitch 导向） | 原方案从演示效果倒推产品设计，本末倒置 |
| 产品组织方式 | 按功能模块（非按屏幕/页面） | 按屏幕组织本质是写 demo 脚本，不是做产品设计 |
| Agent 架构 | 3 个串行独立 session（非单 session + 5 sub-agent） | 按抽象层次递进，每次思维模式转变作为 session 边界 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示效果 |
| Wireframe Agent | **删除** | 线框图推迟到 Stage 3 |
| Critic Agent | 合并为 Session 1 内部自审 | 不再独立角色，概念层定义后立即自审 |
| 淘汰判定 | Session 1 自审不通过 → ELIMINATED.md | 最早阶段淘汰，节省后续 session token |

### Stage 3 Redesign 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 架构 | 3 个串行独立 session（Plan → Dev → Review） | 按任务性质切分 session 边界 |
| Session 切分点 | A 纯规划 / B 全部代码 / C 审查+修复 | A 不碰代码降低复杂度；B 完整负责所有代码产出；C 独立视角审查 |
| 共享层处理 | 独立 Agent 先于 Module Agent | 确保跨模块复用的部分先完成 |
| Scaffold 位置 | Session B（非 Session A） | Session A 纯规划不碰代码 |
| Review 角色 | Designer + Reviewer 两个角色 | 关注点不同：视觉一致性 vs 功能正确性 |
| 打回机制 | Session C → B，中控编排，最多 1 次 | Session C 修不好的结构性问题需要回到开发阶段 |
| Stage 3 超时 | A: 300s / B: 2400s / C: 1200s | 按任务复杂度分配 |
| Stage 3 预算 | A: $2 / B: $8 / C: $5 | 总计 $15/项目，开发复杂度需要更多预算 |
| 构建验证命令 | `npm run build` (非 `npm run dev`) | build 退出干净，dev 启动持久服务器会卡住 session |
| 失败标志 | `BUILD_FAILED.md` | 类比 Stage 2 的 `ELIMINATED.md`，中控据此判断成败 |
| 成功判定 | 检查 `demo/package.json` 存在 | 避免 rglob 扫描 node_modules/ |
| `--prd-dir` 调试入口 | 跳过 Stage 0+1+2 | 便于单独测试 Stage 3 |
| Scaffold 工具 | coordinator 直接用 Bash，不 spawn sub-agent | 脚手架是确定性操作，不需要 AI 判断 |
| 工作目录 | Session B+C 共享，Session A 独立 | Review 需要访问 dev 产出的 demo/ 目录 |

### 真实产品原则决策（🆕）

| 决策 | 选择 | 理由 |
|------|------|------|
| 产品真实性原则 | 在真实环境运行，不做 Mock | 做有意义的作品，而不是为了让评委给分 |
| Mock 策略 | 消灭 Mock。功能依赖缺失 → 不实现，不 Mock | Mock 是假装做了；"不做"是诚实的 MVP 决策 |
| product_type 确定时机 | Stage 2 Session 1（concept.md 阶段）| 宿主环境是产品存在的前提，必须最早确定 |
| 载体依赖处理 | BLOCKED，不降级 | 没有 Slack workspace 的 Slack Bot 不是这个产品 |
| ConfigGate 定位 | 可行性关卡，不是可选优化 | 验证产品能否真实存在 |
| 验收标准 | product_type 感知，不是通用"构建成功" | 不同类型产品有不同的"跑通"定义 |
| 凭证安全 | 只存 .env，环境变量注入，不进 session 工作目录 | 防止 key 泄漏到代码或文档 |
| Stage 1 粗筛 | 加入"外部环境可及性"维度 | 越早发现不可行的方向，越节省后续资源 |
| README 要求 | 必须包含真实运行的完整步骤 | 真实产品的标配，也是验收的一部分 |

### Stage 4 实现决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 实现方式 | 纯 shell 操作 (git/gh)，不用 AI session | 发布是确定性操作，不需要 AI 判断 |
| 仓库命名 | `hackathon-agent-{slug}` | 统一前缀标注来源 |
| README 来源 | 从 Stage 2 concept.md + technical.md + Stage 3 demo/ 生成 | 复用已有文档，保证一致性 |
| `--skip-publish` | 跳过 Stage 4 | 开发测试时不需要发布 |
| `--private` | 创建私有仓库 | 可选隐私保护 |

### Stage 5 Pitch Deck 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 流水线位置 | Stage 4 之前 | Pitch 产出需复制到 demo/ 目录，随项目一起发布到 GitHub |
| Agent 架构 | 2-session 串行 (storyteller → deck builder) | 叙事创作与视觉设计是不同技能 |
| Demo 访问方式 | Symlink demo/ 到 storyteller 工作目录 | Session 可直接读源码，无需复制 |
| Hook 数据来源 | Storyteller 使用 WebSearch | 真实统计/引用，不是编造的数据 |
| 幻灯片格式 | 自包含 HTML，无 JS 框架 | 浏览器直接打开，不需要构建步骤 |
| 幻灯片导航 | CSS-only slides + 键盘事件 | 最小化依赖，投影仪场景可靠 |
| `--skip-pitch` | 跳过 Stage 5 | 开发测试时不需要 pitch deck |
| Session 预算 | $3/session | 与 Stage 2 session 复杂度相当 |

### Stage 1 Redesign 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 整体定位 | 从 hackathon demo 转向 indie developer MVP | 时间不再是约束，token 消耗是真正约束且值得投入 |
| 筛选标准 | 软件可解决 + Agent 可独立完成 | 替代 hackathon feasibility，更多方向存活进入 Stage 2 |
| Main Agent 灵感搜索 | 3-5 次轻量 WebSearch | 拓宽联想空间，发现知识盲区里的人群和痛点角度 |
| scope 字段 | broad / focused 标注方向规模 | 驱动 Research Agent 差异化产出量，大方向深挖多角度 |
| likely_product_types 字段 | 产品形态预判 | 为 ReviewGate 展示外部依赖、Research 参考产品多样性 |
| Search Agent 合并 | Template + Free → 统一 Search | 两者区别不够清晰，合并减少串行步骤 |
| 搜索策略 | 原则 + 示例 + 约束（非模板） | 模板越多 Agent 越机械，site: 搜索大幅失效 |
| Search 并行拆分 | broad 方向按 pain area 拆分并行 | 上下文隔离，避免后半段注意力稀释 |
| Critic 取消 | 合并到 Synthesis 自审 | 避免过度过滤好想法，减少与合成逻辑的重叠 |
| Synthesis 独立 sub-agent | 不由 Research Agent 自己执行 | 搜索和合成是不同任务，独立上下文减少噪音 |
| 证据格式简化 | 一两句话描述（非完整 URL+日期+引用） | 保留"强迫搜索"功能，去掉格式负担 |
| Quality Gates 简化 | 2 条原则（非 5 条硬性门槛） | 配合定位转变和 Critic 取消 |
| Solution Directions 简化 | 方向提示（非完整评估+推荐度） | Research Agent 核心能力是搜索验证，产品设计留给 Stage 2 |
| Dedup 架构 | 流式去重 + 最终轻量审查（非批处理） | 与 Research 并行提速，减少上下文压力 |
| Dedup 排名 | Agent 综合判断（非 5 因子加权公式） | LLM 不会精确执行百分比权重 |
| 不加反平庸排除机制 | 保留 | 平庸的根源是切入角度太泛，应在 Research 阶段通过深挖解决 |

---

## 16. 待定与后续迭代项

### 16.1 第一版不做，后续迭代

- 智能 token 预算管理
- 多轮 ConfigGate（Stage 3 开发过程中发现需要新凭证时的处理）

### 16.2 需要在实现中验证和调整

- 各 product_type 的 Scaffold 模板完整性
- Session C 真实环境验证命令的超时处理（服务启动需要时间）
- ConfigGate CLI 模式的凭证收集交互设计
- Env Planner session 的具体 prompt
- 循环次数上限的最优值
- 搜索深度的最优平衡点

### 16.3 Stage 2 待确定

1. Session 2 和 Session 3 是否带内部自审
2. Prompt 文件组织方式（3 个独立文件 vs 其他形式）
3. 单个 session 失败时的重试策略

### 16.4 Stage 3 待确定

1. dev-plan.md 中 product_type 感知部分的具体格式
2. Session C 真实环境验证各 product_type 的完整命令集
3. 打回机制的触发条件定义
4. 打回时 Session B 接收 Session C 问题描述的格式

---

## 17. Stage 4：GitHub 发布 ✅ 已实现

### 17.1 目标

将 Stage 3 产出的成功项目自动发布到 GitHub，每个项目创建独立的公开仓库。

### 17.2 核心特征

- **纯确定性操作**：README 生成 + git init + gh repo create + push，不需要 AI session
- 单个项目发布失败不影响其他项目
- 项目并行发布

### 17.3 数据流

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

### 17.4 仓库内容

每个 GitHub 仓库包含：
- 项目代码（来自 Stage 3 的 demo/ 目录）
- 标准化 README.md（项目名、问题描述、解决方案、技术栈、安装和启动指令）
- `.env.example`（环境变量字段名，不含实际值）

### 17.5 CLI 选项

- `--skip-publish`：跳过 Stage 4，不发布到 GitHub
- `--private`：创建私有仓库（默认公开）

### 17.6 事件

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `publish_started` | 项目开始发布 | `{project_dir, repo_name}` |
| `publish_completed` | 发布成功 | `{repo_name, repo_url, project_dir}` |
| `publish_failed` | 发布失败 | `{repo_name, error}` |

---

## 18. Stage 5：Pitch Deck 生成 ✅ 已实现

### 18.1 目标

为每个成功构建的项目自动生成 pitch 演讲脚本和 HTML 幻灯片，将技术产出转化为可以在 hackathon 现场使用的演示材料。

### 18.2 核心特征

- **2-session 串行流水线**：storyteller（叙事脚本）→ deck builder（HTML 幻灯片）
- 与 Stage 4 **并行执行**：两者都只依赖 Stage 3 输出
- 不同项目间并行，同一项目 2 个 session 串行

### 18.3 流水线位置

```
Stage 3 (Demo) → Stage 5 (Pitch Deck) → copy to demo/ → Stage 4 (GitHub Publish)
```

Stage 5 在 Stage 4 之前执行。Pitch 产出（pitch-script.md + pitch-deck.html）复制到各项目的 demo/ 目录后，Stage 4 的 `git add -A` 会自动将其包含在 GitHub 仓库中。

### 18.4 数据流

```
Inputs: concept.md + logic.md + technical.md + demo/
    │
    ▼
[Session 1: Storyteller] → pitch-script.md
    │  读取 PRD 文档 + demo 源码，WebSearch 找 hook
    │  产出: Hook + Problem + Solution + Our Demo + Closing
    ▼
[Session 2: Deck Builder] → pitch-deck.html
    │  将 pitch script 转为自包含 HTML 幻灯片
    │  CSS-only slides, 键盘导航, speaker notes
    ▼
Output: workspace/stage5/output/{slug}/pitch-script.md + pitch-deck.html
```

### 18.5 Pitch 结构（4+1 部分）

1. **Hook** — 注意力抓取：惊人统计/问题/场景（Storyteller 使用 WebSearch 找真实数据）
2. **Problem** — 痛点叙事：用 concept.md 中的人物和场景讲故事
3. **Solution** — 产品揭示：产品名 + 价值主张 + 3 个核心功能（来自 logic.md）
4. **Our Demo** — 演示走查：基于实际 demo 源码的具体操作描述
5. **Closing** — 收尾：影响力声明 + 呼应 hook

### 18.6 Agent 角色

| Session | 角色 | 职责 | 工具 |
|---------|------|------|------|
| Session 1 | Storyteller | 阅读 PRD + demo 源码，搜索 hook 数据，撰写演讲脚本 | Read, Write, Glob, Grep, WebSearch, WebFetch |
| Session 2 | Deck Builder | 将脚本转为视觉 HTML 幻灯片 | Read, Write, Glob, Grep, Bash |

### 18.7 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| Storyteller | 600s (10min) | $3 | 需要搜索 + 阅读 + 写作 |
| Deck Builder | 600s (10min) | $3 | HTML/CSS 生成，复杂度适中 |
| **单项目总计** | **1200s** | **$6** | |

### 18.8 工作目录结构

```
workspace/stage5/
├── {slug}/
│   ├── storyteller/          # Session 1 工作目录
│   │   ├── demo -> symlink   # 指向 Stage 3 的 demo/ 目录
│   │   └── pitch-script.md   # 产出
│   └── deck/                 # Session 2 工作目录
│       ├── pitch-script.md   # 从 Session 1 复制
│       └── pitch-deck.html   # 产出
└── output/{slug}/            # 最终产出
    ├── pitch-script.md
    └── pitch-deck.html
```

### 18.9 事件

| 事件 | 触发时机 | data 字段 |
|------|----------|-----------|
| `pitch_started` | Pitch 生成开始 | `{session_id, slug}` |
| `pitch_script_completed` | 演讲脚本完成 | `{session_id, slug, script_path}` |
| `pitch_deck_completed` | 幻灯片完成 | `{session_id, slug, deck_path, script_path}` |
| `pitch_deck_failed` | Pitch 生成失败 | `{session_id, error}` |

### 18.10 CLI 选项

- `--skip-pitch`：跳过 Stage 5，不生成 pitch deck

### 18.11 失败处理

- Storyteller session 失败 → 不启动 Deck Builder，该项目无 pitch 产出
- Deck Builder session 失败 → 仍保留 pitch-script.md 到 output（部分产出优于无产出）
- 单个项目 pitch 失败不影响其他项目
