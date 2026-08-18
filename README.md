# Infoscope · 观澜

观澜是一个个人信息情报界面：它将采集到的 Raw Information 规范化为因子（Signal），再整理为持续演化的 Event，帮助用户看到事件而不是信息流。

当前可用里程碑：`0.1`

## 主要功能

- **NOW**：按用户 Scope 展示当前值得关注的 Event，并支持状态筛选、保存和对比。
- **ASK**：围绕一个或多个 Event 提问；可选择开启 Grok 增强搜索。
- **BRIEF**：基于当前个性化 Event 快照生成简报。
- **ARCHIVE / Search**：访问历史 Event、已保存内容并进行站内搜索。
- **SCOPE / SETTINGS**：配置关注范围、焦点和模型来源。

事实处理遵循固定管线：

```text
Raw → Normalize → Signal → Deduplication → Event → Claims / Timeline / Conflicts / Base Analysis
```

模型回答不直接成为 Evidence；Research 结果必须经过既有事实管线后才能更新 Event。

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

