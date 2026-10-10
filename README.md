# GitHub Trending Daily

**简体中文** | [English](#english)

把 GitHub Trending 的每日快照变成中英双语交互 HTML 日报：按今日新增 Star 排序，附有来源的精选解读和兼容性说明。Agent Skill + Python 标准库脚本 + 离线 HTML 模板。

![Historical template preview](docs/screenshot.png)

> 截图是历史模板示例。当前模板显著标注示例状态；生成日报须重新抓取，不能使用旧数据代替当天榜单。

## 功能

- 直接解析原始榜单 HTML，保存来源、UTC 抓取时间、原始名次、观测记录及 SHA-256。
- 默认只抓总榜；可明确加入语言榜，报告标注为聚合样本，避免混淆榜单口径。
- 搜索、全部分类筛选、编程语言筛选、中英切换、卡片与表格排序；可键盘操作表头。
- README 全文保留短行、代码和链接；Release 附件不截断；兼容性结论附证据。
- API Token 环境变量、有限重试、限额提示、可选成功响应缓存；部分失败非零退出。
- 单文件 HTML，无外部依赖或后台请求，双击离线打开。

## 快速开始

Python 3.8+，无需 pip。**先抓快照，再生成报告：**

```bash
python scripts/fetch_trending.py ranking.json
python scripts/build_report.py ranking.json report.html
```

这会生成可交互表格，保留官方原文。双语分析由 Agent 或人工根据官方资料补充，脚本不猜测。

```bash
# 可选：补全 README（兼容每行 owner/repo 的 repos.txt）
python scripts/fetch_details.py ranking.json details.json --cache-dir .cache/github
# 阅读 details.json 的全文与原始来源，按 docs/editorial-example.json 写 editorial.json
python scripts/build_report.py ranking.json report.html --editorial editorial.json --date YYYY-MM-DD
# 可选：核验抓取的原始 HTML 与 JSON 观测一致
python scripts/build_report.py ranking.json report.html --snapshot-dir ranking-snapshots
```

- `--language python --language rust`：明确加入语言分榜；合并结果不是总榜还原，也不是全 GitHub 热度排名。
- `fetch_details.py repos.txt details.json`：行尾 ` *` 同时抓最新 Release；`--releases` 为所有项目抓 Release。
- 设置 `GH_TOKEN` 或 `GITHUB_TOKEN` 可提高共享 API 限额。匿名请求 20 次 README + 10 次 Release = 30 次；重试和其他程序会占用同一额度，详见 [GitHub 限额说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。
- `--cache-ttl 0` 刷新 API 缓存；缓存保存原抓取时间，不伪装成最新数据。
- `--excerpt-chars 0` 不截断摘要；无论摘要长度如何，`readme_text` 都保存全文。
- 请求失败返回退出码 1（详情文件仍保留逐仓错误供排查），输入/校验错误返回 2。遇到限额停止后续网络请求并记录跳过项。先检查状态，再让 Agent 分析；Release 404 明确标为无已发布版本。
- 日期默认是快照 UTC 日期，`--date YYYY-MM-DD` 可指定用户时区日期。

## 作为 Agent Skill

把目录复制到宿主的技能目录，如 `~/.claude/skills/` 或 `~/.workbuddy/skills/`，然后说「做今天的 GitHub Trending 日报」。详见 [SKILL.md](SKILL.md)。不同宿主使用自己的文件展示工具，不要求固定的 WebFetch/present_files API。

## 数据与兼容性边界

GitHub Trending 是上游提供的榜单，**按新增 Star 重排不等于发现整个 GitHub 的所有热门仓库**。页面可能只返回少量项目，不假设固定 25 个；保存的原始快照用于核查服务器当次返回内容。不同语言榜在不同时刻抓取，重复项目保留最后一次观测及历史观测，不取最大值。

操作系统 `os` 与 `runtime`（Docker、CLI、Web、文档、硬件）分开。只有明确的官方安装说明、支持矩阵或发布附件才可提供平台标签；每个标签需证据 URL 和双语说明。语言生态不能证明跨平台，安装包不能证明已实测，缺少安装包也不能证明不支持。证据不足显示「操作系统待确认」。

精选解读要有双语字段和 `sources`；这些链接支持人工核查，程序不自动判断自然语言的真实性。未编辑项目保留官方简介原文，不冒充翻译。统计针对快照集合；分类占比明确计入 Skill/Agent/RAG/模型，不代表整个 GitHub 的 AI 占比。

## 目录与验证

```text
SKILL.md                         Agent 工作流
scripts/fetch_trending.py         总榜 / 明确选择的语言榜 + 原始快照
scripts/fetch_details.py          README 全文与 Release 证据
scripts/github_http.py           重试、限额、可选缓存
scripts/build_report.py           字段/证据校验与安全 HTML 生成
references/report-template.html  交互模板（历史示例）
docs/editorial-example.json       仅用于说明结构的虚构示例
tests/test_pipeline.py           抓取失败、数据校验与注入回归测试
```

```bash
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)。使用目标项目内容时遵守其许可证。

---

<a id="english"></a>

# GitHub Trending Daily (English)

A daily GitHub Trending snapshot with an offline interactive HTML template and optional evidence-backed bilingual analysis. Python 3.8+, standard library only.

```bash
python scripts/fetch_trending.py ranking.json
python scripts/fetch_details.py ranking.json details.json --cache-dir .cache/github
# Optional: write editorial.json using docs/editorial-example.json after reading official evidence.
python scripts/build_report.py ranking.json report.html --editorial editorial.json --date YYYY-MM-DD
python -m unittest discover -s tests -v
```

Omit `--editorial` to produce a factual ranking table with original upstream descriptions. The scripts do not invent translations, analysis or compatibility. Copy the directory into your agent's skills folder to use [SKILL.md](SKILL.md).

- Default coverage is the overall daily board. Repeat `--language` to add explicitly selected language boards; the union is labelled a sample, not a reconstructed global ranking. Do not assume a fixed number of entries.
- Raw HTML, SHA-256, source URLs, UTC timestamps and per-board observations are saved. Deduplication uses the latest observation, not the maximum daily count. `--snapshot-dir ranking-snapshots` validates hashes and observations against the raw pages.
- README full text preserves short restrictions, Markdown and links. Excerpts explicitly indicate truncation; `--excerpt-chars 0` removes the excerpt limit. Release asset lists are not truncated.
- `GH_TOKEN` / `GITHUB_TOKEN` raises shared API limits. Bounded retries and optional successful-response caching preserve original fetch timestamps. `--cache-ttl 0` forces a fresh request. Failed requests exit 1; invalid inputs exit 2. Release 404 explicitly means no published release.
- `os` is separate from `runtime`. Every platform/runtime label requires official evidence with a URL and bilingual note. Language choice does not prove platform support; missing assets do not prove lack of support. Unverified OS support is shown explicitly.
- Featured analysis requires bilingual fields and source links. Links enable human verification, not automatic fact checking. Statistics describe this snapshot only; Skill/Agent/RAG/Model share is an explicit category metric.
- Controls cover search, categories from all rows, programming languages, consistent dropdown sorting, localized description sorting, keyboard-operable headers and language switching. The HTML makes no external requests and works offline; blocked localStorage does not stop rendering.
- The template/screenshot contains historical sample data, labelled as such. Generate a fresh report rather than publishing the template as today's digest. Dates default to the snapshot's UTC date; `--date` sets the user's local display date.

[MIT](LICENSE). Respect referenced projects' licenses.
