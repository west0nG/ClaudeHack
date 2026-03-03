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
- 完整的 PRD 文档
- HTML 线框图
- 演示脚本

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
- **阶段二**：筛选并深化为 5-7 份完整 PRD
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
- 阶段二：10-20 个并行 PRD session
- 阶段三：5-7 个并行开发 session

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

## 7. 阶段二：PRD 生成

### 7.1 目标

对 10-20 个 Idea Card 并行深入，淘汰不可行的，为存活的 5-7 个各自生成完整的 PRD。

### 7.2 核心设计原则

- 每个 Idea Card 由一组**完全独立**的 sub-agent 处理，Idea Card 之间无交互
- 只做筛选，不做挑选——淘汰明显不可行的，剩余全部保留并生成 PRD
- 如果 5-7 个都能产出完整 PRD，就同时全部进入阶段三
- PRD 产出两份：给开发 Agent 的结构化 Markdown + 给用户的附带 HTML 线框图

### 7.3 Agent 编排

每个 Idea Card 由以下五个角色的 sub-agent 协作处理：

#### 7.3.1 Product Agent

- 读取 Idea Card，从 2-3 个解决方向中选择或组合出最优方案
- 定义产品是什么、核心功能有哪些
- 设计演示路径的逐屏描述

#### 7.3.2 Technical Agent

- 评估 Product Agent 方案的技术可行性
- 确定技术栈（默认偏向 React + Vite + Tailwind 等快速出原型的选择）
- 补充技术实现细节

与 Product Agent 之间存在**小循环**（1-2 轮）：如果某功能技术上做不了或太复杂，反馈给 Product Agent 调整方案。

#### 7.3.3 Critic Agent

- 审视方案是否真的解决了 Idea Card 中的痛点
- 检查逻辑漏洞、是否把简单问题搞复杂
- 如发现根本性问题，打回给 Product Agent 重新设计

与 Product Agent 之间存在**循环**（最多 1-2 轮）。如果连续打回两次以上，标记该 Idea 为不可行，直接淘汰。

#### 7.3.4 Pitch Agent

- 从演示效果角度审视整个方案
- 评估 wow moment 在哪里、叙事线是否清晰
- 建议调整演示路径顺序、强化视觉效果、优化展示节奏
- 产出演示脚本

反馈交给 Product Agent 做**最后一轮微调**。

#### 7.3.5 Wireframe Agent

- 在方案完全确定后介入
- 根据最终逐屏描述生成简单的 HTML 线框图
- 灰色方块级别，只需让用户看到布局和交互流程
- 纯执行，无循环

### 7.4 执行顺序与循环

```
Product Agent
    ↕ (1-2 轮)
Technical Agent
    ↓
Critic Agent → 如发现问题 → 打回 Product Agent (最多 1-2 轮)
    ↓
Pitch Agent → 反馈 → Product Agent 微调 (1 轮)
    ↓
Wireframe Agent → 生成线框图 (无循环)
```

总共约 3-5 轮交互。

### 7.5 淘汰机制

以下情况自然淘汰：

- 搜索发现已有很成熟的产品解决了该痛点
- 核心技术在 hackathon 时间内无法实现
- 深入后发现痛点实为伪需求
- Critic 连续打回两次以上

### 7.6 阶段二产出

每个存活的 Idea 产出：

- 一份完整的 PRD（Markdown 格式，给开发 Agent）
- 一份 HTML 线框图（给用户观察）

---

## 8. 中间产物：PRD 格式

```markdown
# PRD: [产品名称]

## 一、产品概述

[一句话描述：这个产品是什么、解决谁的什么问题。同时可作为 pitch 的开场白。]

## 二、技术方案

### 技术栈
- 框架：[如 React + Vite]
- UI 库：[如 Tailwind CSS]
- 关键依赖：[如 OpenAI API、Supabase 等]

### 项目结构
```
project/
├── src/
│   ├── components/    # 公共组件
│   ├── pages/         # 页面/屏幕
│   ├── utils/         # 工具函数
│   └── ...
├── public/
└── ...
```

### 全局状态管理
[状态管理方式及理由]

## 三、设计规范

### 设计 Token
- 主色调：[色值]
- 辅助色：[色值]
- 字体：[字体名称]
- 圆角：[数值]
- 间距系统：[规则]

### 公共组件
[需要用到的公共组件列表及基本样式描述]

## 四、演示路径

### 屏幕一：[屏幕名称]
- **URL 路径**：/xxx
- **流程位置**：演示第 1 步，入口页面 → 下一步到屏幕二

#### 表面层（用户看到什么）
[页面元素、布局、视觉效果、交互动作的详细描述]

#### 产品逻辑层（为什么这么设计）
[这一步为什么存在、解决用户什么问题、用户核心诉求、设计取舍及原因]

#### 技术逻辑层（怎么实现）
- **输入**：[数据来源——前一屏传来的数据 / 用户输入 / mock 数据]
- **处理逻辑**：[API 调用 / 本地计算 / 状态变更]
- **中间状态**：[loading / 流式输出 / 分步展示]
- **输出数据结构**：[字段、类型、示例值]
- **传递方式**：[路由参数 / 全局状态 / URL query]

### 屏幕二：[屏幕名称]
...（同上三层结构）

### 屏幕三：[屏幕名称]
...（同上三层结构）

## 五、演示脚本

### 开场 (30秒)
[说什么、展示什么]

### 演示步骤一 (X秒)
[操作什么、说什么、观众应该看到什么]

### 演示步骤二 (X秒)
...

### 收尾 (30秒)
[总结、展望、呼吁]

### Wow Moment
[整个演示中最有冲击力的瞬间是什么、在哪个步骤出现]
```

---

## 9. 阶段三：Demo 开发

### 9.1 目标

将 5-7 份 PRD 并行开发为可运行的 Demo，每个项目产出一个完整的、演示路径能跑通的应用。

### 9.2 核心设计原则

- **Demo 优先原则**：能用 mock 数据就不接真实 API；能硬编码就不做配置化；不做边界情况处理；不做用户体系；只实现演示路径上的功能
- 核心功能必须真正 work，纯静态页面不够
- 5-7 个项目完全独立，各起独立 Claude Code session，不需要任何协调

### 9.3 Agent 编排（单个项目内部）

#### 9.3.1 Planner Sub-agent

在最开始工作一次，读取 PRD 产出开发计划：

- 项目骨架定义
- 屏幕任务拆分
- 屏幕间依赖关系
- 执行顺序编排

完成后即结束。

#### 9.3.2 Orchestrator（主 Agent）

拿着 Planner 的开发计划执行：

- 搭建最简项目骨架（脚手架初始化、路由结构、全局样式、基础公共组件）
- 按计划分配屏幕任务给 Coding Sub-agents
- 按依赖关系决定并行/串行
- 在关键节点触发 Review

骨架保持最简：路由、空页面、全局样式即可，不过度预制组件。

#### 9.3.3 Coding Sub-agents

按屏幕分配，每个 sub-agent 负责一整屏的所有内容。

**两层半策略**：
- 默认一个 sub-agent 做一整屏
- 如果屏幕较简单（静态展示页），sub-agent 独立完成
- 如果屏幕较复杂（复杂交互、API 调用），sub-agent 可自行决定再 spawn sub-agent 拆分
- 集成由负责该屏幕的 sub-agent 自己完成（因为拆分决策是它做的，它最清楚怎么拼）

每个 Coding Sub-agent 接收的上下文：

- 该屏幕的 PRD 描述（三层：表面层 + 产品逻辑层 + 技术逻辑层）
- 技术方案（框架、组件库、关键依赖）
- 项目骨架结构（文件放哪、命名规范）
- 全局样式和公共组件
- 前置屏幕的接口定义/数据结构（如果有依赖）

#### 9.3.4 Designer Agent

- 参与骨架阶段定义设计系统（颜色、字体、间距、组件样式）
- 各屏完成后检查视觉一致性
- 关注点与 Reviewer 不同：Reviewer 看功能和逻辑，Designer 看视觉和体验

#### 9.3.5 Reviewer Agent

- 每个屏幕完成后做**屏幕级检查**：是否符合 PRD、样式是否一致、接口是否对齐
- 所有屏幕完成后做**集成检查**：沿演示路径从头到尾跑一遍，确认整条链路通畅
- 发现问题打回 Coding Agent 修复

### 9.4 三层循环机制

#### 最内层：Coding Agent 自修复循环

- Coding agent 写完代码后自行运行检查
- 如报错，根据错误信息修复并重跑
- **上限**：3-5 次。超过则上报 Orchestrator
- 处理范围：语法错误、import 缺失、简单逻辑 bug

#### 中间层：屏幕级 Review 循环

- Reviewer 检查后发现问题，打回 Coding Agent
- Coding Agent 修改后再次提交 Review
- **上限**：2-3 次。超过则标记该屏幕为问题屏幕
- 处理范围：功能不符合 PRD、样式不一致、接口对不上

#### 最外层：集成级循环

- Reviewer 跑完整条演示路径，发现断点
- 定位到具体屏幕，交回 Coding Agent 修复
- 修复后重跑演示路径
- **上限**：2-3 次。超过则评估是否需要 Planner 重新审视技术方案
- 处理范围：屏幕间跳转、数据传递、整体链路

**关键原则：循环范围尽量小。** 哪里出问题就在哪里循环，不轻易重跑整个流程。

### 9.5 执行顺序

```
Planner → 产出开发计划
    ↓
Orchestrator 搭骨架
    ↓
按依赖关系分配屏幕任务：
  - 无依赖的屏幕 → 并行开发
  - 有依赖的屏幕 → 等前置完成后开始
    ↓
每个屏幕完成后：
  - Coding Agent 自修复循环 (最内层)
  - Designer Agent 检查视觉
  - Reviewer Agent 屏幕级检查 (中间层)
    ↓
所有屏幕完成后：
  - Reviewer Agent 集成检查 (最外层)
  - 修复 → 重跑 → 确认通过
    ↓
Demo 完成
```

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
10. 全程通过 EventBus → WebSocket 双向通信 Dashboard
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
│       └── stage1.py            # 阶段一完整逻辑
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
│   ├── stage2/                  # ⬜ 待实现
│   │   ├── product.md
│   │   ├── technical.md
│   │   ├── critic.md
│   │   ├── pitch.md
│   │   └── wireframe.md
│   └── stage3/                  # ⬜ 待实现
│       ├── planner.md
│       ├── orchestrator.md
│       ├── coding.md
│       ├── designer.md
│       └── reviewer.md
│
├── templates/
│   └── idea-card.md             # ✅ Idea Card 模板
│
├── workspace/                   # 运行时工作空间 (gitignored)
│   ├── stage0/
│   │   └── interpreter/         # Stage 0 工作目录
│   └── stage1/
│       ├── main/                # 主 Agent 工作目录
│       ├── research-{slug}/     # 各 Research Session 工作目录
│       ├── dedup/input/         # 去重输入
│       └── output/              # 最终产出
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
| 二 | Product | 每 Idea 1 个 | 方案设计、演示路径规划 | Sub-agent |
| 二 | Technical | 每 Idea 1 个 | 技术可行性、技术方案 | Sub-agent |
| 二 | Critic | 每 Idea 1 个 | 方案合理性审查 | Sub-agent |
| 二 | Pitch | 每 Idea 1 个 | 演示效果优化、演示脚本 | Sub-agent |
| 二 | Wireframe | 每 Idea 1 个 | HTML 线框图生成 | Sub-agent |
| 三 | Planner | 每项目 1 个 | 开发计划制定 | Sub-agent |
| 三 | Orchestrator | 每项目 1 个 | 骨架搭建、任务调度 | 主 session |
| 三 | Coding | 每屏幕 1 个 | 代码实现 | Sub-agent |
| 三 | Designer | 每项目 1 个 | 设计系统、视觉一致性 | Sub-agent |
| 三 | Reviewer | 每项目 1 个 | 质量检查、集成验证 | Sub-agent |

---

## 12. 循环与容错机制总览

### 12.1 阶段一

| 循环 | 参与角色 | 轮次上限 | 触发条件 |
|------|----------|----------|----------|
| Research ↔ Critic | Research + Critic | 1-2 轮 | Critic 质疑痛点 |

失败处理：Critic 质疑后 Research 无法有效回应 → 该 Idea Card 自然淘汰

### 12.2 阶段二

| 循环 | 参与角色 | 轮次上限 | 触发条件 |
|------|----------|----------|----------|
| Product ↔ Technical | Product + Technical | 1-2 轮 | 技术不可行需调整方案 |
| Critic → Product | Critic + Product | 1-2 轮 | 方案存在根本性问题 |
| Pitch → Product | Pitch + Product | 1 轮 | 演示效果需要优化 |

失败处理：Critic 连续打回 2 次以上 → 标记 Idea 为不可行，淘汰

### 12.3 阶段三

| 循环层级 | 参与角色 | 轮次上限 | 处理范围 |
|----------|----------|----------|----------|
| 最内层 | Coding Agent 自修复 | 3-5 次 | 语法错误、import、简单 bug |
| 中间层 | Reviewer ↔ Coding | 2-3 次 | 功能不符 PRD、样式不一致 |
| 最外层 | Reviewer → 定位 → Coding | 2-3 次 | 屏幕间跳转、数据传递 |

失败处理：中间层超限 → 标记问题屏幕；最外层超限 → Planner 重新评估技术方案

---

## 13. Token 消耗预估

### 13.1 阶段零
- Interpreter：0-1 session，轻量级，约 5K-10K tokens（简单 `--theme` 模式跳过）

### 13.2 阶段一
- 主 Agent：1 session，轻量级，约 10K-20K tokens
- Research sessions：约 14 个，每个含搜索和内容分析，约 50K-100K tokens/session
- Critic sessions：约 7 个，每个约 20K-30K tokens/session
- **阶段一预估总计**：约 1M-2M tokens

### 13.3 阶段二
- PRD sessions：约 10-20 个，每个含 5 个角色的多轮交互，约 100K-200K tokens/session
- **阶段二预估总计**：约 1.5M-4M tokens

### 13.4 阶段三
- 开发 sessions：5-7 个，每个含完整的开发循环，约 500K-1M tokens/session
- **阶段三预估总计**：约 3M-7M tokens

### 13.5 总计
- **整体预估**：约 5M-13M tokens
- 以上为粗略估算，实际消耗取决于项目复杂度、循环次数、搜索深度等因素

---

## 14. 待定与后续迭代项

### 14.1 第一版不做，后续迭代

- ~~用户干预机制（暂停、提问、修改方向）~~ → **已部分实现**（ReviewGate 提供阶段间人工筛选）
- Presentation / Pitch Deck 自动生成（原计划的第四阶段）
- 智能 token 预算管理
- 项目间经验学习（一个项目的成功模式应用到其他项目）

### 14.2 需要在实现中验证和调整

- 各角色 Agent 的 Prompt 具体内容
- 循环次数上限的最优值
- 搜索深度的最优平衡点
- 两层半策略中 Coding Agent 自行拆分的判断标准
- PRD 三层描述的精度是否足够支撑开发
- 中控脚本判定 Session 完成的具体机制

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
| PRD 演示路径 | 三层描述（表面+产品逻辑+技术逻辑） | 开发 Agent 需要同时理解 why 和 how |

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
