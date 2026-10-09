---
name: github-trending-daily
description: 每日总结 GitHub Trending 项目并生成双语（中/英）可交互 HTML 报告：按今日新增 Star 排序、含用途/功能/注意事项讲解、操作系统兼容性判定与跳转链接。触发词：GitHub trending、trending 日报、每日趋势、github 趋势总结。
---

# GitHub Trending 每日日报

目标：抓取当天 GitHub Trending → 补全详情 → 撰写双语讲解 → 生成本报告风格的交互式 HTML。

## 工作流

### 1. 抓榜单（注意本机网络限制）

本机沙箱代理对 `github.com` 主站 HTML 返回 **CONNECT 502**（curl exit 56），
但 **`api.github.com` 可直连**。已实测无效的通道：gh-proxy.com/ghfast.top/ghproxy.net（只代理文件不代理页面）、r.jina.ai（被拦截）。

**可行链路：WebFetch 工具抓榜单页面**（走应用内置网络，不受沙箱代理限制）：

1. `WebFetch https://github.com/trending`，提示词要求按 `full_repo_name | language | total_stars | stars_today | description` 管道格式逐行列出。
2. **单次 WebFetch 内容会被截断（约只返回前 11 个项目）**。补全办法：并行抓语言子页（每页是独立 25 条榜单）：
   `/trending/python`、`/trending/rust`、`/trending/c%2B%2B`、`/trending/typescript`、`/trending/go`、`/trending/javascript`，可再加 html/swift/shell 等。
3. 合并去重（以 repo 全名为键，保留 stars_today 最大值）。
4. GitHub 榜单本身不按"今日新增"排序，**生成报告前必须按 stars_today 重排**。

### 2. 补全详情（脚本，走 api.github.com）

1. 把入选仓库写进 `repos.txt`（每行 `owner/repo`；桌面/二进制类项目行尾加 ` *` 表示同时抓 releases）。
2. 运行：
   ```
   python "<skill目录>/scripts/fetch_details.py" repos.txt out.json
   ```
3. 产出 `out.json`：每仓 `readme_excerpt`（README 纯文本摘要，讲解素材）+ 可选 `release_tag`/`release_assets`。

**限额提醒**：匿名 60 次/小时。精选 Top 20 左右 + 约 10 个 releases ≈ 50 次，安全。超限时只给精选项目抓 README。

### 3. OS 兼容性判定规则

| 证据 | 结论 |
|---|---|
| release 附件含 `.exe/.msi` | Windows |
| 含 `.dmg/.pkg` 或 `_universal.dmg` | macOS |
| 含 `AppImage/.deb/.rpm/.tar.xz`(linux) | Linux |
| 含 `.apk` | Android |
| README 写明 Docker 部署 | Docker / 自托管 |
| agent skill / 文档 / 前端库 / 输出 HTML | 系统无关（OS-free） |
| Go/Rust/Node 单二进制 CLI | Windows + macOS + Linux |
| ESP32/嵌入式固件 | 专用硬件 |

判定顺序：release 附件 > README 安装说明 > 语言生态推断。不确定时在注意事项里写明。

### 4. 撰写双语讲解（LLM 工作）

每个精选项目写四段（中英各一份）：**用途**（一句话定位）、**核心功能**（3-5 条 bullet）、**注意事项**（3 条：法律/合规、资源消耗、版本陷阱等）、**系统兼容性**（badge）。素材 = 抓取到的官方 description + readme_excerpt + release 清单 + 你的领域知识。没有把握的内容宁可不写，不要编造。

### 5. 生成 HTML 报告

- 结构与样式**直接复用本 skill 的 `references/report-template.html`**（深色数据密集仪表盘、零外部依赖、可离线打开）：
  - 把模板里的 `DATA`（精选大卡数组）和 `MORE`（完整榜单表格数组）替换为当日数据；
  - 头部日期 `date` 改为当日；
  - 交互已内置：中英切换（localStorage 记忆）、搜索、分类 chip 筛选、语言/排序下拉、表头点击排序。
- 精选卡片建议 Top 20~21（stars_today ≥ ~200），其余进完整榜单表格。
- 若新增分类，同步更新 `I18N.cats` 中英词条。

### 6. 交付

`present_files` 打开 HTML；汇报要点：上榜总数、今日 Star 总增量、Top 3 项目一句话点评。

## 数据字段约定

```js
{name:"owner/repo", lang:"TypeScript", total:35521, today:15335,
 cat:"skill|agent|desktop|devtool|selfhost|web|learn|creative|rag|framework|model|hardware",
 d:{zh:"一句话简介", en:"one-liner"},
 purpose:{zh:"",en:""}, feats:{zh:[],en:[]}, warns:{zh:[],en:[]},   // 精选卡专用
 os:["win","mac","linux","web","android","docker","cli","none","hardware"]}
```

## 踩坑记录（勿重复踩）

1. curl 直连 `github.com/trending` → 代理 502，勿再试主站 HTML。
2. WebFetch 返回不全是**内容截断**而非页面只有 11 个，必须用语言子页补全。
3. 同一 URL 的 WebFetch 有 ~15 分钟缓存，换个 prompt 拿不到"后半页"。
4. `cv2` 式教训不适用此处，但同样注意：本机 Bash 的 curl 偶发对某些域名静默失败，先看 `-w "%{http_code}"`。
