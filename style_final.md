# Infoscope（观澜）最终视觉与交互规范 / style_final.md

> 版本：0.1 Demo 后续视觉基线
> 更新时间：2026-08-19
> 继承 `0.7.zip/style.md` 的设计语言，并以当前实现与 Alan 最新确认覆盖过时部分。

---

# 0. 设计命题

Infoscope 应该像：

> 一个安静、精确、持续更新的编辑式情报终端。

设计组合：

```text
Editorial Intelligence
+ Swiss Information Design
+ Native Productivity UI
+ Restrained Glass
```

不是新闻网站、卡片 Dashboard、AI 渐变 SaaS 或 ChatGPT 换皮。

ASK 可以采用现代 Web 对话产品成熟的空间关系——用户在右、回答在左、composer 在底部、历史可折叠——但必须使用 Infoscope 自有字体、颜色、图标、栅格与信息语义。

---

# 1. 核心原则

## 1.1 Event-first

Event 始终是视觉和交互主体。来源、模型和 AI 状态服务于 Event，不能抢走主层级。

## 1.2 Typography as Interface

优先使用：

- 字号层级。
- 字重。
- 行距。
- 留白。
- 细分隔线。
- 严格对齐。

避免靠大量容器、阴影和彩色 Badge 建立结构。

## 1.3 Invisible Grid

所有标题、正文、meta、时间、按钮和列表边界必须落在稳定网格上。页面切换不能改变正文起始线和 Sidebar 宽度。

## 1.4 Density as Rhythm

- NOW/Event Detail：中等密度，突出阅读。
- Archive/Search/Event rail：较高密度，突出扫描。
- Auth/Onboarding/空 ASK：低密度，突出单一决定。
- Brief：低到中密度，突出连续阅读。

---

# 2. 当前颜色系统

当前 CSS 已使用以下角色；修改时优先保持角色，不随意加颜色：

| 角色 | 当前值 | 用途 |
| --- | --- | --- |
| Ink | `#172022` | 主文字、关键实心按钮 |
| Canvas | `#e9ecec` | 应用背景、Topbar |
| Paper | `#f5f6f5` | 浮层与输入背景混合基色 |
| Accent | `#20666a` | focus、链接、选中指示、关键动作 |
| Text secondary | `#526062` | 说明、正文次级信息 |
| Text muted | `#667375` | Meta、时间、状态 |
| Border | `#bac2c3` | 细分隔线 |
| Control border | `#829092` | 输入和次级 action 边界 |
| Error | `#93423c` | 错误与必要警告 |

原则：

- 状态不能只靠颜色表达。
- Accent 只用于焦点、选择和关键关系。
- 不新增紫蓝 AI 渐变。
- 不用大面积纯 Accent 作为装饰背景。

---

# 3. Typography

## 3.1 字体角色

- UI/正文：`Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`。
- Display/Editorial heading：`Georgia, "Times New Roman", serif`。
- 快捷键、数字和时间允许系统等宽数字特性，但不建立第三套装饰字体。

## 3.2 Display

用于 NOW、Event Detail、ASK 空状态、Brief 等一级页面标题：大字号、紧字距、较低 line-height、正常或中等字重。

## 3.3 Heading

用于 Event title 和二级 section，避免全部大写。

## 3.4 Body

长回答与 Event overview 行高约 1.6–1.75；最大阅读宽度约 44–52rem。

## 3.5 Meta / Editorial Label

小字号、稳定字重、适量 letter spacing。可使用英文产品名和状态，但中文界面说明必须可读。

---

# 4. App Shell

桌面：

```text
Topbar：4.25rem，高度固定、sticky
Sidebar：13.5rem，sticky，不随正文向下滚动
Content：minmax(0, 1fr)
```

Topbar 只保留：

- `IS` wordmark。
- Search 入口和 `⌘K`。

不得显示“系统在线”装饰状态。

Sidebar：

- 一级导航固定 `NOW / ASK / BRIEF / ARCHIVE`。
- 配置区固定 `SCOPE / SETTINGS`。
- 侧边导航不汉化。
- active indicator 是单一共享细条，在旧项和新项之间滑动，不重新闪现。
- ASK 激活时，Event 列表出现在配置区下方并拥有独立滚动区。

移动端小于 640px 时 Sidebar 变为横向导航区域；不能把桌面 Sidebar 固定宽度硬挤进屏幕。

---

# 5. Navigation 与 Motion

只保留三类动画：

1. 导航状态：indicator 平移和高度变化。
2. 内容进入：轻微 opacity + 2–4px translate。
3. Intelligence state：克制 pulse、细进度和文本变化。

推荐时长：160–240ms；大量 Event 的 stagger 每项约 24–30ms，不能导致长等待。

禁止：

- bounce、overshoot、夸张 spring。
- 页面飞入、3D、粒子。
- 用动画掩盖网络或模型等待。
- 切换页面时让 Sidebar、Topbar、正文宽度跳动。

`prefers-reduced-motion: reduce` 下取消非必要位移、stagger 与 pulse，状态仍须清晰。

路由切换后主内容滚动到顶部；特别是 NOW 长列表进入 Event Detail，不能继承旧 scroll position。

---

# 6. NOW

## 6.1 Header

标题：`现在，值得关注的变化。`

统计文案结构：

```text
Raw {total_raw_count} 条 · 因子 {total_signal_count} 个 · Event {current_event_count} 个
```

Raw 与因子是数据库累计值；Event 是当前用户最新 immutable Personalization artifact 中的 relevant 数。Frontend 不推算。

## 6.2 状态筛选

统计下方使用克制毛玻璃 pill：

```text
全部 / 发展中 / 已确认 / 已解决 / 存在冲突
```

- 共享滑动 indicator。
- 筛选切换时 Event list 轻微淡入。
- 不改变同一筛选内的 Backend 顺序。
- 空筛选显示安静的 inline empty state。

## 6.3 Event Item

Event 以分隔线列表呈现，不是 card grid。

信息层级：

```text
State / time / counts
Title
Overview
为什么值得关注
Save action
```

`why_it_matters` 必须带“为什么值得关注”标签；不能让用户把它误认为 Event overview。

---

# 7. Event Detail

顺序：

```text
Back
Event header
Overview
Base Analysis
Timeline
Claims
Conflicts
Evidence
Why It Matters
Actions
```

Actions：

- `询问这个事件`：Accent pill primary button。
- `加入询问选择`：有边框的 secondary pill button；选中态有背景和边界变化。
- Save：书签语义图标或克制 action，不使用浏览器默认方形按钮。

点击 `询问这个事件` 后进入 ASK，并自动选择当前 Event；仍允许在 ASK 增减其他 Event。

Evidence 的私密来源展示由 Backend Public DTO 决定；Frontend 不猜隐私。

---

# 8. ASK 工作区

## 8.1 空状态

主标题居中：

> 观澜能帮忙做什么

下方提供 composer。输入为空时发送按钮保持弱化/不可用；出现有效输入后淡入并可用。

不要显示视觉上的“你的问题”标题；保留 visually-hidden label 供读屏使用。

## 8.2 Event rail

ASK 激活时，Sidebar 配置区下方出现：

```text
Event 列表                         已选择 0 / 8
────────────────────────────────
Event title
Event title                       01
...
```

规则：

- 整行可点击，底层保留语义化 checkbox。
- 浏览器默认 checkbox 必须视觉隐藏。
- 未选项：muted title。
- hover：轻背景，title 加深。
- 选中项：轻深色背景、主文字加深、字重提升、左侧 2px Accent 指示条、右侧选择顺序。
- 不只靠颜色表达。
- 最多 8 个；达到上限时未选项 disabled，并显示解释。
- rail 独立滚动，Sidebar 本体不向下延伸。
- rows 进入时可短 stagger，但 reduced motion 下取消。

## 8.3 提交后的对话布局

提交后：

- 主内容变为独立滚动 conversation。
- composer sticky 在底部，不覆盖最后一条回答。
- 用户问题右对齐、轻圆角、克制浅背景。
- 观澜回答左对齐、自然文字排版，不强制包成大卡片。
- 新回答出现后滚动到可见区域，但不抢夺用户正在查看历史的滚动位置。

## 8.4 Composer

- 显示当前选择的 Event 数和简短标题上下文。
- Textarea 圆角但不是巨大药丸。
- 发送为自有上箭头 icon button。
- “增强搜索”下拉只在 ASK 内出现：关闭 / 开启 Grok。
- pending/running 时冻结本轮提交并防重复点击；结束后恢复输入。

## 8.5 处理过程

进行中显示：

```text
正在比较 Event 数据库
正在获取并规范化补充信息
正在复核 Event 事实
正在组织回答
```

只显示 Backend 返回且实际到达的阶段，并显示累计秒数。

完成后折叠为：

```text
› 已思考 37 秒
```

展开后显示过去式阶段：

```text
已比较 Event 数据库
已获取并规范化补充信息
已复核 Event 事实
已组织回答
```

direct path 只显示实际两步。禁止显示、存储、伪造或暗示模型私有 Chain-of-Thought。

## 8.6 历史提问

- 右上浮动圆角毛玻璃 panel。
- 默认可折叠；pin 后固定，必须可再次取消固定。
- 固定偏好只保存 UI boolean，不在 localStorage 缓存问题/答案正文。
- 列表可分页。
- 点击条目打开具体问题和完整回答。
- 详情有明显 `＋ 新增提问` 按钮返回 composer。
- 选中 Event 后自动加载相关历史。

Glass 在这里成立，因为它是真实浮层；不要把每个普通 section 也做成玻璃卡片。

---

# 9. BRIEF、ARCHIVE、Search

## 9.1 BRIEF

主标题固定：

> 当前视野一览

使用连续阅读列表、serif heading、细分隔线。不要展示内部 artifact/run ID。

## 9.2 ARCHIVE

高密度 EventSummary 列表，保留 Backend 顺序。Save 状态清晰但低视觉重量。

## 9.3 Search

Topbar 入口显示放大镜、`搜索` 和 `⌘K`。

Overlay：

- 右上是明显的圆形叉形 icon button，至少 40×40。
- `aria-label="关闭搜索"`。
- Escape 关闭。
- Dialog focus trap。
- 关闭后焦点回到触发按钮。
- Search results 是 Event 列表，不是来源列表。

---

# 10. SCOPE 与 Onboarding

Onboarding 使用低密度大标题和线性 selection rows，不使用卡片墙。

后续修改 Scope 时，在主问题下显示红色小字：

> 更改将在下次Event更新时生效

该提示只在非首次设置出现。

固定提示和选项必须与 Backend enum 一致；显示文案可中文，ID 不改写。

---

# 11. SETTINGS

模型选择使用两级 Editorial radio rows：

```text
模型来源
Deepseek官方
GPT-5.5
AI Ping

可用模型
...
```

规则：

- 不使用两个并排大原生 Select 作为主 UI。
- 来源变化后模型列表平滑更新。
- available/unavailable 由 Backend 返回。
- unavailable 可见但 disabled，并说明未配置。
- 只有 dirty 时保存按钮可用。
- 成功、失败、处理中不能造成布局跳动。

Maintenance 放在 Settings 下方，展示 Backend 返回的状态、阶段、完成时间和 `next_cycle_at`；Frontend 不推算时间。

---

# 12. Buttons 与 Icons

建立三个 action 层级：

- Primary：少量关键提交，Ink/Accent 实心。
- Secondary：细边框、轻圆角或 pill。
- Icon button：关闭、保存、发送、pin 等图形语义明显的动作。

要求：

- 图标使用项目自有 SVG/线宽，不复制第三方二进制资产。
- Icon button 必须有 `aria-label`，必要时有 tooltip/title。
- 最小交互区域 40×40，关键触控目标建议 44×44。
- focus-visible 使用清晰 Accent outline。
- disabled、busy、pressed 都必须有结构或文本信号，不能只变颜色。

禁止继续把所有动作都做成 `.text-button` 或灰色方块。

---

# 13. 文案与语言

## 13.1 固定产品术语

- `Raw`：前端保留 Raw。
- `Signal`：中文页面写“因子”，内部代码仍为 signal。
- `Event`：保留 Event。
- `ASK`：侧边导航写 ASK，页面内可写“询问观澜”。
- `BRIEF / ARCHIVE / SCOPE / SETTINGS`：侧边导航不汉化。

## 13.2 必须中文

- 登录、注册、Onboarding。
- Loading/Error/Empty/Success。
- 按钮、表单、Maintenance 状态说明。
- NOW 统计与筛选。
- ASK 输入、状态、失败、历史和处理阶段。
- Brief 页面标题和说明。

## 13.3 不强制翻译

- 公司、人名、产品、模型和来源正式名称。
- URL。
- Evidence 原文。
- 用户明确使用其他语言提出的 Ask 可跟随其语言。

---

# 14. Accessibility

必须：

- 全键盘可达。
- 清晰 focus-visible。
- semantic headings 和 landmark。
- 每个 input 有 label；可视觉隐藏但不可删除。
- Dialog focus trap 与焦点归还。
- pressed/selected/expanded/busy 使用 ARIA 状态。
- 状态不只靠颜色。
- reduced motion。
- 文本对比可读。
- 历史 panel、Event rail 和 conversation 各自滚动时仍可键盘操作。

---

# 15. Loading、Error、Empty、Success

所有主要页面必须有四态：

```text
Auth / Session
Onboarding / SCOPE
NOW
ASK
Event Detail
BRIEF
ARCHIVE
Search
SETTINGS / Maintenance
```

规则：

- Loading 不伪造内容或进度。
- Error 给出稳定中文说明和可行重试。
- Empty 是合法产品状态，不写成系统故障。
- Success 不使用 confetti 或夸张庆祝。

---

# 16. Responsive

优先 Desktop/MacBook 常见 16:10 与 16:9。

窄桌面：

- ASK history 可覆盖式浮层，不长期压缩正文。
- Event rail 保持可用宽度和独立滚动。
- composer 不遮挡回答。

移动：

- 导航横向滚动。
- NOW/Event Detail 单栏。
- 双栏分析降为单栏。
- ASK user/assistant 最大宽度收紧但保留左右关系。
- 不为手机破坏桌面信息层级。

---

# 17. 禁止模式

```text
× Traditional news feed
× Everything-is-a-card
× Bento everywhere
× Purple-blue AI gradient
× Glass everywhere
× Huge rounded rectangles
× Colorful category chips
× Source logo wall
× Gamification / confetti
× 黑盒可信度百分比
× 全屏 ChatGPT 视觉复制
× 浏览器默认 checkbox 暴露在 ASK Event rail
× 普通文本 Close 难以发现
× 侧边栏随正文滚动
× 固定 history 后无法取消固定
× composer 覆盖最新回答
× 用假“思考过程”代替可审计阶段
× Frontend 临时翻译或拼接 immutable snapshot
```

---

# 18. UI Review Checklist

每次前端 PR 检查：

1. Event 是否仍是主角？
2. 页面是否退化成 Feed 或 Dashboard？
3. Typography/Grid 是否优先于容器？
4. Sidebar、Topbar 是否稳定？
5. 导航 indicator 是否连续滑动？
6. NOW 是否显示 Raw/因子/Event 正确口径？
7. `why_it_matters` 是否有“为什么值得关注”？
8. 侧边导航是否保持英文？
9. ASK 是否明确选中 Event 上下文？
10. ASK 是否只展示真实公开阶段？
11. history 是否可折叠、pin 和 unpin、打开详情？
12. Search 是否可发现、可键盘关闭并归还焦点？
13. 所有按钮是否有合适语义和 focus？
14. Loading/Error/Empty/Success 是否齐全？
15. reduced motion 是否可用？
16. Frontend 是否只使用 Generated Types 和 Backend 顺序？
17. 私密来源身份是否可能泄露？

---

# 19. 最终视觉定义

用户应该沿着以下路径理解系统：

```text
我现在该注意什么？
→ 发生了什么？
→ 哪些 Claim 可以确认？
→ 哪些信息冲突？
→ 证据是什么？
→ 为什么这与我有关？
→ 我还能就这些 Event 问什么？
```

所有视觉决定都应服务这条路径。
