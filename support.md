# Infoscope 有效信息源

Infoscope · 观澜从公开热榜、RSS / Atom、Telegram、官方发布页和开发者社区获取信息。所有来源都遵循同一事实处理路径：

```text
Source → Raw → Normalize → Signal → Deduplication → Event → Reconciliation
```

来源内容不会直接改写 Event。聚合、镜像和社区消息用于发现线索；重要事实仍需通过原始公告、原始链接或独立来源复核。

## 公开热榜

| 来源 | 范围 |
| --- | --- |
| 百度热搜 | 中文公共热点 |
| 微博 | 中文社交热点 |
| 澎湃新闻 | 中文综合新闻 |
| 华尔街见闻 | 宏观与市场热点 |
| 财联社热门 | 财经与证券热点 |
| 知乎 | 中文社区热点 |
| Bilibili 热搜 | 视频与青年社区热点 |

公开热榜通过 NewsNow-compatible API 读取。榜单排名变化作为新的 Raw observation 保存，不把排名本身视为事实结论。

## RSS / Atom

| 来源 | Feed | 主要范围 |
| --- | --- | --- |
| OpenAI News | `https://openai.com/news/rss.xml` | AI 产品、研究与公司公告 |
| Google DeepMind | `https://deepmind.google/blog/rss.xml` | AI 研究、模型与科学进展 |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | 开源模型、数据集与开发工具 |
| NVIDIA Technical Blog | `https://developer.nvidia.com/blog/feed/` | AI 基础设施、GPU 与开发者技术 |
| U.S. SEC Press Releases | `https://www.sec.gov/news/pressreleases.rss` | 美国证券监管与执法公告 |
| Federal Reserve Press Releases | `https://www.federalreserve.gov/feeds/press_all.xml` | 美联储政策、监管与经济公告 |
| CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss/` | 加密资产与区块链市场 |
| TechCrunch | `https://techcrunch.com/feed/` | 科技公司、创业与产品新闻 |
| GitHub Changelog | `https://github.blog/changelog/feed/` | GitHub 产品与开发者平台更新 |
| Hacker News | `https://hnrss.org/frontpage` | 技术与开源社区热门内容 |

Feed 采集使用 GUID 或 canonical URL 作为幂等依据。字符编码声明异常按受控 UTF-8 容错处理，不能静默丢弃正文。

## Telegram

Telegram 信息源集合由本机 Telegram 中标题严格等于 `News` 的文件夹决定。该文件夹显式包含且未排除的全部群组和频道，共同构成完整的 TG News 信息源；来源范围不固定为某几个人工写入的频道名称。

采集使用 Telegram 用户账号 MTProto API，只读取 `News` 文件夹中的群组和频道，不读取私聊或 Bot。公开来源可以公开列示；邀请制或私密来源同样可以参与采集，但其名称、username、invite link 和内部 ID 不对外披露。

以下是可以公开列示的频道：

| 频道 | 地址 | 主要范围 |
| --- | --- | --- |
| CoinMarketCap Announcements | `https://t.me/CoinMarketCapAnnouncements` | 加密市场与平台公告 |
| Breaking Alert 全球快报 | `https://t.me/GlobalFinance_ZH` | 全球财经与突发新闻 |
| 吴说区块链 | `https://t.me/wublock` | 亚洲加密市场中文资讯 |
| TechFlow 深潮 | `https://t.me/TechFlowDaily` | 加密、Web3 与行业研究 |
| BlockBeats | `https://t.me/theblockbeats` | 加密市场与区块链新闻 |
| Tesla特斯拉 AI & FSD News | `https://t.me/Tesla_share` | Tesla、AI 与自动驾驶 |
| PANews Web3 | `https://t.me/ChannelPANews` | Web3 与加密市场新闻 |
| Glassnode | `https://t.me/glassnode` | 链上数据与市场分析 |
| SoSoValue News Bot 中文 | `https://t.me/sosovaluenewsbot_CN` | 加密 ETF、资金流与市场数据 |
| Odaily资讯速递 | `https://t.me/Odaily_News` | Web3 与加密快讯 |
| Foresight News | `https://t.me/foresightnews` | Web3 新闻与行业研究 |
| 敏感经济信息分享 | `https://t.me/pelosi3` | 宏观、市场与政策信息 |
| A股销金窟 | `https://t.me/hejzl_xjk` | A 股、复盘与财经时讯 |
| 金色财经新闻频道 | `https://t.me/jinse2017` | 区块链与加密市场新闻 |
| Binance Announcements | `https://t.me/binance_announcements` | Binance 官方公告 |
| 经济信息联播 | `https://t.me/eco_cn` | 中文宏观与财经资讯 |
| PANews 编辑部 Web3 资讯严选 | `https://t.me/PANewsSelected` | Web3 编辑精选 |
| NewsTrade.AI | `https://t.me/NewsTradeAI` | X 市场新闻聚合与来源线索 |
| FinancialJuice | `https://t.me/financialjuice` | 宏观、美股与实时市场快讯 |
| Wu Blockchain News | `https://t.me/wublockchainenglish` | 亚洲加密市场英文资讯 |
| Watcher Guru | `https://t.me/WatcherGuru` | 加密、宏观与美股快讯 |
| GitHub Trends | `https://t.me/githubtrending` | GitHub Trending 与开源项目 |
| Tree News | `https://t.me/TreeNewsFeed` | 加密与宏观市场短讯 |

公开 Telegram 消息保留频道、公开 username、消息 URL 和平台消息 ID。私密 Telegram 内容在进入 Signal 前移除来源身份。镜像消息若无法追溯到原始 X URL 或原始公告，只作为 discovery 使用。

## AI 官方与研究

- [Anthropic News](https://www.anthropic.com/news)
- [Meta AI Blog](https://ai.meta.com/blog/)
- [Mistral AI News](https://mistral.ai/news/)
- [Microsoft Research Blog](https://www.microsoft.com/en-us/research/blog/)
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/)
- [Google Research Blog](https://research.google/blog/)
- [arXiv Artificial Intelligence](https://export.arxiv.org/rss/cs.AI)
- [arXiv Machine Learning](https://export.arxiv.org/rss/cs.LG)
- [MIT Technology Review · Artificial Intelligence](https://www.technologyreview.com/topic/artificial-intelligence/)

## 科技与开发者社区

- [The Verge](https://www.theverge.com/)
- [Ars Technica](https://arstechnica.com/)
- [Reuters Technology](https://www.reuters.com/technology/)
- [GitHub Blog](https://github.blog/)
- [GitHub Security Advisories](https://github.com/advisories)
- [Lobsters](https://lobste.rs/)
- [V2EX](https://www.v2ex.com/)
- [TLDR Tech](https://tldr.tech/tech)

## 投资市场与加密

- [Reuters Markets](https://www.reuters.com/markets/)
- [The Block](https://www.theblock.co/)
- [Decrypt](https://decrypt.co/)
- [Cointelegraph](https://cointelegraph.com/)
- [PANews](https://www.panewslab.com/)
- [Bitcoin Magazine](https://bitcoinmagazine.com/)
- [10x Research](https://t.me/tenxresearch)
- [财经慢报](https://t.me/Financial_Express)
- [WhaleBot Alerts](https://t.me/WhaleBotAlerts)

## AI 与科技频道

- [地心引力](https://t.me/bigwalnut)
- [Levix 空间站](https://t.me/synctoai)
- [The Prompt Index](https://t.me/chatgptmastermind)
- [BuildWithAI](https://t.me/buildwithai_io)

## X / Twitter

X 是 AI、科技、加密和美股实时信息的重要来源。Infoscope 可通过固定账号 watchlist、Top Search、Trends、公开列表以及 X → Telegram 镜像发现信息。

可追溯的 X 内容至少保留原帖 URL、Tweet ID、作者 handle 和发布时间。Telegram 镜像、算法热门和社区转述不能替代原始 X provenance，也不能单独确认 Event 事实。

## 来源安全与隐私

- 私密 Telegram 来源身份、invite link、peer ID、账号凭据和 session 不进入 Git、普通日志或公共 DTO。
- Raw、Evidence 正文和 provenance 不因来源聚合而公开。
- 不绕过验证码、付费墙、登录限制或平台安全控制。
- 付费、编辑型或社区来源不被默认视为官方来源。
- 单个来源故障不会阻断其他来源采集。
- 相同来源内容必须幂等；内容变化保存为新的 observation。
