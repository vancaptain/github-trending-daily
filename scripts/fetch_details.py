"""Fetch public README/release evidence. Usage: fetch_details.py repos.txt out.json.

Input: one owner/repo per line; suffix '*' to request the latest release too.
A ranking JSON from fetch_trending.py is also accepted (README for every repo).
Set GH_TOKEN/GITHUB_TOKEN to raise API limits. Exit 1 means partial/total failure;
exit 2 means invalid input. A release 404 means no published release, not a failure.
"""
import argparse
import base64
import binascii
import json
import re
from pathlib import Path

from github_http import fetch, write_json

REPO_NAME = re.compile(r"(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+\Z")


def clean_readme(text):
    """Keep Markdown, short lines, links and code: these are evidence, not noise."""
    return text.replace("\r\n", "\n").strip()


def read_repos(path, releases=False):
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        entries = [(r["name"], releases) for r in json.loads(text)["repos"]]
    else:
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append((line.rstrip("*").strip(), releases or line.endswith("*")))
    unique = {}
    for name, want_release in entries:
        if not REPO_NAME.fullmatch(name):
            raise ValueError("Invalid owner/repo: %s" % name)
        key = name.lower()
        previous = unique.get(key)
        unique[key] = (name, bool(want_release or (previous and previous[1])))
    if not unique:
        raise ValueError("No repositories supplied")
    return list(unique.values())


def asset_evidence(asset, tag):
    """Recognize explicit package/platform names only; do not infer from language."""
    name = asset["name"]
    lower = name.lower()
    platform = None
    if lower.endswith((".exe", ".msi")) or re.search(r"(?:^|[-_.])(?:windows|win32|win64)(?:[-_.]|$)", lower):
        platform = "win"
    elif lower.endswith((".dmg", ".pkg")) or re.search(r"(?:^|[-_.])(?:macos|darwin)(?:[-_.]|$)", lower):
        platform = "mac"
    elif lower.endswith((".appimage", ".deb", ".rpm")) or re.search(r"(?:^|[-_.])linux(?:[-_.]|$)", lower):
        platform = "linux"
    elif lower.endswith(".apk"):
        platform = "android"
    if not platform:
        return None
    arch = next((a for a in ("aarch64", "arm64", "x86_64", "amd64", "x64", "universal", "armv7", "x86")
                 if re.search(r"(?:^|[-_.])" + a + r"(?:[-_.]|$)", lower)), None)
    return {"os": platform, "asset": name, "arch": arch, "release_tag": tag,
            "url": asset.get("browser_download_url"), "basis": "release_asset"}


def enrich(repos, *, cache_dir=None, cache_ttl=3600, excerpt_chars=16000):
    out, failures = {}, 0
    rate_limit = None

    def request(url):
        nonlocal rate_limit
        if rate_limit:
            return {**rate_limit, "skipped": True}
        response = fetch(url, cache_dir=cache_dir, cache_ttl=cache_ttl)
        if response.get("kind") == "rate_limit":
            rate_limit = response
        return response

    for repo, want_release in repos:
        entry = {"readme_excerpt": None, "errors": []}
        out[repo] = entry
        response = request("https://api.github.com/repos/%s/readme" % repo)
        if "__error__" in response:
            entry["errors"].append({"resource": "readme", **response})
            failures += 1
        else:
            data = response["data"]
            try:
                if data.get("encoding") != "base64" or not isinstance(data.get("content"), str) or not data["content"]:
                    raise ValueError("README content missing or unsupported encoding")
                text = clean_readme(base64.b64decode("".join(data["content"].split()), validate=True).decode("utf-8"))
                entry.update(readme_text=text, readme_excerpt=text[:excerpt_chars] if excerpt_chars else text,
                             readme_truncated=bool(excerpt_chars and len(text) > excerpt_chars),
                             readme_url=data.get("html_url"), readme_fetched_at=response["fetched_at"])
            except (ValueError, binascii.Error):
                entry["errors"].append({"resource": "readme", "kind": "invalid_response", "__error__": "README content could not be decoded"})
                failures += 1
        if want_release:
            response = request("https://api.github.com/repos/%s/releases/latest" % repo)
            if "__error__" in response:
                entry["release_assets"] = None
                entry["release_status"] = "absent" if response.get("status") == 404 else "failed"
                if response.get("status") != 404:
                    entry["errors"].append({"resource": "release", **response})
                    failures += 1
            else:
                data = response["data"]
                assets = data.get("assets", [])
                if not isinstance(assets, list) or any(not isinstance(a, dict) or not isinstance(a.get("name"), str) for a in assets):
                    entry.update(release_status="failed", release_assets=None)
                    entry["errors"].append({"resource": "release", "kind": "invalid_response", "__error__": "Invalid release assets"})
                    failures += 1
                else:
                    entry.update(release_status="ok", release_tag=data.get("tag_name"), release_url=data.get("html_url"),
                                 release_fetched_at=response["fetched_at"], release_assets=[a["name"] for a in assets],
                                 release_asset_details=[{k: a.get(k) for k in ("name", "browser_download_url", "size")} for a in assets])
                    entry["os_evidence"] = [e for e in (asset_evidence(a, data.get("tag_name")) for a in assets) if e]
        print("%s: %s" % (repo, "FAIL" if entry["errors"] else "ok"), flush=True)
    return out, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repos")
    parser.add_argument("output")
    parser.add_argument("--releases", action="store_true", help="Fetch latest release for every repository")
    parser.add_argument("--cache-dir", help="Cache successful API responses only")
    parser.add_argument("--cache-ttl", type=int, default=3600)
    parser.add_argument("--excerpt-chars", type=int, default=16000, help="0 keeps full README in excerpt; full text is always saved")
    args = parser.parse_args(argv)
    if args.cache_ttl < 0 or args.excerpt_chars < 0:
        parser.error("Cache TTL and excerpt length must be nonnegative")
    try:
        repos = read_repos(args.repos, args.releases)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))
    out, failures = enrich(repos, cache_dir=args.cache_dir, cache_ttl=args.cache_ttl, excerpt_chars=args.excerpt_chars)
    write_json(args.output, out)
    print("saved %s; failed resources: %s" % (args.output, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
