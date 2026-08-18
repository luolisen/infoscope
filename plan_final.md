# Infoscope（观澜）最终产品与合同基线 / plan_final.md

> 版本：0.1 Demo 后续开发基线
> 更新时间：2026-08-19（Asia/Shanghai）
> 适用仓库：`SCOUT-Infoscope/infoscope`
> 用途：供新的 Codex/开发聊天在没有旧对话上下文时直接接管项目。

---

## 0. 文档优先级

本文件继承 `0.7.zip` 中 `plan.md` 的产品总纲职责，并按当前代码更新。

新聊天按以下顺序读取：

1. `plan_final.md`：产品定义、数据合同、边界与红线。
2. `dev_final.md`：当前 Git/PR/Demo 状态、已完成项和下一步。
3. `style_final.md`：最终视觉、文案与交互规则。
4. `tech_final.md`：真实技术架构、目录、命令与运行机制。
5. `contracts/openapi.json`、Alembic migration 和代码：实现层唯一事实。

若旧的 `plan.md`、`dev.md`、`style.md`、`tech.md` 与这四份 `*_final.md` 在当前实现状态上冲突，以 `*_final.md` 为准；API 字段仍以 OpenAPI 和 Backend Schema 为准。

---

# 1. 产品定义

Infoscope（观澜）是一个 Event-first 的个人智能信息界面。

它解决的问题不是“把新闻摘要得更短”，而是：

> 从持续到来的碎片信息中重构 Event，维护可追溯事实层，再根据用户视野呈现此刻真正值得关注的变化。

产品路径：

```text
External Information
→ Raw Information
→ canonical Signal（前端称“因子”）
→ Event
→ Claim / Timeline / Conflict / Base Analysis
→ Personalization
→ NOW / BRIEF / ARCHIVE / ASK
```

核心理念：

> See the event, not the feed.
> 于信息之海，观其波澜。

## 1.1 不是什么

Infoscope 不是：

- 传统新闻 Feed 或 RSS Reader。
- 只显示来源、缩略图和标题的聚合站。
- 把模型回答直接当事实或 Evidence 的聊天机器人。
- 全库 Event 对所有用户可见的检索器。
- 用“可信度百分比”替代 Claim、Conflict 和 Evidence 关系的黑盒。
- Everything-is-a-card 的通用 SaaS Dashboard。

---

# 2. 两个单一事实来源

## 2.1 API Contract

唯一公开通信合同：

```text
FastAPI Pydantic Schema
→ contracts/openapi.json
→ frontend/src/api/schema.ts
→ openapi-fetch
→ TanStack Query
→ React UI
```

规则：

- Frontend 不手写重复的 Backend DTO。
- Generated Types 与 OpenAPI 必须提交 Git。
- Frontend 不解析 opaque cursor、artifact ID 或内部状态。
- Frontend 不自行排序 NOW、Archive、Search 或 Brief。
- API 变更必须先改 Backend Schema、测试与 OpenAPI，再生成 TypeScript。

## 2.2 Information Contract

事实层唯一权威来源是 PostgreSQL 中的结构化实体与 immutable artifacts。

公开页面不得绕过以下边界：

- 当前事实：Event、Claim、Timeline、Conflict、Base Analysis。
- 用户视图：completed Personalization artifact 和 PersonalizedEvent snapshot。
- Brief：与当前最新 completed Personalization artifact 精确绑定的 Brief artifact。
- 历史访问：用户曾在 completed Personalization artifact 中 `relevant=true` 的 Event。
- Localization：独立 `zh-CN` projection；不得改写事实层或旧快照。

---

# 3. 核心信息模型

## 3.1 Raw Information

采集层保存的原始输入记录。Raw 用于审计、标准化与幂等，不直接成为普通 Public DTO。

## 3.2 Signal / 因子

Backend、数据库、OpenAPI 和代码内部继续使用 `signal`；用户可见中文统一称“因子”。

Signal 是规范化后的观察或证据。canonical Signal 进入后续重构；零 canonical Signal 时必须 deterministic no-change，不调用无意义模型流程。

## 3.3 Event

Event 是一级信息实体，包含稳定 ID、标题、概览、状态、展示时间和更新时间。Event 由 Signal 重构，不等于单篇文章。

## 3.4 EventSignal

Event 与 Signal 的事实关联必须记录专用来源字段并受数据库约束。普通 Personalization、Brief 或 Ask Answer 不得伪造成 EventSignal。

## 3.5 Claim

可以独立验证的事实命题。Claim 通过 ClaimSignal 关联其证据。

## 3.6 Timeline

Event 的时间节点，由 TimelineEntry 和 TimelineClaim 表达。时间线重建必须与 Event 更新事务一致。

## 3.7 Conflict

Claim 或 Signal 之间的矛盾关系。状态不能只靠颜色表达，Public DTO 不泄露私密来源身份。

## 3.8 Base Analysis

用户无关的 Event 基础分析，包括摘要、类型、重要性、主题与实体。它属于共享事实层，不读取用户 Profile。

## 3.9 Personalization

Personalization 使用用户 Profile 和公开 Event/Base Analysis snapshot，生成 immutable artifact 与 PersonalizedEvent snapshots。

必须满足：

- 顶层严格 schema 与完整输入上限。
- Prefilter 空结果为 canonical no-op。
- `(user_id, input_hash)` 唯一。
- 成功 run 与 artifact 一对一。
- NOW 顺序和 cursor 由 immutable artifact 决定。
- `matched_scope_ids`、`matched_focus_ids` 去重并按用户 Profile 保存顺序返回。
- 不读取 Raw、Evidence 正文、私密 provenance。

## 3.10 Brief

Brief 是 Personalization 的阅读投影：

- 每个 source Personalization artifact 最多一个 Brief artifact。
- `GET /brief/latest` 只接受当前最新 completed Personalization artifact 对应的 Brief。
- 新 Personalization 已完成但新 Brief 尚未完成时返回合法空结果，不回退旧 Brief。
- 标题来自 `brief_items.snapshot_title`，不得重新查询当前 Event title。

---

# 4. 一级产品信息架构

侧边导航固定英文大写，顺序固定：

```text
NOW
ASK
BRIEF
ARCHIVE
────────
SCOPE
SETTINGS
```

侧边导航不汉化。页面内部说明、状态、按钮和错误使用中文。

## 4.1 NOW

回答“此刻哪些 Event 值得我注意”。

固定语义：

- Event 列表来自用户最新 completed Personalization artifact。
- 使用 Backend 顺序，Frontend 不按 priority 或时间二次排序。
- 顶部显示数据库当前累计 Raw、canonical Signal（文案称因子）和当前相关 Event 数。
- `why_it_matters` 前显示“为什么值得关注”。
- 支持全部、发展中、已确认、已解决、存在冲突等状态筛选；筛选仅作用于当前 immutable items，不改变 Backend 顺序。
- 点击长列表底部 Event 后，Event Detail 必须从顶部开始，不能继承 NOW scroll position。

## 4.2 ASK

ASK 与 NOW 同级，是 Event Database 上的分析工作区。

固定流程：

```text
选择 1–8 个 Event
→ 输入问题
→ 比较 Event Database
→ 信息足够：直接组织回答
→ 信息不足且允许增强搜索：Research
→ 将新信息规范化并复核 Event
→ 基于复核后的 Event 回答
```

合同：

- 每次提交是一轮独立 Ask，不假设跨轮模型记忆。
- 提交时冻结 Event IDs、标题快照、问题和 `grok_enabled`。
- Answer 永远不是 Evidence。
- Research 结果必须进入现有 Research/Reconciliation 管线，不能直接修改 Event。
- Grok 仅在 ASK 的“增强搜索”开关中可选，用作 X/实时信息补充源。
- Public progress 只显示可审计阶段：`comparing / researching / reconciling / finalizing`。
- 完成后折叠为“已思考 xx 秒”，展开显示实际执行阶段；不显示或伪造私有 Chain-of-Thought。
- owner-only 历史支持 opaque cursor 分页和具体回答查看。
- 选中 Event 时自动载入与任一选中 Event 相关的 owner history。

## 4.3 BRIEF

回答“当前视野一览”。它是阅读模式，不是另一个 NOW 排行或实时 Event 查询。

## 4.4 ARCHIVE

Archive 包含历史可访问 Event，且满足：当前已保存，或已不再属于最新 Personalization relevant 集合。

- 当前 NOW 且未保存：不进入 Archive。
- 当前 NOW 且已保存：进入 Archive。
- 已退出 NOW：无论是否保存都进入 Archive。
- 无 completed Personalization artifact：合法空集合。

## 4.5 Search

Search 只搜索该用户历史可访问 Event，不搜索全库。

允许搜索当前 Event title/overview、BaseAnalysis summary、Claim text；禁止搜索 Raw、Signal/Evidence 正文、provenance、collector metadata、Personalization/Brief rationale 和私密来源身份。

## 4.6 SCOPE

首次 Onboarding 与后续修改共用视野定义。

固定 Scope：

```text
ai
open_source
technology
science
investment
```

仅选择 investment 时出现：

```text
china_market
us_stock
crypto_market
```

固定 Focus：

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

注册完成后的非首次修改，在“哪些内容进入你的视野？”下显示红色小字：

> 更改将在下次Event更新时生效

## 4.7 SETTINGS

包含用户模型偏好和 Maintenance 状态/触发入口。

模型目录由 Backend 返回可用性；Frontend 不能根据本地猜测标记可用。

---

# 5. Save、历史访问与快照语义

`event_saves` 通过 `(user_id, event_id)` 唯一关系表达状态，不使用 nullable boolean。

- `saved=true`：insert on conflict do nothing。
- `saved=false`：删除关系。
- PUT 幂等。
- 所有 Save 操作先使用 Historical Event Access Policy。
- 不存在与不可访问统一为 `404 EVENT_NOT_FOUND`。

Archive/Search Summary 完全取用户对此 Event 最新一次 completed、`relevant=true` 的 PersonalizedEvent snapshot；`saved` 单独取当前关系。不得拼接一半实时、一半历史的 DTO。

分页首页冻结 `source_personalization_artifact_id`；后续 cursor 必须继续在相同历史视图内查询。Search cursor 额外绑定规范化 query SHA-256。

---

# 6. Acquisition、Research 与来源

## 6.1 Acquisition

当前适配器包括：

- TrendRadar。
- Telegram News folder。
- Research 的 Web/GitHub 文档抓取。

采集只负责生成 Raw Information；Normalizer、Deduplication 和 Pipeline 负责后续状态。

## 6.2 Research Runtime

Research 由隔离的 OpenClaw/Agent-Reach 运行环境和直接 HTTPS Fetcher组成，具备 URL/SSRF policy、来源审计和稳定失败语义。

Grok CLI 是 ASK 可选补充源：

- 仅用户显式开启增强搜索时使用。
- 重点补充 X/实时公开信息。
- 输出仍进入 Research source、规范化、Event reconciliation。
- 不把 Grok 文本直接保存成 Event 结论。

## 6.3 私密 Telegram

- 私密来源可参与内部事实处理，但 Public DTO 不泄露群名、username、invite link 或内部标识。
- 发给模型的内容遵守冻结授权和最小必要输入。
- 不发送账户凭据、API Key、Raw 私密身份或 provenance。

---

# 7. Window Analysis、Backwrite 与 Maintenance

## 7.1 Window Analysis

对固定时间窗口内 canonical Signals 进行有界批处理。必须校验完整 Signal 覆盖；批次和最终 artifact 可按输入 hash 幂等复用。

## 7.2 Backwrite

Backwrite 只消费 `UserVisibleEventSnapshotProvider` 提供的、Backend 已排序且当前用户可见的冻结 Event 列表。

禁止：

- 把所有 Event 当作用户可见。
- 接受调用方任意 Event ID 列表。
- Provider unavailable 时降级放行。

Event 更新后的 Claims → Timeline → Conflicts → Base Analysis 必须在同一事务完整刷新；任一下游失败，不得将 item 标记成功或留下事实层不一致。

## 7.3 Maintenance

Maintenance 全局防重入，固定推进 Window Analysis、Reconciliation、Backwrite、Personalization/Brief 下游工作。

- partial/failed cycle 必须向上传播失败。
- 下次调度由 terminal `finished_at + 1 hour` 计算。
- Frontend 只 Polling，不推算 `next_cycle_at`，不使用 WebSocket。
- Worker heartbeat 决定真实 health；API 不得固定伪报 Worker 正常。

---

# 8. Event Localization

中文历史展示使用独立、可审计的 `zh-CN` projection：

- 不覆盖 Event、Claim、Timeline、Conflict、Base Analysis 或历史 PersonalizedEvent/Brief snapshot。
- projection 与当前 Event input hash 一致时才可公开使用。
- Event 更新后旧 projection 自动 stale，Public API 回退原文并重新排队。
- 严格校验 ID 全覆盖、唯一性、长度、中文内容和事实不漂移。
- 成功 batch 按 input hash 幂等复用；失败 batch 可恢复。
- 模型输入不包含 Raw、Signal/Evidence 正文、provenance、Profile 或账户数据。

写入前必须保留受权限保护的 PostgreSQL custom-format backup 与 manifest；备份不进入 Git。

---

# 9. 模型策略

当前 Public Settings 目录：

| 来源 | 模型 |
| --- | --- |
| Deepseek官方 | `deepseek-v4-flash`、`deepseek-v4-pro` |
| GPT-5.5 | `gpt-5.5` |
| AI Ping | `DeepSeek-V4-Flash-0731`、`DeepSeek-V4-Pro`、`Kimi-K3`、`Qwen3.8-Max` |

共享事实层默认使用部署级 `AI Ping / DeepSeek-V4-Flash-0731`，用户偏好仅作用于用户级分析路径。一次完整更新可通过进程级覆盖统一指定模型；本轮固定为 `AI Ping / DeepSeek-V4-Pro`，且不得修改用户的持久模型偏好。

规则：

- 凭据只保存在本机 `.env`，不进入 Git、日志、artifact、Public DTO 或文档。
- Provider/Model unavailable 时 fail-closed。
- 不要求所有模型都完成全流程测试后才能作为 Demo；默认路径和本次改动涉及路径必须通过。
- POK 仅是未来 failback 设想，当前实现和本轮任务不使用。

---

# 10. Public API 总表

当前 `/api/v1` 资源：

```text
GET    /session
POST   /auth/local
POST   /auth/logout

GET    /onboarding
PUT    /onboarding
GET    /scope
PUT    /scope

GET    /now
GET    /events/{event_id}
PUT    /events/{event_id}/saved
GET    /archive
GET    /search/events
GET    /brief/latest

POST   /ask
GET    /ask/history
GET    /ask/{ask_id}

GET    /settings/models
PUT    /settings/models

GET    /maintenance/status
POST   /maintenance/runs
GET    /maintenance/runs/{run_id}

GET    /research/capability
GET    /health
```

精确 query、response、enum 和错误以 `contracts/openapi.json` 为准。

---

# 11. Privacy 与日志红线

Public API 和普通日志禁止包含：

- API Key、密码、Cookie、session token。
- 私密 Telegram 群身份、invite link、内部 source ID。
- Raw 私密正文、完整 provenance、collector metadata。
- 内部 Prompt、模型私有 Chain-of-Thought。
- artifact/run 内部 ID（除专用状态合同明确允许者）。
- 用户 Profile、Personalization rationale、Brief rationale 的普通日志副本。

隐私策略由 Backend 执行。Frontend 不通过 `if source_name` 等临时逻辑猜来源可见性。

---

# 12. Runtime 与部署

Demo 目标：macOS localhost，也支持 Ubuntu 开发协作。

```text
Browser
→ FastAPI（/api/v1 + React production build）

Native Worker
→ PostgreSQL（Docker）
→ configured model/research providers
```

第一版不引入 Nginx、Kubernetes、Redis、Celery、Kafka、GraphQL 或 WebSocket。

`scripts/demo.sh` 必须：

- 启动前检查未知端口占用。
- 校验 PID、进程启动时间和命令身份。
- 等待 API health 和真实 Worker heartbeat。
- stop 只终止身份匹配进程。

---

# 13. Git 与协作

唯一长期分支：`main`。功能使用短期 branch 和 PR，固定 Squash Merge。

规则：

- 不直接向 `main` 开发。
- 不 force push `main`。
- 不回改已合并 migration。
- 修改 API 时同步 OpenAPI、Generated Types 与测试。
- dirty worktree 中不得覆盖用户无关修改。
- GitHub 为当前正式远端；本地 Forgejo 可保留但不是当前发布事实源。

MQTT Display Contract 的 Schema 与 canonical fixture 权威源仍为本仓库 `contracts/mqtt/`；`infoscope-display` 只能 vendoring fixture 并记录上游 immutable commit SHA 与 SHA-256。

---

# 14. 测试与 Definition of Done

任何功能完成至少满足：

```bash
./scripts/check.sh
git diff --check
```

并按风险增加：

- Backend 单元/集成测试。
- Frontend Vitest/Testing Library。
- OpenAPI generation check。
- Production build。
- 真实 Demo 浏览器验证。
- 涉及模型、Worker、Maintenance 时的持久化状态与恢复测试。

DoD：

1. 合同、实现、生成类型一致。
2. 成功、失败、空状态、重试与幂等语义明确。
3. Privacy boundary 通过。
4. 无凭据进入 Git 或日志。
5. UI 不二次排序或伪造 Backend 状态。
6. 完整检查通过。
7. PR 可独立审查并使用 Squash Merge。

---

# 15. 最高优先级红线

```text
× 把全库 Event 当作用户可见
× 用当前 Event 内容改写 immutable 历史 snapshot
× Brief latest 回退旧 Personalization source
× Frontend 推算 next_cycle_at 或重排 NOW
× Ask Answer 直接成为 Evidence
× Research/Grok 直接修改 Event
× 展示或伪造模型私有思维链
× 把 Signal 数冒充 Raw 数
× Public DTO 泄露私密 provenance
× API Key、账户数据或本机备份进入 Git
× Worker 下游失败后仍把 item 标记 completed
× Provider unavailable 时 fail-open
```

---

# 16. 一句话总结

> Infoscope · 观澜持续把碎片信息重构为可追溯 Event，通过 Claim、Timeline、Conflict 和 Evidence 维护事实，再根据用户视野呈现当前值得关注的变化，并允许用户在不破坏事实边界的前提下询问和补充 Event。
