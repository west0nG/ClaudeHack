# Stage 2 PRD 架构改造方案

## 变更概述

对 Stage 2（PRD 生成）进行架构改造，核心方向：**从 Pitch 导向转为产品导向**。

---

## 一、设计理念变更

### 原方案问题

原方案本质上是"倒着写 PRD"——从演示效果倒推产品设计，而非从问题出发正向推导：

- PRD 按**屏幕/页面**组织（屏幕一、屏幕二、屏幕三），实际上是在写 demo 脚本
- Pitch Agent 参与产品设计阶段，演示效果的考量侵入了产品决策
- 产出偏向"怎么展示"而非"解决什么问题"

### 新方案原则

- **产品导向**：先把问题想清楚、把产品设计好，Pitch 是后续包装的事
- **按功能模块组织**：不再按页面/屏幕拆分，而是按功能模块组织产品定义
- **按抽象层次递进**：概念层 → 逻辑层 → 物理层，从粗到细
- **Demo 呈现真实效果**：产品本身设计好了，demo 自然能展示价值，不需要刻意编排

---

## 二、Agent 架构变更

### 原方案：单 Session + 5 角色

```
单个 Claude Code Session (prd.md coordinator)
  ├ Product Agent     → 选方案 + 设计逐屏演示路径
  ├ Technical Agent   → 技术可行性 + 技术栈
  ├ Critic Agent      → 方案合理性审查
  ├ Pitch Agent       → 演示效果优化 + 演示脚本
  └ Wireframe Agent   → HTML 线框图生成
```

### 新方案：3 个串行独立 Session

```
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

---

## 三、角色变更对照

| 原角色 | 新方案处理 | 理由 |
|--------|-----------|------|
| Product Agent | → Session 1 + Session 2 | 拆为概念层和逻辑层两个阶段 |
| Technical Agent | → Session 3 | 独立 session，专注技术方案 |
| Critic Agent | → Session 1 内部自审步骤 | 不再独立角色，概念层定完后自审 |
| Pitch Agent | **删除** | PRD 阶段不考虑演示，产品导向 |
| Wireframe Agent | **删除** | PRD 阶段不做线框图，交给 Stage 3 |

---

## 四、Session 切分理由

按三个原则切分 session 边界：

1. **信息耦合度**：步骤 1-3（验证痛点 → 找 Idea → 概念层）思维高度连贯，必须在同一 session
2. **任务性质变化**：概念层（产品定义）→ 逻辑层（产品设计）→ 物理层（技术方案），每次切换都是思维模式的转变
3. **天然切分点**：每个 session 的产出都是结构化的自包含文档，可以作为下一个 session 的独立输入

---

## 五、产出变更

### 原产出

- 1 份按屏幕组织的 PRD（含三层描述：表面层 + 产品逻辑层 + 技术逻辑层）
- 1 份 HTML 线框图

### 新产出

3 份按抽象层次组织的独立文档：

| 文档 | 内容 | 主要消费者 |
|------|------|-----------|
| `concept.md` | 产品定义、核心价值、目标用户、边界 | Stage 3 所有 agent（作为背景参考） |
| `logic.md` | 功能模块、数据流、用户流程 | Stage 3 Planner / Orchestrator |
| `technical.md` | 技术栈、实现方案、项目架构 | Stage 3 技术类 agent（主要 context） |

---

## 六、中控编排变更

### 原方案

每张 Idea Card → 1 个 Claude Code session（内部 Agent tool 管理 5 sub-agent）

### 新方案

每张 Idea Card → 3 个串行 Claude Code session（中控依次调度）：

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

注意：不同 Idea Card 之间仍然可以并行（Semaphore 控制），但同一张卡的 3 个 session 必须串行。

---

## 七、淘汰机制变更

### 原方案

- Critic 连续打回 2 次以上 → 淘汰
- 搜索发现成熟竞品 → 淘汰
- 技术不可行 → 淘汰

### 新方案

- **Session 1 自审不通过** → 写 `ELIMINATED.md`，中控跳过后续 session
  - 痛点不成立（证据不足、场景不真实）
  - 找不到合理的产品方案
  - 已有成熟方案完全解决了该痛点
- Session 2、Session 3 的淘汰/自审机制 → **待定**，后续讨论

---

## 八、待讨论事项

以下事项在本次讨论中暂未确定，需后续补充：

1. **Session 2 和 Session 3 是否带内部自审**
2. **每个 session 的超时和预算**（原方案 Stage 2 整体 timeout=1800s, budget=$5）
3. **三份文档的具体格式模板**（concept.md / logic.md / technical.md 各包含哪些字段）
4. **Prompt 文件组织**（是 3 个独立 prompt 文件还是其他形式）
5. **Stage 3 的适配改造**（Stage 3 的 dev.md 需要适配新的三文档输入格式）
6. **失败处理与重试策略**（单个 session 失败时是否重试、如何重试）