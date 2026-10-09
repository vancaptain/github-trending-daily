# -*- coding: utf-8 -*-
"""
GitHub Trending Daily — 详情补全脚本
从 api.github.com 拉取每个仓库的 README 摘要（讲解素材）与最新 Release 附件清单（OS 兼容性判定依据）。

用法:
  python fetch_details.py repos.txt out.json
    repos.txt: 每行一个 "owner/repo"；若行尾有 "*" 则同时抓取 releases
    示例:
      morluto/rea
      boykopovar/AnyPS5 *

说明:
  - 无需 token（匿名限额 60 次/小时；README 每仓 1 次 + releases 每仓 1 次）
  - 本脚本只依赖标准库，可在裸 Python 环境直接运行
  - 本机沙箱实测: api.github.com 可直连，github.com 主站 HTML 会被代理 502 拦截
"""
import json, base64, re, sys, time, urllib.request, urllib.error

HDRS = {"User-Agent": "trending-daily-skill", "Accept": "application/vnd.github+json"}


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"__error__": e.code}
    except Exception as e:
        return {"__error__": str(e)}


def clean_readme(text):
    t = re.sub(r"<[^>]+>", " ", text)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[`*_#>|]", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    lines = [l.strip() for l in t.splitlines() if len(l.strip()) > 40]
    return " ".join(lines)[:1600]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    repos = []
    with open(sys.argv[1], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            want_release = line.endswith("*")
            name = line.rstrip("*").strip()
            repos.append((name, want_release))

    out = {}
    for repo, want_rel in repos:
        d = get(f"https://api.github.com/repos/{repo}/readme")
        if "__error__" in d:
            out[repo] = {"readme_excerpt": None, "err": d["__error__"]}
            print(f"readme {repo}: FAIL {d['__error__']}", flush=True)
        else:
            txt = base64.b64decode(d.get("content", "")).decode("utf-8", "replace")
            out[repo] = {"readme_excerpt": clean_readme(txt)}
            print(f"readme {repo}: ok", flush=True)
        time.sleep(0.4)
        if want_rel:
            d = get(f"https://api.github.com/repos/{repo}/releases/latest")
            if "__error__" in d:
                out[repo]["release_assets"] = None
                print(f"release {repo}: FAIL {d['__error__']}", flush=True)
            else:
                out[repo]["release_tag"] = d.get("tag_name")
                out[repo]["release_assets"] = [a["name"] for a in d.get("assets", [])][:30]
                print(f"release {repo}: ok", flush=True)
            time.sleep(0.4)

    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"saved {sys.argv[2]}")


if __name__ == "__main__":
    main()
