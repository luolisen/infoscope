# Infoscope（IS）前端视觉与交互规范 / style.md

> 版本：Final Frontend Style Baseline v4 · Development Freeze  
> 日期：2026-08-15  
> 适用：React + TypeScript + Vite Frontend  
> 产品架构、信息模型、API 与分工以 `plan.md` 为准。  
> 本文档只负责 UI / UX / Visual System / Interaction System。

---

# 0. 设计命题

Infoscope 不是新闻网站，也不是传统 SaaS Dashboard。

前端应表现为：

> **Editorial Intelligence Interface / 编辑式个人情报界面**

设计语言：

```text
Editorial Intelligence
+
Swiss Information Design
+
Native Productivity UI
+
Restrained Glass
```

目标：

- 冷静
- 精密
- 克制
- 信息密度高但不混乱
- 编辑式而非组件墙
- 数据感存在但不像 BI Dashboard
- AI 体现在信息组织、解释和关系中，而不是紫蓝渐变

---

# 1. 核心设计原则

## 1.1 Event-first

页面优先表现：

- Event
- Claim
- Timeline
- Conflict
- Evidence
- Why it matters

而不是：

- News Card
- Article Feed
- Source List
- Platform logo wall

Signal 是 Event 下层 Evidence。

---

## 1.2 Typography as Interface

文字本身就是 UI。

层级、选择、状态、导航、metadata 优先通过：

- 字号
- 字重
- 对齐
- 间距
- 分隔线
- 位置
- 大小写
- 编号

表达。

不要用大量：

- Badge
- Chip
- Icon Button
- Card

替代信息层级。

---

## 1.3 Strict Invisible Grid

视觉上允许非对称，但底层必须严格。

始终保证：

- 对齐基线
- 内容边界
- gutters
- vertical rhythm
- 主次列关系

自由感来自组合方式，不来自失去网格。

---

## 1.4 Density as Rhythm

三级信息密度：

### LOW DENSITY

用于：

- Login
- Register
- Onboarding
- BRIEF Hero
- Empty State
- Event Hero
- 大状态切换

特点：

- 大标题
- 强留白
- 少内容
- Editorial 感最强

### MEDIUM DENSITY

用于：

- NOW
- Event Overview
- SCOPE
- SETTINGS

默认工作密度。

### HIGH DENSITY

用于：

- Timeline
- Claims
- Evidence
- ARCHIVE
- Search Results

特点：

- 严格网格
- 更高扫读效率
- 明确 Divider
- 少 Card

---

# 2. 视觉关键词

推荐：

- Monochrome
- Editorial
- Swiss
- Precise
- Flat
- Strong hierarchy
- Metadata-driven
- Asymmetric
- Calm
- Native-like
- Restrained glass
- Thin dividers
- Information-dense
- Large typography where meaningful

避免：

- Generic AI SaaS
- Bento everywhere
- Dashboard template
- Gradient-heavy AI style
- Neon / Cyberpunk
- Glassmorphism everywhere
- 彩色 Topic 系统
- 大量圆角卡片
- Pill overload
- Decorative icon wall
- Gamification
- Particle effects
- Large animated blob
- 全屏 ChatGPT clone

---

# 3. Color System

当前只冻结**颜色角色**，不冻结最终 Accent 的精确色值。

## 3.1 Base

整体使用：

- 冷调 Off-white / Gray 背景
- Near-black 主文字
- 多级 Neutral Gray
- 单一 Accent Color

避免大面积纯白 + 纯黑造成过强阅读对比。

## 3.2 Accent

一个主 Accent，用于：

- Active
- Focus
- 关键选择
- Event 更新焦点
- 少量重要互动

禁止：

- 每个 Topic 一个颜色
- 每种 Event state 一个高饱和色
- 平台品牌色污染主界面
- AI 紫蓝渐变

## 3.3 Semantic State

状态主要靠：

- 文本
- 字重
- 结构
- 必要 symbol
- 少量颜色

而不是只靠颜色。

产品语义可包含：

```text
DEVELOPING
CONFIRMED
CONFLICTING
COOLING
```

具体代码 enum 由 Contract 冻结。

---

# 4. Typography

当前没有冻结具体字体家族。

因此实现中不能把临时字体当最终品牌字体。

字体正式确定前必须满足：

- 正文可读
- 大标题有 Editorial 识别度
- Metadata 清晰
- 中英文层级良好
- macOS / Ubuntu 有可靠 fallback
- 字体缺失不破坏布局

## 4.1 语义角色

### Display

用于：

- Onboarding
- BRIEF Hero
- Event Hero
- 大型数字 / 状态

### Heading

用于：

- 页面标题
- Event title
- Section title

### Body

用于：

- Summary
- Claim explanation
- Why it matters
- Evidence excerpt

### Meta

用于：

- Updated time
- Topic
- State
- Timeline time
- Label

### Editorial Label

用于：

```text
NOW
BRIEF
ARCHIVE
SCOPE
SETTINGS
EVENT / DEVELOPING
01 / SCOPE
02 / FOCUS
```

## 4.2 Case

英文 metadata 可以适量 uppercase。

禁止整页 uppercase。

Uppercase 主要服务：

- Navigation
- Section label
- State
- Metadata
- Numbering

## 4.3 Line Length

Event Overview、Why it matters、BRIEF 正文不能铺满超宽桌面。

Timeline / Evidence 等扫描型内容可以更宽。

---

# 5. Spacing

当前不冻结精确 px。

实现时必须统一 spacing scale，禁止组件各写一套 margin。

语义：

### Tight

- Metadata
- 同一 Claim 内部
- 时间 + 标题

### Normal

- Event item
- Summary
- Form

### Section

- Overview → Timeline
- Timeline → Claims
- Page section

### Editorial

- Hero
- BRIEF
- Onboarding
- Empty state

原则：

> 留白是信息层级，不是装饰。

---

# 6. Divider / Border

优先使用克制 Divider，而不是 Card 边框墙。

推荐：

```text
Title
Metadata
────────────────────────
Next item
```

避免：

```text
┌───────────────┐
│ Card          │
└───────────────┘
```

Divider 主要用于：

- NOW Event
- Timeline
- Claim
- Evidence
- Sidebar section
- Settings section

---

# 7. Radius / Shadow

圆角不是 IS 主视觉语言。

允许圆角：

- Modal
- Overlay panel
- Input
- Button
- Context panel

避免：

- 每条 Event 一个大圆角 Card
- Timeline 每行一个圆角块
- Metadata 全变成 pill

Shadow 尽量少。

只在真正浮层使用：

- Dialog
- Command Palette
- Login overlay
- Context panel

---

# 8. Glass

Glass 只代表层级关系。

允许：

- 未登录遮罩
- Login / Register overlay
- Modal
- Command Palette
- Context Panel
- Temporary state layer

禁止：

- Event Glass Card
- Sidebar Glass
- Button Glass
- Summary Glass
- BRIEF Glass
- 整个 App Glass

原则：

> **Glass = Layer relationship, not decoration.**

---

# 9. App Shell

桌面：

```text
┌──────────────────────────────────────────────┐
│ IS                                Search ⌘K  │
├──────────────┬───────────────────────────────┤
│              │                               │
│ NOW          │                               │
│ BRIEF        │         Main Content          │
│ ARCHIVE      │                               │
│              │                               │
│ SCOPE        │                               │
│ SETTINGS     │                               │
│              │                               │
└──────────────┴───────────────────────────────┘
```

Navigation 以文字为主。

不要：

- 无意义 icon
- 彩色 badge
- 企业后台菜单树

---

# 10. Navigation

一级：

```text
NOW
BRIEF
ARCHIVE

SCOPE
SETTINGS
```

建议用 spacing / divider 区分：

- 信息工作区
- 用户配置

Active state 优先：

- 字重
- 细线
- Accent
- position marker

不使用大面积高饱和背景块。

Search 为全局能力：

```text
Search
⌘K
```

不作为一级导航。

---

# 11. NOW

NOW 的任务：

> 让用户快速知道“现在真正值得注意的 Event”。

## 11.1 Header

NOW 页面面向用户的主要文案使用中文。

避免：

```text
Dashboard
Welcome back
Here are your updates
```

推荐：

```text
NOW / 现在

过去 1 小时获取了 [Raw Information Count] 条信息，
整理为 [Event Count] 个事件。

其中 [Relevant Event Count] 个值得你现在关注。
```

统计口径必须严格区分：

```text
Raw Information Count
≠
Signal Count
≠
Event Count
```

其中：

- “获取了多少条信息”使用 Backend 返回的 Raw Information 实际计数。
- Event Count 使用实际 Event 数据。
- Relevant Event Count 使用当前用户真正可见 / 被推荐的 Event 数。
- 不使用 Signal 数冒充原始信息数量。
- 不允许 Frontend 写死 Demo 数字。
- 当前 Window Analysis 的逻辑分析窗口已经固定为 1 小时，因此 NOW 的该统计文案使用“过去 1 小时”。
- 计数与窗口统计必须由 Backend 返回，不由 Frontend 自行计算或猜测。

可以保留 `NOW / 现在` 这种 Editorial Label，但说明性句子、统计文案和 Event 主体文案以中文为主。

## 11.2 Event Item

不做传统新闻卡片。

推荐信息顺序：

```text
事件 / 持续发展

事件标题

一句话说明发生了什么。

为什么值得关注
个性化解释。

更新于……
新增……项事实变化
存在……项冲突

────────────────────────────────
```

结构性 Editorial Label 可以保留中英混排，但 NOW 中用户实际阅读的内容以中文为主。

层级：

1. State / Meta
2. Title
3. Overview
4. Why it matters
5. Update metadata

不要让：

- Topic chip
- Source logo
- Action buttons

抢走标题注意力。

## 11.3 Images

NOW 默认不采用：

```text
thumbnail + title + source
```

新闻布局。

只有视觉材料本身对事实有价值时，才放到 Event Detail。

---

# 12. Event Detail

这是 IS 信息密度最高、最核心的页面。

结构：

```text
Event Header
├── Overview
├── Timeline
├── Claims
├── Conflicts
├── Evidence / Signals
├── Why it matters
└── Ask Infoscope
```

## 12.1 Header

包含：

- Event state
- Title
- One-line overview
- Updated time
- 必要 metadata

避免：

- 8 个彩色 tag
- 6 个来源 logo
- 新闻 Hero 图
- 复杂 share bar

## 12.2 Overview

回答：

> 现在能确认发生了什么？

应短，不生成另一篇新闻。

## 12.3 Timeline

桌面推荐严格两列：

```text
09:02   首次出现
09:14   第二个独立信息
09:31   关键 Claim 被支持
10:07   出现 Conflict
11:20   Event state 更新
```

设计：

- 时间列严格对齐
- 内容列占主要空间
- 重要节点靠 Typography
- 不用巨大圆点 / 粗线制造“时间线组件感”

---

# 13. Claims

Claim 是独立事实命题。

推荐：

```text
CONFIRMED

某事实命题

支持它的 Evidence / reasoning 概述

────────────────────────
```

状态不能只靠颜色。

使用：

- 文本状态
- Typography
- Structure
- 必要 symbol

---

# 14. Conflicts

Conflict 不做单纯红色警告框。

应该表达：

```text
CONFLICT

Claim A
vs
Claim B

为什么冲突
哪些 Evidence 分别支持
```

目标是解释矛盾，不是制造警报感。

---

# 15. Evidence / Signals

Evidence 回答：

> 这个 Claim 为什么被支持 / 冲突？

不是展示后台数据源清单。

## 15.1 私密 Telegram

允许：

```text
TELEGRAM

“经过脱敏的原文……”
```

禁止：

- 群名
- 群 username
- invite link
- 内部 identifier
- collector name

正文发生脱敏时要明确表现被隐藏，不得悄悄改变句义。

## 15.2 公开 X / YouTube / Web

允许：

- Platform
- Public author / creator
- Public link
- Excerpt
- Time

但统一使用 IS 视觉，不做平台 Embed 墙。

## 15.3 Evidence Item

推荐统一结构：

```text
X · PUBLIC
Author
Time

Excerpt...

Open original ↗
```

或：

```text
TELEGRAM · PRIVATE SOURCE
Time

Excerpt...
```

Frontend 不自行判断 privacy，Backend DTO 决定可见字段。

---

# 16. Claim Graph

如果做 Claim Graph：

```text
Claim A
├── Signal 1 supports
├── Signal 2 supports
└── Signal 3 contradicts
```

优先 2D、结构化、可读。

不要：

- 3D graph
- 力导向图乱飞
- 粒子
- Hover 才看得到主关系

黑客松阶段宁可 relation list，也不要炫技。

---

# 17. Why It Matters

这是 Personalization 的直接产品价值。

视觉：

```text
WHY IT MATTERS
```

配一小段解释。

原则：

- 不改变 Event facts
- 不覆盖 Overview
- 不隐藏事实层
- 不显示无意义小数评分

---

# 18. BRIEF

BRIEF 是最 Editorial 的页面。

推荐：

```text
DAILY / 015

Three things
worth knowing today.

01 / AI
...

02 / SECURITY
...

03 / OPEN SOURCE
...
```

允许：

- 超大标题
- 大留白
- 非对称
- 强编号
- 报告 / 杂志感

禁止：

- 三个巨大彩色 Card
- AI Gradient
- Dashboard stat wall

BRIEF 是阅读模式：

- 密度更低
- 行宽更窄
- Paragraph spacing 更强
- 互动更少
- 页面更安静

---

# 19. ARCHIVE

ARCHIVE 是效率型页面。

推荐：

- List
- Search
- Date grouping
- Event state
- Saved state
- Strong grid

避免：

- 巨大封面
- Masonry
- Card wall

示意：

```text
DATE / PERIOD

Event
Event
Event

────────────────
```

---

# 20. SCOPE / FOCUS — FINAL

SCOPE 与 FOCUS 是 Onboarding 和长期个性化的固定产品结构。

第一版不提供自定义输入，只展示固定选项。

## 20.1 SCOPE

页面 Label：

```text
01 / SCOPE
```

主问题建议：

> 哪些内容进入你的视野？

固定五项，可多选：

```text
AI
开源社区
技术
科学
投资
```

API ID 与显示文案固定对应：

```text
ai           → AI
open_source  → 开源社区
technology   → 技术
science      → 科学
investment   → 投资
```

至少选择 1 项。

视觉：

- 文字本身作为选择组件。
- 不使用巨大圆角兴趣 Card。
- 选中通过字重、下划线、Accent、小型状态标记表达。
- 多选状态必须清晰，但不要做彩色 Tag 墙。

页面底部固定小字：

> **后续更新将提供自定义SCOPE**

本版本不显示自定义输入框或 `+ Add scope`。

---

## 20.2 投资条件页面

仅当用户在 SCOPE 中选中：

```text
投资
```

才显示。

编号固定：

```text
01.1 / 投资市场
```

主问题固定：

> **你更关注？**

三个选项，可多选：

```text
中国市场
美股
加密市场
```

API ID：

```text
china_market   → 中国市场
us_stock       → 美股
crypto_market  → 加密市场
```

至少选择 1 项。

视觉继续使用 SCOPE 的 Typography-as-interface 选择方式。

不要因为这是投资选项就引入：

- K 线背景
- 红绿金融配色
- Crypto 霓虹
- 平台 Logo

如果用户返回 SCOPE 并取消“投资”：

- 该页面不再出现。
- Frontend 提交 `investment_market_ids: []`。

---

## 20.3 FOCUS

页面 Label：

```text
02 / FOCUS
```

主问题建议：

> 什么内容应该更容易浮上来？

固定八项，可多选：

```text
技术细节
研究进展
重要变化
突发事件
小众趋势
行业变化
争议变化
深度背景
```

API ID：

```text
technical_details      → 技术细节
research_progress      → 研究进展
major_changes          → 重要变化
breaking_events        → 突发事件
niche_trends           → 小众趋势
industry_changes       → 行业变化
controversy_changes    → 争议变化
deep_context           → 深度背景
```

至少选择 1 项。

页面底部固定小字：

> **后续更新将提供自定义FOCUS**

禁止：

```text
Technical 73%
Deep 61%
Novelty 82%
```

第一版不提供 Slider，也不提供自定义 FOCUS 输入。

---

# 21. SETTINGS

SETTINGS 更接近 Native Productivity UI。

可以按 section：

```text
ACCOUNT
...

APPEARANCE
...

LOCAL DATA
...
```

不要把 SCOPE / FOCUS 复制进 Settings。

Settings 可以更标准化，但仍避免 Card 堆叠。

---

# 22. Login / Register

IS 没有传统 Landing Page。

首次进入：

```text
真实 App Shell / NOW Preview
↓
Blur + Reduced Contrast
↓
Disable Interaction
↓
Login / Register Layer
```

用户感觉：

> 已经看见 Infoscope，只差建立自己的视野。

而不是进入与产品割裂的登录网站。

## 22.1 Background Preview

必须是真实产品结构 Preview。

不要 Marketing Hero。

Preview：

- 可以是 Demo Event
- 不能泄露未登录用户不该看的真实数据
- 不可交互
- Blur
- 降低对比

## 22.2 Auth Panel

当前只显示：

- Username
- Password
- Login / Register 切换

不要显示：

- Email
- Apple
- Google
- Verification code

除非未来正式加入。

---

# 23. Onboarding — FINAL

完整流程：

```text
Register / Login
↓
01 / SCOPE
├── AI
├── 开源社区
├── 技术
├── 科学
└── 投资
       │
       └── 仅选中投资时
           ↓
       01.1 / 投资市场
       你更关注？
       ├── 中国市场
       ├── 美股
       └── 加密市场
↓
02 / FOCUS
├── 技术细节
├── 研究进展
├── 重要变化
├── 突发事件
├── 小众趋势
├── 行业变化
├── 争议变化
└── 深度背景
↓
视野已建立
↓
Blur clears
↓
NOW
```

如果未选择投资：

```text
01 / SCOPE
↓
02 / FOCUS
```

不会渲染投资二级页面。

## 23.1 页面推进

- 每一页只处理当前一类选择。
- SCOPE 至少选 1 项才能继续。
- 投资二级页出现时至少选 1 项才能继续。
- FOCUS 至少选 1 项才能完成。
- Back 必须保留此前选择。
- 用户取消投资后，投资市场选择应从提交数据中清空。

## 23.2 固定提示文案

SCOPE 页底部：

> 后续更新将提供自定义SCOPE

FOCUS 页底部：

> 后续更新将提供自定义FOCUS

不要在第一版做 disabled 的自定义输入框假装未来功能。

## 23.3 完成动效

完成文案：

```text
视野已建立
```

然后：

```text
Blurred World
↓
Scope established
↓
Blur clears
↓
NOW interactive
```

重点是“视野变清晰”。

禁止：

- Confetti
- Celebration modal
- 大型粒子
- 游戏化进度奖励

---

# 24. Loading

不默认用巨大 Spinner。

更适合：

```text
RECONSTRUCTING EVENTS
ANALYZING SIGNALS
UPDATING NOW
```

配合：

- subtle opacity
- thin line
- skeleton
- restrained motion

文案必须反映真实系统阶段，不能伪造。


---

# 24.1 持续更新与 Event 回写的前端表现

Event Backwrite 是 Backend 的持续维护机制。

Frontend 的职责不是展示 Worker 的内部队列，而是展示更新后的用户 Event 结果。

```text
Backend Backwrite
↓
Event Updated
↓
Personalization Updated
↓
NOW Refetch / Refresh
↓
展示新的用户 Event 列表
```

当前 Backwrite Cycle 的处理对象来自：

```text
本轮开始时当前用户可见 Event
↓
用户展示所依据的时间排列结果
↓
Backwrite Snapshot
↓
Frozen Queue
```

Backend 对该 Snapshot 使用：

```text
Newest
Oldest
Second Newest
Second Oldest
...
Middle
```

本轮一旦开始，处理顺序冻结。

即使 Event 更新后产生新的用户展示列表：

- Frontend 应展示更新后的新 Event 列表 / NOW。
- 当前 Backend Backwrite Queue 仍按本轮最初 Snapshot 的顺序继续。
- Frontend 不把 Frozen Queue 顺序当成用户的新列表顺序。
- Frontend 不参与重新计算 Backwrite 顺序。
- 不向普通用户暴露内部 newest / oldest 处理队列，除非以后正式设计 Debug / Admin UI。

### 用户正在阅读 Event Detail 时

如果当前 Event 在后台完成回写：

- 不建议突然重排或大幅替换用户正在阅读的内容。
- 应先给予克制的“此事件有更新”提示。
- 用户触发刷新或系统采用不打断阅读的刷新方式后，再显示新 Claim / Timeline / Evidence。

### NOW 中 Event 更新

NOW 可以在数据刷新后重新排序。

```text
旧 NOW
↓
某 Event 回写完成
↓
Personalization 变化
↓
新 NOW 排名
```

动画应克制，避免列表大幅跳动造成阅读位置丢失。

### 更新周期的用户侧含义

Backend 的维护周期已经固定为：

```text
完整一轮更新流程结束
↓
开始计时
↓
等待 1 小时
↓
启动下一轮
```

这不是固定整点刷新。

Frontend 不应显示“每个整点更新”之类与实际调度不一致的文案。

如果未来展示“下一次更新”或维护状态，必须使用 Backend 返回的真实调度状态，不能由 Frontend 按墙钟自行推算。

---

# 25. Error / Empty

## Error

必须：

- 告诉用户发生什么
- 是否可 retry
- 后端若提供 request identifier，可展示

不要：

- stack trace
- 只有 “Something went wrong”
- 夸张错误插画

## Empty

LOW DENSITY。

例如 NOW：

```text
Nothing requires your attention right now.
```

可以提供：

- 修改 SCOPE
- Refresh / run pipeline
- 等待采集

不需要大插画。

---

# 26. Buttons / Inputs

按钮数量要少。

Primary action 才强强调。

Secondary：

- Text button
- subtle border
- link style

避免每个列表 item 三四个按钮。

Input：

- clear focus
- 可读
- 不过度玻璃
- 不强发光
- 不用巨大 Floating Label

---

# 27. Icons

Icon 只在文本不够快时使用。

一级导航默认纯文字。

不要为了“现代感”给：

- NOW
- BRIEF
- ARCHIVE
- SCOPE
- SETTINGS

强行配图标。

---

# 28. Metadata

Metadata 是核心视觉语言。

例如：

```text
EVENT / DEVELOPING
UPDATED ...
03 NEW CLAIMS
01 CONFLICT
01 / SCOPE
DAILY / 015
```

要求：

- 小
- 稳定
- 低视觉重量
- 高一致性
- 严格对齐

---

# 29. Numbering

编号可用于：

- Onboarding
- Brief
- Claims
- Editorial sections

例如：

```text
01 / SCOPE
02 / FOCUS

01 / AI
02 / SECURITY
```

不要给所有 UI 元素编号。

---

# 30. Motion

只保留三类。

## 30.1 State Transition

```text
Login blur
↓
NOW clear
```

## 30.2 Information Entering

轻微：

```text
opacity
+
small translateY
```

## 30.3 Intelligence State

```text
RECONSTRUCTING EVENT
```

配：

- subtle text opacity
- thin progress line
- restrained pulse

避免：

- bounce
- overshoot
- 3D
- particles
- excessive spring
- page flying

动画不能成为等待系统。

---

# 31. Interaction

IS 应像 Productivity Tool。

要求：

- Hover 快
- Keyboard focus 清楚
- 能立即显示的内容立即显示
- UI animation 不人为延迟
- AI processing 与动画解耦

---

# 32. Search / Command

全局：

```text
Search
⌘K
```

Command Palette 可以使用 Glass，因为它是真正的临时 Layer。

Search Results：

- HIGH DENSITY
- Event first
- State
- Time
- Matched context

不优先展示 source。

Search 的职责是“找到 Event”。

询问观澜的职责是“理解一个或多个已选择的 Event”。

两者不要合并成一个模糊的万能输入框。

---

# 33. Ask Infoscope / 询问观澜

中文界面主名称使用：

> **询问观澜**

英文界面可使用：

> Ask Infoscope

它不是全屏 ChatGPT clone，而是建立在 Event Database 上的上下文分析入口。

---

## 33.1 单 Event 提问

Event Detail 内提供：

```text
询问观澜

关于这个事件，你还想了解什么？
```

回答上下文围绕：

- 当前 Event
- Claims
- Timeline
- Conflicts
- Evidence

UI 必须明确当前问题只基于哪个 Event。

推荐采用：

- Event bottom
- Context panel
- Side panel

不要让聊天界面取代 Event Detail。

---

## 33.2 多 Event 联合提问

用户可以从 NOW / ARCHIVE / Search 等 Event 列表显式选择多个 Event，然后进入联合提问。

示意：

```text
已选择 3 个事件

询问观澜

这几个事件之间有什么联系？
```

多 Event Ask 可用于：

- 比较多个 Event
- 分析共同趋势
- 对比 Timeline
- 对比 Claim / Conflict
- 从相同 Perspective 解释多个 Event

选择状态仍应保持 Typography / Grid 为主，不要为了多选模式把 Event 变成巨大 checkbox Card。

---

## 33.3 回答与 Event Database 的关系

Ask 的回答不是脱离数据库单独生成。

前端产品语义必须反映：

```text
用户问题
↓
与已有 Event 数据比对
↓
已有内容 → 直接回答
缺失内容 → Research
↓
新 Signal / Event 补充
↓
基于更新后的 Event 回答
```

如果 Ask 导致 Event 得到补充或修正，UI 可以给予克制提示，例如：

```text
事件信息已补充
```

并提供跳回：

- 新 Claim
- 新 Timeline 节点
- 新 Evidence
- Conflict 更新

的入口。

不要把模型自己的文字表现成 Evidence。

---

## 33.4 多 Event 不等于自动合并

即使 Ask 判断多个 Event 有关联：

- UI 可以表达“存在关联”。
- 不应直接把多个 Event 合并成一个 Event。

是否 Merge 属于 Event Reconstruction / Reconciliation，而不是 Ask UI 的决定。

---

## 33.5 Ask 与来源隐私

Ask 回答中仍必须服从 Backend 已处理好的 Public DTO。

私密 Telegram：

- 可使用脱敏后的正文进行回答。
- 不显示群名、群 username、invite link、internal identifier。

Frontend 不自行做来源身份判断。

---

## 33.6 不做 ChatGPT Clone

避免：

```text
全屏 Chat
User
AI
User
AI
无限对话历史
```

更适合：

```text
询问观澜

问题

结构化回答
├── 结论
├── 相关 Claim
├── Timeline
├── Conflict
└── Evidence links
```

Event 始终是主体，Ask 是理解 Event 的工具。

---

# 34. Responsive

黑客松以 Desktop Web 为主。

优先：

- MacBook 级宽度
- 常见 16:10 / 16:9
- 浏览器窗口缩放

窄桌面：

```text
Sidebar
→ compact / collapsible

Context Panel
→ drawer / stacked
```

不能把三栏硬挤成三条窄柱。

Mobile 不是 MVP 核心。

基础兼容：

- NOW 单栏
- Event sections 纵向
- Evidence 折叠
- Sidebar drawer

不要为手机破坏桌面 Event intelligence layout。

---

# 35. Accessibility

必须：

- Keyboard navigation
- Visible focus
- Semantic headings
- Form label
- Dialog focus management
- 状态不只靠颜色
- 足够对比
- Motion 可降级
- Link / Button 语义正确

Claim / Conflict 状态尤其不能只用颜色。

---

# 36. 页面状态

以下主要页面都必须有：

```text
Loading
Error
Empty
Success
```

包括：

- NOW
- Event Detail
- BRIEF
- ARCHIVE
- SCOPE
- SETTINGS

不能只做正常截图。

---

# 37. Component Philosophy

组件围绕产品概念。

推荐逻辑：

```text
Event
  EventItem
  EventHeader
  EventMeta
  EventState
  EventOverview

Claim
  ClaimItem
  ClaimState
  ClaimEvidence

Timeline
  TimelineItem
  TimelineGroup

Evidence
  EvidenceItem
  EvidenceMeta

Brief
  BriefSection
  BriefItem

Scope
  ScopeSelector
  FocusSelector

Layout
  EditorialGrid
  Navigation
  ContextPanel
```

避免核心架构围绕：

```text
Card
Widget
Stat
DashboardPanel
BentoItem
```

具体文件名 / 目录必须以真实仓库为准，不能据此猜路径。

---

# 38. Server State / UI State

Server State：

- NOW
- Event
- Brief
- Archive
- Scope
- Session
- Pipeline status

使用 TanStack Query。

UI State：

- Dialog
- Sidebar
- Context panel
- Local tab
- Local form

优先 React local state 或项目已经确定的方案。

不要为简单 UI state 引入大型全局状态架构。

---

# 39. API Boundary — FINAL

Frontend 只通过冻结的 `/api/v1` Contract 与 Backend 通信。

固定链：

```text
FastAPI Schema
↓
OpenAPI
↓
openapi-typescript
↓
Generated Types
↓
openapi-fetch
↓
TanStack Query
↓
UI
```

Frontend 规则：

- API request 使用相对 `/api/v1/...`。
- 不硬编码 Backend host / port。
- 不保存 Bearer Token。
- Session 由 HttpOnly `is_session` Cookie 管理。
- 不手写重复的 Backend entity interface。
- 不把 `snake_case` 转成另一套字段名。
- 不解析 opaque ID / cursor。
- 不根据 UI 猜 API 字段。
- 不重新排序 NOW items；使用 Backend 返回顺序。
- Ask / Maintenance 使用 Polling。
- Frontend 不使用 WebSocket。

Onboarding API ID 必须精确使用：

```text
scope:
ai
open_source
technology
science
investment

investment market:
china_market
us_stock
crypto_market

focus:
technical_details
research_progress
major_changes
breaking_events
niche_trends
industry_changes
controversy_changes
deep_context
```

UI 显示文本与这些 ID 的对应关系以本文件第 20 节为准。

---

# 40. Source Privacy UI

Frontend 不自行判断来源是否私密。

Backend 必须返回已处理的 Public DTO。

禁止 Frontend 写类似：

```text
if source_name ...
  hide ...
```

作为 privacy policy。

---

# 41. UI Review Checklist

每次 Frontend PR Review：

- Event 是否仍是一等实体？
- Signal 是否只作为 Evidence？
- NOW 是否回答“现在该注意什么”？
- 是否退化成传统 News Feed？
- 是否 Everything-is-a-card？
- 是否出现无意义彩色 Badge？
- 是否用 Typography / Grid 代替容器？
- BRIEF 是否仍是阅读模式？
- ARCHIVE 是否高效率？
- SCOPE 是否还是产品概念？
- Glass 是否只用于真正 Layer？
- 动画是否表达状态？
- Loading / Error / Empty 是否齐全？
- 私密 TG 是否可能泄露身份？
- 是否完全遵循 Generated API Contract？
- NOW 的信息数量是否来自 Raw Information，而不是 Signal？
- NOW 用户侧主要文案是否使用中文？
- Ask 是否支持单 Event / 多 Event 范围并明确显示选择上下文？
- Ask 产生的新事实是否先进入 Event 数据链，而不是把 AI Answer 当 Evidence？
- Event 回写后是否展示新的用户 Event 列表，而当前 Backend Frozen Queue 顺序保持不变？
- Backwrite 是否以本轮开始时当前用户可见 Event 的时间排列结果确定 Newest / Oldest？
- 是否错误地把维护周期描述成固定整点更新，而不是“完整流程结束后等待 1 小时”？
- NOW 是否使用固定 1 小时统计窗口的真实 Raw Information Count？
- SCOPE 是否严格只有 AI / 开源社区 / 技术 / 科学 / 投资？
- 是否只有选择投资时才出现“你更关注？”二级页？
- 投资市场是否严格只有中国市场 / 美股 / 加密市场？
- FOCUS 是否严格只有八个冻结选项？
- SCOPE / FOCUS 底部未来功能小字是否准确？
- Frontend 是否只使用冻结 API ID，没有创造近似 ID？

---

# 42. 禁止模式

```text
× Traditional news feed
× thumbnail + source + title 卡片墙
× Generic SaaS dashboard
× Bento everywhere
× Purple-blue AI gradient
× Glass cards everywhere
× Huge rounded rectangles
× Colorful category chips
× Source logo wall
× Gamification
× Confetti onboarding
× Fullscreen chatbot as product center
× Black-box credibility percentage
× Slider-based AI preference
× Frontend source-privacy guessing
× 用 Signal Count 冒充 Raw Information Count
× NOW 写死假统计数字
× Ask 的 AI Answer 直接当 Evidence
× 多 Event Ask 自动合并 Event
× 把 Backend Backwrite Queue 当成用户 NOW 排名
× Event 列表更新后重排本轮 Frozen Backwrite Queue
× Frontend 自行选择 created_at / updated_at 等字段决定 Backwrite 新旧
× 把维护周期错误实现为固定整点触发
× Frontend 自行推算下一轮维护时间
```

---

# 43. 仍需 Prototype 冻结的视觉值

当前资料没有确定：

- 最终字体家族
- 最终 Accent Color
- 精确 Color Tokens
- 精确 Type Scale
- 精确 Spacing Scale
- 精确 Radius
- 精确 Sidebar Width
- 精确 Breakpoints
- 精确 Animation Duration / Easing
- 最终 Icon Set

正确流程：

```text
Style Baseline
↓
Frontend Prototype
↓
Review
↓
Freeze Tokens
↓
写入实际 Design System / CSS Tokens
```

冻结前不能把临时值描述为“IS 官方最终标准”。

---

# 44. 最终视觉定义

Infoscope 应该像：

> **一个编辑式情报终端。**

而不是：

> 新闻网站。  
> AI SaaS Dashboard。  
> 漂亮的 RSS Reader。  
> ChatGPT 套壳。

用户信息路径：

```text
我现在该注意什么？
↓
发生了什么？
↓
哪些 Claim 可以确认？
↓
哪些信息冲突？
↓
证据是什么？
↓
为什么这对我重要？
```

视觉系统必须服务这条路径。
