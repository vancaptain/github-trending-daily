"""Fetch the complete returned daily Trending page, with auditable raw snapshots.

Default scope is the overall board. --language adds separate language boards;
that union is explicitly labelled a sample, never a reconstruction of the overall board.
"""
import argparse
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from fetch_details import REPO_NAME
from github_http import fetch, write_json


class TrendingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.stack, self.row = [], [], None
        self.articles = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "Box-row" in attrs.get("class", "").split():
            self.articles += 1
            self.row = {"name": None, "lang": "", "description": "", "total_text": "", "today_text": ""}
            self.stack = []
        if self.row is None:
            return
        if tag == "a" and any(t == "h2" for t, _ in self.stack):
            name = attrs.get("href", "").strip("/")
            if REPO_NAME.fullmatch(name):
                self.row["name"] = name
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if self.row is None:
            return
        if tag == "article":
            self.rows.append(self.row)
            self.row = None
            self.stack = []
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        if self.row is None:
            return
        if any(t == "p" for t, _ in self.stack):
            self.row["description"] += text
        if any(a.get("itemprop") == "programmingLanguage" for _, a in self.stack):
            self.row["lang"] += text
        if any(t == "a" and a.get("href", "").endswith("/stargazers") for t, a in self.stack):
            self.row["total_text"] += text
        if any(t == "span" and "float-sm-right" in a.get("class", "").split() for t, a in self.stack):
            self.row["today_text"] += text


def parse_trending(html):
    parser = TrendingParser()
    parser.feed(html)
    if not parser.rows or len(parser.rows) != parser.articles:
        raise ValueError("No complete Trending articles found; page may be blocked or truncated")
    rows, names = [], set()
    for rank, row in enumerate(parser.rows, 1):
        daily = re.fullmatch(r"\s*([\d,]+)\s+stars? today\s*", row["today_text"])
        total = row["total_text"].strip()
        if not row["name"] or not daily or not re.fullmatch(r"[\d,]+", total):
            raise ValueError("Trending article %s lacks valid repository/daily/total fields" % rank)
        key = row["name"].lower()
        if key in names:
            raise ValueError("Duplicate repository in a board: %s" % row["name"])
        names.add(key)
        rows.append({"name": row["name"], "lang": row["lang"].strip(),
                     "description": " ".join(row["description"].split()),
                     "total": int(total.replace(",", "")), "today": int(daily[1].replace(",", "")),
                     "source_rank": rank})
    return rows


def collect(languages, snapshot_dir):
    sources, repos = [], {}
    for language in [None] + list(dict.fromkeys(languages)):
        url = "https://github.com/trending" + ("/" + quote(language, safe="") if language else "") + "?since=daily"
        response = fetch(url, api=False)
        if "__error__" in response:
            raise ValueError("Cannot fetch %s: %s" % (url, response["__error__"]))
        html = response["data"]
        rows = parse_trending(html)
        snapshot_dir = Path(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        filename = (quote(language, safe="") if language else "overall") + ".html"
        (snapshot_dir / filename).write_text(html, encoding="utf-8", newline="")
        source = {"url": url, "language": language, "fetched_at": response["fetched_at"],
                  "count": len(rows), "raw_file": filename, "sha256": hashlib.sha256(html.encode()).hexdigest()}
        sources.append(source)
        for row in rows:
            key = row["name"].lower()
            observation = {"url": url, "fetched_at": response["fetched_at"], "source_rank": row.pop("source_rank"),
                           "today": row["today"], "total": row["total"]}
            observations = repos.get(key, {}).get("observations", []) + [observation]
            # Use the latest observation, not the highest number from different snapshots.
            repos[key] = {**row, "observations": observations, "fetched_at": response["fetched_at"]}
    return {"scope": "overall+languages" if languages else "overall", "period": "daily",
            "fetched_at": sources[-1]["fetched_at"], "sources": sources,
            "repos": sorted(repos.values(), key=lambda r: (-r["today"], r["name"].lower()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--language", action="append", default=[], help="Explicitly add a language board (repeatable)")
    parser.add_argument("--snapshot-dir", help="Raw HTML evidence (default: OUTPUT-stem-snapshots beside JSON)")
    args = parser.parse_args(argv)
    if any(not re.fullmatch(r"[A-Za-z0-9+#.-]+", language) for language in args.language):
        parser.error("Invalid language slug")
    try:
        result = collect(args.language, args.snapshot_dir or str(Path(args.output).with_suffix("")) + "-snapshots")
    except (ValueError, OSError) as error:
        print(str(error))
        return 1
    write_json(args.output, result)
    print("saved %s: %s repositories (%s)" % (args.output, len(result["repos"]), result["scope"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
