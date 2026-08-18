# Infoscope 最终开发收口 / dev_final.md

> 状态：已由 Alan 确认冻结，执行中
> 日期：2026-08-18
> 适用仓库：`SCOUT-Infoscope/infoscope`
> 目的：在 Lingjiu 转入 `infoscope-display` 硬件开发后，收口 Infoscope 应用端 Demo、前端体验与最终验收。

---

## 0. 文档优先级与职责

本文件是 `plan.md`、`tech.md`、`style.md`、`dev.md` 之后的最终增量说明。冲突时，仅以下明确覆盖项以本文件为准；未提及部分继续遵守原基线。

明确覆盖：

1. Ask 从 Event 页面底部工具升级为与 NOW 同级的一级工作区。
2. 应用端尚未完成的 Lingjiu Phase 6 职责全部转由 Alan/Codex 完成。
3. Lingjiu 转入 `infoscope-display`，从已批准硬件基线继续 A1，不再承担当前 Infoscope 应用前端切片。

长期职责：

- `infoscope`：MQTT Display Contract 的唯一权威源，拥有 Schema、canonical fixture、版本升级和破坏性变更。
- `infoscope-display`：只按批准基线 vendoring canonical fixture，记录上游 immutable commit SHA 与 SHA-256；不得建立第二份权威 Schema。
- MQTT Contract 若未来重新推进，仍须在独立 PR 完成审查和测试后合并；已关闭的
  PR #45 不作为本轮应用端 Demo Freeze 的门禁。

---

## 1. 最终执行顺序

严格按以下顺序推进，不因 UI 修改跳过运行时可靠性：

```text
F0  MQTT Display Contract v1（已退出本轮应用端收口）
↓
F1  Demo Runtime Readiness
↓
F2  Phase 6 前端与全流程验收
↓
F3  最终 UI / UX 改造（问题 1–8）
↓
F4  Final Demo Freeze
```

每个阶段独立 task branch、独立 PR、测试通过后 Squash Merge。

---

## 2. F0 — MQTT Display Contract v1

状态：Alan 已明确关闭并忽略 GitHub PR #45。本节保留长期 Contract 所有权与安全
边界，供未来独立重启该工作时使用；F1–F4 与 PR #70 不再等待 PR #45。

必须保持：

- 主仓库新增权威 `display-events-v1` JSON Schema、canonical fixture、README 与 Contract tests。
- 不新增 live publisher、数据库/API、device binding、Pipeline 或固件。
- `infoscope-display` 不复制 Schema，不迁移 Contract 所有权。
- 硬件仓库后续只复制 canonical fixture，并记录 PR #45 最终 merge commit SHA 与 fixture SHA-256。

冻结前补充：

- 明确 `event.id`、`event.state` 在 Display Contract v1 中是 opaque metadata。
- A1 终端只消费标题，不得根据 `state` 过滤、排序、着色、显示状态图标或拒绝未知但 Schema 合法的值。
- 若不采用 opaque 语义，则必须把 `state` 冻结为明确 enum 并增加拒绝测试；不得保持语义模糊。

未来若重新创建 MQTT Contract PR，Lingjiu 只能在该独立 PR 完成后开始对应 fixture
vendoring 与 simulator/host tests。

---

## 3. F1 — Demo Runtime Readiness

### 3.1 启动与进程所有权

当前问题：旧 API 占用 8000 时，`demo.sh start` 可能请求到旧进程并错误打印 ready；新 API 实际绑定失败，PID 文件与真实进程不一致。

必须修复：

- 启动前检查目标端口；发现未知监听进程时 fail-closed，输出 PID/命令摘要，不自动 kill。
- API 健康返回后再次校验本轮 API PID 与命令身份。
- Worker 同样校验 PID、命令身份和持续存活。
- `status` 必须区分 `running / stopped / stale pid / port conflict`。
- `stop` 只能终止身份匹配的本轮进程，不能误杀复用 PID。
- macOS 与 Ubuntu 26.04 LTS 使用共同可用的 `ps`/端口检查路径。

### 3.2 真实 Health

当前 `worker: ok` 是固定值，即使 Worker 不存在也返回正常。

必须实现：

- Worker heartbeat 存储与超时判定。
- `/api/v1/health` 的 Worker 状态来源于真实 heartbeat。
- API/DB 正常但 Worker 缺失时，不得返回整体完全健康。
- Public Health 不泄露队列内容、任务参数、凭据或内部主机信息。

### 3.3 Maintenance 全链验收

必须完成一次真实：

```text
Window Analysis
→ Event Reconstruction
→ Claims
→ Timeline
→ Conflicts
→ Base Analysis
→ Event Backwrite
→ Personalization
→ Brief
```

验收要求：

- Maintenance terminal status 为 completed。
- 失败阶段保留稳定错误码，不留下部分成功状态。
- Worker 重启后 pending/running 状态可安全恢复或 fail-closed。
- 不重复调用已具 canonical artifact 的模型步骤。

### 3.4 Research Capability

当前 OpenClaw 可执行文件存在，但 Agent-Reach 与 Research 专用配置未就绪。

必须完成：

- Demo preflight 明确检查 OpenClaw、Agent-Reach、隔离 HOME/config/state/workdir。
- Research 不可用时 UI 与 API 给出稳定、可理解状态，不伪装成处理中。
- Ask 直接回答路径可独立工作；需要 Research 的路径只有 capability ready 后才进入运行。

### 3.5 模型演示策略

- 共享事实层固定使用已完整验证的 DeepSeek Flash。
- GPT-5.5、Kimi 可用于 Personalization、Brief、Ask。
- Qwen 在严格合同稳定通过前标记为实验性或不可用，不作为现场默认选项。
- 不在 Demo 中进行 50-Signal 多模型压力对比。

### 3.6 Demo 数据

必须提供可重复、可识别的 Demo 数据准备流程：

- 不依赖某次本机数据库偶然残留。
- 明确复用现有完整事实层还是从受控 fixture 恢复。
- Demo 用户、Profile、Personalization、Brief 必须可重复准备。
- 不把真实账户密码、API Key、Telegram 身份或私密 provenance 写入仓库。

### 3.7 历史 Event 中文展示投影

历史 Event 汉化与 F1/F2 其他开发并发推进，不等待全部 UI 工作结束。

固定模型与调度：

- 渠道：AI Ping。
- 模型：`DeepSeek-V4-Flash-0731`。
- Key group：现有 AI Ping group 1，由 Backend 配置读取，不写入任务、日志或 artifact 正文。
- 默认每批 10 个 Event，并发 2；可配置但 v1 最大并发不得超过 3。
- 每 5 分钟读取持久化 run/batch 状态并报告进度；不得靠扫描日志或模型正文判断完成。
- 任务可与代码开发并行，但不能与同一 Event 的事实层写事务互相覆盖。

数据安全前置：

- 第一次写入任何汉化数据前，必须生成完整 PostgreSQL custom-format dump。
- 备份必须包含 Raw Information、Signals、Events、Claims、Timeline、Conflicts、Base Analysis、Pipeline artifacts/runs、Research、Ask、Personalization、Brief、用户关系和迁移版本。
- 备份目录权限为 `0700`，dump/manifest 为 `0600`；保存 SHA-256、文件大小、Alembic revision 与关键表行数。
- 使用 `pg_restore -l` 验证归档结构；恢复演练只能进入独立空数据库，不得覆盖 live database。
- 备份与 manifest 都属于本机私密数据，不进入 GitHub、Forgejo、普通日志或 Demo 包。

事实边界：

- 不直接覆盖 `events.title`、`events.overview`、Base Analysis、Claim、Timeline、Conflict、Evidence 或历史 PersonalizedEvent/Brief snapshot。
- 新增独立、可审计的 `zh-CN` Event localization projection；Public API 只在 localization 与当前 Event 输入 hash 一致时使用。
- Event 更新导致输入 hash 变化时，旧 localization 立即视为 stale，Public API 回退原文，后台重新排队。
- 历史 Personalization 与 Brief 保持 immutable；汉化完成后为 ready users 生成新的 Personalization/Brief snapshot，不改写旧 artifact。

最小模型输入：

- `event_id`。
- 当前 `title`。
- 当前 `overview`。
- 为避免语义漂移所需的最小状态/时间上下文。
- 不发送 Raw、Signal/Evidence 正文、provenance、collector metadata、用户 Profile、账户数据或内部 Prompt 历史。

严格模型输出：

- 每个输入 Event 恰好返回一个相同 `event_id` 的中文 `title` 与 `overview`。
- 不允许新增、删除、合并 Event，不允许改变数字、时间、状态、专有名词、URL 或事实含义。
- Backend 校验 ID 完整覆盖、唯一性、长度、输入 hash 与中文内容要求；任一失败则整批不持久化。
- 已是合格中文的文本允许保持原文，不为了“改写感”强制润色。
- 模型返回后重新锁定/复核 Event 输入；变化时以稳定错误码丢弃旧输出并重新排队。

持久化与恢复：

- 使用独立 localization run、batch、artifact/projection，不伪造 PipelineRun、PersonalizationRun 或 Event 更新。
- run 保存 provider/model、input hash、batch count、completed/failed counts、稳定错误码、token usage 和时间；不保存凭据或普通日志中的正文。
- batch 按稳定 Event ID 顺序构建；成功批次按 input hash 幂等复用，失败批次可单独重试。
- 进程重启后从持久化状态继续；不得重新调用已成功且输入未变化的批次。
- 489 个历史 Event 完成后生成覆盖报告，并触发新的用户级 Personalization/Brief，而不是直接修改历史页面快照。

---

## 4. F2 — Lingjiu 剩余应用职责转交

以下原 Phase 6 前端职责由 Alan/Codex 接管：

- Frontend bug fix。
- Loading / Error / Empty / Success 全页面复核。
- Desktop、窄桌面与基础移动布局。
- Keyboard、focus、dialog focus trap、semantic heading、contrast、reduced motion。
- Demo flow polish。
- Frontend lint/typecheck/test/build 稳定化。
- 完整浏览器 E2E 演练。
- Contract consistency 与 Source privacy review。

至少覆盖页面：

```text
Auth
Onboarding / SCOPE
NOW
ASK
Event Detail
BRIEF
ARCHIVE
Search
SETTINGS
Maintenance
```

---

## 5. F3 — 最终 UI / UX 问题清单

本节对应 Alan 新提出的问题 1–8，排在运行时与 Phase 6 基础验收之后实施。

### 问题 1 — Search 入口与关闭按钮不明显

现状：顶部 Search 入口视觉权重不足；Overlay 的 `Close` 是普通文本，难以发现。

目标：

- 顶部入口显示放大镜图形、`搜索` 文案与 `⌘K`，形成克制的全局工具入口。
- Search Overlay 右上角使用清晰的叉形关闭按钮。
- 关闭按钮为圆形或柔和圆角 icon button，不能只是 `Close` 文本。
- 点击区域至少 40×40，包含 `aria-label="关闭搜索"`、hover、active、focus-visible。
- `Escape` 关闭，关闭后焦点回到原搜索入口。
- 不复制第三方产品资产；使用符合 IS 线宽、网格与颜色角色的自有叉形图标。

### 问题 2 — NOW Event 下方英文内容不明确

截图中的英文段落是 `why_it_matters`，即 Personalization 生成的“为什么与你相关”。当前缺少标签且模型输出为英文，用户无法判断它是什么。

目标：

- 在该段落前增加清晰标签：`为什么值得关注`。
- 用户可见 `why_it_matters` 由 Backend Personalization 直接生成中文；Frontend 不进行临时机器翻译。
- 已有英文 immutable snapshot 通过重新运行 Personalization 更新，不在展示层偷偷改写。
- NOW 顶部统计、时间和 Event metadata 使用统一中文格式。

### 问题 3 — 软件汉化

先完成系统 UI 文案汉化，再决定事实内容语言。

第一批必须汉化：

- 登录、注册、Onboarding、Loading/Error/Empty/Success。
- 搜索、保存、取消保存、重试、返回、提交、清除选择。
- NOW 统计、Maintenance 状态、模型设置说明。
- Ask 页面、发送状态、Research/失败提示、Event 更新提示。
- 日期时间使用中文 locale，但 Backend 时间仍为 UTC ISO 8601。

不得翻译：

- 模型/厂商正式名称。
- 人名、公司名、产品名、来源名和 URL。
- Evidence 原文。

汉化边界：

| 项目 | 推荐方案 |
| --- | --- |
| 侧边导航 | **不汉化**；固定保持 `NOW / ASK / BRIEF / ARCHIVE / SCOPE / SETTINGS` |
| NOW 页面 | 侧边导航保留 NOW；页面主标题、统计和说明使用中文 |
| ASK 页面 | 侧边导航固定 ASK；页面内使用“询问观澜” |
| BRIEF 页面 | 侧边导航固定 BRIEF；页面标题和说明使用中文 |
| ARCHIVE 页面 | 侧边导航固定 ARCHIVE；页面标题和说明使用中文 |
| SCOPE 页面 | 侧边导航固定 SCOPE；页面标题、问题和提示使用中文 |
| SETTINGS 页面 | 侧边导航固定 SETTINGS；设置项、状态和说明使用中文 |
| Event title/overview | 新事实层优先生成中文；既有 489 Events 使用 AI Ping `DeepSeek-V4-Flash-0731` 有界并发生成独立 `zh-CN` 展示投影，不覆盖事实层 |
| Ask answer | 跟随中文 UI，默认中文；用户明确用其他语言提问时可跟随问题语言 |

侧边导航的英文大写名称属于产品信息架构与 Editorial metadata，不得改成中文、双语或英文下方附中文小字。

产品术语固定：用户可见的 `Signal/signal` 统一称为“因子”；`Raw` 与 `Event` 保留英文产品名。数据库表、Backend 类型、OpenAPI 字段和代码标识继续使用 `signal`，本次不进行破坏性内部重命名。NOW 顶部通过 Backend `corpus_stats` 展示数据库当前累计的全部 Raw 与 canonical Signal（因子）数量；当前 Event 数仍取用户最新 immutable Personalization artifact 的 relevant Event 数。Frontend 不自行查询或推算。

### 问题 4 — Ask 升级为一级页面

#### 4.1 导航与路由

- 左侧一级工作区增加 `ASK`，与 NOW、BRIEF、ARCHIVE 同级；页面内部主名称使用“询问观澜”。
- 推荐顺序：NOW → ASK → BRIEF → ARCHIVE；SCOPE、SETTINGS 保持配置区。
- 新路由使用 `#ask`。
- Event Detail 不再渲染底部 Ask 输入框。

#### 4.2 单 Event 入口

- Event Detail 底部改为一个漂亮、克制、符合 Editorial 风格的 `询问这个事件` 按钮。
- 按钮点击后携带该 Event 的 ID 与标题快照进入 Ask 页面。
- Ask 页面仍允许增加或取消其他 Event。
- 从 Archive/Search/Event Detail 携带的已选 Event 即使不在当前 NOW 首屏，也必须保留在已选上下文中。

#### 4.3 Ask 页面左栏 Event 列表

当 Ask 激活时，在 SETTINGS 下方：

```text
────────────
Event 列表
Event title
Event title                         已选深色态
...
```

规则：

- Divider 使用 style.md 的细线系统。
- `Event 列表` 使用灰色小型 Meta 文本。
- Event row 整行可选择；不显示浏览器默认复选框。底层保留语义化 checkbox 供键盘与读屏使用。
- 选中项以更深文字、轻背景和左侧细指示条表达，不能只靠颜色；不显示内部 ID。
- 使用 Backend NOW 顺序，不在 Frontend 二次排序。
- 最多选择 8 个 Event；达到上限后禁用未选择项并给出解释。
- 列表是独立滚动区，不能把整个 Sidebar 无限拉长。
- Keyboard 可达，语义化 checkbox 有完整 Event title accessible name。

#### 4.4 Ask 主布局

空状态居中显示：

> 观澜能帮忙做什么

其下是类似现代对话产品的输入 composer，但保持 IS 的冷静编辑式风格：

- 默认输入框为空。
- 输入为空时不显示强强调发送按钮。
- 输入出现有效文字时，发送按钮淡入并可用。
- 发送按钮使用自有上箭头/发送图形，不复制 ChatGPT 专有资产。
- 明确显示当前选中的 Event 数量与标题上下文。
- 发送后冻结该轮 Event ID 与标题快照，不受用户随后勾选变化影响。
- pending/running 时禁止重复提交，但允许浏览历史。
- 提交后 composer 下沉并 sticky 于工作区底部；用户问题以右侧气泡呈现，观澜回答在左侧自然排版，保持 Editorial 字体与间距，不复制 ChatGPT 专有视觉资产。
- 处理中只展示 Backend 可审计阶段（Event 数据库比较、Research、Reconciliation、Finalization）与累计耗时，不展示、存储或伪造模型私有 Chain-of-Thought。
- 完成或失败后阶段轨迹默认折叠为 `已思考 xx 秒`，用户可展开查看公开阶段；输入框立即恢复，可继续提交下一轮独立 Ask。
- 结果始终明确 Answer ≠ Evidence；Event 有补充时显示 `事件信息已补充` 并 refetch NOW/Event Detail。

#### 4.5 Ask 历史浮动栏

- Ask 历史使用圆角、克制毛玻璃的浮动 Context Panel；Glass 只用于该真实浮层。
- 默认折叠，不长期压缩正文宽度。
- hover、focus 或显式展开按钮可临时展开。
- 提供 pin 按钮固定展开；使用通用、自有的置顶图标，不复制 ChatGPT 二进制/专有图形资产。
- 固定状态持久化到本地 UI preference；不包含问题正文或答案正文的 localStorage 缓存。
- 历史记录必须 owner-only。
- 只要 Ask 页面当前选中了 Event，Frontend 自动载入 owner history 中与任一所选 Event 相关的最近 Ask，并按时间正序渲染为左右对话；当前正在 Poll 的 Ask 按 `ask_id` 去重。

Backend Contract 前置：

- 当前 API 只有创建与按 ID Polling，没有历史列表 Contract。
- 实现前必须先冻结 owner-only Ask history API、分页、排序、公开摘要字段和隐私边界。
- v1 每条历史记录仍是一轮独立 Ask；本轮不擅自升级为具有跨轮模型记忆的多轮会话。
- 不从内部 artifact、Prompt、模型元数据或 Evidence 正文拼装公共历史 DTO。

### 问题 5 — 按钮视觉质量

建立统一 Action System：

- Primary：少量关键提交动作，使用克制实心或高对比边框，不使用巨大灰色方块。
- Secondary：细边框、轻圆角、明确 hover/focus。
- Icon button：只用于搜索关闭、保存、发送、pin 等“图形比文字更快”的动作。
- 每个 icon button 必须有 tooltip/accessible label。
- 最小交互区域 40×40；关键触控目标建议 44×44。
- 禁止把普通链接、保存状态和主要提交按钮全部做成同一种 `text-button`。

具体替换：

- `Save event / Remove saved` → 书签图形 toggle；保存态有结构差异，不只靠颜色。
- `Ask Infoscope` 灰色方按钮 → Event Detail 的 `询问这个事件` Editorial action。
- Search `Close` → 叉形 icon button。
- Ask 发送 → 输入有效时出现的圆形发送按钮。
- 处理中按钮显示紧凑 progress，不改变宽度造成跳动。

### 问题 6 — SETTINGS 模型选择器

移除两个并排的原生大 Select 作为主要视觉。

推荐结构：

```text
模型来源
DeepSeek 官方
GPT-5.5
AI Ping
────────────
可用模型
Flash / Pro / Kimi / Qwen ...
```

实现规则：

- 使用语义化 radio group，视觉为严格对齐的 Editorial selection rows，而不是卡片墙。
- 来源选择后，下方模型列表平滑更新。
- 每项显示名称、可用/不可用状态和必要的一行说明。
- 不可用项可见但不可选，说明“服务端未配置”或“暂不稳定”。
- Shared fact default 与个人偏好边界使用中文解释。
- 只有 dirty 时显示/启用 `保存模型设置`。
- 保存成功、失败、处理中不引发布局跳动。
- Qwen 在严格合同稳定前不得伪装为正常推荐模型。

### 问题 7 — 页面与 Sidebar 动画

#### 7.1 Active indicator

- 当前选项左侧灰色/Accent 细指示条不重新闪现，而是在旧项和新项之间滑动。
- 使用单一共享 indicator，通过测量目标位置更新 `transform: translateY(...)` 与高度。
- 动画只表达导航状态，不使用 bounce、overshoot 或 spring。

#### 7.2 通用页面切换

参考 SCOPE 现有选择推进节奏：

- 当前内容先轻微淡出并位移 2–4px。
- 新内容轻微淡入并回到基线。
- 不等待数据请求完成才开始导航；Loading state 使用同一容器。
- 不让 Sidebar、Header 或内容宽度跳动。

#### 7.3 进入 Ask 的专用序列

顺序：

```text
当前内容淡出
→ SETTINGS 下方 Divider 展开
→ “Event 列表”标签出现
→ Event rows 以轻微 stagger 逐渐浮现
→ Ask 主标题与 composer 淡入
```

退出 Ask 时反向收起，不残留 Event 列表。

建议总时长保持约 180–320ms；列表 stagger 很短，不能让大量 Event 造成长时间等待。

#### 7.4 Reduced Motion

`prefers-reduced-motion: reduce` 时：

- Indicator 直接到位。
- 页面与列表取消位移/stagger，只保留即时 opacity 或完全无动画。
- 功能与焦点顺序不得依赖动画。

### 问题 8 — 已注册用户修改 SCOPE 的生效提示

首次注册后的 Onboarding SCOPE 不显示额外提示；用户完成注册与 Onboarding 后，从 `SCOPE` 页面编辑现有关注范围时，在标题：

> 哪些内容进入你的视野？

正下方显示红色小字：

> 更改将在下次Event更新时生效

实现规则：

- 判断依据必须是 Backend/路由已经明确的“编辑现有 SCOPE”状态，例如当前 `editExisting` 语义；不得使用 localStorage、页面访问次数、是否已有选项或数组长度猜测。
- 仅在已完成首次 Onboarding 的编辑流程显示；注册后的首次设置不显示。
- 文案位置固定在主标题下、选项说明或表单上方，不随选择变化反复出现/消失。
- 使用设计系统中的语义警示红色、小型 Meta 字号；颜色克制但对比度满足可访问性要求。
- 不能只靠红色传达含义；文本必须始终完整可读，并使用适当的说明语义供读屏读取。
- 严格使用上述文案，不显示内部任务、队列、Personalization 或 Maintenance 状态。
- Event 更新完成并重新生成用户快照后的实际行为必须与提示一致；如果 Backend 当前会立即生效或采用其他调度语义，先修正 Contract/实现，不能仅修改前端文案。

---

## 6. API 与数据边界

- Frontend 继续只使用 Generated Types。
- 新 Ask history 必须先 Backend Schema → OpenAPI → TypeScript generation。
- Event 列表不得扫描全库，只能使用当前用户有权访问的 NOW/Historical Access 数据。
- Frontend 不解析 cursor，不自行排序，不猜模型状态。
- 汉化不得修改 Evidence 原文或 provenance。
- UI 动画不得改变请求、Polling、幂等或事务语义。

### 6.1 Grok 联网 Research 渠道

- 本轮模型生成渠道固定使用 AI Ping，已确认剩余额度足够；POK 只登记为未来 failback，本轮不得探测、调用或自动切换至 POK，以免引入额外变量。
- Grok 只可作为用户在 ASK composer 中主动开启的 X/实时 Research 补充来源；不得用于 Maintenance、自动 Event Backwrite、Personalization 或 Brief，也不能直接写入 Event、Claim、Timeline、Conflict 或 Base Analysis。
- 渠道必须完整兼容 OpenAI Responses 语义：`POST /v1/responses`、服务端 `web_search` 工具调用，以及可审计的 citations/source URLs；仅能列出模型或仅兼容 Chat Completions 不算可用。
- `grok-build-0.1`、`grok-4.5` 等模型名本身不代表联网能力；接入前必须用真实搜索请求验证工具调用与来源 URL。
- 搜索结果仍必须进入既有 Research Request → Raw → Normalize → Signal → canonical deduplication → Reconciliation 流程；前端可见术语继续写作 `Signal`，中文产品定义为“因子”。
- 来源抓取必须执行 SSRF 防护、协议 allowlist、响应体长度限制、超时和隐私过滤；不得向渠道发送账户凭据、Raw、私密来源身份/provenance 或 API Key。
- 渠道暂时不可用、未返回来源或不支持服务端搜索时必须 fail-closed，不能退化为依赖模型记忆回答，也不能把无来源文本写入事实层。
- 本机 Sub2API/Grok Build 反代当前探测结果为：模型列表可用，但最小 Responses 与 `web_search` Responses 均返回 `Service temporarily unavailable`；在通过上述能力探测前不进入正式配置。
- 官方 Grok Build CLI 1.0.5 已通过独立能力探测：`grok-4.6` 的 `streaming-json` 明确产生 completed X Search 工具事件，查询 `from:githubstatus` / Latest，并返回可核验的 `x.com` 原帖 URL、发布时间和正文；该 CLI 可进入下一独立切片。
- 正式接入使用专用 `GrokXResearchCollector`，定位为 X/实时信息补充源，而不是默认模型或事实写入器。Collector 必须只消费 Backend 构建的 public-safe 查询，不接收 Raw、private_sanitized Evidence、Profile、账户数据、完整 Ask 历史或内部 provenance。
- ASK 输入框内部提供轻量 `增强搜索` 下拉菜单，开启选项文案为 `开启 Grok`，默认关闭。开关按单次 Ask 冻结并持久化，提交后不可被下一轮选择覆盖；未开启时不得调用 Grok CLI，历史详情不得暴露该内部执行配置。
- Collector 必须解析有上限的 `streaming-json`，至少验证一次目标 X Search/Web Search 工具调用成功、最终输出满足严格 Schema、每个候选为规范化 `https://x.com/<account>/status/<id>` URL，并记录查询、检索时间、模型、CLI 版本和 token/cost usage；不得记录 OAuth、Cookie、会话令牌、思维文本或完整模型流水。
- X 结果必须作为公开 Raw 独立持久化，随后经过 Normalize → Signal → canonical deduplication → Reconciliation；模型输出不能直接成为 Claim、Timeline、Conflict、Base Analysis 或 Event 更新。
- CLI 不可用、未实际调用搜索工具、输出超限、URL/时间/正文不一致或没有可审计来源时，该补充源 fail-closed；原 Research 主链可继续，不能将补充源失败伪装为成功来源。
- Grok 接入必须位于 PR #70 完成后的独立 `feat/research-grok-x`，避免扩大 Demo Freeze 的回滚与审查单元。

### 6.2 Ask 历史详情

- 历史列表项必须可选择；选择后在 ASK 主区域展示该轮完整问题、公开回答、状态、Event 数量和是否补充 Event，历史浮层保持可切换。
- 提供 `新建提问` 返回 composer；查看历史不得改变当前 Event 选择、创建新 Ask 或重新触发 Polling/Research。
- 不显示内部 ID、Prompt、模型/provider、token、artifact、Research rationale、Evidence/provenance 或内部错误码。
- Event 名称若要展示，必须来自 Ask 创建时保存的有序标题快照；不得用当前 Event 标题回填历史，也不得向用户显示裸 UUID。

---

## 7. 推荐 Branch / PR 顺序

```text
feat/integration-mqtt-contract          # PR #45，Lingjiu 修复，Alan 审查
fix/demo-runtime-readiness              # API/Worker/Health/startup
fix/maintenance-e2e                     # Maintenance 全链与 Research capability
feat/event-localization-contract        # zh-CN projection、run/batch 与 Public DTO Contract
feat/worker-event-localization          # AI Ping 并发汉化、续跑与进度检查
fix/frontend-demo-freeze                # 原 Lingjiu Phase 6 剩余项
feat/frontend-ask-workspace-contract    # Ask history Public API Contract
feat/frontend-ask-workspace             # Ask 一级页面与 Event picker
feat/frontend-localization              # UI 汉化与模型输出语言
fix/frontend-visual-polish              # Search、按钮、Settings、动效
fix/final-demo-freeze                   # 最终 E2E、隐私与演示冻结
```

若 Ask history 需要数据库 Migration，API Contract 与 Frontend 必须拆成独立 PR，不能在 Frontend 中猜字段。

---

## 8. 每个 PR 的最低验证

```bash
uv run --project backend --no-sync ruff check backend/src backend/tests scripts
cd backend && uv run --no-sync python -m pytest -q
uv run --project backend --no-sync python scripts/generate_openapi.py --check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
git diff --check
```

涉及浏览器交互时额外验证：

- Desktop 16:10、16:9、窄桌面。
- Keyboard-only。
- reduced motion。
- Search focus return。
- Ask Event carry-in、1–8 多选、Polling、失败、完成、历史折叠/pin。
- 中文与中英混排不溢出。

---

## 9. Final Demo 验收

只有同时满足以下条件，才能称为完整 Demo：

1. 一条命令可靠启动 API、Worker、PostgreSQL 和 production frontend。
2. Health 真实反映 Worker。
3. Demo 数据可重复准备。
4. 登录 → NOW → Event → Ask → 必要时 Research → Event 更新可完成。
5. Brief、Archive、Search、Save、SCOPE、SETTINGS 可正常使用；已注册用户编辑 SCOPE 时显示正确的下次 Event 更新生效提示。
6. Maintenance 至少一轮完整成功。
7. UI 主要文案中文化，英文内容有明确语义来源。
8. 历史 Event localization 使用独立投影完成或显示可审计进度，不改写事实层与旧快照。
9. Search、按钮、模型设置和 Ask 页面达到本文件视觉要求。
10. 动画克制、可降级、不阻塞交互。
11. 不泄露 Raw、私密 provenance、凭据、内部 Prompt 或模型响应正文。

---

## 10. 明确不做

- 不复制 ChatGPT 专有图形资产或逐像素克隆页面。
- 不把 Ask 变成无 Event 上下文的通用聊天机器人。
- 不在本轮引入 WebSocket、Redis、Celery 或新前端框架。
- 不让 Frontend 翻译 Evidence 或重写事实层。
- 不在硬件仓库维护第二份 Schema。
- 不在 Demo Freeze 中进行大规模架构重构。
