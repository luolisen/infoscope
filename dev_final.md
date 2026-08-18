# Infoscope（观澜）最终开发交接 / dev_final.md

> 状态：0.1 Demo 可用；ASK 对话体验 PR 待审查
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
gh pr view 77 --repo SCOUT-Infoscope/infoscope \
  --json state,headRefName,headRefOid,baseRefOid,mergeStateStatus,url
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
| 当前 branch | `codex/ask-chat-experience` |
| 当前功能提交 | `8dc3796`（文档提交会继续前进） |
| Open PR | GitHub PR #77 `feat(ask): add conversational workspace` |
| PR 状态 | OPEN、CLEAN |
| PR base | `origin/main` at `f44c357` |
| 可用版本 tag | `0.1` at `97fd66f` |
| Demo | API running、Worker running |

注意：worktree 的本地 `main` 曾落后于 `origin/main`。新聊天创建后续分支时应以最新 `origin/main` 为基线，不要盲信未 fetch 的本地 `main`。

PR #77 当前不应由文档生成任务自动合并。完成审查或收到 Alan 明确合并指令后再 Squash Merge。

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

当前最近一次完整检查：

- Backend：297 passed，12 skipped。
- Frontend：37 passed。
- Frontend production build：通过。
- OpenAPI generation check：通过。
- ASK 浏览器验收：通过。

这些数字是 2026-08-19 的快照；新提交后必须重新运行检查，不能把历史结果当当前结果。

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

## 4. PR #77：ASK 对话体验

PR #77 已实现：

- ASK 成为与 NOW 同级的一级页面。
- Event Detail 使用“询问这个事件”按钮携带上下文进入 ASK。
- 左侧 Event 列表整行选择；隐藏默认 checkbox，选中后加深并出现左侧指示条。
- 最多选择 8 个 Event。
- 空状态居中“观澜能帮忙做什么”。
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

本 PR 的最后实现提交：

```text
8dc3796 fix(ask): show auditable processing stages
```

文档提交后 head 会变化；以 `gh pr view 77` 的 `headRefOid` 为准。

---

## 5. 下一步严格顺序

### D1 — 审查 PR #77

检查重点：

1. `AskProgress.stages` 与 `AskHistoryItem.process_stages` 是否只暴露公开阶段。
2. direct path 不得虚构 Research/Reconciliation。
3. research path 必须在存在 reconciliation artifact 时显示完整阶段。
4. owner-only history 不泄露 Prompt、provider/model、artifact ID、Evidence/provenance。
5. composer、history、Event rail 在常见 viewport 不互相遮挡。
6. Generated OpenAPI/TypeScript 与 Backend 一致。

审查后运行：

```bash
./scripts/check.sh
git diff --check
```

### D2 — 按明确指令合并

只有审查通过且 Alan 明确要求合并时：

```bash
gh pr merge 77 --repo SCOUT-Infoscope/infoscope --squash
```

不要在没有新指令时自动合并。

### D3 — 合并后验证 main

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
./scripts/check.sh
./scripts/demo.sh restart
./scripts/demo.sh status
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

### D4 — 创建下一任务

所有新建议必须单独建 `codex/*` branch 和 PR。不得继续在已合并 PR branch 堆叠无关功能。

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

Commit：

```text
feat(scope): summary
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
先只读核验 Git、PR #77 和 Demo 状态，并完整阅读
plan_final.md、dev_final.md、style_final.md、tech_final.md。
以 contracts/openapi.json、Backend Schema、migration 和代码为实现事实源。
保护 .env/.state/数据库备份，不输出任何 key。
先报告当前状态，再执行我接下来的需求；未经明确指令不要合并 PR。
```
