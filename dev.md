# Infoscope（观澜）开发职责与顺序

> 版本：Development Execution Baseline v1  
> 日期：2026-08-15  
> 依据：`plan.md`、`tech.md`、`style.md` Final Baseline v4 · Development Freeze

本文档负责把已冻结的产品、技术和协作基线转换为可执行的开发顺序。若本文档与 `plan.md` 的冻结 Contract 冲突，以 `plan.md` 为准；前端视觉与交互以 `style.md` 为准。

---

## 1. 总体原则

Infoscope 采用：

```text
GitHub Monorepo
+ Modular Monolith
+ React/Vite Frontend
+ FastAPI API
+ Independent IS Worker
+ PostgreSQL in Docker
```

第一版不采用 Redis、Celery、GraphQL、WebSocket、Nginx、Caddy、Traefik、Kubernetes、Kafka或微服务。

核心开发原则：

1. 按 Phase 1 至 Phase 6 顺序推进，不跨阶段大规模开发。
2. 一个 task branch 只负责一个主要任务。
3. Frontend 不猜 Backend 字段；Backend 不因实现方便改变 Public DTO。
4. FastAPI Schema 是 API 数据结构唯一事实来源。
5. 所有外部信息必须经过 `Raw → Normalize → Signal`，不得直接写 Event、NOW 或 Brief。
6. AI 推理不是 Evidence；新事实必须重新进入信息 Pipeline。
7. Source privacy、权限、计数、排序、调度和状态机由确定性程序控制。
8. 未冻结的路径、字段、模型、SDK、数据库结构或配置不得猜测。

---

## 2. 人员职责

## 2.1 Alan — Backend / Architecture / Intelligence

Alan 主责：

- 总体架构
- FastAPI
- PostgreSQL
- SQLAlchemy 2
- Alembic Migration
- 独立 IS Worker
- Scheduler
- TrendRadar Integration
- TG News Integration
- Telegram API 模块
- Research Adapter
- Hermes / OpenClaw / Agent-Reach 集成
- Analysis Adapter
- Normalize
- Deduplicate
- Window Analysis
- Event Matching / Reconstruction / Reconciliation
- Event Backwrite Snapshot / Frozen Queue
- Claim Extraction
- Timeline Reconstruction
- Conflict / Relationship Analysis
- Base Analysis
- Personalization
- Source Privacy Boundary
- FastAPI Schema 与 OpenAPI Contract 主导
- Backend lint、test 与 Pipeline tests
- macOS Demo integration
- Startup reliability

Alan 不应：

- 在 FastAPI Route 中直接抓取 Telegram、运行 TrendRadar 或调用模型。
- 让 Agent/LLM 直接覆盖 Event 或把模型推理写成 Evidence。
- 擅自改变冻结 endpoint、method、JSON key、enum 或状态语义。
- 修改已经合入 `main` 的 Alembic Migration。
- 把真实 Secret、私密群组身份或敏感 payload 写入 Git 或普通日志。

## 2.2 Lingjiu — Frontend

Lingjiu 主责：

- React + TypeScript + Vite
- `pnpm`
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
- Ask Infoscope UI
- Generated API Client
- `openapi-typescript`
- `openapi-fetch`
- TanStack Query Server State
- Loading / Error / Empty / Success
- Responsive
- Accessibility
- Frontend lint、typecheck、build 与 tests
- `style.md` 落地

Lingjiu 不应：

- 手写与 Generated Types 重复的 API entity interface。
- 修改 Generated TypeScript Types。
- 根据 UI 需要自行创造 API 字段或近似字段。
- 在 React 中硬编码 Backend localhost 地址。
- 读取 `is_session` Cookie 或在浏览器存储认证 Token。
- 对 NOW 返回的 Event 做二次排序。
- 在 Frontend 判断私密来源是否应该脱敏。
- 根据错误 `message` 字符串决定业务逻辑。

## 2.3 两人共同确认

以下事项必须由 Alan 与 Lingjiu 共同确认：

- API Contract
- Database Schema
- Signal / Event Schema
- Onboarding Contract
- Source visibility policy
- AI output schema
- Event / Claim state semantics
- 实现阻塞是否足以中止 Contract Freeze

共同确认不等于两人同时修改同一文件。每项变更仍须指定唯一 owner，另一人负责 Review。

---

## 3. 开发顺序总览

```text
Phase 1 — Skeleton
↓
Phase 2 — User Loop
↓
Phase 3 — Acquisition
↓
Phase 4 — Event Intelligence
↓
Phase 5 — Personalization
↓
Phase 6 — Demo Freeze
```

阶段可以有少量准备工作并行，但不得在基础 Contract、持久化和用户闭环尚未稳定时提前进行大规模 AI 功能开发。

---

## 4. Phase 0 — 开发前准备

> Phase 0 是为执行补充的准备步骤，不是 `plan.md` 原有的正式产品 Phase。

### 负责人

- Alan：Owner
- Lingjiu：Review

### 任务

1. 确认 GitHub 仓库、`main` 和 `origin/main` 可用。
2. 将 `plan.md`、`tech.md`、`style.md` 和本文件纳入 Git。
3. 确认实际仓库目录，不根据逻辑 Monorepo 图猜路径。
4. 配置 Git 身份和安全的环境变量示例。
5. 建立基础 `.gitignore`、LF 与跨平台约定。
6. 确认 macOS 与 Ubuntu 都不依赖个人绝对路径。
7. 确认 task branch、PR、Review、Squash Merge 流程。

### 完成条件

- `main` 有可用提交并可创建 worktree。
- 冻结文档可由所有开发者和 Codex 在仓库内读取。
- 仓库无 Secret。
- 开始 Phase 1 的 task branch 已创建。

---

## 5. Phase 1 — Skeleton

### 目标

建立可安装、可启动、可测试、前后端可通信的最小 Monorepo 骨架。

### Alan 的顺序

1. 确认并建立实际 Monorepo 基础组织。
2. 初始化 Python Backend，依赖管理使用 `uv`。
3. 初始化 FastAPI。
4. 配置 SQLAlchemy 2。
5. 配置 PostgreSQL Docker。
6. 配置 Alembic 基础能力。
7. 实现 `GET /api/v1/health`。
8. 建立 FastAPI OpenAPI 生成流程。
9. 建立独立 Worker 的最小启动入口。
10. 添加 Backend lint 与 test。

### Lingjiu 的顺序

1. 初始化 React + TypeScript + Vite，依赖管理使用 `pnpm`。
2. 建立 App Shell 最小入口。
3. 配置 Vite relative `/api/v1/*` proxy。
4. 配置 `openapi-typescript`。
5. 配置 `openapi-fetch`。
6. 配置 TanStack Query。
7. 使用 Generated Types 调用 Health API。
8. 添加 Frontend lint、typecheck、build 与基础 test。

### 协作关口

Alan 先提供 FastAPI Schema 和 OpenAPI；Lingjiu 只从 OpenAPI 生成类型。涉及 Contract 的变更必须在同一 PR 或明确配对的 PR 中保持一致。

### 验收

```text
React/Vite can start
FastAPI can start
IS Worker can start
PostgreSQL can start
GET /api/v1/health works
Frontend can call relative /api/v1/health
OpenAPI and Generated Types are committed
Frontend lint/typecheck/build pass
Backend lint/test pass
```

---

## 6. Phase 2 — User Loop

### 目标

完成第一个端到端用户闭环：

```text
Register
→ Onboarding
→ Empty NOW
```

### Alan 的顺序

1. 建立 User 与 Server-side Session 所需的数据库模型和 Migration。
2. 实现 `is_session` HttpOnly Cookie。
3. 实现 `GET /api/v1/session`。
4. 实现 `POST /api/v1/auth/register`。
5. 实现 `POST /api/v1/auth/login`。
6. 实现 `POST /api/v1/auth/logout`。
7. 实现 Onboarding 固定 enum 与 Validation。
8. 实现 `GET /api/v1/onboarding`。
9. 实现 `PUT /api/v1/onboarding`。
10. 实现 `GET /api/v1/scope` 与 `PUT /api/v1/scope`。
11. 实现 Event API skeleton 和 Empty NOW。
12. 生成并提交最新 OpenAPI 与 TypeScript Types。
13. 添加 Auth、Session、Onboarding、Scope 和 NOW tests。

### Lingjiu 的顺序

1. 接入 Session 状态：`anonymous`、`onboarding_required`、`ready`。
2. 实现 Register / Login。
3. 实现 SCOPE。
4. 实现仅在选择 `investment` 时出现的投资市场页面。
5. 实现 FOCUS。
6. 实现 Onboarding 完成后的路由推进。
7. 实现 Empty NOW shell。
8. 覆盖 Loading / Error / Empty / Success。
9. 完成 Phase 2 响应式与基础无障碍检查。

### 验收

- 未登录用户正确进入 Login/Register。
- 注册或登录后由 Backend 设置 `is_session`。
- 未完成 Onboarding 时正式产品 endpoint 返回既定错误。
- Onboarding enum、条件分支和 Validation 与冻结 Contract 一致。
- 完成 Onboarding 后进入 Empty NOW。
- Frontend 没有手写重复 API 类型或读取 Cookie。

---

## 7. Phase 3 — Acquisition

### 目标

建立可靠的信息采集、早期持久化、标准化和时间窗口处理链路。

### Alan 的顺序

1. 在共同确认后建立 Raw、Signal 及必要 Pipeline 数据结构和 Migration。
2. 按已冻结的 7 个 Hotlist + 10 个 RSS 薄 Adapter 边界实现
   TrendRadar Integration；不引入 TrendRadar AI、SQLite、通知、MCP 或 Scheduler。
3. 实现 TG News / Telegram Integration。
4. 采集后立即持久化 Raw Information。
5. 实现 Normalize。
6. 持久化 Signal。
7. 实现 Deduplicate，保持其与 Event Reconstruction 分离。
8. 实现逻辑长度固定为 1 小时的 Window Analysis。
9. 明确并测试精确窗口边界、Raw 游标和补偿策略。
10. 添加失败重试、Pipeline 重放和可审计日志。

### Lingjiu 的顺序

1. 完善与采集状态相关的 Loading / Error / Empty 表现。
2. 接入已冻结且实际提供的维护状态数据。
3. 不展示 Raw Information 或内部 collector metadata。
4. 配合验证私密来源不会进入 Public DTO。

### 验收

- TrendRadar 与 TG News 只进入 `Raw → Normalize → Signal`。
- Raw 在 AI 处理前已经持久化。
- AI 或外部服务失败后可以重试，不需要重新采集。
- Window Analysis 逻辑窗口为 1 小时。
- 已持久化 Raw 不因调度耗时被静默遗漏。
- 私密 provenance 不出现在 Frontend 或普通日志。

---

## 8. Phase 4 — Event Intelligence

### 目标

把 Signal 重构为持续维护的 Event，并完成 Ask、Research 和 Backwrite。

### Alan 的顺序

1. 实现 Event Matching / Clustering / Reconstruction。
2. 实现 Claim Extraction。
3. 实现 Timeline Reconstruction。
4. 实现 Conflict / Relationship Analysis。
5. 实现 Base Analysis。
6. 建立 Analysis Adapter，业务代码不绑定特定模型供应商。
7. 建立 Research Adapter。
8. 在读取真实 README、CLI help、Config、Source entry 或 API definition 后接入 Hermes/OpenClaw/Agent-Reach。
9. 实现单 Event 与多 Event Ask 的数据库比对。
10. 实现缺失事实触发 Research，并让结果重新经过 `Raw → Normalize → Signal`。
11. 实现 Event Reconciliation。
12. 实现 Event Backwrite Snapshot。
13. 实现 Newest/Oldest 向中间交替的 Frozen Queue。
14. 实现完整更新流程完成后等待 1 小时的调度。
15. 实现 Ask 与 Maintenance 的异步任务状态和 Polling Contract。
16. 添加模型输出 schema、timeout、retry 和 failure isolation tests。

### Lingjiu 的顺序

1. 实现 Event Detail。
2. 实现 Claims。
3. 实现 Timeline。
4. 实现 Conflicts。
5. 实现 Evidence。
6. 实现私密 Telegram `private_sanitized` 展示。
7. 实现公开 Evidence 的作者和 URL 展示。
8. 实现单 Event Ask。
9. 实现多 Event Ask。
10. 通过 `GET /api/v1/ask/{ask_id}` Polling。
11. 完成后根据 `updated_event_ids` 显示“事件信息已补充”并 refetch Event/NOW。
12. 接入 Maintenance Polling；第一版不使用 WebSocket。

### 验收

- `AI Answer ≠ Evidence`。
- Research Result 不直接覆盖 Event Summary。
- 新事实全部重新经过 Signal 层。
- 多 Event Ask 不自动合并 Event。
- Backwrite 使用本轮开始时的用户可见时间排序 Event Snapshot。
- Frozen Queue 不因 NOW 更新而重排、重复或遗漏。
- 相同维护周期不重入。
- 私密 Telegram 不返回群名、username、invite link 或 internal ID。

---

## 9. Phase 5 — Personalization

### 目标

根据用户 SCOPE/FOCUS 决定 Event 是否进入 NOW，并生成用户级解释和 Brief。

### Alan 的顺序

1. 实现 SCOPE / FOCUS cheap prefilter。
2. 实现 Personalization 输入边界：Event/Base Analysis + User SCOPE + User FOCUS。
3. 实现 relevance、priority、why it matters 和 personalized angle。
4. 实现 NOW 用户可见集合。
5. 按 `display_time DESC` 返回 NOW，Frontend 不二次排序。
6. 使用 Raw Information 实际计数实现 `window_stats.raw_information_count`。
7. 实现 Brief selection 与 generation。
8. 确保 Brief 只基于已持久化 Event 事实层。
9. 实现 SCOPE 修改后的 Personalization 更新任务。

### Lingjiu 的顺序

1. 完成 NOW Event 列表与统计信息。
2. 实现 Why it matters。
3. 实现 BRIEF。
4. 实现 ARCHIVE。
5. 实现 Search。
6. 完成长期 SCOPE/FOCUS 页面。
7. 实现 Event 保存状态。
8. 确保 Frontend 不重新计算 `next_cycle_at`、统计或排序。

### 验收

- Personalization 不修改 Event、Claim、Timeline、Conflict 或 Evidence 事实层。
- 不对整个数据库逐条携带 User Profile 调用 LLM。
- NOW 信息数是 Raw Information 实际计数，不是 Signal 数或 AI 估算。
- Brief 不建立独立事实系统。
- 内部评分不以无解释价值的精细小数展示给用户。

---

## 10. Phase 6 — Demo Freeze

### 目标

冻结功能范围，保证 Demo 可靠。

### Alan

- Backend bug fix
- Pipeline failure handling
- Privacy audit
- Secret/log audit
- Startup reliability
- macOS integration
- Demo data
- Performance
- Backend test stabilization

### Lingjiu

- Frontend bug fix
- UI polish
- Loading/Error/Empty/Success 完整性
- Responsive
- Accessibility
- Demo flow polish
- Frontend lint/typecheck/build/test stabilization

### 两人共同

- 完整 E2E 演练
- Contract consistency 检查
- Demo 启动脚本验证
- Source privacy review
- 最终 PR Review

### 禁止事项

- 换数据库
- 换 ORM
- 换 React framework
- 换 package manager
- 引入 Redis
- 引入 WebSocket
- 微服务化
- 大规模架构重构

---

## 11. 推荐的 Task Branch 顺序

以下 branch 名是执行建议；创建前仍须检查实际仓库与当前 `main`：

```text
Phase 0
docs/development-baseline

Phase 1
feat/infra-skeleton
feat/api-health
feat/frontend-skeleton
feat/contract-generation

Phase 2
feat/api-auth-session
feat/api-onboarding
feat/frontend-auth
feat/frontend-onboarding
feat/api-now
feat/frontend-now-shell

Phase 3
feat/integration-trendradar
feat/integration-telegram
feat/worker-normalize
feat/worker-deduplicate
feat/worker-window-analysis

Phase 4
feat/analysis-event-reconstruction
feat/analysis-claims-timeline
feat/analysis-conflicts
feat/integration-research
feat/api-ask
feat/frontend-event-detail
feat/frontend-ask
feat/worker-backwrite
feat/worker-maintenance

Phase 5
feat/analysis-personalization
feat/api-brief
feat/frontend-brief
feat/frontend-archive-search

Phase 6
fix/demo-stability
```

不要一次性提前创建所有 branch。只有前一依赖达到可用状态时才从最新 `main` 创建下一 task branch。

---

## 12. Git 与 Worktree 流程

唯一长期分支：

```text
main
```

开始任务：

```bash
git switch main
git pull --ff-only
git switch -c <task-branch>
```

Codex 新工作树若处于 detached HEAD，必须先创建并切换到 task branch，不能直接开发和提交。

Commit 格式：

```text
type(scope): description
```

允许的 type：

```text
feat fix refactor chore docs test
```

推荐 scope：

```text
frontend api worker db integration analysis contract infra
```

合并前：

```bash
git fetch origin
git rebase origin/main
```

所有代码通过 PR 进入 `main`，默认由另一名队员 Review，并固定使用 Squash Merge。

涉及 API 的 PR 必须同时确认：

- FastAPI Schema
- OpenAPI
- Generated TypeScript Types
- Frontend typecheck

涉及 UI 的 PR 必须检查：

- Loading
- Error
- Empty
- Success

---

## 13. 阻塞与决策规则

出现以下情况时停止相关实现，不得自行猜测：

- 文档与当前 `main` 的冻结 Contract 冲突。
- 所需 API 字段不存在。
- 需要修改冻结 endpoint、method、JSON key 或 enum。
- 需要修改 Database Schema 但尚未共同确认。
- Hermes/OpenClaw/Agent-Reach 的真实接口尚未读取。
- TG News 或 TrendRadar 的真实输入输出尚未确认。
- Source visibility policy 无法确定。
- AI output schema 尚未共同确认。

处理顺序：

```text
记录阻塞
→ 指定受影响 Contract
→ Alan 与 Lingjiu 共同确认
→ 更新冻结文档/Schema
→ OpenAPI 与 Generated Types 同步
→ 恢复实现
```

禁止通过近似字段、双字段兼容、临时 `/v2` 或前端字符串判断绕过 Contract。

---

## 14. Definition of Done

每个任务必须同时满足：

```text
代码完成
+ 能运行
+ lint/typecheck 通过
+ 相关 test 通过
+ 无 Secret
+ 无来源隐私泄漏
+ API Contract 同步
+ PR Review
+ Squash Merge
```

Frontend 任务还必须覆盖 Loading、Error、Empty、Success。

AI 任务不验证逐字输出，验证：

- Schema
- Required fields
- Types
- Invalid output handling
- Timeout
- Retry
- Failure isolation

核心 E2E：

```text
Register
→ SCOPE
→ [if investment] 投资市场
→ FOCUS
→ NOW
→ Event Detail
→ 询问观澜
→ 必要时补充 Event
```

---

## 15. 当前立即执行项

1. 在 Codex 工作树中创建并切换到正式 task branch，不能停留在 detached HEAD。
2. 将冻结文档和本文件纳入 Git。
3. 完成 Phase 0 检查。
4. 从 Phase 1 Skeleton 开始。
5. Phase 1 验收通过并合入 `main` 后，再开始 Phase 2。
