# Infoscope（观澜）最终开发交接 / dev_final.md

> **功能冻结已生效（2026-08-19）**：严格禁止继续开发新功能。任何后续变更必须遵守
> [RELEASE_FREEZE.md](RELEASE_FREEZE.md) 与 `Release freeze gate`；仅允许经 Alan 明确批准的
> 发布阻断修复、安全修复、既有行为回归测试和非扩展性文档修正。

> 状态：0.1 Demo 可用；PR #77 / #78 已合并；进入质量与路演收尾
> 快照时间：2026-08-19（Asia/Shanghai）
> 适用仓库：`SCOUT-Infoscope/infoscope`
> 本文件只写当前执行状态与下一步；长期产品合同见 `plan_final.md`。

---

## 0. 新聊天启动指令

新的开发聊天开始后，先执行只读核验：

```bash
pwd
git status --short
git branch --show-current
git fetch origin --prune
git log -5 --oneline --decorate
gh pr view 77 --repo SCOUT-Infoscope/infoscope --json state,mergedAt,mergeCommit,url
gh pr view 78 --repo SCOUT-Infoscope/infoscope --json state,mergedAt,mergeCommit,url
git ls-remote origin refs/heads/main
./scripts/demo.sh status
```

然后完整阅读：

```text
plan_final.md
dev_final.md
style_final.md
tech_final.md
```

不要从旧聊天猜状态，不要在读取四份文件前改代码。

---

## 1. 当前 Git 快照

生成本文件时：

| 项目 | 值 |
| --- | --- |
| 当前正式 main | `origin/main` at `1e31b16` |
| PR #77 | MERGED，merge commit `f7ab462` |
| PR #78 | MERGED，merge commit `1e31b16` |
| 当前文档收尾 branch | `codex/readme-positioning-handoff`（head 会继续前进） |
| 可用版本 tag | `0.1` at `97fd66f` |
| Demo | API running、Worker running |

PR #77 与 PR #78 都是已完成历史，不得继续把它们当作待审查、待合并任务。新任务先 fetch，并以最新 `origin/main` 建立新的 `codex/*` 分支。

---

## 2. 当前可用 Demo

入口：

```text
http://127.0.0.1:8000/
```

启动：

```bash
./scripts/demo.sh start
```

常用命令：

```bash
./scripts/demo.sh status
./scripts/demo.sh restart
./scripts/demo.sh stop
./scripts/demo.sh preflight
```

注意：在某些一次性自动化 shell 中，宿主会在命令返回后回收后台子进程。无人值守启动时应让 Demo 运行在持续终端会话中，并在返回用户前再次执行 `./scripts/demo.sh status` 和 health 检查。

2026-08-19 最近一次安全自检：

- Backend 不连接 Demo 数据库的定向测试：65 passed，1 个 deprecation warning。
- Frontend：38 passed；lint、typecheck、production build 通过。
- Ruff、OpenAPI generation check、`git diff --check` 通过。
- API、数据库与 Worker health 通过。
- 完整 PostgreSQL 集成套件本轮未重跑：现有测试会连接本机 Demo 数据库；应先使用隔离 test database。

这些数字只属于该次自检。新提交后必须重新验证，不能把历史结果当当前结果。

---

## 3. 已完成能力

### 3.1 Skeleton 与用户循环

- FastAPI + PostgreSQL + Alembic + Native Worker + React/Vite monorepo。
- 单一本地称呼入口、登出与 HttpOnly session；公开界面不出现账号或密码。
- Settings 的 `演示demo` 仅在前端重放称呼、Scope、市场与 Focus，不写入 User/Profile，不排队 Personalization。
- Onboarding、SCOPE、投资二级 Scope、FOCUS。
- ready-user gate 与统一错误 DTO。
- React production build 由 FastAPI 托管，API 路由不被静态 fallback 覆盖。

### 3.2 Acquisition 与事实层

- TrendRadar 与 Telegram acquisition adapter。
- Raw Information、Normalization、canonical Signal、Deduplication。
- Event Reconstruction。
- Claims、Timeline、Conflicts、Base Analysis。
- strict model schema、输入限制、ID 完整覆盖与幂等 artifacts。
- Window Analysis 有界批处理与 batch cache。

### 3.3 Research

- OpenClaw/Agent-Reach 隔离 Research runtime。
- Web/GitHub document direct fetcher、URL/SSRF policy、source audit。
- Research capability health。
- Grok CLI ASK opt-in source，用于 X/实时搜索补充；不直接写 Event。

### 3.4 Backwrite 与 Maintenance

- fail-closed `UserVisibleEventSnapshotProvider`。
- Backwrite 固定 snapshot 与 durable cycle/item 状态。
- Event 更新后 Claims → Timeline → Conflicts → Base Analysis 同事务刷新。
- abandoned item/runtime recovery。
- Maintenance 全局防重入、固定顺序、失败传播。
- terminal `finished_at + 1 hour` 调度语义。
- Worker heartbeat 与真实 `/health`。
- demo PID 身份、端口冲突与 Worker readiness 检查。

### 3.5 Personalization、NOW 与 Brief

- strict canonical Personalization input/output。
- immutable Personalization artifact 与 PersonalizedEvent snapshot。
- NOW 使用 Backend 排序与 cursor。
- NOW 显示累计 Raw、canonical Signal（前端称因子）与当前 Event 数。
- `why_it_matters` 标记“为什么值得关注”。
- NOW 状态毛玻璃筛选和切换动画。
- Brief source artifact 唯一绑定，不回退旧 Brief。
- Brief 标题读取 snapshot_title。

### 3.6 Save、Archive 与 Search

- Event Save 关系幂等与 Historical Access Policy。
- NOW/Event Detail 保存状态。
- Archive 历史集合语义。
- Search 只搜索历史可访问 Event 的允许字段。
- immutable historical EventSummary。
- source Personalization artifact 冻结的 opaque cursor。

### 3.7 Localization

- 独立 `zh-CN` Event localization run/batch/artifact/projection。
- input hash stale 语义。
- 并发、严格覆盖、失败重试与恢复。
- Public DTO 只在 projection 新鲜时使用。
- 不覆盖事实层和历史 snapshots。

### 3.8 Model Settings

- Backend 固定来源/模型目录和真实可用性。
- Deepseek官方、GPT-5.5、AI Ping 二级模型选择。
- Editorial radio rows 取代难看的大 Select。
- 用户偏好 upsert 更新 `updated_at`。
- 共享事实层与用户偏好边界分离。

### 3.9 最终前端体验

- 侧边栏 sticky，不随正文滚动。
- Desktop 共享 active indicator 滑动；移动端有对应指示动画。
- 页面切换、Ask Event rail、NOW filter 动画与 reduced-motion。
- Search 入口、`⌘K`、清晰叉形关闭、focus trap、Escape 与焦点归还。
- 核心 UI 汉化；一级侧边导航保留英文。
- Scope 非首次修改提示。
- Save、Event Detail ASK/选择等 action button 视觉优化。
- NOW → Event Detail scroll reset。

---

## 4. 已合并交付：PR #77 / #78

PR #77 已合并并交付：

- ASK 成为与 NOW 同级的一级页面。
- Event Detail 使用“询问这个事件”按钮携带上下文进入 ASK。
- 左侧 Event 列表整行选择；隐藏默认 checkbox，选中后加深并出现左侧指示条。
- 最多选择 8 个 Event。
- 空状态居中“观澜能帮你做什么？”。
- 提交后 composer 下沉并固定在工作区底部。
- 用户问题显示在右侧，观澜回答显示在左侧。
- 对话区独立滚动，composer 不覆盖最新回答。
- 选中 Event 后自动加载相关 owner history。
- 历史浮动栏可折叠、固定、取消固定、分页、打开具体回答。
- “增强搜索”仅 ASK 可见，可显式开启 Grok。
- 处理中显示 Backend 可审计阶段和累计耗时。
- 完成后折叠为“已思考 xx 秒”；展开显示实际执行阶段。
- direct path 只显示“已比较 Event 数据库 → 已组织回答”。
- 只有确实执行 Research/Reconciliation 的 Ask 才显示相应阶段。
- 不公开模型私有 Chain-of-Thought。

PR #78 随后已合并并交付：

- 仅询问称呼的本地入口。
- Settings 中不持久化 Profile 的“演示demo”。
- AI Ping `DeepSeek-V4-Pro` 与运行时模型覆盖。
- 新来源采集、Window Analysis cache 与并发恢复能力。
- README 和产品定位收尾从 PR #78 合并后的 `main` 继续。

权威合并点：

```text
PR #77 -> f7ab462
PR #78 -> 1e31b16
```

---

## 5. 下一步严格顺序

### D1 — 从最新 main 开始

```bash
git fetch origin --prune
git switch -c codex/<task-name> origin/main
```

不得继续向 PR #77、PR #78 的历史 head 堆叠新功能。

### D2 — 冻结后的质量收尾

当前优先级：

1. 冻结 README 的目标用户、具体问题与用户结果。
2. 更新过期交接快照，避免新聊天重复处理已合并 PR。
3. 使用隔离 test database 跑完整 PostgreSQL 集成套件。
4. 冻结三分钟 `NOW → Event Detail → ASK` 路演与截图/录屏备用。

不得以“质量收尾”为名新增错误态入口、页面、API、模型、信息源或其他产品能力。

### D3 — Demo 验证

```bash
./scripts/demo.sh status
curl -fsS http://127.0.0.1:8000/api/v1/health
```

真实浏览器至少验证：

```text
称呼 → Onboarding → NOW → Event Detail → ASK
选择多个 Event → direct Ask
开启增强搜索 → Research Ask
展开“已思考”阶段
历史具体回答 → 新增提问
Save → Archive → Search
Settings → Maintenance status
```

涉及真实 Provider 的 ASK/Research 测试必须遵守既有数据授权；路演优先准备无需 Grok 的 direct Ask。

### D4 — 提交冻结后的修复

每个获准修复使用独立 `codex/*` branch 和 PR；必须携带 `release-approved`，通过
`Release freeze gate`，完成检查并经人工批准后才能合并。任何新功能请求一律暂停到明确解除冻结之后。

---

## 6. 已知边界与非阻塞项

- API 中仍有一个 Starlette `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning；当前测试通过，可在独立小 PR 更新为新常量。
- 历史 Event 内容可能仍有英文；Localization 是异步 projection，不得用 Frontend 临时翻译覆盖 immutable snapshot。
- Grok 依赖本机 CLI 和可用认证；不可用时 Research capability 必须稳定 fail-closed，direct Ask 仍可工作。
- 模型 Provider 会有额度或 5xx 波动；不要求把所有模型逐个做全流程压力测试。默认路径和被修改路径优先。
- 当前 Demo 数据复用本机已完成事实层，不把凭据、真实用户数据或数据库 dump 提交仓库。
- `scripts/demo.sh` 的后台进程可能被一次性执行宿主回收；持久会话内运行可规避，仍应以 status/heartbeat 为准。

---

## 7. Secret 与本机数据

当前 `.env` 包含本机配置的 Provider keys。规则：

- 不读取后复制到聊天、PR、日志或文档。
- 不加入 Git。
- 不在测试输出打印配置对象或请求 headers。
- 不把 keys 写进 shell history 示例。
- POK 当前不使用。

本机数据库、Telegram session、OpenClaw state、Research state、backup dump 和 `.state/` 均不进入 Git。

用户已经授权的模型数据边界只用于冻结合同允许的测试；新用途或新增敏感数据范围需要重新确认。

---

## 8. 分支与提交规范

推荐：

```text
codex/<task-name>
```

Commit（冻结期间不允许 `feat`）：

```text
fix(scope): summary
docs: summary
test(scope): summary
```

每个 PR：

- 单一审查目标。
- 包含测试和生成合同。
- 无 Secret。
- 合并固定 Squash Merge。
- 合并后删除远端短期分支可选，但不得删除 tag 或历史 release。

---

## 9. Definition of Done

功能切片只有同时满足以下条件才完成：

1. 产品行为符合 `plan_final.md`。
2. 视觉行为符合 `style_final.md`。
3. 技术边界符合 `tech_final.md`。
4. Schema/OpenAPI/Generated Types 一致。
5. Backend、Frontend、build 和 diff check 通过。
6. 涉及页面时完成真实浏览器验收。
7. 涉及 Worker/模型时验证失败、重试、幂等和恢复。
8. 不泄露 Secret、Profile、Raw 私密正文或 provenance。
9. PR 可独立审查。
10. 未经明确指令不合并。

---

## 10. 给新聊天的简短任务模板

可直接粘贴：

```text
请接管 /Users/alan/.codex/worktrees/88dd/infoscope。
先只读核验 Git、当前开放 PR、PR #77 / #78 的已合并状态和 Demo 状态，并完整阅读
plan_final.md、dev_final.md、style_final.md、tech_final.md。
以 contracts/openapi.json、Backend Schema、migration 和代码为实现事实源。
保护 .env/.state/数据库备份，不输出任何 key。
不要把 PR #77 或 PR #78 当作待办；先报告当前状态，再执行我接下来的需求。
未经明确指令不要合并新的 PR。
```
