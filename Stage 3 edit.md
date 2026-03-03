# Hackathon Agent — Stage 2 & Stage 3 架构改造方案

## 变更概述

对 Stage 2（PRD 生成）和 Stage 3（Demo 开发）进行架构改造。

**核心方向**：从 Pitch 导向转为产品导向，从单 session 多角色转为多 session 按抽象层次递进。

---

## 一、设计理念变更

### 原方案问题

原方案本质上是"倒着写 PRD"——从演示效果倒推产品设计：

- PRD 按**屏幕/页面**组织（屏幕一、屏幕二、屏幕三），实际上是在写 demo 脚本
- Pitch Agent 参与产品设计阶段，演示效果的考量侵入了产品决策
- 产出偏向"怎么展示"而非"解决什么问题"

### 新方案原则

- **产品导向**：先把问题想清楚、把产品设计好，Pitch 是后续包装的事
- **按功能模块组织**：不再按页面/屏幕拆分，而是按功能模块组织产品定义
- **按抽象层次递进**：概念层 → 逻辑层 → 物理层，从粗到细
- **Demo 呈现真实效果**：产品本身设计好了，demo 自然能展示价值，不需要刻意编排

---

## 二、Stage 2 架构变更

### 2.1 原方案：单 Session + 5 角色

```
单个 Claude Code Session (prd.md coordinator)
  ├ Product Agent     → 选方案 + 设计逐屏演示路径
  ├ Technical Agent   → 技术可行性 + 技术栈
  ├ Critic Agent      → 方案合理性审查
  ├ Pitch Agent       → 演示效果优化 + 演示脚本
  └ Wireframe Agent   → HTML 线框图生成
```

执行流：Product ↔ Technical (1-2轮) → Critic (1-2轮打回) → Pitch (1轮微调) → Wireframe

### 2.2 新方案：3 个串行独立 Session

```
Session 1（产品定义）
  输入：Idea Card
  步骤：
    1. 验证痛点 — 基于 Idea Card 的场景和证据，判断痛点是否成立
    2. 找产品 Idea — 从 Idea Card 的 2-3 个解决方向中选择/组合/改进
    3. 概念层定义 — 产品是什么、为谁、核心价值主张、边界
    4. 自审 — 概念层是否真正解决痛点、边界是否合理；不通过则内部修正，修不好则淘汰
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

### 2.3 Session 切分理由

按三个原则切分 session 边界：

1. **信息耦合度**：步骤 1-3（验证痛点 → 找 Idea → 概念层）思维高度连贯，必须在同一 session
2. **任务性质变化**：概念层（产品定义）→ 逻辑层（产品设计）→ 物理层（技术方案），每次切换都是思维模式的转变
3. **天然切分点**：每个 session 的产出都是结构化的自包含文档，可以作为下一个 session 的独立输入

### 2.4 角色变更对照

| 原角色 | 新方案处理 | 理由 |
|--------|-----------|------|
| Product Agent | → Session 1 + Session 2 | 拆为概念层和逻辑层两个阶段 |
| Technical Agent | → Session 3 | 独立 session，专注技术方案 |
| Critic Agent | → Session 1 内部自审步骤 | 不再独立角色，概念层定完后自审 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示，产品导向 |
| Wireframe Agent | **删除** | PRD 阶段不做线框图，交给 Stage 3 |

### 2.5 产出变更

**原产出**：
- 1 份按屏幕组织的 PRD（含三层描述：表面层 + 产品逻辑层 + 技术逻辑层）
- 1 份 HTML 线框图

**新产出**：3 份按抽象层次组织的独立文档

| 文档 | 内容 | 主要消费者 |
|------|------|-----------|
| `concept.md` | 产品定义、核心价值、目标用户、边界 | Stage 3 所有 agent（作为背景参考） |
| `logic.md` | 功能模块、数据流、用户流程 | Stage 3 Planner / Orchestrator |
| `technical.md` | 技术栈、实现方案、项目架构 | Stage 3 技术类 agent（主要 context） |

### 2.6 淘汰机制

- **Session 1 自审不通过** → 写 `ELIMINATED.md`，中控跳过后续 session
  - 痛点不成立（证据不足、场景不真实）
  - 找不到合理的产品方案
  - 已有成熟方案完全解决了该痛点

### 2.7 中控编排

```python
# 伪代码
for card in idea_cards:
    # Session 1: 产品定义
    result1 = await session_mgr.run(concept_config(card))
    if is_eliminated(result1):
        emit("prd_eliminated", card)
        continue

    # Session 2: 产品设计
    result2 = await session_mgr.run(logic_config(card, concept_md))

    # Session 3: 技术方案
    result3 = await session_mgr.run(technical_config(card, concept_md, logic_md))

    # 收集三份文档
    collect_outputs(card, concept_md, logic_md, technical_md)
```

不同 Idea Card 之间仍然可以并行（Semaphore 控制），同一张卡的 3 个 session 必须串行。

### 2.8 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| Session 1（产品定义）| 600s (10min) | $3 | 验证痛点 + 找 Idea + 概念层 + 自审 |
| Session 2（产品设计）| 600s (10min) | $3 | 功能模块 + 数据流 + 用户流程 |
| Session 3（技术方案）| 600s (10min) | $3 | 技术栈 + 实现方案 + 架构 |
| **单卡总计** | **1800s** | **$9** | 原方案 1800s / $5 |

*注：先按此分配，跑起来再调。*

---

## 三、Stage 3 架构变更

### 3.1 原方案：单 Session + 7 步流水线

```
单个 Claude Code Session (dev.md coordinator)
  Step 1: Planner Agent       → 按屏幕拆开发计划
  Step 2: Scaffold             → 脚手架初始化
  Step 3: Coding Agents        → 每屏幕一个 sub-agent，按 wave 并行
  Step 4: Designer Agent       → 视觉一致性检查
  Step 5: Reviewer Agent       → 功能检查 + 端到端验证
  Step 6: Fix Issues           → 条件性修复
  Step 7: Final Verification   → 最终检查
```

### 3.2 新方案：3 个串行独立 Session

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

### 3.3 关键设计决策

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

### 3.4 循环机制

| 循环层级 | 位置 | 上限 | 触发条件 |
|----------|------|------|----------|
| Coding Agent 自修复 | Session B 内部 | 5 次 | build 失败 |
| Session C 内部修复 | Session C 内部 | 2 次 | Designer/Reviewer 发现问题 |
| Session C → B 打回 | 中控编排 | 1 次 | Session C 内部修不好 |

失败处理：打回 1 次后仍修不好 → 写 `BUILD_FAILED.md`

### 3.5 超时与预算

| Session | 超时 | 预算 | 理由 |
|---------|------|------|------|
| A（规划）| 300s (5min) | $2 | 纯文本规划，不写代码 |
| B（开发）| 2400s (40min) | $8 | scaffold + 共享层 + 多页面开发 + 自修复 |
| C（审查）| 1200s (20min) | $5 | review + 可能的修复 |
| **单项目总计** | **3900s** | **$15** | 原方案 3600s / $10 |
| **最坏情况（含 1 次打回）** | **~7500s** | **~$28** | 额外 B + C |

*注：先按此分配，跑起来再调。*

---

## 四、中控编排变更总览

### 4.1 Stage 2 编排

```
每张 Idea Card → 3 个串行 session（不同卡之间可并行）：
  Session 1（产品定义）→ concept.md / ELIMINATED.md
  Session 2（产品设计）→ logic.md
  Session 3（技术方案）→ technical.md
```

### 4.2 Stage 3 编排

```
每份 PRD（三文档）→ 3 个串行 session（不同项目之间可并行）：
  Session A（规划）→ dev-plan.md
  Session B（开发）→ 项目代码
  Session C（审查）→ 验证通过 / BUILD_FAILED.md
  [条件] C 修不好 → 打回 B → 再跑 C（最多 1 次）
```

### 4.3 端到端流水线（更新后）

```
用户输入
  → [Stage 0: 赛题解析]（可选）
  → [Stage 1: 需求发现] → 10-20 Idea Cards
  → [ReviewGate: 人工筛选]
  → [Stage 2: PRD 生成] → 每张卡 3 session → concept.md + logic.md + technical.md
  → [Stage 3: Demo 开发] → 每份 PRD 3 session → 可运行项目
  → 5-7 个独立项目
```

---

## 五、Prompt 文件变更

### 原结构

```
prompts/stage2/
  └── prd.md            # 单 coordinator prompt，内嵌 5 角色
prompts/stage3/
  └── dev.md            # 单 coordinator prompt，内嵌 7 步
```

### 新结构

```
prompts/stage2/
  ├── concept.md        # Session 1: 验证痛点 + 找 Idea + 概念层 + 自审
  ├── logic.md          # Session 2: 功能模块 + 数据流 + 用户流程
  └── technical.md      # Session 3: 技术栈 + 实现方案 + 架构
prompts/stage3/
  ├── plan.md           # Session A: Planner（功能→页面映射 + 开发计划）
  ├── dev.md            # Session B: Scaffold + Shared Layer + Page Coding
  └── review.md         # Session C: Designer + Reviewer + Fix + Final Verification
```

---

## 六、待定事项

以下事项需要在实现过程中验证和补充：

1. **Session 2、Session 3（Stage 2）是否需要内部自审** — 跑起来看质量再决定
2. **三份 PRD 文档的具体格式模板** — concept.md / logic.md / technical.md 各包含哪些字段
3. **dev-plan.md 的具体格式** — 功能→页面映射怎么表达
4. **超时与预算的实际调优** — 当前值为初始估计，需根据实际运行调整
5. **Dashboard 事件适配** — 新增 session 类型的事件定义
6. **Stage 3 的 allowed_tools** — 各 session 的工具权限是否需要区分