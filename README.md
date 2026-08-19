# Infoscope · 观澜

观澜是为持续追踪 AI、科技、开源与投资市场变化的个人研究者设计的 Event-first 信息情报界面。

这些变化通常散落在新闻、RSS、社区和即时消息中。只依赖传统信息流，研究者需要反复阅读、去重并手动拼接前因后果，仍可能错过事件的新进展、事实冲突和重要转折。

观澜将采集到的 Raw Information 规范化为因子（Signal），再重构为持续演化、可追溯且可以直接提问的 Event。它帮助使用者从“今天又出现了哪些消息”，转向“事情正在怎样变化，为什么值得现在关注”。

> 看见事件，而不是信息流。

当前可用里程碑：`0.1`

## 主要功能

- **NOW**：按用户 Scope 展示当前值得关注的 Event，并支持状态筛选、保存和对比。
- **ASK**：围绕一个或多个 Event 提问；可选择开启 Grok 增强搜索。
- **BRIEF**：基于当前个性化 Event 快照生成简报。
- **ARCHIVE / Search**：访问历史 Event、已保存内容并进行站内搜索。
- **SCOPE / SETTINGS**：配置关注范围、焦点和模型来源。

## Infoscope Display（ISD）

[Infoscope Display（ISD）](https://github.com/SCOUT-Infoscope/infoscope-display) 是 Infoscope 的硬件展示功能与设备端呈现方式，并非一套独立产品。它使用独立仓库，是为了隔离硬件、固件和设备端依赖，避免这些工程内容污染 Infoscope 主仓库。

Infoscope 主仓库负责产品事实层、API，以及 `contracts/mqtt/` 中唯一权威的 MQTT Display Contract；ISD 只消费经过冻结的合同与 canonical fixture，在设备端呈现 Event。ISD 不维护第二份权威 Schema，vendoring fixture 时必须记录对应的上游 immutable commit SHA 与 SHA-256。

事实处理遵循固定管线：

```text
Raw → Normalize → Signal → Deduplication → Event → Claims / Timeline / Conflicts / Base Analysis
```

模型回答不直接成为 Evidence；Research 结果必须经过既有事实管线后才能更新 Event。

## 快速首屏与正式个性化

用户提交 Scope、投资子类和 Focus 后，NOW 会先从已经完成的模型个性化历史中寻找最接近的完整 Profile，并按历史相关性与优先级生成快速预览。这不是关键词或固定规则匹配；不同的 Scope/Focus 组合拥有独立的 Profile Signature、历史排序和后台生成任务，结果可以合理重叠，但不会把同一份个性化产物冒充所有组合的答案。

正式 Personalization 会同时在后台运行，通常需要约 10–15 分钟。完成后，NOW 自动用该组合的正式模型产物整体替换历史预览；生成期间或模型暂时失败时，预览仍保持可用。历史预览只服务快速首屏，不会成为 Evidence、Brief 输入或 Event 回写依据。

## 启动本地 Demo

需要 Docker、Python、[uv](https://docs.astral.sh/uv/)、Node.js 和 pnpm。

```bash
cp .env.example .env
# 在 .env 中填写本机所需配置
./scripts/demo.sh start
```

启动完成后访问：<http://127.0.0.1:8000>

常用命令：

```bash
./scripts/demo.sh status   # 查看 API 与 Worker 状态
./scripts/demo.sh restart  # 重启 Demo
./scripts/demo.sh stop     # 停止 API 与 Worker，保留 PostgreSQL
```

## 开发与检查

```bash
./scripts/check.sh
```

该命令会运行后端测试与静态检查、前端 lint/typecheck/test/build，并检查 OpenAPI Generated Types 是否同步。

更多产品与实现约束见 [dev.md](dev.md)、[dev_final.md](dev_final.md)、[tech.md](tech.md) 和 [style.md](style.md)。
