"""Small stdlib HTTP client: bounded retries, optional public-API cache, no token logging."""
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        tmp = f.name
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fetch(url, *, api=True, cache_dir=None, cache_ttl=3600, attempts=3):
    cache_file = None
    if api and cache_dir:
        cache_file = Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            age = time.time() - cached["saved_at"]
            result = cached["result"]
            if 0 <= age < cache_ttl and isinstance(result, dict) and isinstance(result.get("data"), dict) and isinstance(result.get("fetched_at"), str):
                return result
        except (OSError, ValueError, KeyError, TypeError):
            pass
    headers = {"User-Agent": "github-trending-daily", "Accept": "application/vnd.github+json" if api else "text/html"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    # Never send API credentials to a web page or another host.
    if api and url.startswith("https://api.github.com/") and token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(attempts):
        delay = min(2 ** attempt, 30)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
            payload = json.loads(body) if api else body
            if api and not isinstance(payload, dict):
                return {"__error__": "Expected a JSON object", "kind": "invalid_response"}
            result = {"data": payload, "fetched_at": utc_now()}
            if cache_file:
                write_json(cache_file, {"saved_at": time.time(), "result": result})
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            secondary = False
            if status == 403 and error.fp is not None:
                secondary = "rate limit" in error.read(4096).decode("utf-8", "replace").lower()
            limited = status == 429 or (status == 403 and (secondary or error.headers.get("X-RateLimit-Remaining") == "0" or error.headers.get("Retry-After")))
            result = {"__error__": "GitHub rate limit" if limited else "HTTP %s" % status,
                      "status": status, "kind": "rate_limit" if limited else "http"}
            if limited:
                result["retry_at"] = error.headers.get("X-RateLimit-Reset")
                retry_after = error.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else max(1, float(result["retry_at"]) - time.time())
                except (TypeError, ValueError):
                    delay = 60  # GitHub requires at least a minute without reset/retry headers.
                result["retry_after"] = delay
                # Report a long reset rather than block a daily job indefinitely.
                if delay > 30:
                    return result
            if not limited and status not in (500, 502, 503, 504):
                return result
        except (urllib.error.URLError, TimeoutError, OSError):
            result = {"__error__": "Network request failed", "kind": "network"}
        except ValueError:
            return {"__error__": "Invalid JSON response", "kind": "invalid_response"}
        if attempt + 1 < attempts:
            time.sleep(max(0, delay))
    return result
