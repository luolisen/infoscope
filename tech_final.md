# Infoscope · 观澜最终技术说明 / tech_final.md

> 版本：0.1 Demo 后续技术基线
> 更新时间：2026-08-19
> 用途：让新的开发聊天理解真实架构、目录、运行方式、数据边界和验证命令。

---

## 一、系统概览

Infoscope 是一个 Modular Monolith：API、Worker、数据库模型和领域服务在同一 Backend 包中，Frontend 通过生成的 OpenAPI Types 访问 `/api/v1`。

```text
React 19 + TypeScript + Vite
              ↓ HTTP / JSON
FastAPI API + static production frontend
              ↓ SQLAlchemy async
PostgreSQL  ← Native Worker
              ↓
Analysis providers / Research runtime / Grok CLI
```

第一版刻意不使用：

- 微服务。
- GraphQL。
- WebSocket。
- Redis/Celery/Kafka。
- Kubernetes。
- 前端自行执行模型任务。

---

## 二、仓库结构

```text
backend/
  alembic/versions/        # 只追加 migration
  config/                  # 非 Secret 配置
  src/infoscope/
    api/                   # FastAPI app、routes、dependencies
    schemas/               # Public Pydantic DTO
    models/                # SQLAlchemy persistence models
    services/              # 领域服务与事务边界
    analysis/              # 严格模型 schema、prompt、transport
    integrations/          # TrendRadar、Telegram、Research
    pipeline/              # Windowing 等管线基础能力
    worker/                # Durable queue processor
  tests/

frontend/
  src/
    api/                   # openapi-fetch wrappers + generated schema.ts
    components/            # 共享 icon 等
    features/              # auth/now/events/ask/brief/archive/search/settings
    App.tsx                # hash routing 与 app shell
    styles.css             # 当前设计系统与 responsive/motion

contracts/
  openapi.json             # Public API generated contract
  mqtt/                    # Display v1 authoritative schema/fixture

scripts/
  check.sh
  demo.sh
  generate_openapi.py
  prepare_demo_data.py
  trigger_maintenance.py
  resume_backwrite.py
  inspect_personalization_input.py
  compare_analysis_models.py
  probe_personalization_model.py
```

根目录还包含 `plan_final.md`、`dev_final.md`、`style_final.md`、`tech_final.md`，作为新聊天交接入口。

---

## 三、技术栈

### Frontend

- React 19。
- TypeScript 5.9。
- Vite 7。
- TanStack Query 5。
- `openapi-fetch`。
- `openapi-typescript`。
- Vitest 4 + Testing Library + jsdom。
- ESLint 9。

### Backend

- Python 3.12。
- FastAPI。
- Pydantic v2 / pydantic-settings。
- SQLAlchemy 2 async。
- asyncpg。
- Alembic。
- pwdlib Argon2。
- HTTPX。
- Telethon。
- BeautifulSoup、feedparser、PyYAML。
- Pytest / pytest-asyncio。
- Ruff。

### Runtime

- PostgreSQL 使用 Docker Compose。
- API 与 Worker 原生运行。
- Package manager：Backend `uv`，Frontend/root workspace `pnpm`。

---

## 四、数据模型与迁移

当前 migration 序列从 `20260816_0001` 到 `20260818_0028`，覆盖：

```text
Auth / Session
Onboarding / Scope
Acquisition / Pipeline artifacts
Event Reconstruction
Claims / Timeline / Conflicts / Base Analysis
Research
ASK comparison / bridge / reconciliation / finalization
Backwrite
Worker / Maintenance / heartbeat
Personalization
Brief
Event Save
Window batches/cache
Model preferences
Event localization
NOW corpus counts
ASK Grok preference
```

主要表族：

### 用户

- `users`
- `user_sessions`
- Onboarding/Profile 相关表
- `user_model_preferences`
- `event_saves`

### 采集与管线

- `raw_information`
- `signals`
- `pipeline_runs`
- `pipeline_checkpoints`
- `pipeline_artifacts`
- `window_analysis_batch_cache`

### 事实层

- `events`
- `event_signals`
- `claims` / `claim_signals`
- `timeline_entries` / `timeline_claims`
- `conflicts` / conflict relation tables
- `base_analyses`

### Research

- `research_requests`
- `research_request_events`
- `research_runs`
- `research_discovery_artifacts`
- `research_sources`

### ASK

- `ask_requests`
- `ask_request_events`
- `ask_runs`
- `ask_comparison_artifacts`
- `ask_research_bridges` / artifacts
- `ask_event_reconciliations` / runs / artifacts
- `ask_finalizations` / runs / final artifacts

### Backwrite / Maintenance

- `backwrite_cycles`
- `backwrite_items`
- Backwrite research/reconciliation runs/artifacts
- `maintenance_runs`
- `worker_heartbeats`

### 用户快照

- `personalization_runs`
- `personalization_artifacts`
- `personalized_events`
- `brief_runs`
- `brief_artifacts`
- `brief_items`

### Localization

- `event_localization_runs`
- `event_localization_batches`
- `event_localization_artifacts`
- `event_localizations`

规则：

- 已合并 migration 不回改，只追加新 migration。
- DB unique/FK/check constraints 是合同的一部分，不能只靠 Python 校验。
- durable task 的成功状态必须在相关 artifact 和下游事务成功后提交。

---

## 五、Backend 分层

### API Routes

Routes 只负责 HTTP contract、依赖注入和 response model；领域逻辑进入 Services。

### Schemas

`backend/src/infoscope/schemas/` 是 Public DTO 定义。内部模型、Prompt payload 和 DB entity 不直接返回。

### Services

Services 负责：

- access policy。
- snapshot 构建。
- transaction/idempotency。
- durable state transition。
- artifact 查找与复用。
- Public DTO 投影。

### Analysis

`analysis/` 负责模型输入输出合同：

- Pydantic strict schemas。
- canonical JSON/input hash。
- 字节/长度/数组上限。
- Prompt。
- provider-compatible request transport。
- 重试与 JSON repair。

### Integrations

外部系统只能通过 adapter 进入领域层，不让 Provider-specific 数据结构渗入 Public DTO。

---

## 六、Public API 与生成类型

当前公开路由族：

```text
auth/session
onboarding/scope
now/events/save
archive/search
brief
ask/history/status
settings/models
maintenance
research-capability
health
```

生成链：

```bash
UV_CACHE_DIR=.state/uv-cache \
  uv run --project backend python scripts/generate_openapi.py
pnpm --dir frontend generate:api
```

完整检查会验证 OpenAPI 未漂移。

Frontend 规则：

- 请求使用相对 `/api/v1/...`。
- Session 通过 HttpOnly Cookie，不把 bearer token 存 localStorage。
- 只使用 generated paths/components types。
- cursor 当 opaque string。
- Server state 交给 TanStack Query。
- Dialog、selection、pin 等 UI state 使用 React local state或最小 local preference。
- ASK 和 Maintenance 使用 Polling，不使用 WebSocket。

---

## 七、认证与访问策略

Session 状态：

```text
anonymous
onboarding_required
ready
```

受保护页面和 API 依赖 ready user。

关键访问策略：

### Current visibility

Event 在用户最新 completed Personalization artifact 中 `relevant=true`。

### Historical Event Access

Event 曾在用户任一 completed Personalization artifact 中 `relevant=true`。

用途：Event Detail、Save、Archive、Search 和 ASK selection 校验。

不存在与无权限应尽量统一 `404 EVENT_NOT_FOUND`，避免泄露 Event 是否对其他用户存在。

---

## 八、事实管线

```text
Collector
→ RawInformation
→ Normalization
→ Signal
→ Deduplication
→ Event Reconstruction
→ EventSignal
→ Claims
→ Timeline
→ Conflicts
→ BaseAnalysis
```

关键约束：

- canonical Signal ID 全覆盖且只出现一次。
- 零 Signal 是 deterministic no-change。
- EventSignal 使用专用审计来源字段。
- 私密 provenance 不进入模型输出或 Public DTO。
- 模型超限稳定失败，不静默截断、分页或拆分（除合同明确的 Backend batch）。
- 下游事实层重建失败时，Event update 不得成为 completed artifact。

---

## 九、Window Analysis 与 Backwrite

### Window Analysis

- 从 canonical Signals 构建有界窗口。
- 支持最多窗口、Signal、input chars、batch 数和并发配置。
- batch cache 按 canonical input 重用。
- 最终 artifact 必须覆盖所有输入 Signal。

### Backwrite

输入不是任意 Event ID 文件，而是：

```text
user_id + idempotency_key
→ fail-closed UserVisibleEventSnapshotProvider
→ 当前用户可见、Backend 已排序的冻结列表
```

每个 item 更新后在单事务刷新：

```text
Event
→ Claims
→ Timeline
→ Conflicts
→ Base Analysis
```

之后才允许 item/cycle 成功。

`scripts/resume_backwrite.py` 使用原 idempotency key 恢复 durable cycle，不制造新语义。

---

## 十、Maintenance 与 Worker

Worker 可处理：

```text
ASK queue
Maintenance queue
Personalization queue
Brief queue
Event localization queue
```

Demo 启动参数显式开启这些队列。

Maintenance：

- DB unique `active_slot` 防全局重入。
- 固定 phase 与失败传播。
- 每个 ready/onboarded user 的 Backwrite 使用可见性 Provider。
- terminal `finished_at + 1 hour` 是下次时间。
- API 只公开稳定状态和时间，不公开 queue payload。

Worker heartbeat：

- Worker 周期写入 heartbeat。
- API health 按 stale threshold 判断。
- API 活着但 Worker 不健康时，不能返回整体完全健康。

---

## 十一、Personalization 与 NOW

Personalization 输入：

- 用户 Scope/Focus。
- 公开 Event/Base Analysis snapshot。
- 必要的排序、状态和时间锚点。

禁止输入：

- Raw。
- Evidence/Signal 正文。
- 私密 provenance。
- 账户凭据。

严格输出保存：

- `schema_version`。
- decisions。
- relevant/priority/why_it_matters。
- matched Scope/Focus IDs。
- snapshot title/overview/state/display time/update time/topics/counts。

NOW：

- 只读取最新 completed artifact。
- cursor、顺序和锚点由 immutable artifact 决定。
- corpus Raw/Signal counts 是 Backend 统计，不影响 artifact 排序。
- Frontend 状态筛选仅过滤当前 items。

---

## 十二、Brief

Brief run/artifact/item 与 source Personalization artifact 绑定。

`latest` 算法：

1. 找用户当前最新 completed Personalization artifact。
2. 只查 `source_personalization_artifact_id` 相等的 completed Brief。
3. 不存在则返回 `{generated_at: null, items: []}`。
4. title 返回 BriefItem snapshot_title。

数据库必须保证每个 source artifact 最多一个 Brief artifact。

---

## 十三、Archive、Search 与 Save

Save：`event_saves(user_id,event_id)` 关系是否存在即状态，PUT 幂等。

Historical EventSummary：从用户最新一次相关 PersonalizedEvent snapshot 读取；只把当前 Save relation 合入 `saved`。

Archive/Search 首页冻结 source Personalization artifact。Cursor 至少绑定：

```text
version
endpoint
source_personalization_artifact_id
last display_time
last event_id
```

Search 额外绑定规范化 query SHA-256。

Search 使用 PostgreSQL case-insensitive literal substring matching，并正确转义 `%`、`_`、`\`。

---

## 十四、ASK Pipeline

### 创建合同

```json
{
  "event_ids": ["1..8 unique UUIDs"],
  "question": "1..2000 trimmed chars",
  "grok_enabled": false
}
```

### Durable 流程

```text
AskRequest
→ AskComparisonArtifact
→ enough: AskFinalization
→ missing facts: AskResearchBridge
→ ResearchRequest / sources
→ AskEventReconciliation
→ shared Event fact refresh
→ AskFinalization
→ AskFinalArtifact
```

Grok 开启时只改变 Research source 选择，不绕过上述流程。

### Public Progress

```text
comparing
researching
reconciling
finalizing
```

`stage` 是当前阶段；`stages[]` 是本轮真实到达的公开阶段。历史使用 `process_stages[]`。

Backend 通过 reconciliation artifact 判断 completed Ask 是否走过 Research；direct Ask 返回 `comparing → finalizing`。

这些阶段是应用流水线状态，不是模型 Chain-of-Thought。

### History

- owner-only。
- opaque cursor。
- 可按 Event IDs 过滤相关历史。
- DTO 只包含问题、Event IDs、状态、时间、公开 answer、updated Event IDs 和公开 process stages。
- 不包含 provider、model、internal Prompt、artifact IDs、Evidence/provenance。

---

## 十五、Research 与 Grok

Research runtime 默认使用隔离的：

```text
.state/openclaw/research.json
.state/openclaw/research/
```

能力检查需要 OpenClaw、Agent-Reach 和相关配置可用。

直接 Fetcher：

- credential-free HTTPS。
- SSRF/URL policy。
- published_at 和 source kind 审计。
- `web_page / github_document` 等允许来源。

Grok CLI：

- 配置 executable、model、timeout。
- ASK 用户显式开启时使用。
- 用于 X/实时公开搜索补充。
- 失败进入稳定 Research/Ask 失败或回退语义，不能假装成功。

---

## 十六、Event Localization

Localization 是独立 projection，不是事实重写。

```text
Event current title/overview + minimal context
→ strict batch model output
→ validate IDs/content/input hash
→ EventLocalizationArtifact
→ EventLocalization projection
```

默认 batch size 10、concurrency 2；配置上限 batch 10、concurrency 3。

Event 内容变化后 input hash 不同，旧 projection 不再用于 Public DTO。

输入禁止包含 Raw、Signal/Evidence 正文、provenance、Profile 和账户数据。

---

## 十七、模型配置

Settings 使用 Pydantic SecretStr，所有 base URL 必须为无凭据 HTTPS。

共享事实模型：

```text
AI Ping / DeepSeek-V4-Flash-0731
```

用户可选：

```text
Deepseek官方: deepseek-v4-flash / deepseek-v4-pro
GPT-5.5: gpt-5.5
AI Ping: DeepSeek-V4-Flash-0731 / Kimi-K3 / Qwen3.8-Max
```

Key groups 只存在 `.env`/SecretStr：

- 不写文档或代码。
- 不返回 API。
- 不记录普通日志。
- 不进入 model input。

Transport 支持 OpenAI-compatible JSON API 和 DeepSeek thinking compatibility。JSON object mode 的 Prompt 必须包含明确 `json` 指令，避免兼容中转返回 400。

---

## 十八、Demo 启动

前置：

- Docker daemon。
- Python 3.12 + `uv`。
- Node/pnpm。
- 本机 `.env`。
- 需要增强搜索时配置 Research runtime/Grok CLI。

启动：

```bash
./scripts/demo.sh start
```

脚本执行：

```text
preflight
→ docker compose up postgres
→ uv sync
→ alembic upgrade head
→ pnpm install/build
→ API start + PID identity
→ Worker start + PID identity
→ API health
→ Worker heartbeat readiness
```

状态：

```bash
./scripts/demo.sh status
curl -fsS http://127.0.0.1:8000/api/v1/health
```

日志：

```text
.state/demo/api.log
.state/demo/worker.log
```

`.state/` 是本机私密运行数据，不提交 Git。

Demo 数据验证：

```bash
UV_CACHE_DIR=.state/uv-cache uv run --project backend \
  python scripts/prepare_demo_data.py --username <demo-user> --require-complete
```

该脚本只输出非敏感 readiness manifest，不读取密码。

---

## 十九、测试与生成命令

完整：

```bash
./scripts/check.sh
```

等价主要步骤：

```bash
uv sync --project backend --all-groups --locked
uv run --project backend --no-sync ruff check backend/src backend/tests scripts
(cd backend && uv run --no-sync python -m pytest -q)
uv run --project backend --no-sync python scripts/generate_openapi.py --check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
git diff --check
```

定向开发时可先跑相关 test file，但提交前必须跑完整检查。

---

## 二十、Security 与 Privacy

### Secret

- `.env` ignored。
- API keys 使用 SecretStr。
- Telegram session 权限收紧。
- HTTP client 不继承不受控环境代理时使用明确 `trust_env=False` 路径。

### Public DTO

- 私密 Telegram 只返回 sanitized public projection。
- 不返回 Raw、内部 provenance、collector metadata。
- 不返回模型私有 reasoning。
- 不返回内部 artifact/run IDs，除专用状态合同显式允许。

### Research Fetch

- HTTPS-only 和 URL policy。
- 防本机/内网 SSRF。
- 不跟随页面文本中的指令执行外部操作。

### Backup

数据库备份、manifest、Telegram/OpenClaw state 都是本机私密数据，目录 `0700`、文件 `0600`，不进入 Git/PR/Demo 包。

---

## 二十一、MQTT Display Contract

本仓库是 Display Contract 唯一权威源：

```text
contracts/mqtt/display-events-v1.schema.json
contracts/mqtt/examples/display-events-v1.json
contracts/mqtt/README.md
```

`infoscope-display` 只 vendoring canonical fixture，并记录上游 immutable commit SHA 与 SHA-256；不得复制或拥有第二份权威 Schema。

Display v1 中 Event metadata 语义按 Contract README 执行，硬件端不得擅自按未冻结字段过滤或重排。

---

## 二十二、常见修改流程

### 改 API

```text
Schema/model/service
→ Backend tests
→ OpenAPI generate
→ frontend schema generate
→ API wrapper/UI
→ Frontend tests
→ full check
```

### 改数据库

```text
New Alembic migration
→ SQLAlchemy model
→ repository/service
→ PostgreSQL integration test
→ rollback/recovery reasoning
```

### 改模型合同

```text
canonical input bounds
→ strict output schema
→ prompt
→ transport compatibility
→ invalid/duplicate/missing ID tests
→ persistence idempotency
→ privacy review
```

### 改 Frontend

```text
Generated DTO
→ query/mutation wrapper
→ component
→ loading/error/empty/success
→ keyboard/reduced-motion
→ test
→ real browser verification
```

---

## 二十三、技术红线

```text
× Frontend 直接访问数据库或模型
× FastAPI BackgroundTasks 执行模型长任务
× WebSocket 替代已冻结 Polling
× offset pagination 替代 opaque keyset cursor
× 手写与 OpenAPI 重复的 DTO
× 修改已合并 migration
× Provider unavailable 时 fail-open
× durable item 下游失败后仍 completed
× Research/Grok 绕过 Reconciliation 直接改 Event
× 用当前 Event 拼历史 snapshot
× keys/credentials 出现在 Git、日志或 Public DTO
× 展示模型私有 Chain-of-Thought
```

---

## 二十四、接管检查表

新的开发聊天在修改前应确认：

- 当前 branch/PR/head SHA。
- `origin/main` 是否已 fetch。
- worktree 是否 dirty。
- Demo API/Worker 是否真实 running。
- `.env` 存在但不读取输出。
- 当前 Alembic head。
- `contracts/openapi.json` 未漂移。
- 目标功能属于 Public API、Worker、模型、Frontend 中哪条边界。
- 是否需要真实模型/Research 授权。
- 是否会触及 immutable snapshot 或 Historical Access Policy。

确认后再按 `dev_final.md` 的下一步执行。
