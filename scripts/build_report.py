"""Validate a daily ranking and optional evidence-backed editorial JSON, then render offline HTML."""
import argparse
import json
import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fetch_details import REPO_NAME
from fetch_trending import parse_trending

CATEGORIES = {"skill", "agent", "desktop", "devtool", "selfhost", "web", "learn", "creative", "rag", "framework", "model", "hardware", "uncategorized"}
OS_KEYS = {"win", "mac", "linux", "android", "ios"}
RUNTIME_KEYS = {"web", "docker", "cli", "none", "hardware"}


def safe_url(value):
    if not isinstance(value, str):
        raise ValueError("Evidence URL must be a string")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Evidence URL must be an https URL without credentials")
    return value


def bilingual(value, field, *, list_value=False):
    if not isinstance(value, dict):
        raise ValueError("%s requires zh and en" % field)
    for lang in ("zh", "en"):
        content = value.get(lang)
        if list_value:
            if not isinstance(content, list) or not content or any(not isinstance(x, str) or not x.strip() for x in content):
                raise ValueError("%s.%s must be a nonempty string list" % (field, lang))
        elif not isinstance(content, str) or not content.strip():
            raise ValueError("%s.%s must be nonempty text" % (field, lang))
    return value


def validate_ranking(ranking):
    if ranking.get("scope") not in ("overall", "overall+languages") or ranking.get("period") != "daily":
        raise ValueError("Expected an explicit overall/overall+languages daily scope")
    timestamp = ranking.get("fetched_at")
    if datetime.fromisoformat(timestamp).utcoffset() is None:
        raise ValueError("Snapshot timestamp requires a timezone")
    sources = ranking.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Ranking must include source snapshots")
    source_urls = set()
    for source in sources:
        safe_url(source["url"])
        if urlsplit(source["url"]).hostname != "github.com" or not urlsplit(source["url"]).path.startswith("/trending"):
            raise ValueError("Ranking sources must be GitHub Trending pages")
        if datetime.fromisoformat(source["fetched_at"]).utcoffset() is None:
            raise ValueError("Source timestamp requires a timezone")
        if source["url"] in source_urls:
            raise ValueError("Duplicate source URL")
        if type(source.get("count")) is not int or source["count"] < 1:
            raise ValueError("Source count must be a positive integer")
        if not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", "")):
            raise ValueError("Source snapshot SHA-256 is required")
        source_urls.add(source["url"])
    if ranking["scope"] == "overall" and (len(sources) != 1 or sources[0].get("language") is not None or urlsplit(sources[0]["url"]).path.rstrip("/") != "/trending"):
        raise ValueError("Overall scope must contain the overall board only")
    if ranking["scope"] == "overall+languages" and (len(sources) < 2 or not any(s.get("language") for s in sources)):
        raise ValueError("Language-union scope requires language boards")
    rows = ranking.get("repos")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Ranking contains no repositories")
    names = set()
    for row in rows:
        name = row.get("name", "")
        if not REPO_NAME.fullmatch(name) or name.lower() in names:
            raise ValueError("Invalid or duplicate repository: %s" % name)
        names.add(name.lower())
        for field in ("total", "today"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError("%s.%s must be a nonnegative integer" % (name, field))
        if not isinstance(row.get("lang"), str) or not isinstance(row.get("description"), str):
            raise ValueError("%s requires language and description strings" % name)
        observations = row.get("observations", [])
        if not observations or any(o.get("url") not in source_urls for o in observations):
            raise ValueError("%s requires source observations" % name)
        for observation in observations:
            if datetime.fromisoformat(observation["fetched_at"]).utcoffset() is None:
                raise ValueError("Observation timestamp requires a timezone")
            if type(observation.get("source_rank")) is not int or observation["source_rank"] < 1:
                raise ValueError("Observation requires a positive source rank")
        latest = observations[-1]
        if latest.get("today") != row["today"] or latest.get("total") != row["total"]:
            raise ValueError("%s counters differ from its latest observation" % name)
    return rows


def verify_snapshots(ranking, directory):
    """Verify hashes, complete board membership and every observation against raw HTML."""
    directory = Path(directory)
    parsed_sources = {}
    for source in ranking["sources"]:
        filename = source.get("raw_file", "")
        if not filename or Path(filename).name != filename or not filename.endswith(".html"):
            raise ValueError("Snapshot raw_file must be a plain .html filename")
        raw = (directory / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Snapshot hash mismatch: %s" % filename)
        rows = parse_trending(raw.decode("utf-8"))
        if len(rows) != source["count"]:
            raise ValueError("Snapshot count mismatch: %s" % filename)
        parsed_sources[source["url"]] = {r["name"].lower(): r for r in rows}
    actual_names = {name for rows in parsed_sources.values() for name in rows}
    if actual_names != {row["name"].lower() for row in ranking["repos"]}:
        raise ValueError("Ranking membership differs from source snapshots")
    for row in ranking["repos"]:
        expected_urls = {url for url, rows in parsed_sources.items() if row["name"].lower() in rows}
        observations = row["observations"]
        if expected_urls != {o["url"] for o in observations} or len(expected_urls) != len(observations):
            raise ValueError("Missing or duplicate source observation: %s" % row["name"])
        for observation in observations:
            original = parsed_sources[observation["url"]].get(row["name"].lower())
            source = next(s for s in ranking["sources"] if s["url"] == observation["url"])
            if original is None or any(original[k] != observation.get(k) for k in ("today", "total", "source_rank")) or source["fetched_at"] != observation["fetched_at"]:
                raise ValueError("Observation differs from snapshot: %s" % row["name"])
        latest = parsed_sources[observations[-1]["url"]][row["name"].lower()]
        if any(latest[k] != row[k] for k in ("lang", "description")):
            raise ValueError("Repository details differ from latest snapshot: %s" % row["name"])


def prepare_report(ranking, editorial=None, report_date=None):
    rows = validate_ranking(ranking)
    if editorial is None:
        editorial = []
    if not isinstance(editorial, list):
        raise ValueError("Editorial JSON must be an array")
    edits = {}
    names = {r["name"].lower() for r in rows}
    for edit in editorial:
        key = edit["name"].lower()
        if key not in names or key in edits:
            raise ValueError("Unknown or duplicate editorial repository: %s" % edit["name"])
        edits[key] = edit
    data, more = [], []
    for row in sorted(rows, key=lambda r: (-r["today"], r["name"].lower())):
        item = {"name": row["name"], "lang": row["lang"], "total": row["total"], "today": row["today"],
                "cat": "uncategorized", "d": {"zh": row["description"], "en": row["description"]},
                "os": [], "runtime": [], "os_evidence": [], "sources": [], "observations": row["observations"]}
        edit = edits.get(row["name"].lower())
        if edit:
            category = edit.get("cat", "uncategorized")
            if category not in CATEGORIES:
                raise ValueError("Unknown category: %s" % category)
            item["cat"] = category
            if "d" in edit:
                item["d"] = bilingual(edit["d"], "d")
            item["os"] = edit.get("os", [])
            item["runtime"] = edit.get("runtime", [])
            for field, allowed in (("os", OS_KEYS), ("runtime", RUNTIME_KEYS)):
                if not isinstance(item[field], list) or any(x not in allowed for x in item[field]):
                    raise ValueError("Unknown %s value" % field)
            evidence = edit.get("os_evidence", [])
            if not isinstance(evidence, list):
                raise ValueError("os_evidence must be an array")
            for e in evidence:
                if e.get("os") not in OS_KEYS | RUNTIME_KEYS:
                    raise ValueError("Invalid compatibility evidence key")
                safe_url(e["url"])
                bilingual(e["note"], "os_evidence.note")
            for os_key in item["os"] + item["runtime"]:
                if not any(e["os"] == os_key for e in evidence):
                    raise ValueError("%s: %s needs explicit compatibility evidence" % (item["name"], os_key))
            item["os_evidence"] = evidence
            sources = edit.get("sources", [])
            if not isinstance(sources, list):
                raise ValueError("sources must be an array")
            for source in sources:
                safe_url(source["url"])
                bilingual(source["label"], "sources.label")
            item["sources"] = sources
            if type(edit.get("featured", False)) is not bool:
                raise ValueError("featured must be a boolean")
            if edit.get("featured"):
                if not sources:
                    raise ValueError("Featured analysis requires source links")
                for field in ("d", "purpose", "feats", "warns"):
                    item[field] = bilingual(edit.get(field), field, list_value=field in ("feats", "warns"))
                data.append(item)
                continue
        more.append(item)
    resolved_date = report_date or ranking["fetched_at"][:10]
    date.fromisoformat(resolved_date)
    metadata = {"date": resolved_date, "scope": ranking["scope"], "fetched_at": ranking["fetched_at"],
                "sources": ranking["sources"], "editorial": bool(editorial)}
    return metadata, data, more


def render(template, metadata, data, more):
    def js(value):
        return json.dumps(value, ensure_ascii=False, indent=1).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    block = "/* BEGIN REPORT_DATA */\nconst REPORT = %s;\nconst DATA = %s;\nconst MORE = %s;\n/* END REPORT_DATA */" % (js(metadata), js(data), js(more))
    output, count = re.subn(r"/\* BEGIN REPORT_DATA \*/.*?/\* END REPORT_DATA \*/", lambda _: block, template, flags=re.S)
    if count != 1:
        raise ValueError("Template must contain exactly one REPORT_DATA block")
    output = re.sub(r"<title>.*?</title>", "<title>GitHub Trending · %s</title>" % metadata["date"], output, count=1)
    output = re.sub(r'(<span class="date-pill" id="datePill">).*?(</span>)', lambda m: m[1] + metadata["date"] + m[2], output, count=1)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ranking")
    parser.add_argument("output")
    parser.add_argument("--editorial", help="Optional bilingual analysis array; facts must include evidence")
    parser.add_argument("--snapshot-dir", help="Verify raw snapshot hashes, membership and observations before rendering")
    parser.add_argument("--date", help="Display date YYYY-MM-DD; default is the source snapshot's UTC date")
    parser.add_argument("--template", default=str(Path(__file__).resolve().parents[1] / "references/report-template.html"))
    args = parser.parse_args(argv)
    try:
        ranking = json.loads(Path(args.ranking).read_text(encoding="utf-8"))
        editorial = json.loads(Path(args.editorial).read_text(encoding="utf-8")) if args.editorial else None
        metadata, data, more = prepare_report(ranking, editorial, args.date)
        if args.snapshot_dir:
            verify_snapshots(ranking, args.snapshot_dir)
        output = render(Path(args.template).read_text(encoding="utf-8"), metadata, data, more)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))
    print("saved %s: %s featured + %s table rows" % (args.output, len(data), len(more)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
