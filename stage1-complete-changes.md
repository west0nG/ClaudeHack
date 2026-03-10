# Stage 1 完整改动总结

---

## 一、方向性调整

### 定位转变

整个 Stage 1 的定位从"hackathon 几小时做 demo"转向"indie developer 做真实 MVP"。

**核心变化：**

- 时间不再是筛选标准。Agent 的时间成本会随模型能力提升持续下降，token 成本也在快速降低。在所有 Agent 的假设下，时间约束不成立，真正成立的约束是 token 消耗量——而这个消耗是值得的
- "hackathon feasibility"、"buildable in hours"、"compelling demo" 等表述全部需要调整
- 筛选标准从"hackathon 能不能做"换成"Agent 能不能独立做出来"

### 新的筛选标准（贯穿 Stage 1 所有环节）

1. **软件可解决**：这个痛点能否用纯软件解决——排除需要硬件、物理交互、线下服务的方向
2. **Agent 可独立完成**：这个痛点能否由 Agent 独立完成开发——排除需要人类专业判断才能推进的方向（比如需要医生验证的医疗诊断、需要律师审核的法律工具），但不排除需要较长开发时间或较多 token 的方向

这意味着会有更多方向存活下来进入 Stage 2，由 Stage 2 根据具体的产品定义做更精确的可行性判断。

---

## 二、Main Agent 改动

### 改动 1：新增灵感搜索步骤

**内容：** 在人群发散之前，Main Agent 先执行 3-5 次轻量级 WebSearch。

**搜索定位：**

- 不是为了追踪时效性或最新新闻——时效性不是核心价值，过度关注近期事件可能导致 Agent 输出不稳定，聚焦于短期问题而非长期真实需求
- 不是深度研究（深度研究是 Research Agent 的职责）
- 是灵感补充——拓宽 Claude 的联想空间，发现自身知识盲区里的人群和痛点角度

**设计理由：**

Claude 靠自身知识能覆盖大众方向（教育、开发者、自由职业者），但对于一些真实存在却不在主流讨论里的人群，它可能根本联想不到。搜索能补上这些盲区。即使搜索碰巧返回了一个很小众但吸引眼球的方向，在 hackathon/indie dev 语境下这反而是好东西——而且后续管道（Research → Dedup）有能力做证据验证和质量筛选，方向不靠谱的会自然被淘汰。

**搜索 Query 方向（示例）：**

- `"[theme] biggest frustration reddit"`
- `"[theme] underserved users"`
- `"[theme] workflow problems forum"`

**结果处理方式：**

- 不需要 WebFetch 读完整页面，只看搜索结果的标题和摘要
- 提取出的人群/痛点关键词与 Agent 自身知识平等对待，不需要特别区分来源
- 搜索发现的小众但真实的方向应该被保留

**Token 影响：**

- 3-5 次搜索增加约 3K-5K input token + 1K-2K output token
- Main Agent 总消耗从约 5K 增加到约 12-15K
- 相对 Stage 1 整体 1M-2M token 消耗，可忽略不计

**耗时影响：**

- 增加约 10-20 秒延迟
- 当前 120 秒超时足够覆盖

---

### 改动 2：新增方向规模标注（scope 字段）

**内容：** 输出 JSON 中每个方向增加 `scope` 字段，标注该方向的"痛点空间"大小。

**字段定义：**

| 值 | 含义 | Research Agent 预期产出 |
|---|---|---|
| `"broad"` | 人群大、痛点多样，值得深挖多个切入角度 | 3-5 张 Idea Card |
| `"focused"` | 人群或痛点比较集中 | 1-2 张 Idea Card |

**设计理由：**

当前架构中每个方向分配一个 Research session，不论方向大小。这导致两个问题：

1. 大方向（如"远程工作者的协作痛点"）探索深度不够，容易产出正确但平庸的结果——"正确但没有洞察"，比如每个参赛者都能想到的"学生需要个性化辅导"
2. 小方向（如"独立纪录片剪辑师的素材管理"）可能被过度展开

平庸的根源不是"方向本身太常见"，而是切入角度太泛。大方向不该被排除，它应该被分配更多的探索资源，在大市场里找到不平庸的具体切入点。对抗平庸的主战场在 Research Agent（通过 `scope: "broad"` 驱动更深的探索），不在 Main Agent。

**下游影响：**

- `research.md` 需要读取 `scope` 字段，动态调整 Idea Card 产出数量上限
- 中控脚本传参时需要将 `scope` 值注入 Research session 的 prompt 模板

---

### 改动 3：新增产品形态预判（likely_product_types 字段）

**内容：** 输出 JSON 中每个方向增加 `likely_product_types` 字段，列出该方向最可能的产品形态。

**字段定义：**

```json
"likely_product_types": ["web_app", "cli_tool"]
```

可选值与设计文档 Stage 2 的 `product_type` 枚举一致：`web_app`、`slack_app`、`vscode_extension`、`chrome_extension`、`cli_tool`、`api_service`、`notion_integration`、`github_app`。

**设计理由：**

设计文档要求 ReviewGate 面板展示每张卡的外部依赖评估，但当前 Idea Card 格式中缺少这部分数据。在 Main Agent 阶段做初步的产品形态预判，为两个下游环节提供信息：

1. ReviewGate：用户筛选时可以看到该方向可能需要的宿主环境（如 Slack workspace），据此决定是否保留
2. Research Agent：产出 Idea Card 时可以参考产品形态，在解决方向中体现多样性（不全是 web dashboard）

**精度预期：**

Main Agent 的预判不需要很准确——Stage 2 Session 1 会正式确定 `product_type`。这里只是提供一个方向性的参考。

---

### 改动后的输出 JSON 格式

```json
[
  {
    "slug": "freelance-designers-multizone",
    "persona": "Freelance graphic designers managing 5+ clients across different time zones with overlapping deadlines",
    "relevance": "high",
    "scope": "broad",
    "likely_product_types": ["web_app", "chrome_extension"],
    "pain_areas": [
      "Manually checking Slack, email, and project tools each morning to reconstruct which deliverables are due today",
      "Losing track of which client approved which version of a design, leading to rework and awkward conversations",
      "No single view showing billable hours across clients, forcing manual spreadsheet reconciliation every week"
    ]
  },
  {
    "slug": "estate-sale-liquidators",
    "persona": "Estate sale liquidators who price and photograph hundreds of items weekly for online listing",
    "relevance": "high",
    "scope": "focused",
    "likely_product_types": ["web_app", "api_service"],
    "pain_areas": [
      "Manually researching comparable prices for each item across eBay, Craigslist, and specialty sites",
      "Photographing items one by one with inconsistent lighting and backgrounds for online listings"
    ]
  }
]
```

---

### 未改动的部分（经讨论确认保留）

- **不加"反平庸"排除机制**：直接排除最显而易见的方向会把最大的市场也排除掉。平庸的核心不是"方向本身太常见"，而是"切入角度太泛"，这应该在 Research 阶段通过深挖来解决
- **不拆分为两步 session**：Main Agent 任务相对简单，拆成"发散 + 收敛"两个 session 带来的质量提升有限，不值得额外的 token 和延迟成本
- **筛选标准中的 Must NOT Match 列表保留**：排除法律合规、硬件依赖、机构合作等仍然有效，但需要将"hackathon feasibility"相关的表述替换为"Agent 可独立完成"的标准
- **输出数量范围不变**：仍为 8-12 个方向

---

## 三、Research Agent 改动

### 架构级改动：从四步三 Sub-Agent 简化为两步两 Sub-Agent

**原架构：**

```
Step 1: Template Search Sub-Agent（结构化搜索）
  ↓ 串行
Step 2: Free Search Sub-Agent（开放式搜索）
  ↓ 串行
Step 3: Critic Sub-Agent（批判评估）
  ↓ 串行
Step 4: Research Agent 自己合成 Idea Card
```

**新架构：**

```
Step 1: Search Sub-Agent（按 pain area 可并行拆分）
  ↓
Step 2: Synthesis Sub-Agent（独立上下文合成 Idea Card）
```

---

### 改动 1：合并 Template Search 和 Free Search 为单一 Search Agent

**设计理由：**

Free Search 和 Template Search 的区别不够清晰。Free Search 的五个搜索角度中，"工作流缺口"和"情绪信号"与 Template Search 高度重叠。唯一真正不同的是"邻近社区"和"工具投诉"——这些可以作为搜索原则之一合并到统一的 Search Agent 中，不需要单独的 sub-agent。

合并后减少一个串行步骤，缩短总耗时，也减少了 sub-agent 之间传递信息时的重复读取开销。

---

### 改动 2：重写搜索策略——从"按平台模板"改为"原则 + 示例 + 约束"

**设计理由：**

原 Template Search 按平台（Reddit、HN、Twitter、论坛、统计）分类，给出大量 query 模板让 Agent 逐条执行。问题是：

1. 模板越多，Agent 越倾向于机械执行而不是动脑子
2. `site:twitter.com` 在 2024-2025 几乎失效（X 大幅限制搜索引擎索引）
3. `site:news.ycombinator.com` 效果也很差（HN 页面结构对搜索引擎不友好）
4. 单个 sub-agent 可能跑 20-30 次搜索，后半段质量下降

**新搜索策略结构：**

不给模板，给原则 + 少量高质量示例 + 约束。

**搜索原则（3-4 条，简短直接）：**

1. 搜行为描述优于搜情绪表达。`"every week I have to"` 比 `"so frustrated with"` 更能找到真实痛点（来源：Mom Test 方法论——关注行为证据而不是态度表达）
2. 先确定这个人群在哪里讨论问题（哪些 subreddit、论坛、社区），再定向搜这些地方
3. 搜人们的 workaround 和手搓方案——有人愿意花时间自己搭解决方案（Zapier 自动化、Google Sheets 公式、Python 脚本），说明痛点足够痛（来源：Scratch Your Own Itch 逆向版）
4. 搜对现有工具的具体不满和替代品讨论——用户离开一个产品的原因就是最纯粹的痛点（来源：YC "Talk to Users" + Indie Hackers 验证框架）

**示例（展示搜索的思维过程，而非 query 模板）：**

> 假设 persona 是 "freelance designers managing multiple clients"。好的搜索路径：先搜 `r/freelanceDesign client management` 找到社区讨论 → 发现很多人抱怨 revision tracking → 搜 `"which version" client approved freelance` 深挖这个具体痛点 → 搜 `"switched from" revision tracking tool` 看现有方案的不足。

这个示例展示的不是 query 模板，而是搜索的思维过程——从宽到窄，根据中间发现调整方向。Agent 看到示例后会理解它应该做类似的推理，而不是机械套模板。

**约束：**

- 每个 pain area 做 3-5 次搜索，总共不超过 10 次
- 每次搜索如果前 5 条结果都不相关，换个角度而不是翻页
- 至少找到 2 个有真实证据的发现，否则标记为证据不足
- 质量比数量重要

---

### 改动 3：Search Agent 按 pain area 并行拆分

**内容：** 对于 `scope: "broad"` 的方向（有 2-3 个 pain area），为每个 pain area 启动一个独立的 Search sub-agent，并行执行。

**设计理由：**

如果让一个 sub-agent 跑所有 pain area 的搜索，到后半段上下文里塞满了前面的搜索结果，注意力被稀释。按 pain area 拆分后，每个 sub-agent 只关注一个 pain area，做 3-5 次搜索，上下文很轻。

**下游影响：**

- 每个 sub-agent 各写一个 findings 文件（`findings-pain1.md`、`findings-pain2.md`、`findings-pain3.md`）
- Synthesis sub-agent 读多个小文件，总信息量与读一个大文件相当

**对于 `scope: "focused"` 的方向：**

只有 1-2 个 pain area，不需要并行拆分，单个 Search sub-agent 即可。

---

### 改动 4：取消独立 Critic Sub-Agent

**设计理由：**

Critic 的价值（提供独立批判视角，对抗搜索 Agent 的确认偏差）是真实的，但存在多个问题：

1. **过滤好想法的风险**：Critic 倾向于保守。一个证据不多但切入角度非常独特的痛点可能被 DROP，但这恰恰可能是最好的方向——证据少也许只是因为人群小众，不代表痛点不真实
2. **与 Step 4 合成逻辑重叠**：合成阶段本来就会做质量判断（Quality Gates），Critic 先评一遍、合成再评一遍，两次评估标准高度相似
3. **剥夺 Research Agent 判断权**：Prompt 里要求"If Critic says DROP, don't include it"，但 Research Agent 可能基于对搜索结果的完整理解有不同判断

**替代方案：**

把 Critic 的核心价值（批判性审视）合并到 Synthesis sub-agent 的合成逻辑里。Synthesis sub-agent 在合成 Idea Card 时做一轮自审，用 Critic 的评估维度作为检查清单，但不作为硬性的 RECOMMEND/DROP 门槛。保留"批判性审视"功能，去掉独立 sub-agent 的开销和过度过滤风险。

---

### 改动 5：新增独立 Synthesis Sub-Agent

**内容：** 合成 Idea Card 的工作从 Research Agent 自己执行，改为启动一个独立的 Synthesis sub-agent。

**设计理由：**

搜索和合成是完全不同的任务。搜索是信息收集（大量 WebSearch 调用、读结果、记录发现），合成是创造性工作（把零散证据编织成有说服力的用户故事，提炼痛点，构思解决方向）。

到合成阶段，搜索 sub-agent 的上下文里已经塞满了搜索过程中的各种中间结果、无关的搜索返回、失败的搜索尝试。独立的 Synthesis sub-agent 只读搜索产出的 findings 文件，不继承搜索过程的上下文噪音，合成质量更稳定。

**信息损失的控制：**

信息损失发生在搜索 sub-agent 写 findings 的时候，不是在 Synthesis sub-agent 读 findings 的时候。因此在搜索 sub-agent 的 prompt 里应强调：宁可多记录一些"不确定但可能有价值"的发现，让合成阶段来做最终判断。

**Token 影响：**

取消了 Free Search 和 Critic 两个 sub-agent，新增了 Synthesis sub-agent。总 sub-agent 数从 3 个变为 2 个（Search + Synthesis），token 消耗重新平衡但总量相近。

---

### 改动 6：简化证据记录格式

**内容：** 不再要求搜索 sub-agent 记录完整的 URL + 平台 + 日期 + 精确引用，改为用一两句话描述发现。

**原格式：**

```
- **Source**: Reddit r/freelanceDesign — https://reddit.com/r/freelanceDesign/xxx
- **Key Quote**: "I spend 20 minutes every morning just checking which client needs what"
- **Date**: 2024-11-15
- **Engagement**: 47 upvotes, 23 replies
- **Relevance**: Shows daily time waste in client management
```

**新格式：**

```
Reddit r/freelanceDesign 上多个帖子讨论 revision tracking 的混乱，有用户描述每周花 2 小时手动对比不同版本。
```

**设计理由：**

URL 和精确引用在当前设计里承担两个功能：

1. 强迫 Agent 真的去搜索而不是编造痛点——这是最重要的功能
2. 让下游验证证据真实性——下游（Stage 2）实际不会去验证 URL

简化后的描述格式仍然足够证明 Agent 真的做了搜索（提到了具体平台和具体内容），也给了下游足够的上下文判断痛点是否可信。但 Agent 不再需要花精力格式化引用、确保 URL 格式正确、记录日期和互动数据，可以把精力放在搜索和分析上。

**核心原则：保留约束的"强迫搜索"功能，去掉约束的"格式负担"功能。**

---

### 改动 7：简化 Quality Gates

**原 Quality Gates（5 条）：**

1. Evidence: 至少 2 个 real URLs with specific quotes or data points
2. Scenario: Grounded in real complaints — not hypothetical
3. Feasibility: A working demo could be built in hours with web technologies
4. Gap: No existing product fully solves this pain
5. Critic Verdict: RECOMMEND or strong MAYBE

**新 Quality Gates（2 条原则）：**

1. 搜索过程中是否找到了真实的用户在描述这个痛点（不要求精确的 URL 数量，但需要有真实证据支撑）
2. 这个痛点是否能用软件解决，并且一个小团队（1-3 人）或 Agent 能在合理时间内做出 MVP

**变化说明：**

- 去掉了 Critic Verdict（Critic 已取消）
- 去掉了精确的 URL 数量要求（配合证据格式简化）
- "hackathon feasibility" 替换为 "indie developer / Agent 可独立完成"
- 保留了"真实证据"和"市场缺口"的核心要求，但以原则形式表达而非硬性门槛

---

### 改动 8：简化 Idea Card 的 Solution Directions

**内容：** 不再要求 Research Agent 给出完整的解决方向和推荐度评估（High/Medium/Low + Rationale），只要求给出一两句话的"可能的产品方向提示"。

**设计理由：**

Research Agent 的核心能力是搜索和验证痛点，不是产品设计。让它在搜索完痛点后立刻给出解决方向，质量不会很高——大概率给出最显而易见的方案。而且 Stage 2 Session 1 会完全重新评估解决方向，Research Agent 给的方向基本不会被直接采用。

把真正的解决方向设计留给 Stage 2。

---

### 改动 9：scope 字段控制产出量

**内容：** Research Agent 读取 Main Agent 输出的 `scope` 字段，动态调整 Idea Card 产出数量。

| scope | 产出量 | 说明 |
|---|---|---|
| `"broad"` | 2-5 张 | 鼓励从不同角度切入大方向，在大市场里找到不平庸的具体切入点 |
| `"focused"` | 1-2 张 | 保持精炼，避免过度展开小众方向 |

**实现方式：**

中控把 `scope` 值渲染进 research.md 的模板（`{{scope}}`），Synthesis sub-agent 的指令里引用这个变量来控制产出量。搜索 sub-agent 的行为不受 scope 影响——不管方向大小，搜索都应该尽量全面，差异化在合成阶段体现。

---

### Research Agent 输入变化

模板顶部的输入区块从：

```
- **Persona**: {{persona}}
- **Hypothesized Pain Areas**:
{{pain_areas}}
- **Hackathon Theme**: {{theme}}
```

改为：

```
- **Persona**: {{persona}}
- **Hypothesized Pain Areas**:
{{pain_areas}}
- **Hackathon Theme**: {{theme}}
- **Direction Scope**: {{scope}}
```

`likely_product_types` 不需要传入 Research Agent——搜索痛点时不需要知道产品形态，Idea Card 的 Solution Directions 部分自然会涉及产品形态，但那是基于痛点推导出来的。

---

## 四、Dedup Agent 改动

### 架构级改动：从批处理改为流式处理 + 最终轻量审查

**原架构：**

```
所有 Research session 完成
  ↓
收集全部 Idea Card 到 dedup/input/
  ↓
启动 Dedup Agent 一次性处理（去重 + 质量筛选 + 格式标准化 + 排名）
  ↓
输出到 output/
```

**新架构：**

```
Research session A 完成 → 新卡片进入累积池 → 轻量去重比较
Research session B 完成 → 新卡片进入累积池 → 轻量去重比较
Research session C 完成 → 新卡片进入累积池 → 轻量去重比较
...
所有 Research session 完成
  ↓
最终轻量审查（池子已被流式去重缩小）
  ↓
输出到 output/
```

---

### 改动 1：流式去重

**内容：** 中控维护一个累积的 Idea Card 池。每当一个 Research session 完成并产出卡片，中控把新卡片和池子里已有的卡片做比较。

**比较方式：**

- 每次比较是一个轻量的 Claude 调用（`claude -p` 一次性调用）
- 只问一个问题："这张新卡和已有的这些卡是否有重复？如果有，应该合并还是保留两张？"
- 上下文很小：新卡片的全文 + 已有卡片的标题和一句话摘要
- 只有判定为重复时，才需要读两张卡的全文来做合并

**设计理由：**

原方案等所有 Research session 跑完再批处理有两个问题：

1. 管道被最慢的 Research session 卡住——前面跑完的产出在那里闲着等
2. Dedup Agent 一次处理 15-20 张卡片，上下文很长，去重判断质量随卡片数量下降

流式处理让去重和 Research 同时进行，不需要等待。每次去重判断的上下文都很轻。

**Token 消耗：**

- 每次比较约 1-2K token，15 张卡陆续进来大约需要 15 次比较，总消耗约 15-30K token
- 加上最终审查约 5-10K token
- 对比原方案（单个 Dedup session 30-50K token），总量相近
- 优势在于时间上的并行——去重和 Research 同时在跑

---

### 改动 2：流式阶段只做明显去重，不做细粒度质量筛选

**内容：** 流式阶段只处理明显重复的合并（两张卡的 persona 和痛点高度重叠），不做加权排名、格式标准化等工作。

**设计理由：**

流式处理的去重质量可能不如批处理——前两张卡进来时看起来不重复，第三张进来时才发现它们其实是一个簇。流式阶段做保守的去重（只合并明显重复的），把细粒度判断留给最终审查。

---

### 改动 3：最终轻量审查

**内容：** 所有 Research session 完成后，对流式去重后的卡片池做一次最终审查。

**审查内容：**

- 检查是否有流式阶段遗漏的重复（三张卡构成一个簇的情况）
- 格式标准化（确保所有卡片符合 canonical Idea Card 格式）
- 按质量排序确定文件编号

**与原 Dedup 的区别：**

- 原 Dedup 需要处理 15-20 张卡片，新方案的最终审查只需要处理流式去重后的剩余卡片（可能只有 8-12 张）
- 上下文压力更小，判断质量更稳定
- 去掉了原 Dedup 中过于复杂的加权排名公式（5 个因子 × 权重），改为让 Agent 做综合判断

---

### 改动 4：去掉复杂的加权排名公式

**原方案：**

| Factor | Weight |
|---|---|
| Evidence Strength | 35% |
| Pain Severity | 25% |
| Hackathon Fit | 20% |
| Market Gap | 15% |
| Uniqueness | 5% |

**新方案：** 去掉量化排名公式，让 Agent 做综合判断来排序。

**设计理由：**

LLM 对精确的百分比权重执行精度存疑——Agent 不太可能严格按 35%/25%/20%/15%/5% 来算分。给一个不会被精确执行的公式不如直接让 Agent 基于自己的判断排序。排名的目的只是决定文件编号顺序，不影响卡片是否存活。

---

### 改动 5：筛选标准对齐新的 Quality Gates

**内容：** Dedup 阶段的质量筛选标准与 Research Agent 的新 Quality Gates 对齐：

1. 是否有真实证据支撑（不要求精确 URL 数量）
2. 是否能用软件解决且 Agent 可独立完成

原 Dedup 中的 "Hackathon Feasibility: Core demo buildable in hours with web tech" 替换为新标准。

---

## 五、Stage 1 最终产出

经过 Main Agent → Research Agent（并行）→ 流式去重 → 最终审查后，Stage 1 的最终产出为：

**5-15 张标准格式的 Idea Card**，存放于 `workspace/stage1/output/`，按质量排序命名：

- `idea-card-01-{slug}.md`（最强）
- `idea-card-02-{slug}.md`
- ...

每张 Idea Card 包含：

- Specific Scenario（基于真实证据的用户故事）
- Evidence（简化格式的证据描述）
- Existing Solutions & Gaps
- Solution Directions（简化为方向提示，不做详细评估）

这些卡片进入 ReviewGate，由用户筛选后进入 Stage 2。

---

## 六、改动对照总表

| 组件 | 原设计 | 新设计 | 理由 |
|------|--------|--------|------|
| **整体定位** | Hackathon demo | Indie developer MVP | 扩大适用范围，时间不再是约束 |
| **Main Agent 搜索** | 无搜索，纯知识 | 3-5 次灵感搜索 | 拓宽联想空间，发现知识盲区 |
| **Main Agent 输出** | slug + persona + relevance + pain_areas | 新增 scope + likely_product_types | 驱动下游差异化处理 |
| **Research Sub-Agents** | 3 个串行：Template + Free + Critic | 2 个：Search（可并行）+ Synthesis | 简化结构，减少串行步骤 |
| **搜索策略** | 按平台分类的 query 模板 | 原则 + 示例 + 约束 | Agent 自主决策搜索方向 |
| **搜索并行** | 单个 sub-agent 处理所有 pain areas | 按 pain area 拆分并行（broad 方向）| 上下文隔离，提高搜索质量 |
| **Critic** | 独立 sub-agent | 合并到 Synthesis 的自审逻辑 | 避免过度过滤好想法 |
| **证据格式** | 完整 URL + 平台 + 日期 + 引用 + 互动数据 | 一两句话描述 | 保留"强迫搜索"功能，去掉格式负担 |
| **Quality Gates** | 5 条硬性门槛 | 2 条原则 | 配合定位转变和 Critic 取消 |
| **Solution Directions** | 2-3 个方向 + 推荐度 + 理由 | 简化为方向提示 | 产品设计留给 Stage 2 |
| **Dedup** | 批处理（等所有 Research 完成）| 流式去重 + 最终轻量审查 | 并行提速，减少上下文压力 |
| **Dedup 排名** | 5 因子加权公式 | Agent 综合判断 | LLM 不会精确执行百分比权重 |
| **Dedup 筛选** | Hackathon feasibility | 软件可解决 + Agent 可独立完成 | 对齐新的整体定位 |
