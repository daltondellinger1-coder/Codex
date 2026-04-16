#!/usr/bin/env python3
"""Pull reSimpli data and dump raw JSON to resimpli/raw/.

Reads RESIMPLI_API_TOKEN from the environment (or .env at repo root).

The reSimpli public API isn't well documented. On first run this script
probes a short list of candidate base URLs + auth header styles and
caches the working combo in resimpli/.cache.json so subsequent runs go
straight to the right endpoint.

Exit codes:
    0 success (at least one endpoint returned data)
    1 config/probe failure (no combo worked)
    2 partial failure (probe worked, some endpoints errored)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
RAW_DIR = ROOT / "raw"
CACHE_FILE = ROOT / ".cache.json"

# Endpoints to pull. Keys are local filenames; values are URL path candidates.
# If the first path 404s we try the rest. Extend this list as you discover
# what your account actually exposes.
ENDPOINTS: dict[str, list[str]] = {
    "leads": ["leads", "lead", "v1/leads", "api/leads"],
    "contacts": ["contacts", "contact", "v1/contacts"],
    "tasks": ["tasks", "task", "v1/tasks"],
    "appointments": ["appointments", "v1/appointments"],
    "campaigns": ["campaigns", "v1/campaigns"],
    "lead_statuses": ["lead-statuses", "lead_statuses", "v1/lead-statuses"],
    "users": ["users", "v1/users"],
}

BASE_URL_CANDIDATES = [
    "https://app.resimpli.com/api/",
    "https://app.resimpli.com/api/v1/",
    "https://api.resimpli.com/",
    "https://api.resimpli.com/v1/",
]

AUTH_STYLES = [
    ("Authorization", "Bearer {t}"),
    ("X-API-Key", "{t}"),
    ("X-Api-Token", "{t}"),
    ("apikey", "{t}"),
]

PROBE_PATHS = ["leads", "lead", "me", "user", "account"]


def load_env() -> str:
    """Load RESIMPLI_API_TOKEN from env or .env at repo root."""
    token = os.environ.get("RESIMPLI_API_TOKEN")
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "RESIMPLI_API_TOKEN":
                return v.strip().strip('"').strip("'")
    sys.exit("ERROR: RESIMPLI_API_TOKEN not set (env var or .env at repo root)")


def probe(token: str) -> dict[str, str]:
    """Find a working (base_url, auth header, auth format) combo.

    Returns a dict like {"base_url": ..., "auth_header": ..., "auth_format": ...}.
    """
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text())
            if all(k in cached for k in ("base_url", "auth_header", "auth_format")):
                print(f"[probe] using cached config: {cached['base_url']} / {cached['auth_header']}")
                return cached
        except json.JSONDecodeError:
            pass

    print("[probe] discovering working base URL + auth header...")
    for base in BASE_URL_CANDIDATES:
        for header, fmt in AUTH_STYLES:
            for path in PROBE_PATHS:
                url = base + path
                headers = {header: fmt.format(t=token), "Accept": "application/json"}
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                except requests.RequestException as exc:
                    print(f"  [skip] {url} ({header}): {exc.__class__.__name__}")
                    continue
                # 200 = works; 401/403 = auth header wrong; 404 = path wrong, auth could be right;
                # we accept 200 only as confirmation.
                if r.status_code == 200:
                    try:
                        r.json()
                    except ValueError:
                        continue
                    cfg = {"base_url": base, "auth_header": header, "auth_format": fmt}
                    CACHE_FILE.write_text(json.dumps(cfg, indent=2))
                    print(f"[probe] HIT {url} ({header}) -> cached to {CACHE_FILE.name}")
                    return cfg
                print(f"  [{r.status_code}] {url} ({header})")
    sys.exit(
        "ERROR: no base URL + auth combination returned 200. "
        "Add your account's API base URL and header to the candidates in pull.py, "
        "or share a doc link with the exact format."
    )


def fetch(cfg: dict[str, str], token: str, path: str) -> tuple[int, Any]:
    url = cfg["base_url"] + path
    headers = {
        cfg["auth_header"]: cfg["auth_format"].format(t=token),
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=30)
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return r.status_code, body


def pull_all(cfg: dict[str, str], token: str) -> int:
    RAW_DIR.mkdir(exist_ok=True)
    manifest: dict[str, dict[str, Any]] = {}
    partial = False
    for name, path_candidates in ENDPOINTS.items():
        hit = None
        for path in path_candidates:
            code, body = fetch(cfg, token, path)
            if code == 200:
                hit = (path, body)
                break
            print(f"  [{code}] {name}: {path}")
        if hit is None:
            print(f"[miss] {name}: no candidate path returned 200")
            manifest[name] = {"status": "missing", "tried": path_candidates}
            partial = True
            continue
        path, body = hit
        count = len(body) if isinstance(body, list) else (
            len(body.get("data", [])) if isinstance(body, dict) and isinstance(body.get("data"), list) else 1
        )
        out = RAW_DIR / f"{name}.json"
        out.write_text(json.dumps(body, indent=2, default=str))
        print(f"[ok]  {name}: {count} records -> {out.relative_to(REPO_ROOT)}")
        manifest[name] = {"status": "ok", "path": path, "count": count}

    (RAW_DIR / "_manifest.json").write_text(
        json.dumps(
            {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "endpoints": manifest},
            indent=2,
        )
    )
    return 2 if partial else 0


def main() -> None:
    token = load_env()
    cfg = probe(token)
    exit_code = pull_all(cfg, token)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
