---
name: github-trending-daily
description: 每日抓取 GitHub Trending 并生成中英双语交互 HTML 日报，保留榜单快照与解读证据，明确总榜或语言榜样本范围。触发词：GitHub trending、trending 日报、每日趋势、github 趋势总结。
---

# GitHub Trending 每日日报

目标：获取可核查的每日榜单 → 补全官方资料 → 撰写有来源的双语解读 → 校验并生成离线 HTML。所有脚本仅依赖 Python 3.8+ 标准库。

## 1. 获取总榜快照

```bash
python scripts/fetch_trending.py ranking.json
```

直接解析 GitHub 返回的完整 HTML，而非让模型从工具截断的摘要中提取数字。产物包含仓库、编程语言、官方简介、总 Star、今日新增、原始名次、来源 URL、UTC 抓取时间与原始 HTML 的 SHA-256。原始页面保存在 `ranking-snapshots/`。

如用户明确要覆盖语言分榜，可重复指定 `--language python --language rust --language c++`。此时输出范围为 `overall+languages`，报告必须标注「总榜 + 所选语言分榜聚合样本」。**语言分榜不能还原总榜的缺失部分；不得称为全 GitHub 排名或完整总榜。**重复仓库保留最后一次抓取的计数，保留每次观测；不能挑最大值拼接统计。

页面无项目、文章被截断或缺少数值时脚本非零退出，不发布新的排名文件。GitHub 自身可能只返回少量项目，不假设每天固定 25 个。若网络阻断，应保留错误并报告失败；不得沿用历史模板数据冒充今日数据。WebFetch 可用于阅读，但不能用其不完整摘要替代原始榜单。

## 2. 补全官方资料

```bash
python scripts/fetch_details.py ranking.json details.json --cache-dir .cache/github
```

也兼容 `repos.txt`（一行一个 `owner/repo`，后缀 ` *` 抓取最新 Release）；`--releases` 为所有仓库抓取最新 Release。只为需要判断安装包的项目请求 Release，减少请求数。

- 用 `GH_TOKEN` 或 `GITHUB_TOKEN` 提高 API 限额；不要把 Token 写入命令、日志或报告。
- 匿名请求共享限额；20 次 README + 10 次 Release 是 30 次请求，不保证限额仍然充足。
- 网络/临时服务错误会有限重试；较长的限额等待直接返回失败及重置时间。缓存仅保存成功响应，并保留原抓取时间；`--cache-ttl 0` 强制刷新。
- README 保存全文，保留短行、链接、代码与格式。默认摘要前 16000 字符，`readme_truncated` 明确标记截断；先阅读全文或定位安装、平台、License、限制章节，再做判断。`--excerpt-chars 0` 取消摘要截断。
- 请求失败会写入 `errors` 并非零退出。遇到限额时停止后续网络请求，逐项记录 `skipped`。必须检查退出码与每仓状态，失败项目不可凭记忆补事实。Release 404 表示无已发布 Release，不等于平台不支持；其他 Release 错误仍视为失败。

## 3. 兼容性与证据

操作系统 `os` 与运行方式 `runtime` 分开：

- `os`: `win`, `mac`, `linux`, `android`, `ios`。
- `runtime`: `web`, `docker`, `cli`, `none`（文档/Skill）, `hardware`。

仅依据官方安装说明、支持矩阵、CI 构建目标或明确命名的 Release 附件判断。**Go/Rust/Node 不代表三平台支持，Skill 也可能依赖某个系统工具。**Docker/CLI 是运行方式，不是操作系统。

每个标签都需要 `os_evidence` 的 URL 和中英说明，注明支持版本、CPU 架构、系统版本或依赖限制。附件只证明该版本发布了对应包，不证明本机已运行；缺少附件不能推断「不支持」。证据不足时留空，页面显示「操作系统待确认」。脚本提供 `release_asset_details`、`os_evidence` 素材，不自动将其升级为兼容性结论。

## 4. 撰写双语解读

按今日增量选取约 Top 20；不足 20 不补历史项目。阅读官方 README/Release，按 `docs/editorial-example.json` 的结构输出 `editorial.json` 数组：

- `name` 必须在本次榜单内；不能编辑或覆盖 Star 计数。
- `cat` 使用规定分类；没有依据时 `uncategorized`。
- `featured: true` 的精选项需要 `d`、`purpose`、`feats`、`warns`，每个字段都有 `zh` 和 `en`；列表非空。
- 功能、限制、费用和兼容性只写资料明确支持的内容。无需强凑三条警告；不要用领域常识推断产品事实。
- `sources` 链接到实际支持解读的 README 章节、Release 或官方文档，附双语标签。明确区分项目宣传、作者说明与实测结论。来源链接帮助人工核查，不等于脚本自动验证了每句话。
- 非精选项也可补双语简介、分类、运行方式和有证据的平台标签。

## 5. 校验与生成

```bash
python scripts/build_report.py ranking.json report.html --editorial editorial.json --date YYYY-MM-DD
```

`--date` 使用用户时区的报告日期；省略时使用快照 UTC 日期。脚本校验范围、数值、重复仓库、双语字段、来源 URL 和平台证据，并用安全 JSON 写入模板，统一更新日期。可用 `--snapshot-dir ranking-snapshots` 验证原始 HTML 哈希、项目观测和榜单数量。

不传 `--editorial` 也能生成可交互快照表；保留官方原文，**不生成虚构双语分析或兼容性标签**。模板内历史数据仅供样式预览，显著标为历史示例。

## 6. 检查与交付

先检查所有脚本退出码；运行 `python -m unittest discover -s tests -v`。在浏览器确认报告日期/范围、搜索、全部分类、排序、双语切换及手机宽度显示。报告统计针对本次快照集合；分类占比明确仅包含 Skill/Agent/RAG/模型，不能解释为整个 GitHub 的 AI 占比。

交付 HTML 与排名/资料 JSON、原始快照目录（如用户需要核查）。用宿主提供的文件展示能力，不依赖固定的 `present_files` 工具。说明抓取范围、时间、项目数和失败项。请求失败时说明缺失，不把空值或旧数据当作成功日报。
