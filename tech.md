# Infoscope · 观澜

> Final Product & Technology Introduction · Development Freeze  
> 2026-08-15

> 于信息之海，观其波澜。

## 一、产品介绍

**Infoscope（观澜）** 是一个 Event-first 的个人智能信息界面。

它不是传统新闻聚合器，也不是 RSS Reader，更不是简单的“新闻 + AI 摘要”工具。Infoscope 关注的核心问题是：

> 当用户面对大量碎片化、重复、互相冲突的信息时，如何从信息流中还原真正发生的事件，并只呈现当前真正值得关注的变化。

Infoscope 的核心理念是：

> **See the event, not the feed.**  
> 从信息流中，还原事件。

系统首先从 Telegram、Web、RSS、Hotlist 等固定信息渠道持续获取原始信息，然后经过标准化、去重、事件重构、事实命题提取、时间线重建和冲突分析，把大量碎片信息组织成结构化的 **Event**。

核心信息模型为：

```text
External Information
        ↓
Raw Information
        ↓
Normalize
        ↓
Signal
        ↓
Deduplicate
        ↓
Event Reconstruction
        ↓
Event
├── Claims
├── Timeline
├── Conflicts
└── Evidence / Signals
        ↓
Personalization
        ↓
User
```

其中：

- **Signal**：一条经过标准化的观察或证据。
- **Event**：多个 Signal 被重构后形成的事件，是用户真正消费的一级信息实体。
- **Claim**：Event 中可以独立验证的事实命题。
- **Timeline**：事件随时间发生的重要变化。
- **Conflict**：不同 Claim 或 Evidence 之间存在的矛盾关系。
- **Evidence**：支撑、补充或反驳 Claim 的底层信息证据。

### NOW：此刻真正值得关注什么

Infoscope 不使用传统的无限新闻 Feed。

默认页面 **NOW** 根据用户的 `SCOPE` 和 `FOCUS` 对 Event 进行筛选和个性化排序，回答：

> **此刻哪些事情值得我注意？**

例如：

```text
NOW / 现在

过去 1 小时获取了 2,314 条信息，
整理为 63 个事件。

其中 4 个值得你现在关注。
```

其中“信息数量”直接根据实际 Raw Information 计数，不使用 AI 估算，也不使用去重后的 Signal 数量代替。 

### Event Detail：不是告诉你结论，而是还原过程

进入一个 Event 后，用户可以看到：

```text
Event
├── Overview
├── Timeline
├── Claims
├── Conflicts
├── Evidence
├── Why it matters
└── 询问观澜
```

相比只给出一个 AI Summary，Infoscope 更强调：

- 发生了什么
- 信息什么时候出现
- 哪些事实已经确认
- 哪些事实仍然未知
- 哪些说法彼此冲突
- 结论依据哪些 Evidence
- 为什么这个 Event 与当前用户有关

因此系统不会用一个类似“可信度 82%”的黑盒数字代替事实关系。 

---

## 二、个性化与 Onboarding

用户首次注册后建立最小但明确的个性化画像。

完整流程：

```text
Register
↓
01 / SCOPE
↓
[仅选择“投资”时]
01.1 / 投资市场
↓
02 / FOCUS
↓
NOW
```

### SCOPE

第一版固定五项，可多选：

- AI
- 开源社区
- 技术
- 科学
- 投资

至少选择一项。

如果用户没有选择“投资”，直接进入 FOCUS。

如果选择“投资”，出现二级页：

> **你更关注？**

可多选：

- 中国市场
- 美股
- 加密市场

SCOPE 页面底部固定提示：

> 后续更新将提供自定义SCOPE

### FOCUS

固定八项，可多选：

- 技术细节
- 研究进展
- 重要变化
- 突发事件
- 小众趋势
- 行业变化
- 争议变化
- 深度背景

至少选择一项。

FOCUS 页面底部固定提示：

> 后续更新将提供自定义FOCUS

Infoscope 第一版不使用连续 Slider，也不让用户编写 Prompt。

个性化只改变：

- 哪些 Event 进入当前用户的 NOW
- Why it matters
- BRIEF
- 其他用户级解释

不会改变 Event、Claim、Timeline、Conflict 和 Evidence 的事实层。

---

## 三、询问观澜 / Ask Infoscope

**询问观澜** 是建立在 Event Database 上的上下文分析能力，而不是一个独立的通用 Chatbot。

支持：

```text
单 Event 提问
+
多 Event 联合提问
```

例如用户可以针对单个 Event 问：

- 最近三天到底发生了什么？
- 哪些事实目前还没有确认？
- 为什么存在冲突？
- 从开发者角度这件事有什么影响？

也可以选择多个 Event：

- 这几个事件是否属于同一个趋势？
- A 和 B 是否存在因果关系？
- 这几个事件有哪些共同变化？
- 它们的 Timeline 有什么对应关系？

Ask 在回答之前必须先读取并比对现有 Event Database。 

流程是：

```text
User Question
↓
Existing Event Database
↓
Database Comparison
├── 已有事实 → 直接使用
├── 信息缺失 → Research
├── 新事实 → New Signal
└── 冲突 → Event Reconciliation
↓
必要时更新 Event
↓
Answer
```

核心原则：

> **AI Answer ≠ Evidence**

模型自己推理出来的内容不能直接写入事实数据库。

只有新的外部材料经过：

```text
Raw
↓
Normalize
↓
Signal
```

之后，才能成为 Event 的补充证据。

---

## 四、Event 持续更新机制

Infoscope 的 Event 不是生成一次后永久固定。

系统通过三种机制持续维护 Event：

```text
Window Analysis
+
Event Backwrite
+
Ask Reconciliation
```

### Window Analysis

系统以 **1 小时**为逻辑分析窗口，对这一时间段中新获得的信息进行：

- 分类
- 去重
- Event Matching
- Event Clustering
- Relationship Analysis
- Missing Context Detection

最终决定：

```text
New Information
├── 补充 Existing Event
└── 形成 New Event
```

### Event Backwrite

系统还会反过来从已有 Event 主动重新检查信息。

每轮开始时，以：

> **当前用户展示的按时间排列 Event 列表**

生成一个固定 Snapshot。

例如：

```text
A B C D E F G
↑           ↑
最新        最旧
```

回写顺序为：

```text
A
G
B
F
C
E
D
```

即：

> 最新 → 最旧 → 次新 → 次旧 → …… → 中间

这样既优先保证快速发展的新事件，又避免较旧 Event 长时间没有得到重新检查。

本轮 Snapshot 一旦形成，后台更新顺序就冻结。

即使 Event 更新以后用户看到的 NOW 列表已经重新排序：

- 用户看到新的列表；
- 当前后台回写 Queue 仍继续使用原来的顺序。 

### 更新周期

维护流程不采用固定整点执行。

而是：

```text
完整一轮更新开始
↓
Window Analysis / Event Backwrite / Reconciliation
↓
本轮全部结束
↓
开始计时
↓
等待 1 小时
↓
启动下一轮
```

因此：

```text
Next Start Time
=
Previous Cycle Finish Time
+
1 hour
```

---

# 五、产品信息架构

Infoscope 一级导航采用：

```text
NOW
BRIEF
ARCHIVE

SCOPE
SETTINGS
```

### NOW

当前值得关注的 Event。

### BRIEF

根据已经建立好的 Event、Claim、Timeline 和 Conflict 生成的编辑式信息简报。

Brief 不独立创造新事实。

### ARCHIVE

长期 Event 记忆，包括历史、Saved Event 和已经退出 NOW 的事件。

### SCOPE

管理：

```text
SCOPE
+
FOCUS
```

即用户希望观察什么，以及哪些变化应该更突出。

### SETTINGS

负责帐号、系统、界面和本地数据设置。

---

# 六、来源与隐私

Infoscope 不简单采用“所有来源全部隐藏”。

而是根据来源本身的公开程度决定用户可以看到多少 provenance。

### 私密 Telegram

邀请制 Telegram 群允许显示：

```text
Telegram

“经过脱敏处理的原文证据……”
```

但绝不显示：

- 群组名称
- 群 username
- Invite Link
- Chat / Peer internal ID
- Collector 配置
- 可以反推出私密群身份的信息

私密 Telegram 正文允许发送给第三方模型进行分析，但发送前必须移除群组身份信息。

### 公开来源

X、YouTube、公开网站等可以显示：

- 平台
- 公开作者 / 博主 /频道
- 公开链接
- 原文 Evidence
- 发布时间

但后台的采集器、Agent trace、内部 mapping 和 credential 永远不会暴露给用户。

---

# 七、技术栈介绍

Infoscope 采用：

> **Monorepo + Modular Monolith + Frontend / Backend 分离开发**

而不是在黑客松阶段引入复杂微服务。

## Frontend

```text
React
+
TypeScript
+
Vite
+
TanStack Query
+
openapi-typescript / openapi-fetch
+
pnpm
```

负责：

- Register / Login
- Onboarding
- NOW
- Event Detail
- BRIEF
- ARCHIVE
- SCOPE
- SETTINGS
- Search
- 询问观澜交互
- Loading / Error / Empty State

Frontend 不直接处理：

- Telegram API
- TrendRadar
- Agent-Reach
- LLM
- 来源隐私规则
- Event Reconstruction
- Personalization Pipeline

Frontend 的 Server State 主要通过 TanStack Query 管理。

---

## Backend

```text
Python
+
FastAPI
+
PostgreSQL
+
SQLAlchemy 2
+
Alembic
+
Independent Worker
+
uv
```

Backend 主要分为两个进程：

```text
Process A
FastAPI
→ 服务用户请求

Process B
IS Worker
→ 生产和维护 Event
```

二者属于同一个 Backend Codebase，共享：

- Models
- Schemas
- Services
- Integrations
- Analysis
- Database
- Configuration

因此：

> 独立进程 ≠ 微服务。

整体仍然是 Modular Monolith。

---

# 八、AI 与 Agent 架构

Infoscope 将 AI 分成两个不同职责。

## Research Runtime

```text
Research Adapter
↓
Hermes / OpenClaw
↓
Agent-Reach
```

负责：

- 搜索
- 多步骤 Research
- 工具调用
- Context Enrichment
- 补充 Evidence

---

## Analysis Runtime

```text
Analysis Adapter
↓
Model API
```

负责：

- Classification
- Claim Extraction
- Timeline Reconstruction
- Conflict Detection
- Base Analysis
- Personalization
- Brief Generation

业务代码不会直接绑定具体模型供应商。

模型、SDK 和具体 API 将通过 Adapter 隔离。

---

# 九、采集层

当前主要有两种固定 Acquisition Source。

## TrendRadar

TrendRadar 不作为独立服务部署，而是拆解其：

- Web / RSS / Hotlist
- Search
- Keyword Filtering
- Ranking Change
- Trend Logic
- Multi-platform Acquisition

能力，融合进入 IS。

Phase 3 v1 的实现边界冻结为 IS 内部异步薄 Adapter：兼容 NewsNow Hotlist
与 RSS / Atom / JSON Feed 输入，不复制或运行 TrendRadar 的 SQLite、通知、
MCP、Scheduler 或 AI 模块。API 地址和来源由 Backend 配置提供，采集结果逐条
幂等写入 Raw 后才允许进入后续处理。

固定 Hotlist 来源为：

- `baidu`
- `weibo`
- `thepaper`
- `wallstreetcn-hot`
- `cls-hot`
- `zhihu`
- `bilibili-hot-search`

固定 RSS 来源为：

- `hacker-news`：`https://hnrss.org/frontpage`

采集阶段不执行 AI 分类或关键词丢弃。相同 NewsNow snapshot 与相同 RSS
GUID / URL 保持幂等；新的 Hotlist snapshot 作为新的 Raw observation 保存，
供后续排名变化与趋势逻辑使用。

流程：

```text
TrendRadar Integration
↓
Raw
↓
Normalize
↓
Signal
```

## TG News

TG News 是内部 Telegram 采集模块。

负责：

```text
Telegram API
↓
固定群组 / 渠道
↓
Raw Telegram Information
↓
Normalize
↓
Signal
```

TG News 不直接生成 NOW、Event 或 Brief。

### TG News Integration v1（已冻结）

- 使用 Telegram 用户账号 MTProto API；Bot API 不具备聊天文件夹读取能力。
- 通过 `messages.getDialogFilters` 精确匹配标题 `News`（可由环境变量覆盖），
  按该 Filter 的显式 include / exclude、群组 / 频道规则解析会话。
- 只采集群组和频道中的文本或媒体 caption；不采集私聊 / bot，不下载媒体。
- `api_id`、`api_hash`、手机号与 Telethon session 只存在本地环境；session 不入 Git。
- 首次按每个会话最近 100 条（可配置）回溯，随后以数据库中该会话最大
  Telegram message ID 为 durable lower bound，逐条增量采集并立即持久化 Raw。
- 有公开 username 的群组 / 频道标记为 `public`；其他会话标记为 `private`。
  私密群名、username、peer ID 与链接只允许存在于内部 Raw provenance，普通日志
  只记录计数与稳定错误码，后续 Signal 仍必须转为 `private_sanitized`。
- Raw 唯一键由 peer ID 与 message ID 的 SHA-256 生成；重复采集幂等。
- 本模块不新增 Public API，不调用 AI，不直接写 Signal、Event、NOW 或 Brief。

---

# 十、完整数据 Pipeline

```text
TrendRadar / TG News
        ↓
COLLECT
        ↓
RAW PERSIST
        ↓
NORMALIZE
        ↓
SIGNAL PERSIST
        ↓
DEDUPLICATE
        ↓
1-HOUR WINDOW ANALYSIS
        ↓
EVENT MATCH / CLUSTER / RECONSTRUCT
        ↓
RESEARCH IF NEEDED
        ↓
NEW SIGNALS
        ↓
CLAIM EXTRACTION
        ↓
TIMELINE RECONSTRUCTION
        ↓
CONFLICT ANALYSIS
        ↓
BASE ANALYSIS
        ↓
EVENT PERSIST
        ↓
SCOPE / FOCUS PREFILTER
        ↓
PERSONALIZATION
        ↓
NOW
```

同时存在：

```text
Event Backwrite
+
Ask Reconciliation
```

不断重新补充和校正已有 Event。

---

# 十一、数据库与任务系统

第一版统一采用：

> **PostgreSQL**

PostgreSQL 不仅保存用户资料，还负责：

- Raw Information
- Signal
- Event
- Claim
- Timeline
- Conflict
- Analysis
- Personalization
- Job State

第一版不额外引入 Redis。

Worker 可以先基于 PostgreSQL 的 Job Table 工作。

逻辑状态：

```text
pending
running
completed
failed
```

只有未来真正出现多 Worker、高并发、Priority / Delay Queue 等需求时，再评估专业消息队列。

---

# 十二、API 与前后端通信

正式开发使用固定：

```text
/api/v1
```

通信链：

```text
FastAPI Schema
↓
OpenAPI
↓
openapi-typescript
↓
Generated TypeScript Types
↓
openapi-fetch
↓
TanStack Query
↓
React
```

关键原则：

- REST + JSON。
- JSON 使用 `snake_case`。
- 时间使用 UTC ISO 8601。
- Frontend 只使用相对 `/api/v1/...`。
- Dev 通过 Vite proxy。
- Demo 由 FastAPI 同源提供 API 与 React build。
- ID / cursor 对 Frontend 是 opaque string。
- NOW / Archive / Search 使用 cursor pagination。
- Ask 与 Maintenance 使用 `202 Accepted + Polling`。
- 第一版不使用 WebSocket。

认证：

```text
Username + Password
↓
FastAPI
↓
HttpOnly is_session Cookie
```

Frontend 不保存 Bearer Token，也不把 Token 写入 localStorage。

除 Session / Register / Login / Health 外，正式产品 API 都要求有效 Session；未完成 Onboarding 的用户只能进入 Onboarding，不能访问 NOW / Event / Ask 等正式产品数据。

核心 API 资源已经冻结：

```text
session / auth
onboarding
scope
now
events
archive
search
brief
ask
maintenance
health
```

Onboarding 的 SCOPE、投资市场、FOCUS ID 与条件关系同样已经冻结，前后端不得自行创建另一套字段。

Public API 只返回经过 Privacy Policy 处理的 DTO；数据库中的完整 provenance 不直接序列化给 Frontend。

---

# 十三、Git 协作

仓库采用 GitHub Monorepo。

唯一长期 Branch：

```text
main
```

开发使用短生命周期任务 Branch：

```text
feat/*
fix/*
refactor/*
chore/*
docs/*
test/*
```

标准流程：

```text
main
↓
task branch
↓
commit
↓
rebase origin/main
↓
PR
↓
review
↓
Squash Merge
↓
main
```

规则：

- 禁止直接在 `main` 上开发功能。
- 禁止长期个人分支。
- Commit 使用 `type(scope): description`。
- 所有功能通过 PR。
- Merge 固定 Squash Merge。
- `main` 始终保持可运行。
- `git push --force-with-lease` 只允许自己的 Feature Branch。
- 永远禁止 Force Push `main`。
- 已 Merge 的 Alembic Migration 不回改。
- OpenAPI 与 Generated TypeScript Types 必须进入 Git。
- API Contract Freeze 后，Frontend / Backend 都不能自行修改字段。

# 十四、部署

黑客松阶段不做 Everything in Docker。

运行方式：

```text
macOS / Ubuntu Host

React / Vite       Native
FastAPI            Native
IS Worker          Native
TrendRadar         Native / Integrated
TG News            Native
Hermes / OpenClaw  Native

PostgreSQL
↓
Docker
```

最终 Demo 目标是 macOS localhost：

```text
Browser
↓
FastAPI
├── API
└── React Production Build

Worker
↓
PostgreSQL
```

因此第一版不引入：

- Nginx
- Caddy
- Kubernetes
- 微服务
- GraphQL
- WebSocket
- Redis
- Celery
- Kafka

重点是保证整个 Event Intelligence Pipeline 能够稳定演示。

---

# 十五、前端设计语言

Infoscope 的视觉方向是：

```text
Editorial Intelligence
+
Swiss Information Design
+
Native Productivity UI
+
Restrained Glass
```

即：

> 编辑式情报界面 + 瑞士信息设计 + 原生生产力工具交互 + 克制的毛玻璃层级。

强调：

- Typography as Interface
- Strict Grid
- Monochrome
- Strong Hierarchy
- Metadata-driven
- Information Density
- Editorial Layout

避免：

- Generic SaaS Dashboard
- Bento Grid 滥用
- Everything-is-a-card
- AI 紫蓝渐变
- 大量彩色 Badge
- Glassmorphism Everywhere
- Gamification
- 全屏 ChatGPT Clone

Event 是界面的主角，AI 是理解和操作 Event 的工具。 

---

# 十六、一句话介绍

**Infoscope · 观澜是一个持续重构信息的个人智能界面：它把分散的信息整理成可追溯的 Event，通过 Claim、Timeline、Conflict 和 Evidence 还原发生了什么，再根据用户的视野，只呈现此刻真正值得关注的变化。**

技术上：

> **React + TypeScript + Vite + FastAPI + PostgreSQL + Native Worker + OpenAPI + Agent / Model Adapter**

共同组成一个 Event-first 的 Modular Monolith 信息智能系统。
