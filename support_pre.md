# Infoscope 信息源扩展清单（内部）

> 本文件用于内部接入规划。对外统一使用 `support.md`，不得对外披露本文件中的接入阶段、优先级、暂缓原因或实现状态。

## 当前接入基线

当前准备更新的信息源基线为：

- 7 个 NewsNow 热榜源；
- 10 个 RSS / Atom Feed；
- Telegram 标题严格等于 `News` 的文件夹中，显式包含且未排除的全部群组和频道。

Hacker News 继续使用现有 `https://hnrss.org/frontpage`，不同时接入 `https://news.ycombinator.com/rss`，避免重复采集。

### News 文件夹当前快照

2026-08-19 通过 Telegram MTProto API 只读解析，`News` 文件夹当前包含 17 个公开群组 / 频道：

1. CoinMarketCap Announcements：`@CoinMarketCapAnnouncements`
2. Breaking Alert 全球快报：`@GlobalFinance_ZH`
3. 吴说区块链 新闻与深度：`@wublock`
4. TechFlow 深潮：`@TechFlowDaily`
5. BlockBeats：`@theblockbeats`
6. Tesla特斯拉 AI & FSD News：`@Tesla_share`
7. PANews Web3：`@ChannelPANews`
8. Glassnode：`@glassnode`
9. SoSoValue News Bot 中文：`@sosovaluenewsbot_CN`
10. Odaily资讯速递：`@Odaily_News`
11. Foresight News：`@foresightnews`
12. 敏感经济信息分享：`@pelosi3`
13. A股销金窟：`@hejzl_xjk`
14. 金色财经新闻频道：`@jinse2017`
15. Binance Announcements：`@binance_announcements`
16. 经济信息联播：`@eco_cn`
17. PANews 编辑部 Web3 资讯严选：`@PANewsSelected`

### 本次文件夹新增项

批准的 8 个公开频道中，`@wublock` 已存在于 `News` 文件夹，因此实际只需新增以下 7 个：

- NewsTrade.AI：`https://t.me/NewsTradeAI`
- FinancialJuice：`https://t.me/financialjuice`
- Wu Blockchain News：`https://t.me/wublockchainenglish`
- Watcher Guru：`https://t.me/WatcherGuru`
- Yummy：`https://t.me/GodlyNews1`
- GitHub Trends：`https://t.me/githubtrending`
- Tree News：`https://t.me/TreeNewsFeed`

批准的频道列表不构成 TG News 的完整来源清单。后续采集范围始终由 `News` 文件夹的实时 include / exclude 结果决定。

## 后续支持来源

以下来源保留在扩展清单中。接入前仍需逐项验证可访问性、授权边界、更新频率、内容结构、稳定唯一键和公开 provenance。

### AI 官方与研究来源

- Anthropic News：`https://www.anthropic.com/news`
- Meta AI Blog：`https://ai.meta.com/blog/`
- Mistral AI News：`https://mistral.ai/news/`
- Microsoft Research Blog：`https://www.microsoft.com/en-us/research/blog/`
- AWS Machine Learning Blog：`https://aws.amazon.com/blogs/machine-learning/`
- Google Research Blog：`https://research.google/blog/`
- arXiv Artificial Intelligence：`https://export.arxiv.org/rss/cs.AI`
- arXiv Machine Learning：`https://export.arxiv.org/rss/cs.LG`
- MIT Technology Review AI：`https://www.technologyreview.com/topic/artificial-intelligence/`

Anthropic 当前未提供已核验可用的原生 RSS Endpoint，后续只能在具备稳定网页采集合同后接入，不使用来源不明的第三方 Feed 冒充官方源。

### 科技新闻与开发者来源

- The Verge：`https://www.theverge.com/`
- Ars Technica：`https://arstechnica.com/`
- Reuters Technology：`https://www.reuters.com/technology/`
- GitHub Blog：`https://github.blog/`
- GitHub Security Advisories：`https://github.com/advisories`
- Lobsters：`https://lobste.rs/rss`
- V2EX Public API：`https://www.v2ex.com/api/topics/hot.json`
- TLDR Tech：`https://tldr.tech/tech`

### 投资市场与加密来源

- Reuters Markets：`https://www.reuters.com/markets/`
- The Block：`https://www.theblock.co/`
- Decrypt：`https://decrypt.co/`
- Cointelegraph：`https://cointelegraph.com/`
- PANews：`https://www.panewslab.com/`
- Bitcoin Magazine：`https://bitcoinmagazine.com/`
- 10x Research Telegram：`https://t.me/tenxresearch`
- 财经慢报 Telegram：`https://t.me/Financial_Express`
- WhaleBot Alerts Telegram：`https://t.me/WhaleBotAlerts`

付费墙、授权限制或不稳定页面不得通过绕过访问控制的方式采集。无稳定 canonical URL 的市场快讯只能进入 discovery，不能单独确认事实。

### AI 与科技 Telegram 来源

- 地心引力：`https://t.me/bigwalnut`
- Levix 空间站：`https://t.me/synctoai`
- The Prompt Index：`https://t.me/chatgptmastermind`
- BuildWithAI：`https://t.me/buildwithai_io`

### X / Twitter 直接来源能力

- RSSHub X user route：固定账号 watchlist；需要隔离的 X 登录凭据或正式 API 凭据。
- `twscrape`：支持 Top Search、Trends、List 与账号时间线；仅允许使用隔离账号并评估平台风控。
- Agent Reach `twitter-cli` / OpenCLI：用于按需 Research，不作为无审计的 Event 写入通道。
- 自建 X → Telegram bridge：必须保留原始 X URL、Tweet ID、作者 handle 和发布时间。

直接 X 采集优先保留以下字段：

```text
x_origin_url
x_tweet_id
x_author_handle
x_published_at
mirror_channel_id
mirror_message_id
mirror_observed_at
provenance_status
```

## 明确不支持的来源

- 泛娱乐或政治噪声占主导的 `twitter_read`、`ttttwitter`；
- 无原帖链接、作者或稳定消息 ID 的匿名“热门推文”频道；
- 公共 Nitter 实例作为生产核心依赖；
- 币圈喊单、付费带单、空投拉新或冒充官方的 Telegram 频道；
- 要求绕过登录、验证码、付费墙或平台访问控制的采集方式；
- 无法满足 Raw、provenance、幂等键和来源隐私边界的任何来源。

## 接入前检查

每个扩展来源必须满足：

1. 内容先持久化为 Raw，再进入 Normalize → Signal → Event；
2. 存在稳定 source ID、canonical URL 或平台消息 ID；
3. 重复采集幂等，内容变化形成新的 observation；
4. 单个来源失败与其他来源隔离；
5. 不在普通日志、公共 DTO 或 Git 中保存凭据和私密来源身份；
6. 聚合、镜像和社区来源只作 discovery，重要事实需由原始公告或独立来源复核；
7. 新来源必须通过采集、解析、去重、重试和隐私回归测试后再启用。
