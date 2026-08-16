# Infoscope（IS）最终开发基线 / plan.md

> 版本：Final Baseline v4 · Development Freeze  
> 日期：2026-08-15  
> 产品名：Infoscope · 观澜  
> 产品理念：于信息之海，观其波澜。  
> 团队名：斥候  
> 团队理念：斥候先行，观澜于后。  
> 本文档负责：产品定义、信息模型、架构、AI Pipeline、API 原则、隐私规则、分工、Git、部署、MVP 与视觉总则。  
> 前端详细视觉与交互规范以 `style.md` 为准。

---

## 0. 最终基线

当前方案正式收敛为：

- **Event-first**，不再采用 Signal-first。
- `Signal` = 一条被 IS 标准化后的观察 / 证据单位。
- `Event` = 多个 Signal 被重构以后，用户真正消费的一级核心实体。
- 一级导航：
  - `NOW`
  - `BRIEF`
  - `ARCHIVE`
  - `SCOPE`
  - `SETTINGS`
- 不再使用 `STREAM` / `SIGNALS` 作为一级导航。
- 本地注册系统：
  - Username
  - Password
  - 用户资料保存在本地 PostgreSQL
- TrendRadar 与 TG News 负责固定渠道采集。
- Hermes / OpenClaw 负责调用 Agent-Reach 进行 Research / Enrichment，并可辅助脱敏和分类。
- 结构化分析优先通过独立 `Analysis Adapter` 调模型 API。
- 私密 Telegram 正文允许发送给第三方模型，但必须先隐藏群组身份等敏感 provenance。
- Alan 主责 Backend / Architecture / Integration / AI。
- Lingjiu 主责 Frontend。
- Frontend：React + TypeScript + Vite + TanStack Query。
- Backend：FastAPI + PostgreSQL + 独立 Worker。
- PostgreSQL 使用 Docker；其余核心服务原生运行。
- 第一版不使用 Redis、Celery、Nginx、Caddy、Kubernetes、GraphQL、WebSocket、微服务。
- GitHub Monorepo + task branch + PR + Squash Merge。
- Event 是持续维护对象，不是一次性生成结果。
- 系统包含三条持续更新链路：
  - Ask Infoscope / 询问观澜：问题 → Event Database 比对 → 必要时补充事实。
  - Event Backwrite / Event 回写：从已有用户可见 Event 主动回查最新变化。
  - Window Analysis / 时间窗口分析：周期性处理最近一个时间窗口中的新信息。
- Ask Infoscope 支持单 Event 与多 Event 联合提问。
- NOW 的“信息数量”严格按 Raw Information 实际计数，不使用 Signal 数替代。
- NOW 面向用户的主要文案使用中文。
- Backwrite 与 Window Analysis 采用完成后延时调度：完整一轮更新流程结束后开始计时，1 小时后启动下一轮。
- Window Analysis 的逻辑分析窗口长度固定为 1 小时。

---

# 1. 两个单一事实来源

## 1.1 API Contract

```text
FastAPI Schema
↓
OpenAPI
↓
Generated TypeScript Types
↓
Frontend
```

Frontend、Codex、Agent 不得根据 UI 或调用方式猜 Backend 字段。

任何 Contract 修改：

```text
Backend Schema
↓
OpenAPI
↓
Regenerate TypeScript Types
↓
Frontend
```

## 1.2 Information Contract

```text
External Raw Information
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

所有来源必须经过 Adapter / Integration 和 Normalize，来源差异不得一路传播到用户层。

Event 建立后仍持续维护：

```text
New Information ─────→ Window Analysis ────┐
                                           │
User Question ───────→ Ask Reconciliation ─┼→ New / Updated Signals
                                           │
Existing Event ──────→ Event Backwrite ────┘
                                           ↓
                                    Event Reconciliation
                                           ↓
                                      Updated Event
                                           ↓
                                      Personalization
                                           ↓
                                           NOW
```

三条链路最终必须回到同一套 Signal / Event 数据模型，不建立旁路事实系统。

---

# 2. 产品定义

Infoscope 不是：

- 传统新闻聚合器
- RSS Reader
- “AI Summary + Feed”
- 通用 AI Dashboard

IS 要解决：

> 信息过载、来源碎片化、重复传播、事实冲突，以及用户不知道“现在真正该关注什么”。

核心产品命题：

> **See the event, not the feed.**

中文：

> 从信息流中，还原事件。

用户最终看到的不是“更多内容”，而是：

```text
大量碎片信息
↓
IS 标准化
↓
重构 Event
↓
拆解 Claim
↓
重建 Timeline
↓
识别 Conflict / Evidence
↓
结合 SCOPE / FOCUS
↓
只呈现真正值得关注的变化
```

---

# 3. 核心信息模型

## 3.1 Raw Information

Raw 是采集器直接获得的信息。

可能包括：

- Telegram 原始消息
- RSS / Web 内容
- TrendRadar-derived acquisition 结果
- X / YouTube 等公开信息
- Agent-Reach Research 结果
- 原始 payload
- 完整 provenance
- collector metadata

Raw 只属于 Backend Internal，不得直接返回 Frontend。

Raw 应在采集后尽早持久化，以便：

- 后续 AI 失败时重试
- Pipeline 重放
- Debug
- 不必重新采集

---

## 3.2 Signal

Signal 定义：

> **IS 标准化以后的一条观察或证据。**

Signal 已脱离具体采集器结构，但仍保留受策略控制的 provenance。

Signal 可来自：

- TrendRadar
- Telegram
- X
- YouTube
- RSS / Web
- Agent-Reach Research
- 未来其他来源

Signal 不是首页主要消费单位。

主要用途：

- Deduplication
- Event Reconstruction
- Claim 支持 / 冲突
- Timeline
- Evidence View

---

## 3.3 Deduplication

Deduplication 处理：

> 多条 Signal 是否只是同一信息的重复传播。

它与 Event Reconstruction 分开：

- Deduplicate：是不是同一条信息的重复。
- Event Reconstruction：不同信息是不是在描述同一件事。

不得合并为一个黑盒步骤。

---

## 3.4 Event

Event 定义：

> **多个 Signal 被重构以后形成的、用户真正消费的一级核心实体。**

Event 不是静态文章。

它会随着新 Signal 到来持续演化。

一个 Event 可以因为：

- 新 Claim
- 新 Conflict
- 关键确认
- 对用户相关性上升

重新进入 NOW。

Event 概念结构：

```text
Event
├── Overview
├── Claims
├── Timeline
├── Conflicts
├── Evidence / Signals
├── Base Analysis
└── Personalized Interpretation
```

---

## 3.5 Claim

Claim 是 Event 内的独立事实命题。

用户侧强调：

- Confirmed
- Unresolved
- Conflicting
- Contradicted

这些是产品语义。具体代码枚举值必须在正式 Contract 中冻结，不能从本文档猜实现标识符。

---

## 3.6 Timeline

Timeline 表示 Event 的演化，而不是简单列出所有 Signal 发布时间。

重点：

- 首次出现
- 第二个独立信息
- 关键 Claim 确认
- Conflict 出现
- Event 状态变化
- 重要更新

---

## 3.7 Conflict

Conflict 表示：

- Claim 与 Claim 相互矛盾
- Signal 对 Claim 提供相反证据
- 同一事实出现互不一致描述

AI 可协助发现，但结果必须进入受 Schema 约束的结构化 Event 数据。

---

# 4. 一级产品信息架构

正式采用：

```text
NOW
BRIEF
ARCHIVE
SCOPE
SETTINGS
```

Search 是全局能力，不作为一级导航。

Ask Infoscope 第一版位于 Event Detail 内，不做独立全屏 Chat 页面。

---

## 4.1 NOW

NOW 是默认主界面。

它回答：

> **此刻哪些 Event 值得我注意？**

NOW 不是：

- 新闻 Feed
- Raw Stream
- 时间倒序文章列表
- Signal 浏览器

逻辑：

```text
Active Events
↓
Time / State Filter
↓
SCOPE Prefilter
↓
FOCUS / Importance Filter
↓
Personalization Selection
↓
按 Backend `display_time` 倒序形成用户可见列表
↓
NOW
```

Event 可以因重要更新重新浮到 NOW。

这正是 NOW 比 Feed / Stream 更适合 Event-first 的原因。

### NOW 统计口径

NOW 中“获取了多少条信息”必须使用 **Raw Information 的真实计数**。

必须区分：

```text
Raw Information Count
≠
Signal Count
≠
Event Count
```

NOW 面向用户的主要文案使用中文。

当前 Window Analysis 的逻辑窗口固定为 1 小时，因此推荐：

```text
NOW / 现在

过去 1 小时获取了 [Raw Information Count] 条信息，
整理为 [Event Count] 个事件。

其中 [Relevant Event Count] 个值得你现在关注。
```

要求：

- Raw Information Count 来自实际 Raw 数据。
- Event Count 来自实际 Event 数据。
- Relevant Event Count 来自当前用户真正可见 / 被推荐的 Event。
- 禁止用 Signal Count 替代 Raw Information Count。
- 禁止 Frontend 为 Demo 写死假数字。

---

## 4.2 BRIEF

BRIEF 回答：

> **如果我现在没时间逐个看 Event，今天最值得知道什么？**

BRIEF 是 Event 的编辑式压缩层，不建立另一套事实。

```text
Events
↓
Claims / Timeline / Conflict
↓
Personalization
↓
Brief
```

禁止：

```text
Raw Information
↓
独立 LLM
↓
产生与 Event 不一致的新事实
```

---

## 4.3 ARCHIVE

ARCHIVE 是长期事件记忆。

用于：

- 搜索过去 Event
- Saved Event
- 已结束 / Cooling Event
- 回看 Event Timeline
- 找回已经退出 NOW 的内容

产品语义：

```text
NOW = 当前注意力
ARCHIVE = 长期记忆
```

历史 Brief 留在 BRIEF，不混进 ARCHIVE。

---

## 4.4 SCOPE

SCOPE 是用户长期维护的个人观察模型，也是首次 Onboarding 的核心输入。

第一版 SCOPE 正式冻结为以下五项，可多选：

| API ID | 用户显示 |
|---|---|
| `ai` | AI |
| `open_source` | 开源社区 |
| `technology` | 技术 |
| `science` | 科学 |
| `investment` | 投资 |

规则：

- 至少选择 1 项。
- 第一版不提供自定义 SCOPE 输入。
- SCOPE 页面底部固定显示小字：**“后续更新将提供自定义SCOPE”**。
- 如果没有选择 `investment`，不会出现投资二级页面。
- 如果选择 `investment`，进入条件页面 `01.1 / 投资市场`。

投资二级页面问题固定为：

> **你更关注？**

可多选：

| API ID | 用户显示 |
|---|---|
| `china_market` | 中国市场 |
| `us_stock` | 美股 |
| `crypto_market` | 加密市场 |

投资二级页面规则：

- 仅当 `scope_ids` 包含 `investment` 时出现。
- 出现时至少选择 1 项。
- 未选择 `investment` 时，`investment_market_ids` 必须为空数组。

FOCUS 正式冻结为以下八项，可多选：

| API ID | 用户显示 |
|---|---|
| `technical_details` | 技术细节 |
| `research_progress` | 研究进展 |
| `major_changes` | 重要变化 |
| `breaking_events` | 突发事件 |
| `niche_trends` | 小众趋势 |
| `industry_changes` | 行业变化 |
| `controversy_changes` | 争议变化 |
| `deep_context` | 深度背景 |

FOCUS 规则：

- 至少选择 1 项。
- 第一版不提供自定义 FOCUS 输入。
- FOCUS 页面底部固定显示小字：**“后续更新将提供自定义FOCUS”**。

修改 SCOPE / FOCUS：

```text
不改变 Event 事实
↓
保存 User Preferences
↓
触发 Personalization 更新
↓
NOW 展示集合 / Why it matters / BRIEF 随之更新
```

---

# 4.5 SETTINGS

SETTINGS 只处理：

- 帐号
- 系统
- 界面
- 本地数据

以下不放 SETTINGS：

- 用户关心什么
- 哪类变化更重要

这些属于 SCOPE。

来源管理也不作为普通用户的一级产品心智。

---

# 5. 注册与 Onboarding

第一版采用本地帐号：

```text
Username
+
Password
+
Local User Data in PostgreSQL
```

不接：

- Email verification
- Apple OAuth
- Google OAuth
- 云端用户系统

密码不得明文保存，只保存安全密码哈希。

## 5.1 首次进入

```text
IS Main UI Preview
↓
Blur / Reduce Contrast / Disable Interaction
↓
Register / Login Overlay
↓
Create Local Account
↓
01 / SCOPE
↓
如果选择“投资”
    └→ 01.1 / 投资市场
       “你更关注？”
↓
02 / FOCUS
↓
视野已建立
↓
Blur clears
↓
NOW
```

如果没有选择“投资”：

```text
Register
↓
01 / SCOPE
↓
02 / FOCUS
↓
NOW
```

## 5.2 SCOPE

固定可选项：

```text
AI
开源社区
技术
科学
投资
```

可多选，至少选择 1 项。

页面底部小字：

> 后续更新将提供自定义SCOPE

## 5.3 投资二级页

仅在选择“投资”后出现。

问题：

> **你更关注？**

选项：

```text
中国市场
美股
加密市场
```

可多选，至少选择 1 项。

## 5.4 FOCUS

固定可选项：

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

可多选，至少选择 1 项。

页面底部小字：

> 后续更新将提供自定义FOCUS

## 5.5 已有用户

```text
Login
↓
GET /api/v1/session
├── onboarding_required → Onboarding
└── ready               → NOW
```

MVP Onboarding 不加入：

- RHYTHM
- 连续强度 Slider
- 用户自写 Prompt
- 自定义 SCOPE
- 自定义 FOCUS

以上 Onboarding 结构、选项、ID 与条件分支在本轮开发中冻结。

---

# 6. 来源与隐私策略

## 6.1 原则

不是“所有来源全部隐藏”。

正确原则：

> **根据来源本身的公开性决定 provenance 可以暴露多少。**

数据库内部保存完整 provenance。

Public API 只返回 Visibility Policy 允许的信息。

---

## 6.2 私密 / 邀请制 Telegram

允许 Frontend 显示：

- `Telegram` 这一平台级标识
- 经过脱敏检查的原文 Evidence
- 时间
- 与 Claim 的关系

禁止显示：

- 具体群组名称
- 群组 username
- invite link
- peer / chat 等内部标识
- collector 配置
- 任何可直接反推出群组身份的数据

不仅 metadata 要脱敏。

如果正文中本身出现：

- 群名
- 群 username
- invite link
- 明确身份提示

也必须先 Public Sanitization。

脱敏不能悄悄改写事实；隐藏内容应以明确方式表达。

---

## 6.3 公开来源

对于：

- X
- YouTube
- 公开网站
- 公开 RSS

Evidence 可以显示：

- 平台
- 公开作者 / 博主 / 频道
- 公开链接
- 相关公开原文
- 时间

仍禁止暴露：

- 内部 collector 配置
- TrendRadar 内部实现
- Agent trace
- credential
- 内部 source mapping

---

## 6.4 私密 TG → 第三方模型

已经确认：

> **允许发送正文，只要求隐藏群组身份。**

因此：

```text
Private TG Raw
↓
Remove / Mask Confidential Provenance
↓
Sanitize identity-bearing content
↓
Model / Agent Input
```

禁止将：

- 群名
- invite link
- 群 username
- internal ID

原样发送第三方模型。

来源可见性不能交给 AI 自主决定。

AI 可以帮助识别敏感文本，但最终策略由程序控制。

---

# 7. Acquisition / Research 架构

## 7.1 TrendRadar

定位：

> Acquisition Layer。

TrendRadar 不作为独立容器或外部服务部署。

主要复用：

- Web / RSS / Hotlist
- 搜索逻辑
- 关键词筛选
- 趋势 / 排名变化
- 多平台聚合方法

Phase 3 v1 已冻结为 IS 内部异步薄 Adapter，不复制或运行 TrendRadar 的
SQLite、通知、MCP、Scheduler 或 AI 模块。Adapter 兼容 NewsNow Hotlist
和 RSS / Atom / JSON Feed，并在任何 Normalize、筛选或分析前逐条持久化 Raw。

固定 Hotlist 来源：

- `baidu`
- `weibo`
- `thepaper`
- `wallstreetcn-hot`
- `cls-hot`
- `zhihu`
- `bilibili-hot-search`

固定 RSS 来源：

- `hacker-news`：`https://hnrss.org/frontpage`

相同 NewsNow snapshot 与相同 RSS GUID / URL 必须幂等；新的 Hotlist
snapshot 必须作为新的 Raw observation 保存，以保留后续排名变化分析所需证据。

必须输出到：

```text
Raw
↓
Normalize
↓
Signal
```

不得直接写 Event / NOW。

---

## 7.2 TG News

TG News 是 IS 内部模块。

职责：

- 调用 TG API
- 获取固定群组 / 渠道信息
- 输出 Raw Telegram Information
- 进入 Normalize

TG News 不直接生成最终 NOW / Event / Brief。

### TG News Integration v1（已冻结）

TG News v1 自行实现为内部 Telethon 薄 Adapter。它使用用户账号 MTProto API
读取标题严格等于 `News` 的 Telegram Dialog Filter，只接收该文件夹中的群组与
频道，并把文本 / caption 作为 `telegram` Raw Information 立即持久化。

固定边界：

- 不使用 Bot API，不采集私聊 / bot，不下载媒体文件。
- 首次每个会话回溯最近 100 条（可配置）；后续从该会话已持久化的最大
  message ID 开始增量获取，重复消息由 Raw 唯一键幂等处理。
- 有公开 username 的群组 / 频道为 `public`，其余为 `private`；私密来源身份只
  保存在内部 Raw，普通日志不得输出群名、username、邀请链接或 peer ID。
- credential 与 Telethon session 只保存在本地环境，禁止进入 Git。
- 不新增 Public API，不调用 AI，不直接生成 Signal / Event / NOW / Brief。

### Normalize v1（已冻结）

Normalize v1 是确定性 `Raw → Signal` 映射：每条 `telegram` 或 `trend_radar`
Raw 生成一个 `signal_index=0` Signal，只清理 Unicode NFC、换行和首尾空白，映射
来源字段并计算标准化正文哈希。它不进行摘要、分类、筛选、Deduplicate 或任何 AI
调用。

公开 provenance 采用来源专属 allowlist；私密 Telegram 最终必须由 Signal 持久化
边界强制转成 `private_sanitized` 并清空 `public_provenance`，正文中的群名、
username、邀请链接和长 peer ID 以 `[PRIVATE_SOURCE_REDACTED]` 明确替换。空正文和
未知来源使用稳定错误码并隔离失败；Pending 与 Failed 分开批处理，重试不需要重新采集 Raw。

### Deduplicate v1（已冻结）

Deduplicate v1 仅把标准化正文 SHA-256 完全相同的 Signal 标记为 exact duplicate。
同一 hash 中 `(created_at, id)` 最早者保持 canonical，后续 Signal 通过
`duplicate_of_signal_id` 直接指向它。所有 Signal、独立 provenance 和 visibility
继续保留，不删除或合并 Evidence。

该步骤使用稳定游标批量扫描且可幂等重跑，与 Event Reconstruction 严格分离。
语义 / 模糊去重涉及 embedding API、阈值与 output schema，当前继续冻结，不自行猜测。

### Window Analysis Artifact v1（已冻结）

Window Analysis 按 Raw `acquired_at` 运行连续的一小时 `[start, end)` 窗口。首个窗口
从最早 Raw 开始，只执行 `end <= watermark` 的完整窗口；积压补偿从最近成功窗口的
`end` 连续推进，窗口内使用 `(acquired_at, raw_id)` 复合游标。

模型仅接收 Normalize 成功的非重复 Signal、已脱敏正文和 public-safe provenance。
`private_sanitized` Signal 不允许携带公开 provenance，也禁止模型反推 Telegram 私密
群名、用户名、邀请链接或内部 ID。exact duplicate Signal 不重复进入模型，但 Raw 仍
推进采集游标。

冻结输出 `window_analysis.v1` 包含逐 Signal 分类与事实声明、聚类建议、关系、缺失上下文
和未归类 Signal，不生成 Event ID。结果必须通过 JSON Schema 与完整覆盖校验，并先写入
Backend Internal `pipeline_artifacts`，再完成 run 与 checkpoint。API、Schema、覆盖或
前置条件失败会停止后续窗口且不推进 checkpoint；本步骤不新增 Public API、前端 Contract、
Event、NOW 或 Brief。

超过 Signal 数量或输入字符上限的窗口必须在调用模型前以稳定错误码失败。在跨批聚合
Contract 尚未共同冻结前，禁止静默截断输入或把一个逻辑窗口拆成互不关联的模型结果。

失败恢复复用同一窗口与 lower cursor，并创建递增 attempt；到达 `next_retry_at` 后自动
重试，也可按 run UUID 立即 retry 或 replay terminal run，均不重新采集 Raw。审计日志
仅包含 pipeline/run ID、窗口、attempt、计数、状态、稳定错误码和重试时间，不记录正文、
私密 provenance、Prompt、模型响应或 API Key。

### Event Reconstruction v1（已冻结）

Event Reconstruction v1 消费一个成功的 `window_analysis.v1` artifact、其标准化 Signal
和 Backend 提供的 Existing Event candidates。`events` 固定保存 `id`、`title`、
`overview`、`state`、`display_time` 与审计时间；state 使用既有
`developing / confirmed / conflicting / cooling`。`event_signals` 保存多对多 Evidence
关系及首次 attached pipeline run，一个 Signal 可关联多个 Event。

模型只输出 `new_events`、`existing_event_updates` 和 `unassigned_signal_ids`。模型不得为
New Event 生成 ID，Existing Event 更新只能引用 Backend 提供的 candidate ID；每个本轮
输入 Signal 必须且只能进入一个 decision 或 unassigned。Backend 校验 decision key、
Candidate、UTC display time 与完整覆盖后分配或复用 Event ID。

模型输出的 state 仅作为内部建议保留在 artifact；Backend 对 New Event 固定使用
`developing`，Existing Event 在本切片保持当前合法状态。后续状态变化必须由确定性的
Claim / Conflict 规则驱动，模型不得直接写入 Event state。

reconstruction artifact、Event 变化与 Event–Signal 关系原子持久化，之后才能完成 pipeline
run。同一个 source artifact 永远复用首次 assignment，不再次调用模型或重复创建 Event。
Backend 在模型调用前对 source artifact 加锁并在锁内复查；数据库使用
`(artifact_type, source_artifact_id)` 唯一约束兜底，冲突时回滚并复用 canonical artifact，
重放 run 不复制第二份 reconstruction artifact。
本切片不实现 Claim、Timeline、Conflict、Base Analysis、Personalization、Public API 或前端。

### Claim Extraction + Timeline Reconstruction v1（已冻结）

Claim Extraction 消费 canonical `event_reconstruction.v1` artifact、对应 Event、Event 已关联
Signal 与 Existing Claim candidates。`claims` 保存 `id / event_id / text / state` 与审计时间；
state 固定为 `confirmed / unresolved / conflicting / contradicted`。模型不输出 state，New Claim
固定为 `unresolved`，Existing Claim 保持当前合法状态。`claim_signals` 是 Claim–Signal 多对多
Evidence 关系，一个 Signal 可以支撑多个 Claim，但只能引用同 Event 已关联的真实 Signal。

Timeline Reconstruction 消费 canonical `claim_extraction.v1` artifact、对应 Events、Claims、
已脱敏 Evidence Signals 与 Existing Timeline candidates。模型只接收同 Event 已关联的真实
Signal 正文、时间和 public-safe provenance。`timeline_entries` 保存
`id / event_id / occurred_at / summary` 与审计时间，`timeline_claims` 保存 Timeline–Claim
多对多关系。`occurred_at` 必须为 Backend 校验的带时区时间，Timeline 表示关键演化节点，
不是逐条 Signal 发布时间列表。

两个严格模型输出都只允许 Backend candidates，New ID 均由 Backend 分配，并通过 used/unused
完整覆盖校验。模型 rationale 不是 Evidence。两条 pipeline 均在模型调用前锁定 source
artifact 并复查，以 `(artifact_type, source_artifact_id)` 唯一约束兜底；实体、关系与 artifact
原子持久化后才完成 run。本切片不实现 Conflict、Base Analysis、Public API 或前端。

### Conflict Analysis v1（已冻结）

Conflict Analysis 消费 canonical `timeline_reconstruction.v1` artifact、对应 Events、当前全部
Claims、Claims 通过 `claim_signals` 关联的真实 Evidence Signals 与 Existing Conflict candidates。
模型只接收 `signal_id / published_at（可空）/ sanitized_text / public_safe_provenance`，不得推导
Signal `occurred_at`。冲突语义由模型基于受限输入判断；Backend 只验证结构、同 Event 归属、
Claim–Signal Evidence 关联、候选范围与完整覆盖，rationale 只用于内部审计，不是 Evidence。

模型输出 `new_conflicts / existing_conflict_updates / unconflicted_claim_ids`。每个 decision 包含
`decision_key / event_id / summary / claim_ids / evidence_signal_ids / rationale`，update 另含
`existing_conflict_id`。Claim 非空；合法结构为至少两个 Claim，或单 Claim 加至少一个关联
Evidence。New Conflict ID 由 Backend 分配，update 只能引用同 Event 的 Backend candidate。

Existing update 对 `conflict_claims` 与 `conflict_signals` 只追加，summary 使用本轮值；不删除关系，
不覆盖首次 attached run。`unconflicted_claim_ids` 仅表示本轮无新增或更新，不解除历史关系或恢复
状态。used 与 unconflicted 互斥并完整覆盖全部输入 Claim；一个 Claim 可参与多个 Conflict。

Backend 确定性执行 `confirmed/unresolved → conflicting`，保留 `conflicting/contradicted`，涉及
Conflict 的 Event 转为 `conflicting`。模型不得输出状态，v1 不实现 Conflict resolution 或自动恢复。
Pipeline 沿用来源锁、canonical artifact 复用、数据库并发唯一约束、原子持久化与私密 provenance
调用前阻断。本切片不新增 Base Analysis、Public API、Event Detail 或 Frontend Contract。

### Base Analysis v1（已冻结）

Base Analysis 消费 canonical `conflict_analysis.v1` artifact。Source Event 集合为所有
`new_conflicts / existing_conflict_updates` 的 `event_id`，并入全部 `unconflicted_claim_ids`
反查得到的 Claim `event_id`；不得只依赖 Conflict assignments。空 Event 集合不调用模型，但仍
生成 canonical 空 artifact，保持 pipeline 链和 replay 幂等。

每个 Event 输入当前完整的 Event、Claims、Timeline、Conflicts、受限 Evidence 与 Existing Base
Analysis candidate。Signal 仅包含 `signal_id / published_at（可空）/ sanitized_text /
public_safe_provenance`。模型只能总结已持久化事实层，不得把 Evidence 中尚未进入 Claim、Timeline
或 Conflict 的内容提升为新事实。

`base_analyses` 是 Event 一对一的用户无关当前快照，保存 `id / event_id / source_artifact_id /
summary / event_type / importance / topics / entities` 与审计时间。Importance 固定为
`low / medium / high / critical`；Topics 与 Event 内 Entity 注释使用严格受限 JSONB，v1 不建立
全局 Topic、Entity 或实体合并系统。

模型输出 `new_analyses / existing_analysis_updates`，每个 source Event 必须且只能有一个 decision。
New ID 由 Backend 分配，update 只能引用同 Event candidate。Existing update 对 summary、event
type、importance、topics、entities 与 source artifact 执行完整快照替换，历史由 immutable
pipeline artifact 保留；不允许静默跳过或部分成功。

Base Analysis 不修改 Event title/overview/state/display_time、Claim state、Timeline、Conflict 或
Evidence 关系，也不产生 Personalization。来源锁、唯一幂等键、全批原子提交、rollback 与私密
provenance 调用前阻断沿用既有规则。本切片不新增 Public API、Event Detail、NOW 或前端 Contract。

### Research Integration v1（已冻结）

Research v1 固定 `openclaw@2026.7.1-2`，使用
`openclaw agent --local --agent infoscope-research --session-key research-<request_id> --message-file <file> --model <id> --timeout <s> --json`
作为 headless Runtime；不使用 Gateway、stdin、deliver、channel 或 recipient。Agent-Reach 只负责
公开搜索能力的安装、选择与 `doctor` 健康检查，不存在也不假设统一 Research API。Backend 创建
`research_requests.id` 并注入严格 `research_fact_snapshot.v1`，模型只能返回
`research_discovery.v1` 的公开候选 URL，回显的 `request_id` 必须与 Request 主键一致。

OpenClaw 使用独立 regular config、state 与每次运行的 0700 workdir；Prompt 是 workdir 内的 0600
UTF-8 临时文件，并在成功或失败后始终清理。OpenClaw 与 Agent-Reach 的 `HOME / TMPDIR` 均固定为
research state 下的 0700 专用目录，不继承用户真实 HOME。子进程不得继承完整环境：只继承
`PATH`，Backend 注入 `OPENCLAW_CONFIG_PATH / OPENCLAW_STATE_DIR`，模型凭据 allowlist 固定且仅含
`DEEPSEEK_API_KEY`，不得配置通配规则。稳定版 JSON 只解析 `payloads + meta`：排除
reasoning/commentary 后必须恰好一个非空且非错误的 visible text，provider/model/usage 只从
`meta.agentMeta` 读取。非零退出、外层超时、aborted、meta error/failureSignal、错误 payload 或
协议偏差使用稳定内部错误码。

事实快照固定包含同一批 Event 的 Event、Claims、Timeline、Conflicts 与已脱敏 Evidence；Backend
验证全部 Event/Claim/Timeline/Conflict/Signal 归属和关系后才执行 canonical JSON 与 input hash。
私密 Evidence 仅允许 `private_sanitized` 正文，`public_safe_provenance` 必须为空。Snapshot 不包含
Raw、collector metadata、内部 provenance 或 Base Analysis。

v1 来源枚举仅为 `web_page / github_document`。OpenClaw 只发现 URL；正文由 Backend 的受控
HTTPS Fetcher 获取。URL 只允许 HTTPS:443、无凭据、无 IP literal、无 redirect，并在 DNS 与实际
peer 两处阻断私网、回环、link-local、保留地址和 DNS rebinding。GitHub Document 只允许
`raw.githubusercontent.com`。网页使用锁定的 `beautifulsoup4==4.15.0` 与 `html.parser` 执行确定性
HTML→文本；`published_at` 只接受一致且带时区的 `article:published_time`，GitHub Document 固定为空。

Request、Run、Discovery Artifact 与 Source 使用专用 Research 表。`idempotency_key` 控制一次业务
任务重放，相同 key 不得改变 input hash；不同 key 允许在后续周期对相同问题重新 Research。已有
canonical discovery 的 retry 不再调用模型，只重试失败 Source。零候选是 canonical success；部分
成功、无有效候选、全部 Fetch 失败与 Runtime/Schema 失败使用稳定状态和错误码。

每个候选都必须持久化一条 Source 审计：合法候选保存 canonical URL；非法 URL、SSRF 与 canonical
重复候选保存 failed、稳定 error code 和原始 URL 的 SHA-256，不保存原始候选 URL。Discovery
artifact 保存完整且有序的 privacy-safe 候选结果：accepted 项保存 source kind、canonical URL、URL
hash 与 relevance summary；rejected 项仅保存 source kind、URL hash 与稳定 error code，不保存原始
URL 或 relevance summary。URL percent normalization 解码 unreserved，保留其他合法 escape 并统一
大写十六进制，只拒绝非法或不完整 escape。

Fetcher 获取的规范化正文按 SHA-256 计算 content hash，Raw source key 固定由
`source_kind + canonical_url + content_hash` 生成。同 URL 同内容跨运行复用，内容变化形成新
observation。模型正文和 relevance summary 永远不是 Evidence；真实材料必须先写 public Raw，再走
`Raw → Normalize → Signal → Deduplicate → Event Reconciliation`。本切片不新增 Public API、Ask、
Event Detail、NOW 或前端 Contract，也不直接修改任何事实层。

---

## 7.3 Hermes / OpenClaw / Agent-Reach

Hermes / OpenClaw：

> Agent Runtime。

Agent-Reach：

> Research / Enrichment。

推荐：

```text
Event Reconstruction
↓
缺上下文 / 需要验证 / 需要扩展
↓
Research Adapter
↓
Hermes / OpenClaw
↓
Agent-Reach
↓
Research Result
↓
Normalize
↓
New Signal
↓
回到 Event
```

Agent 找到的事实必须重新成为 Signal。

禁止：

```text
Agent Result
↓
直接覆盖 Event Summary
```

Hermes / OpenClaw 也可辅助：

- 脱敏
- 分类
- 上下文处理

但实际调用方式必须读取真实版本：

- README
- CLI help
- Config
- Source entry
- API definition

后再实现 Adapter，不得猜。

---

# 8. AI 架构

分成两类运行时。

## 8.1 Research Runtime

```text
Research Adapter
↓
Hermes / OpenClaw
↓
Agent-Reach
```

适合：

- Search
- Tool use
- Multi-step research
- Context enrichment
- Additional evidence

## 8.2 Analysis Runtime

```text
Analysis Adapter
↓
Model API
```

适合：

- Classification
- Claim Extraction
- Timeline Reconstruction
- Conflict Detection
- Base Analysis
- Personalization
- Brief generation

当前不冻结：

- 模型供应商
- 模型名
- SDK
- Request format

业务代码不得直接绑定特定模型供应商。

---

## 8.3 Base Analysis

回答：

> 这个 Event 本身是什么？

与用户无关。

包括概念上的：

- Summary
- Topic
- Entity
- Event type
- Importance
- Claim
- Timeline
- Conflict

---

## 8.4 Personalization

回答：

> 为什么这个 Event 值得这个用户关注？

输入：

```text
Event / Base Analysis
+
User SCOPE
+
User FOCUS
```

用于：

- relevance
- priority
- why it matters
- personalized angle
- NOW ranking
- BRIEF selection

内部可以有评分，但不向用户展示无解释价值的精细小数。

---

## 8.5 Ask Infoscope / 询问观澜

Ask Infoscope 不是通用 Chatbot，而是建立在 Event Database 上的上下文分析入口。

支持：

```text
Single-Event Ask
Multiple-Event Ask
```

### 单 Event

```text
User Question
+
Current Event
├── Claims
├── Timeline
├── Conflicts
└── Evidence
↓
Database Comparison
↓
Answer / Research if Missing
```

### 多 Event

用户可以显式选择多个 Event 联合提问：

```text
Selected Events
↓
Cross-Event Context
↓
Database Comparison
↓
Compare / Analyze
↓
Research if Missing
↓
Answer
```

适用于：

- 比较多个 Event 的共同点与差异
- 分析多个 Event 之间的联系
- 对比 Timeline
- 对比 Claim / Conflict
- 从相同 Perspective 分析多个 Event

多 Event Ask 发现关联，不代表 Ask 可以自动 Merge Event。Event 的 Merge / Split / Relationship 仍由 Event Reconstruction / Reconciliation 决定。

### 回答前必须和 Event Database 比对

```text
User Question
↓
Read Existing Event Data
↓
Determine Required Facts
↓
Compare With Database
├── 已有 → 使用现有事实
├── 缺失 → Research
├── 新事实 → New Signal
└── 冲突 → Conflict / Reconciliation
↓
Update Event if needed
↓
Answer from updated Event state
```

如果所需事实缺失：

```text
Missing Information
↓
Research Adapter
↓
Research Result
↓
Normalize
↓
Signal
↓
Deduplicate
↓
Event Reconciliation
↓
Event Update
↓
Answer
```

硬规则：

```text
AI Answer
≠
Evidence
```

模型自身推理不能直接变成 Signal / Claim。只有新的外部事实材料经过 Raw → Normalize → Signal 后，才可以补充或修正 Event。

Ask 同样服从来源隐私边界。私密 Telegram 可以使用脱敏后的正文，但不得输出群名、群 username、invite link、internal ID 或其他禁止暴露的 provenance。

### Ask Database Comparison v1（已冻结）

- 内部输入 `ask_database_comparison_input.v1` 固定为：trim 后的 question、用户选择顺序不变的
  `selected_event_ids`，以及每个 Event 当前完整的 Event、Base Analysis、Claims、Timeline、
  Conflicts 和脱敏 Evidence。每个 Event 必须存在并具备当前 Base Analysis；否则在调用模型前以
  `ASK_EVENT_NOT_FOUND / ASK_EVENT_BASE_ANALYSIS_MISSING` 失败。未来 Public API 必须另外校验
  `user_id` 对全部所选 Event 的访问权限。
- `input_hash` 是 question、按选择顺序的 Event IDs、验证后的 canonical snapshot 的 SHA-256；
  不包含 Ask ID、时间或 attempt，顺序变化必须改变 hash。failed retry 重新构造当前 snapshot，
  hash 不一致以 `ASK_INPUT_CHANGED` 失败，并要求创建新 Ask。
- 模型只允许返回 `answerable / research_required`。两种 decision 的 `event_ids` 都必须与输入完全
  一致且顺序一致；所有 ID 数组去重，Claim、Timeline、Conflict、Evidence 引用必须属于关联的
  selected Event。模型不能生成 ID、事实、状态变化、Event merge 或事实层写入。
- `answer` 上限 20,000 字符，`rationale` 上限 4,000；`missing_facts` 最多 8 项，每项 question
  1–500、reason 1–2,000 字符，并按 `(event_ids, question)` 去重。missing Event IDs 必须是输入
  的有序子集。`rationale` 仅供内部审计，不是 Evidence。
- `ask_requests / ask_request_events / ask_runs / ask_comparison_artifacts` 独立持久化。Artifact 有
  Backend ID，`created_by_run_id` 唯一且 immutable；只有模型输出通过严格 Schema、范围校验和
  事务提交时才创建。运行时、JSON、Schema、持久化失败只记录稳定错误状态，不伪造 Artifact。
- 初次 comparison 从 `pending/comparing` 进入 `running/comparing`；仅 `failed/comparing` 可重试。
  `completed` 与 `pending/awaiting_research` 都复用既有结果，不再次调用模型或生成 comparison。
  `research_required` 固定回到 `pending/awaiting_research`，Ask Research Bridge 合并前不得自动重跑
  或调用 Research；`answerable` 进入 `pending/finalizing`，只有 canonical Final Answer artifact 成功
  提交后才进入 completed。
- 单请求行锁防止并发重复模型调用；Artifact 与 run/request 状态原子提交。canonical input snapshot
  与模型输出属于内部敏感数据，不进入普通日志或 Public DTO。私密 Signal 仅传
  `sanitized_text + null provenance`。本切片不新增 Public API，不触发 Research，不修改事实层。

### Ask Research Bridge v1（已冻结）

- 仅消费 `pending/awaiting_research` 且 canonical comparison decision 为 `research_required` 的
  Ask。初次无 Bridge；retry 只允许 Ask 仍为 `pending/awaiting_research`、Bridge 为 failed 且
  `attempt_count < max_attempts`。running 不重入，completed 复用 artifact，terminal failed 不重试。
- 每个 Ask Comparison 只建立一个 Research Request。`idempotency_key` 使用固定 namespace 的
  UUIDv5，由 Ask ID、comparison artifact ID 与 schema version 组成，不含时间或 attempt。retry
  读取已关联 Research Request 的原始 payload，不重新构造 Research snapshot。
- Research trigger 固定为 `ask_missing_fact`；questions 按 missing facts 原顺序无损传入；source
  Event 是全部 missing Event 的并集，并按原 selected Event 顺序排列；source kinds 固定为
  `web_page / github_document`。reason 与 comparison rationale 只留在原 artifact，不截断、不传给
  Research prompt。
- Research 结果先写 Raw。Bridge 只定向处理该 Research Request 中 succeeded source 对应的 Raw；
  pending/failed 可重新 Normalize，succeeded 复用既有 Signal，processing 不并发接管。Signal 仍只
  能由 DeterministicNormalizer 生成，Research 模型内容不能直接成为 Signal。
- `ask_research_bridges` 独立保存 status、attempt/max attempts、稳定错误码与 Ask/Comparison/
  Research 唯一关系。三套计数互不覆盖：Ask request 只计 Database Comparison，Bridge 只计编排，
  Research request 只计 Research runtime/fetch。
- `ask_research_bridge.v1` 是下一步 Event Reconciliation 的 canonical source artifact，只保存 Ask、
  Comparison、Research IDs、有序 source Event IDs，以及每个成功来源的 candidate index、source ID、
  Raw ID、Signal IDs 和 `succeeded/partial` Research status；不复制 URL、正文、provenance、reason、
  rationale 或模型输出。无 Signal 不创建 artifact。
- Bridge attempt 期间 Ask 为 `running/awaiting_research`。可重试失败恢复为
  `pending/awaiting_research`，错误只保存在 Bridge；不可重试、底层或 Bridge attempts 耗尽、以及
  `ASK_RESEARCH_NO_USABLE_SIGNALS` 进入 `failed/awaiting_research` 终态。至少一个有效 Signal 时，
  artifact、Bridge completed 与 Ask `pending/awaiting_reconciliation` 原子提交。
- 本切片不自动调度、不执行 Event Reconciliation、不生成最终回答、不修改事实层，也不新增
  Public API 或 Frontend Contract。

### Ask Event Reconciliation v1（已冻结）

- 仅消费 `pending/awaiting_reconciliation` Ask 与唯一 `ask_research_bridge.v1` artifact，只更新其
  有序 `source_event_ids` 中的既有 Event；不新建、合并或拆分 Event，不修改 Claim、Timeline、
  Conflict、Base Analysis，也不生成最终回答。
- 只对 Bridge 引用的 observation Signal 执行定向 exact dedupe；canonical 仍由相同 content hash
  下 `(created_at, id)` 最早记录决定。去重结果先独立提交，canonical Signal 按 Bridge 首次出现顺序
  输入模型，并保留 observation IDs 映射；禁止扫描全局 Signal。
- `ask_event_reconciliation_input.v1` 包含 Ask、完整 Bridge payload、trimmed question、去除 reason
  的 missing facts、有序 source Events、当前 Base Analysis/Claims/Timeline/Conflicts/Evidence，以及
  canonical Signal 的脱敏正文、可空 published_at、visibility 与 public-safe provenance。私密
  Evidence 必须为 `private_sanitized + null provenance`。
- 模型输出固定为 `ask_event_reconciliation.v1`：`event_updates` 与
  `unassigned_signal_ids`。每个 update 的 `signal_ids` 必须非空、唯一且来自输入；同一 Signal 可支持
  多个所选 Event。每个 canonical Signal 必须被至少一个 update 使用或明确 unassigned，不能两者
  同时出现。全 unassigned 时终态 `ASK_RECONCILIATION_NO_RELEVANT_SIGNALS`，不得改写 Event。
- Backend 只应用模型验证后的 title、overview、display_time，保留 Event state；EventSignal 仅追加、
  重放幂等。`event_signals` 使用 pipeline run 或 Ask reconciliation run 二选一的真实 attached source，
  不伪造一小时 PipelineRun。
- 独立 reconciliation、attempt run、immutable artifact 记录 source Bridge、input hash、模型
  输出、assignments 与有序 updated Event IDs。running 不重入、completed 复用；失败重试不改变 Ask
  Comparison 或 Bridge attempts。
- 模型返回后在同一事务按 Ask、Bridge、Event、Signal、EventSignal、Claim/relations、Timeline/
  relations、Conflict/relations、Base Analysis 的固定顺序逐表加锁，重建完整 canonical input 并复核
  SHA-256。任一内容、关系、顺序或 duplicate mapping 变化均终态
  `ASK_RECONCILIATION_INPUT_CHANGED`，丢弃模型输出且不创建 artifact。
- 成功时 Event 更新、EventSignal 追加、artifact、run/reconciliation completed 与 Ask
  `pending/finalizing` 原子提交。本切片不新增 Public API、Frontend Contract、NOW 或 Event Detail。

### Ask Finalization & Public API v1（已冻结）

- Finalization 仅消费 `pending/finalizing` Ask。`direct_reuse` 严格复核并复用 answerable Comparison，
  不调用模型且 `updated_event_ids=[]`；`researched_model` 消费唯一 Reconciliation artifact，并从更新后
  的当前完整 Event 事实快照生成最终回答。
- `ask_finalizations`、独立 attempt runs 与 immutable `ask_final_answer.v1` artifacts 分别对 Ask、source
  与 run 唯一。direct artifact 的 provider/model/token usage 必须全为 null；researched artifact 必须
  全部非空，禁止伪造模型元数据。
- researched input hash 覆盖 question、原选择顺序、source artifacts、Backend 生成的 updated Event IDs
  以及当前 Event/Base Analysis/Claim/Timeline/Conflict/脱敏 Evidence。模型返回后锁定并重建输入；变化
  以 `ASK_FINALIZATION_INPUT_CHANGED` 终态失败。
- 模型只能返回 answer 与当前候选范围内的引用 ID；Backend 校验 Event 顺序、ID 唯一性和引用归属。
  Final Answer 不修改事实层，也不是 Evidence。私密 Evidence 仍只能是脱敏正文与 null provenance。
- direct 或 researched 成功都必须先原子创建 final artifact，再将 Ask 置为 completed。Public GET 只从
  final artifact 构造结果；内部 stage、source、prompt、模型元数据及内部错误码不进入 DTO。
- `POST /api/v1/ask` 要求 ready user、1–8 个唯一 Event 与 1–2,000 字符 trimmed question，只持久化
  `pending/comparing` 并返回 202。`GET /api/v1/ask/{ask_id}` owner-only，使用严格 status 联合 DTO；
  failed 只暴露 `ASK_FAILED` 通用错误。Ask 全流程由独立 Worker 根据数据库 stage 驱动，FastAPI 不执行
  模型任务，Frontend 使用 Polling，不使用 WebSocket。

---

## 8.6 Event Backwrite / Event 回写

Event Backwrite：

> 从当前用户可见的已有 Event 出发，周期性重新检查是否出现了新变化、遗漏或需要修正的信息。

普通采集：

```text
New Information → Event
```

Event Backwrite：

```text
Existing Event → Research / New Information → Event Update
```

### 回写对象与“最新 / 最旧”定义

Backwrite 不再自行选择某个数据库时间字段判断“最新 / 最旧”。

唯一依据是：

> **本轮开始时，当前用户展示的 Event 集合所形成的按时间排列列表。**

即：

```text
Current User-visible Events
↓
Current Time-ordered Event List
↓
Backwrite Snapshot
↓
Frozen Backwrite Queue
```

在该时间排列列表中：

- 列表最前端 = 本轮“最新”。
- 列表最末端 = 本轮“最旧”。
- Backwrite 不额外猜 `created_at`、`updated_at` 或其他时间字段。
- 具体由哪个数据库字段生成“用户展示的按时间排列列表”，必须由后续正式 Event / NOW Contract 明确；Backwrite 只消费该既定排列结果。

### 回写顺序

对 Snapshot 使用两端向中间交替：

```text
Newest
Oldest
Second Newest
Second Oldest
Third Newest
Third Oldest
...
Middle
```

例如：

```text
A B C D E F G
↑           ↑
新          旧
```

本轮：

```text
A
G
B
F
C
E
D
```

### Snapshot / Queue 冻结规则

回写开始后，本轮 Snapshot 与 Queue 固定。

如果某个 Event 更新后导致用户展示列表发生变化：

```text
Old User-visible Event List
↓
Event Updated
↓
Personalization / Event List Recomputed
↓
New User-visible Event List
```

Frontend 展示新的 Event 列表。

但是当前 Backwrite Cycle 继续按照本轮最初冻结的 Queue 更新，顺序不变。

禁止：

- 根据更新后的 Event 列表重新计算本轮剩余顺序。
- 已处理 Event 因重新排序而被本轮重复处理。
- 未处理 Event 因列表变化被本轮遗漏。

### 单 Event 回写链

```text
Event
↓
Research / Check New Information
↓
Raw
↓
Normalize
↓
Signal
↓
Deduplicate
↓
Reconcile With Existing Event
↓
Claims / Timeline / Conflicts Update
↓
Base Analysis Update if needed
↓
Personalization
↓
Updated User-visible Event List
```

Event Backwrite 不是：

```text
Event
↓
LLM
↓
直接重写 Event
```

任何新事实仍必须经过 Signal 层。

---

## 8.7 Window Analysis / 时间窗口分析

Window Analysis：

> 周期性对一个固定时间窗口内获取的信息进行归类、分析、补充，并判断它们应该补充已有 Event 还是形成新 Event。

逻辑分析窗口长度正式冻结为：

> **1 小时。**

概念：

```text
Raw Information in 1-hour Window
↓
Normalize
↓
Signals
↓
Window Analysis
├── Deduplicate
├── Classification
├── Event Matching
├── Event Clustering
├── Relationship Analysis
└── Missing Context Detection
↓
Existing Event Supplement / New Event Reconstruction
```

Window Analysis 解决：

> 最近这一小时获取的信息分别属于什么、应该补充哪个已有 Event、是否需要建立新 Event？

它与 Event Backwrite 分工：

```text
Window Analysis:
New Information → Event

Event Backwrite:
Existing Event → New / Missing Information

Ask Reconciliation:
User Question → Database Gap → New Information
```

三者最终统一回到 Signal / Event Reconciliation。

Raw Acquisition 本身不应因为 Window Analysis 尚未执行而停止；窗口分析负责处理已持久化 Raw Information。

---

## 8.8 Backwrite / Window Analysis 调度语义

执行节奏正式冻结为：

> **完整一轮更新流程结束后开始计时，等待 1 小时，再启动下一轮。**

不是固定墙钟：

```text
00:00
01:00
02:00
```

而是 completion-based delay：

```text
Cycle N starts
↓
Window Analysis / Event Backwrite / related update flow
↓
Cycle N finishes
↓
开始 1 小时计时
↓
Cycle N+1 starts
```

因此：

```text
Next Start Time
=
Previous Cycle Finish Time
+
1 hour
```

如果一轮更新本身耗时 20 分钟，则两轮开始时间之间是 1 小时 20 分钟，而不是强制压到整点。

调度要求：

- 当前轮未结束时，不启动下一轮相同维护周期。
- 下一轮计时从当前完整更新流程结束时开始。
- Window Analysis 的逻辑数据窗口长度保持 1 小时。
- Backwrite 使用本轮开始时冻结的当前用户可见时间排序 Event Snapshot。
- Event 更新后可以立即影响用户侧新列表，但不改变本轮 Backwrite Queue。

Window Analysis 的精确窗口边界 / Raw 游标规则应在数据库与 Scheduler 实现时明确，但必须保证已持久化 Raw Information 不因调度耗时而被静默遗漏。

---

# 9. 最终 Pipeline

主采集链：

```text
COLLECT
TrendRadar / TG News
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
Hermes / OpenClaw → Agent-Reach
        ↓
NEW SIGNALS
        ↓
CLAIM EXTRACTION
        ↓
TIMELINE RECONSTRUCTION
        ↓
CONFLICT / RELATIONSHIP ANALYSIS
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
        ├── Event Detail
        ├── BRIEF
        └── ARCHIVE
```

Event 回写链：

```text
Current User-visible Time-ordered Event List
        ↓
Freeze Backwrite Snapshot
        ↓
Newest / Oldest → Toward Middle
        ↓
Research / Reconciliation
        ↓
Updated Event
        ↓
Personalization
        ↓
New User-visible Event List

本轮 Frozen Queue 不随新列表改变
```

Ask 链：

```text
Single / Multiple Event Ask
        ↓
Compare With Event Database
        ↓
Missing Information?
   ├── No  → Answer from existing Event state
   └── Yes → Research → New Signal → Event Reconciliation
                                      ↓
                                Updated Event
                                      ↓
                                    Answer
```

维护调度：

```text
Maintenance Cycle
↓
完整更新流程结束
↓
Wait 1 hour
↓
Next Maintenance Cycle
```

原则：

```text
Cheap Filter
↓
Expensive AI
```

不能对整个数据库逐条带 User Profile 调 LLM。

---

# 10. Worker 与 Modular Monolith

IS 采用：

```text
Process A: FastAPI
Process B: IS Worker
```

共享：

- Config
- Database
- Models
- Schemas
- Services
- Integrations
- Analysis
- Utilities

Worker 是信息生产核心。

负责：

- Scheduler
- TrendRadar
- TG News
- Normalize
- Deduplicate
- 1-hour Window Analysis
- Event Matching / Reconstruction
- Event Backwrite Snapshot / Frozen Queue
- Newest / Oldest → Middle Backwrite traversal
- Completion-based 1-hour maintenance delay
- Research trigger
- Ask reconciliation jobs when needed
- Claim
- Timeline
- Conflict
- Base Analysis
- Personalization
- Persistence

禁止把长期采集循环塞进 FastAPI startup background task。

---

# 11. 技术栈

## Frontend

- React
- TypeScript
- Vite
- TanStack Query
- `pnpm`
- `openapi-typescript`
- `openapi-fetch`

## Backend

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy 2
- Alembic
- 独立 Worker
- `uv`

依赖管理正式冻结：

```text
Frontend → pnpm
Backend  → uv
ORM      → SQLAlchemy 2
```

不得在开发过程中改成 npm / yarn / pip requirements / SQLModel，除非项目发生无法继续实现的阻塞并由两人共同决定修改基线。

## 第一版不采用

- Next.js
- Redis
- Celery
- GraphQL
- WebSocket
- Nginx
- Caddy
- Traefik
- Kubernetes
- Kafka
- 微服务

---

# 12. Docker

Docker 暂时只负责 PostgreSQL。

macOS / Ubuntu：

```text
React / Vite       Native
FastAPI            Native
IS Worker          Native
TrendRadar         Integrated / Native
TG News            Native Module
Hermes/OpenClaw    Native
PostgreSQL         Docker
```

原因：

Agent / Telegram / TrendRadar 可能涉及：

- Host filesystem
- CLI
- 本地进程
- 用户配置
- 网络权限
- 浏览器 / 其他工具链

黑客松不为“容器化完整性”增加额外复杂度。

---

# 13. Monorepo

采用 GitHub Monorepo。

逻辑上包含：

```text
repository
├── frontend
├── backend
├── contracts
├── scripts
├── docs
├── .github
├── compose
└── root project files
```

这里只表示逻辑组织。

真正操作仓库前必须读取实际目录，不能据此猜现有路径或擅自重命名。

---

# 14. Backend 分层

```text
API / Route
↓
Service
↓
Repository / Integration
↓
Database / External System
```

Route 只负责：

- HTTP
- Validation
- Auth
- Service call
- Response serialization

Route 禁止直接：

- 抓 Telegram
- 跑 TrendRadar
- 调 Agent
- 调 LLM
- Deduplicate
- Event clustering
- Ranking
- 写复杂 SQL

---

# 15. Adapter 层

所有外部系统必须通过 Adapter / Integration。

至少需要逻辑上的：

- TrendRadar Integration
- Telegram Integration
- Research Adapter
- Analysis Adapter

上层业务不得依赖外部系统私有调用方式。

---

# 16. API Communication Contract — FINAL FREEZE

本节从本版本开始是 **Frontend ↔ Backend 的固定通信 Contract**。

开发期间不得由任何一方自行：

- 改 endpoint
- 改 JSON key
- 改 enum ID
- 改 HTTP method
- 改状态语义
- 新造近似字段

如果实现中发现 Contract 无法执行，必须先停止相关实现并由两人共同确认；禁止为了“先跑起来”在前后端各写一套兼容字段。

---

## 16.1 基础通信

API Prefix 固定：

```text
/api/v1
```

通信：

```text
HTTP
+
REST
+
JSON
```

开发环境：

```text
Browser
↓
Vite Dev Server
↓
relative /api/v1/*
↓
Vite proxy
↓
FastAPI
```

最终 Demo：

```text
Browser
↓
FastAPI same-origin
├── /api/v1/*
└── React production build
```

Frontend **只使用相对路径** `/api/v1/...`。

禁止在 React 中硬编码：

```text
http://127.0.0.1:xxxx
http://localhost:xxxx
```

JSON：

- Request / Response 使用 `application/json`。
- JSON key 统一 `snake_case`。
- 时间统一 UTC ISO 8601，例如 `2026-08-15T13:00:00Z`。
- ID 对 Frontend 一律是 opaque string；Frontend 不解析 ID 格式。
- 列表字段无内容时返回 `[]`，不返回 `null`。
- 可选单值不存在时使用 `null`。
- Frontend 不对 Backend Response 做 snake_case ↔ camelCase 转换。

---

## 16.2 OpenAPI 与 TypeScript

唯一 Contract 来源：

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

规则：

1. Backend Schema 是 API 数据结构唯一事实来源。
2. OpenAPI 必须由 FastAPI 生成。
3. Generated TypeScript Types 必须进入 Git。
4. Frontend API Client 使用 `openapi-fetch`。
5. TanStack Query 负责 Server State。
6. Frontend 不手写重复的 API entity interface。
7. Contract 变动在本次 Freeze 后禁止常规发生。

---

## 16.3 Authentication

认证方式固定为：

> **Server-side session + HttpOnly Cookie**

Cookie 名固定：

```text
is_session
```

规则：

- Register / Login 成功后由 FastAPI 设置 `is_session`。
- Cookie 使用 `HttpOnly`。
- `SameSite=Lax`。
- `Path=/`。
- Frontend 不读取 Cookie。
- Frontend 不保存 Bearer Token。
- 禁止把认证 Token 放入 `localStorage` / `sessionStorage`。
- HTTPS 环境使用 `Secure`；localhost HTTP Demo 不强制 `Secure`。
- Session 有效期属于 Backend 配置，不作为 Frontend Contract。

### Protected Endpoint 规则

无需已登录 Session 的 endpoint 只有：

```text
GET  /api/v1/session
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/health
```

`POST /api/v1/auth/logout` 允许在已登录状态下调用。

其余 endpoint 均要求有效 `is_session`。

缺少或 Session 无效：

```text
401 Unauthorized
error.code = AUTH_REQUIRED
```

用户已登录但尚未完成 Onboarding 时：

- 允许访问 `/api/v1/onboarding`。
- 不允许访问 NOW / Event / Brief / Archive / Ask 等正式产品数据。

返回：

```text
403 Forbidden
error.code = ONBOARDING_REQUIRED
```

### Session State

固定枚举：

```text
anonymous
onboarding_required
ready
```

### GET `/api/v1/session`

始终返回 `200 OK`。

Anonymous：

```json
{
  "state": "anonymous",
  "user": null
}
```

Authenticated：

```json
{
  "state": "onboarding_required",
  "user": {
    "username": "alan"
  }
}
```

或：

```json
{
  "state": "ready",
  "user": {
    "username": "alan"
  }
}
```

### POST `/api/v1/auth/register`

Request：

```json
{
  "username": "alan",
  "password": "..."
}
```

成功：

```text
201 Created
Set-Cookie: is_session=...
```

Response 使用 Session Response。

用户名已存在：

```text
409 Conflict
error.code = USERNAME_TAKEN
```

### POST `/api/v1/auth/login`

Request：

```json
{
  "username": "alan",
  "password": "..."
}
```

成功：

```text
200 OK
Set-Cookie: is_session=...
```

失败：

```text
401 Unauthorized
error.code = INVALID_CREDENTIALS
```

### POST `/api/v1/auth/logout`

成功：

```text
204 No Content
```

并使当前 `is_session` 失效。

---

## 16.4 Onboarding Contract

### 固定 Enum

`scope_ids`：

```text
ai
open_source
technology
science
investment
```

`investment_market_ids`：

```text
china_market
us_stock
crypto_market
```

`focus_ids`：

```text
technical_details
research_progress
major_changes
breaking_events
niche_trends
industry_changes
controversy_changes
deep_context
```

### GET `/api/v1/onboarding`

成功 `200 OK`：

```json
{
  "completed": false,
  "scope_options": [
    {"id": "ai", "label": "AI"},
    {"id": "open_source", "label": "开源社区"},
    {"id": "technology", "label": "技术"},
    {"id": "science", "label": "科学"},
    {"id": "investment", "label": "投资"}
  ],
  "investment_market_options": [
    {"id": "china_market", "label": "中国市场"},
    {"id": "us_stock", "label": "美股"},
    {"id": "crypto_market", "label": "加密市场"}
  ],
  "focus_options": [
    {"id": "technical_details", "label": "技术细节"},
    {"id": "research_progress", "label": "研究进展"},
    {"id": "major_changes", "label": "重要变化"},
    {"id": "breaking_events", "label": "突发事件"},
    {"id": "niche_trends", "label": "小众趋势"},
    {"id": "industry_changes", "label": "行业变化"},
    {"id": "controversy_changes", "label": "争议变化"},
    {"id": "deep_context", "label": "深度背景"}
  ],
  "answers": {
    "scope_ids": [],
    "investment_market_ids": [],
    "focus_ids": []
  }
}
```

Frontend 必须使用 Response 中的 option `id` 与 `label`，不得自行创建另一套 ID。

### PUT `/api/v1/onboarding`

Request：

```json
{
  "scope_ids": ["ai", "investment"],
  "investment_market_ids": ["us_stock", "crypto_market"],
  "focus_ids": ["technical_details", "research_progress"]
}
```

Validation：

- `scope_ids` 至少 1 项且不得重复。
- `focus_ids` 至少 1 项且不得重复。
- 如果 `scope_ids` 包含 `investment`：
  - `investment_market_ids` 至少 1 项。
- 如果 `scope_ids` 不包含 `investment`：
  - `investment_market_ids` 必须为 `[]`。
- 所有 ID 必须来自冻结 Enum。

成功 `200 OK`：返回与 GET `/api/v1/onboarding` 相同结构，其中：

```json
{
  "completed": true
}
```

成功后 Session State 为 `ready`。

非法组合：

```text
422 Unprocessable Content
error.code = INVALID_ONBOARDING_SELECTION
```

---

## 16.5 SCOPE Page Contract

Onboarding 完成后，长期 SCOPE 页面使用：

### GET `/api/v1/scope`

返回结构与 GET `/api/v1/onboarding` 一致，`completed` 必须为 `true`。

### PUT `/api/v1/scope`

Request 与 PUT `/api/v1/onboarding` 完全一致。

成功：

- 保存新的 SCOPE / 投资市场 / FOCUS。
- 触发 Personalization 更新任务。
- 返回最新 SCOPE Response。
- 不修改 Event 事实层。

---

## 16.6 NOW Contract

### GET `/api/v1/now`

Query：

```text
limit
cursor
```

规则：

- `limit` 默认 `20`。
- `limit` 最大 `100`。
- `cursor` 是 Backend 生成的 opaque string。
- Frontend 不解析 cursor。

Response：

```json
{
  "window_stats": {
    "window_started_at": "2026-08-15T12:00:00Z",
    "window_ended_at": "2026-08-15T13:00:00Z",
    "raw_information_count": 2314,
    "event_count": 63,
    "relevant_event_count": 4
  },
  "items": [
    {
      "id": "opaque-event-id",
      "title": "事件标题",
      "overview": "一句话说明发生了什么。",
      "state": "developing",
      "display_time": "2026-08-15T12:58:00Z",
      "updated_at": "2026-08-15T13:01:00Z",
      "why_it_matters": "为什么值得这个用户关注。",
      "new_claim_count": 3,
      "conflict_count": 1,
      "topics": ["AI"],
      "saved": false
    }
  ],
  "next_cursor": null
}
```

Event State 固定枚举：

```text
developing
confirmed
conflicting
cooling
```

NOW 规则：

- Personalization 决定 Event 是否进入当前用户可见集合。
- Backend 最终按照 `display_time DESC` 返回用户可见 Event。
- Frontend 不二次排序。
- Event Backwrite 直接消费本轮开始时这套用户可见时间排列结果生成 Snapshot。
- Backwrite 本轮开始后，即使新的 NOW Response 顺序改变，本轮 Frozen Queue 仍保持原顺序。

`display_time` 是 Public Contract 中的用户展示时间锚点；其 Backend 内部推导方式不属于 Frontend Contract。

---

## 16.7 Event Detail Contract

### GET `/api/v1/events/{event_id}`

Response：

```json
{
  "id": "opaque-event-id",
  "title": "事件标题",
  "overview": "当前能确认发生了什么。",
  "state": "developing",
  "display_time": "2026-08-15T12:58:00Z",
  "updated_at": "2026-08-15T13:01:00Z",
  "why_it_matters": "个性化解释。",
  "topics": ["AI"],
  "saved": false,
  "claims": [
    {
      "id": "opaque-claim-id",
      "text": "事实命题",
      "state": "confirmed",
      "evidence_ids": ["opaque-evidence-id"]
    }
  ],
  "timeline": [
    {
      "id": "opaque-timeline-id",
      "occurred_at": "2026-08-15T12:30:00Z",
      "summary": "关键变化",
      "claim_ids": ["opaque-claim-id"]
    }
  ],
  "conflicts": [
    {
      "id": "opaque-conflict-id",
      "claim_ids": ["opaque-claim-id-a", "opaque-claim-id-b"],
      "summary": "冲突原因",
      "evidence_ids": ["opaque-evidence-id"]
    }
  ],
  "evidence": [
    {
      "id": "opaque-evidence-id",
      "platform": "telegram",
      "visibility": "private_sanitized",
      "author_name": null,
      "url": null,
      "published_at": "2026-08-15T12:20:00Z",
      "excerpt": "经过脱敏处理的原文证据。"
    }
  ]
}
```

Claim State 固定枚举：

```text
confirmed
unresolved
conflicting
contradicted
```

Evidence Platform 固定枚举：

```text
telegram
x
youtube
web
rss
```

Evidence Visibility 固定枚举：

```text
private_sanitized
public
```

Privacy：

- `private_sanitized` 的私密 Telegram 不得返回群名、群 username、invite link、internal ID。
- 私密 Telegram 的 `author_name` 与 `url` 必须为 `null`。
- `public` Evidence 可以返回公开作者与公开 URL。

---

## 16.8 Save / Archive / Search

### PUT `/api/v1/events/{event_id}/saved`

Request：

```json
{
  "saved": true
}
```

Response：

```json
{
  "event_id": "opaque-event-id",
  "saved": true
}
```

### GET `/api/v1/archive`

Query：

```text
limit
cursor
```

Response：

- `items` 使用与 NOW 相同的 Event Summary 结构。
- `next_cursor` 使用 opaque cursor。

### GET `/api/v1/search/events`

Query：

```text
q
limit
cursor
```

Response：

- `items` 使用 Event Summary 结构。
- `next_cursor` 使用 opaque cursor。

Search 只负责找到 Event，不替代 Ask Infoscope。

---

## 16.9 BRIEF Contract

### GET `/api/v1/brief/latest`

Response：

```json
{
  "generated_at": "2026-08-15T13:05:00Z",
  "items": [
    {
      "event_id": "opaque-event-id",
      "title": "事件标题",
      "summary": "Brief 内容",
      "why_it_matters": "为什么值得当前用户关注。"
    }
  ]
}
```

Brief 只能基于已经持久化的 Event 事实层生成，不建立独立事实。

---

## 16.10 Ask Infoscope Contract

单 Event 与多 Event 共用一个 endpoint。

### POST `/api/v1/ask`

Request：

```json
{
  "event_ids": [
    "opaque-event-id"
  ],
  "question": "这个事件目前最大的疑点是什么？"
}
```

多 Event：

```json
{
  "event_ids": [
    "opaque-event-id-a",
    "opaque-event-id-b"
  ],
  "question": "这两个事件之间有什么联系？"
}
```

Validation：

- `event_ids` 至少 1 项。
- ID 不得重复。
- `question` 去除首尾空白后不得为空。

Ask 可能触发 Research，因此统一异步。

成功：

```text
202 Accepted
```

Response：

```json
{
  "ask_id": "opaque-ask-id",
  "status": "pending"
}
```

### GET `/api/v1/ask/{ask_id}`

Status 固定枚举：

```text
pending
running
completed
failed
```

Pending / Running：

```json
{
  "ask_id": "opaque-ask-id",
  "status": "running",
  "result": null,
  "error": null
}
```

Completed：

```json
{
  "ask_id": "opaque-ask-id",
  "status": "completed",
  "result": {
    "answer": "结构化回答正文。",
    "event_ids": ["opaque-event-id"],
    "claim_ids": ["opaque-claim-id"],
    "timeline_ids": ["opaque-timeline-id"],
    "conflict_ids": [],
    "evidence_ids": ["opaque-evidence-id"],
    "updated_event_ids": ["opaque-event-id"]
  },
  "error": null
}
```

Failed：

```json
{
  "ask_id": "opaque-ask-id",
  "status": "failed",
  "result": null,
  "error": {
    "code": "ASK_FAILED",
    "message": "Ask processing failed.",
    "request_id": "opaque-request-id"
  }
}
```

Frontend 通过 `updated_event_ids` 判断是否显示：

> 事件信息已补充

然后 refetch 对应 Event / NOW。

硬规则：

```text
AI Answer ≠ Evidence
```

---

## 16.11 Maintenance Contract

### GET `/api/v1/maintenance/status`

Response：

```json
{
  "status": "idle",
  "phase": null,
  "cycle_started_at": null,
  "cycle_finished_at": "2026-08-15T13:00:00Z",
  "next_cycle_at": "2026-08-15T14:00:00Z"
}
```

Maintenance Status：

```text
idle
running
failed
```

Phase：

```text
window_analysis
event_backwrite
reconciliation
personalization
```

或 `null`。

`next_cycle_at` 只能由 Backend 根据：

```text
Previous Cycle Finish Time + 1 hour
```

计算。

Frontend 禁止自己按整点推算。

### POST `/api/v1/maintenance/runs`

用于 Demo / 手动触发完整维护流程。

空 Request Body。

成功：

```text
202 Accepted
```

```json
{
  "run_id": "opaque-run-id",
  "status": "pending"
}
```

如果已有完整维护流程正在运行：

```text
409 Conflict
error.code = MAINTENANCE_ALREADY_RUNNING
```

### GET `/api/v1/maintenance/runs/{run_id}`

Response：

```json
{
  "run_id": "opaque-run-id",
  "status": "running",
  "phase": "event_backwrite",
  "started_at": "2026-08-15T13:10:00Z",
  "finished_at": null
}
```

Run Status：

```text
pending
running
completed
failed
```

Frontend 使用 Polling。

第一版不使用 WebSocket。

---

## 16.12 Health

### GET `/api/v1/health`

成功：

```json
{
  "status": "ok",
  "api": "ok",
  "database": "ok",
  "worker": "ok"
}
```

不得返回：

- Telegram 群信息
- Source URL
- Agent config
- Secret
- Credential

---

## 16.13 Error Schema

所有非 2xx API 错误统一：

```json
{
  "error": {
    "code": "STABLE_ERROR_CODE",
    "message": "Human-readable message.",
    "request_id": "opaque-request-id"
  }
}
```

Frontend：

- 逻辑判断使用 `error.code`。
- `message` 只用于展示。
- 不通过字符串匹配 `message` 决定业务逻辑。

主要 HTTP Status：

```text
200 OK
201 Created
202 Accepted
204 No Content
400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
409 Conflict
422 Unprocessable Content
429 Too Many Requests
500 Internal Server Error
```

---

## 16.14 Contract Freeze

从本版本开始以下内容视为黑客松正式开发 Contract：

- `/api/v1` Prefix
- Endpoint 路径
- HTTP Method
- JSON key
- Enum ID
- Onboarding 选项 / 条件分支
- Auth Session 方式
- Error Schema
- Cursor Pagination
- Ask Polling
- Maintenance Polling
- NOW Event 排序责任
- 来源隐私 Public DTO 边界

开发期间禁止自行修改。

如果发现实现阻塞：

1. 不在 Frontend 添加兼容字段。
2. 不在 Backend 偷换字段。
3. 不创建 `/v2` 临时旁路。
4. 记录阻塞点。
5. 两人共同决定是否中止 Freeze。

在没有共同决定前，Contract 保持本文档定义。

---

# 20. 持久化边界

不能等 Base Analysis 完成后才第一次入库。

至少按逻辑阶段：

```text
Raw
↓ persist

Signal
↓ persist

Event Reconstruction
↓ persist

Analysis
↓ persist

Personalized Result
↓ persist
```

目标：

- 失败可恢复
- AI 可重试
- Pipeline 可重放
- Debug 可定位

---

# 21. Public Source Boundary

采用：

```text
Internal Full Provenance
↓
Visibility Policy
↓
Public Sanitization
↓
Response DTO
↓
Frontend
```

私密 TG：

- Frontend 只能收到允许的脱敏信息。

公开 X / YouTube / Web：

- 可以收到公开作者与链接。

隐私逻辑必须发生在 Backend，不由 Frontend 根据字符串自行判断。

---

# 22. 日志与 Secret

允许日志：

- request identifier
- endpoint
- status
- duration
- internal Event / Signal id
- job id
- error code

禁止随意记录：

- Password
- Cookie
- Token
- Telegram credential
- LLM API key
- Agent credential
- 私密群名
- invite link
- 完整敏感 payload

Git 只提交安全的环境变量示例，不提交真实 secret。

Secret 一旦进入 Git history：

- 删除文件不够
- 必须 rotate / revoke

---

# 23. 跨平台规范

Alan：macOS  
Lingjiu：Ubuntu 26.04 LTS

必须：

- 不硬编码个人绝对路径
- 使用 project-relative path / environment / config
- 文件名大小写逐字符一致
- Git 统一 LF
- 平台特有逻辑必须明确分支处理

禁止正式业务代码写死：

```text
/Users/alan/...
/home/lingjiu/...
```

---

# 24. 分工

## Alan — Backend / Architecture / Intelligence

主责：

- 总体架构
- FastAPI
- PostgreSQL
- Migration
- Worker
- TrendRadar Integration
- TG News Integration
- Telegram API 模块
- Research Adapter
- Hermes / OpenClaw / Agent-Reach
- Analysis Adapter
- Normalize
- Deduplicate
- Event Reconstruction
- Claim Extraction
- Timeline
- Conflict / Relationship Analysis
- Base Analysis
- Personalization
- Source Privacy Boundary
- OpenAPI Contract 主导
- Backend tests
- macOS Demo integration
- Startup reliability

## Lingjiu — Frontend

主责：

- React + TypeScript + Vite
- App Shell
- Register / Login
- Onboarding
- NOW
- Event Detail
- BRIEF
- ARCHIVE
- SCOPE
- SETTINGS
- Search
- Context Panel
- Generated API Client
- Loading / Error / Empty
- Frontend lint / typecheck / build
- Frontend tests
- Responsive
- `style.md` 落地

## 两人共同

必须共同确认：

- API Contract
- Database Schema
- Signal / Event Schema
- Onboarding Contract
- Source visibility policy
- AI output schema
- Event / Claim state semantics

---

# 25. 前后端协作与 Contract Ownership — FINAL

开发主线：

```text
plan.md / style.md / tech.md
↓
Backend FastAPI Schema
↓
OpenAPI
↓
Generated TypeScript Types
↓
Frontend API Client
↓
React UI
```

职责：

- Alan 主导 Backend Schema 与 API 实现。
- Lingjiu 只按 OpenAPI / Generated Types 接 Frontend。
- 前端需要新数据时，不自行创造字段；先确认现有 Contract 是否已有。
- 后端不能因为实现方便改变 Public DTO。
- DB Model 与 Public API Schema 严格分离。

本版本之后，Onboarding 与 API Contract 进入 Freeze。

---

# 26. Git Principles — FINAL FREEZE

Git 协作规则从本版本开始固定，黑客松开发期间不再更换 Git Flow。

## 26.1 唯一长期 Branch

```text
main
```

禁止长期存在：

```text
develop
alan-dev
lingjiu-dev
```

`main` 必须始终能够：

- 安装依赖
- 启动
- 通过基础检查
- 用于 Demo

## 26.2 Task Branch

只允许短生命周期任务 Branch：

```text
feat/*
fix/*
refactor/*
chore/*
docs/*
test/*
```

命名格式：

```text
<type>/<area>-<task>
```

例如：

```text
feat/frontend-onboarding
feat/api-now
feat/worker-backwrite
fix/frontend-event-refresh
```

一个 Branch 只解决一个主要任务。

## 26.3 开始任务

固定流程：

```bash
git switch main
git pull --ff-only
git switch -c <task-branch>
```

禁止从过期 Feature Branch 再切新的 Feature Branch。

## 26.4 Commit

固定格式：

```text
type(scope): description
```

允许 type：

```text
feat
fix
refactor
chore
docs
test
```

推荐 scope：

```text
frontend
api
worker
db
integration
analysis
contract
infra
```

规则：

- 一个 commit = 一个可以明确描述的逻辑变化。
- 禁止 `update` / `final` / `test2` / `修好了` 一类无意义信息。
- Secret 永远不能 Commit。

## 26.5 合并前同步 main

Feature Branch 完成后：

```bash
git fetch origin
git rebase origin/main
```

解决冲突后运行对应检查。

如果 Rebase 的 Branch 已经 Push：

```bash
git push --force-with-lease
```

只允许对**自己正在负责的 Feature Branch**使用。

永久禁止：

```bash
git push --force origin main
```

## 26.6 Pull Request

所有代码通过 PR 进入 `main`。

PR 至少包含：

```text
What
Why
Test
Screenshot（涉及 UI）
```

涉及 API 的 PR 必须同时确认：

```text
FastAPI Schema
OpenAPI
Generated TypeScript Types
Frontend Typecheck
```

涉及 UI 的 PR 必须检查：

```text
Loading
Error
Empty
Success
```

## 26.7 Review

默认由另一名队员 Review。

Review 重点：

- 是否违反 Contract
- 是否泄露 Source / Secret
- 是否引入重复类型
- 是否擅自改依赖管理方式
- 是否影响另一人的模块
- 是否 Build / Test 通过

## 26.8 Merge

固定使用：

> **Squash Merge**

Merge 后：

```text
删除远端 Feature Branch
↓
本地切 main
↓
git pull --ff-only
↓
开始下一任务
```

不使用 Merge Commit 作为默认合并方式。

## 26.9 API Contract Freeze

`plan.md` 第 16 节 API Contract 在本版本后冻结。

禁止 Feature PR：

- 自行新增近似字段
- 修改 enum ID
- 改 endpoint
- 改 HTTP method
- 修改 Onboarding ID
- 以“兼容”为名同时保留两套字段

如果确有实现阻塞，必须在写代码前由两人明确讨论；未达成共同决定前仍按冻结 Contract 开发。

## 26.10 Database Migration

任何 DB Schema 修改：

```text
Model Change
↓
New Alembic Migration
↓
Test
↓
Commit
```

已经 Merge 到 `main` 的 Migration：

> 不修改。

后续变化：

> 新建 Migration。

准备创建 Migration 前，Backend 负责人应通知另一人，避免同时产生分叉 Migration Head。

## 26.11 Generated Contract Files

OpenAPI 与 Generated TypeScript Types 属于代码的一部分。

规则：

- 必须进入 Git。
- 不能只在某个人电脑上生成。
- Backend Schema 更新时必须同一个 PR 更新 Generated Types。
- Frontend 不手工编辑 Generated Types。

## 26.12 Conflict Ownership

谁的 Branch，谁主要负责解决 Conflict。

如果冲突涉及另一人刚完成的模块：

- 先读取最新 `main`
- 不猜对方意图
- 必要时直接确认

禁止第一反应使用：

```bash
git reset --hard
```

Rebase 出错时优先：

```bash
git rebase --abort
```

---

# 27. Codex / AI Coding Rules — FINAL

每次 Codex 工作前必须：

1. 确认当前 branch。
2. 读取实际目录。
3. 读取相关代码。
4. 读取 `plan.md`、相关 OpenAPI Schema 与 Generated Types。
5. 涉及 Frontend 样式时读取 `style.md`。
6. 不猜路径。
7. 不猜字段。
8. 不猜配置。
9. 不猜依赖版本。
10. 不自行新增 API 字段。
11. 不自行修改 DB Schema。
12. 不更换 `pnpm` / `uv` / SQLAlchemy 2。
13. 不创建近似字段名。
14. 修改完成后检查 `git diff`。

如果文档与实际代码冲突：

> 停止猜测，以实际冻结 Contract 与当前 `main` 为依据定位问题。

---

# 28. CI / Test


Frontend：

- lint
- typecheck
- build

Backend：

- lint
- test

Contract：

- OpenAPI / generated types consistency

测试重点：

- Normalize
- Source sanitization
- Deduplicate
- Event reconstruction
- Claim schema
- Conflict relation
- Auth / Session
- Onboarding
- NOW query 与 Raw / Event 真实统计口径
- Ask 单 Event / 多 Event 的 Database comparison
- Ask Research → New Signal → Event Reconciliation
- Event Backwrite Snapshot 稳定性
- 当前用户可见时间排序列表 → Newest / Oldest → Middle 的回写顺序
- Event 列表更新后本轮 Frozen Queue 顺序保持不变
- 完整更新流程结束后 1 小时再启动下一轮
- 1 小时 Window Analysis
- Pipeline jobs
- API Schema

核心 E2E：

```text
Register
↓
SCOPE
↓
[if investment] 投资市场
↓
FOCUS
↓
NOW
↓
Event Detail
↓
询问观澜
↓
必要时补充 Event
```

AI 测试不验证逐字输出。

验证：

- Schema
- Required fields
- Types
- Invalid output handling
- Timeout
- Retry
- Failure isolation

---

# 29. Definition of Done

任务完成必须：

```text
代码完成
+
能运行
+
lint / typecheck 通过
+
相关 test 通过
+
无 secret
+
无来源隐私泄漏
+
API Contract 同步
+
PR Merge
```

Frontend 还必须有：

- Loading
- Error
- Empty
- Success

---

# 30. MVP

采集：

1. TrendRadar-derived 固定 Web / RSS / Hotlist
2. TG News 固定 Telegram 群组
3. Agent-Reach 用于 Event Research / Enrichment

核心：

1. Raw persistence
2. Normalize
3. Signal
4. Deduplicate
5. 1-hour Window Analysis
6. Event Reconstruction
7. Claim Extraction
8. Timeline
9. Conflict / Evidence Relationship
10. Base Analysis
11. SCOPE / FOCUS
12. Personalization
13. NOW + 真实 Raw / Event 统计
14. Event Detail
15. Ask Infoscope（单 Event / 多 Event）
16. Ask Database comparison / 缺失信息补充
17. Event Backwrite
18. Completion-based 1-hour maintenance scheduler
19. Source sanitization

时间充足再做：

- Claim Graph
- 更复杂 Brief
- 更多 Source
- 通知
- Native App

---

# 31. Demo Story

不要 Demo：

- 支持 RSS
- 支持 Telegram
- AI 会摘要

应该 Demo：

```text
Raw Information
↓
Signals
↓
Deduplicate
↓
Events
↓
Claims / Timeline / Conflicts
↓
SCOPE
↓
NOW
```

打开 Event：

```text
Overview
↓
Timeline
↓
Claims
↓
Conflict
↓
Evidence
↓
Why it matters
```

核心：

> We don't give you more information.  
> We reconstruct what happened.

---

# 32. 开发阶段

## Phase 1 — Skeleton

- Monorepo
- React/Vite
- FastAPI
- PostgreSQL
- OpenAPI generation
- Health
- 前后端打通

## Phase 2 — User Loop

Frontend：

- Register / Login
- SCOPE
- FOCUS
- NOW shell

Backend：

- Local Auth
- Session
- User
- Onboarding / Scope
- Event API skeleton

目标：

```text
Register
↓
Onboarding
↓
Empty NOW
```

## Phase 3 — Acquisition

- TrendRadar
- TG News
- Raw persistence
- Normalize
- Signal
- Deduplicate
- 1-hour Window Analysis

## Phase 4 — Event Intelligence

- Event reconstruction
- Claim
- Timeline
- Conflict
- Base Analysis
- Research Adapter
- Ask Infoscope Database reconciliation
- Single / Multiple Event Ask
- Event Backwrite
- Frozen Backwrite Snapshot / Queue
- Completion-based 1-hour maintenance scheduling

## Phase 5 — Personalization

- Scope Prefilter
- Focus matching
- Personalization
- NOW ranking
- Why it matters
- Brief

## Phase 6 — Demo Freeze

只做：

- Bug fix
- UI polish
- Privacy audit
- Error handling
- Startup reliability
- Demo data
- Performance

禁止最后阶段：

- 换数据库
- 换 ORM
- 换 React framework
- 引入 Redis
- 引入 WebSocket
- 微服务化
- 大规模架构重构
- 更换 package manager

---

# 33. 最终本地部署

目标：

macOS localhost。

开发：

```text
Browser
↓
Vite Dev Server
↓
API Proxy
↓
FastAPI

FastAPI / Worker
↓
PostgreSQL in Docker
```

Demo：

```text
React production build
↓
FastAPI 同源提供 UI / API
+
Native Worker
+
Docker PostgreSQL
```

默认绑定 localhost。

不需要：

- 公网域名
- TLS certificate
- Reverse Proxy
- Nginx
- Caddy

---

# 34. 前端视觉总则

详细见 `style.md`。

总体：

```text
Editorial Intelligence
+
Swiss Information Design
+
Native Productivity UI
+
Restrained Glass
```

关键词：

- Calm
- Precise
- Editorial
- Event-first
- Evidence-aware
- Information-dense
- Monochrome
- Strong hierarchy
- Strict grid
- Typography as interface

避免：

- Generic SaaS Dashboard
- Bento everywhere
- Everything-is-a-card
- AI 紫蓝渐变
- 全局 Glassmorphism
- 大量圆角
- 彩色 Badge
- 图标泛滥
- Gamification
- 过度动画

Glass 只用于：

- Login overlay
- Modal
- Command palette
- Context panel
- Temporary state layer

---

# 35. 最高优先级红线

1. **Event-first**：Event 是用户一级实体，Signal 是 Evidence / Observation。
2. **Contract-first**：Frontend 不猜字段。
3. **Source Privacy**：私密 TG 只显示允许的脱敏 provenance。
4. **Source Policy 非 AI 决策**：AI 不能自主决定来源是否可公开。
5. **Adapter-first**：所有外部系统必须经过 Adapter / Integration。
6. **Research 回流 Signal**：Agent 结果不能绕过 Signal 直接写最终 Event。
7. **NOW 不现场跑重型 AI**：Worker 尽量预处理。
8. **main 可运行**。
9. **不硬编码个人路径**。
10. **不擅自改 Contract / Schema / Dependency**。
11. **Ask Answer ≠ Evidence**：模型回答不能直接成为事实。
12. **Event 持续维护**：Ask、Window Analysis、Backwrite 都必须回流 Signal / Event Reconciliation。
13. **Backwrite Queue 冻结**：本轮开始后不因用户 Event 列表更新而改变处理顺序。
14. **Backwrite 新旧依据冻结**：只使用本轮开始时当前用户可见 Event 的时间排列结果，不在 Backwrite 中另猜时间字段。
15. **维护周期固定**：完整更新流程结束后开始计时，1 小时后再启动下一轮。
16. **Window 固定 1 小时**：Window Analysis 的逻辑分析窗口长度为 1 小时。
17. **NOW 统计真实**：信息数量使用 Raw Information 实际计数，禁止用 Signal 数替代或写假数字。

---

# 36. 实现期未冻结内容

以下不是冲突，而是下一阶段要基于真实代码 / 环境确定：

- Analysis Model API 供应商与模型
- Analysis Adapter SDK
- TG News 当前源码输入输出
- 精确 Database ER Model
- 最终字体
- 最终 Accent Color
- 精确 Design Token 数值
- Window Analysis 的精确窗口边界 / Raw 游标与补偿实现
- Ask Research 的同步 / 异步执行边界

已冻结、不再列为未决：

- Onboarding SCOPE / 投资二级页 / FOCUS 的选项、ID、条件分支与固定文案。
- API `/api/v1` Prefix、endpoint、method、JSON key、enum、Error Schema、Auth Session、Polling 与分页。
- Frontend API communication：relative `/api/v1` + Vite proxy / same-origin production。
- `pnpm` / `uv` / SQLAlchemy 2。
- Git Flow、Branch、Commit、PR、Rebase、Squash Merge 与 Contract Freeze 原则。
- Event Backwrite 的“最新 / 最旧”依据：本轮开始时当前用户可见 Event 的时间排列结果。
- Event Backwrite 顺序：Newest / Oldest 两端交替向中间。
- Backwrite Queue：本轮 Snapshot 后冻结，用户 Event 列表更新不改变本轮剩余顺序。
- Backwrite / Window Analysis 调度：完整更新流程结束后开始计时，1 小时后启动下一轮。
- Window Analysis 逻辑窗口长度：1 小时。
- TrendRadar Phase 3 v1 拆分边界与固定来源：IS 内部 NewsNow / RSS 薄
  Adapter；7 个固定 Hotlist 与 Hacker News RSS；不引入其 AI、SQLite、通知、
  MCP 或 Scheduler。
- Research Integration v1：OpenClaw headless JSON envelope、Agent-Reach capability/doctor
  边界、严格事实快照、专用 Request/Run/Artifact/Source 表、`web_page / github_document`
  来源枚举、直接 HTTPS Fetcher、URL/SSRF/published_at/Raw 幂等与失败语义。

未冻结前：

> 不允许开发者或 Agent 猜精确标识符、路径、字段或配置。

---

# 37. 一句话总结

产品：

```text
External Information
→ Signal
→ Event
→ Claim / Timeline / Conflict
→ Personalization
→ NOW

并持续通过：

1-hour Window Analysis
+
Event Backwrite
+
Ask Reconciliation

补充、校正和维护 Event。
```

工程：

```text
Monorepo
→ Modular Monolith
→ FastAPI + Worker + PostgreSQL
→ OpenAPI
→ React/Vite
→ PR / Squash Merge
```

理念：

> **世界不断产生 Signals，Infoscope 重构 Events，只把此刻真正值得你注意的变化呈现出来。**
