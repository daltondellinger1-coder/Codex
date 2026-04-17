#!/usr/bin/env python3
"""Pull reSimpli data and dump raw JSON to resimpli/raw/.

Reads RESIMPLI_API_TOKEN from the environment (or .env at repo root).

The reSimpli API lives at https://live-api.resimpli.com/api/v4/
All endpoints use POST with JSON bodies and Bearer-token auth.

Exit codes:
  0  success (at least one endpoint returned data)
  1  config/auth failure
  2  partial failure (some endpoints errored)
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

BASE_URL = "https://live-api.resimpli.com/api/v4/"

# Endpoints to pull. Key = local filename; value = (path, body_template)
# All endpoints use POST with JSON body.
ENDPOINTS: dict[str, tuple[str, dict]] = {
    "leads":        ("lead/listWithFilter",   {"page": 1, "perPage": 500}),
    "lead_statuses":("mainStatus/list",       {}),
    "contacts":     ("contact/list",          {"page": 1, "perPage": 500}),
    "tasks":        ("task/list",             {"page": 1, "perPage": 500}),
    "appointments": ("events/list",           {"page": 1, "perPage": 500}),
    "campaigns":    ("campaign/list",         {"page": 1, "perPage": 500}),
    "users":        ("user/getUsers",         {}),
}


def load_env() -> str:
    """Load RESIMPLI_API_TOKEN from env or .env at repo root."""
    token = os.environ.get("RESIMPLI_API_TOKEN", "").strip()
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


def make_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def probe(token: str) -> bool:
    """Verify the token works by calling a lightweight endpoint."""
    url = BASE_URL + "user/get_user_detail"
    try:
        r = requests.post(url, headers=make_headers(token),
                          json={}, timeout=15)
    except requests.RequestException as exc:
        print(f"[probe] connection error: {exc}")
        return False

    if r.status_code == 200:
        print(f"[probe] authenticated OK (user/get_user_detail)")
        return True

    try:
        msg = r.json().get("message", r.text[:120])
    except Exception:
        msg = r.text[:120]

    print(f"[probe] {r.status_code}: {msg}")
    if r.status_code == 401:
        print(
            "HINT: The token may be expired or the session is inactive.\n"
            "  1. Open https://dashboard.resimpli.com in your browser and log in.\n"
            "  2. Open DevTools -> Application -> Local Storage -> dashboard.resimpli.com\n"
            "  3. Copy the value of the 'token' key (the long JWT string).\n"
            "  4. Update the RESIMPLI_API_TOKEN GitHub secret with that value."
        )
    return False


def fetch_endpoint(token: str, path: str, body: dict) -> tuple[int, Any]:
    url = BASE_URL + path
    try:
        r = requests.post(url, headers=make_headers(token),
                          json=body, timeout=30)
    except requests.RequestException as exc:
        return -1, str(exc)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def extract_records(body: Any, name: str) -> list:
    """Try to pull the list of records out of the response body."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "leads", "contacts", "tasks", "appointments",
                    "campaigns", "users", "records", "list", "items", "result"):
            if isinstance(body.get(key), list):
                return body[key]
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("leads", "records", "list", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
    return []


def pull_all(token: str) -> int:
    RAW_DIR.mkdir(exist_ok=True)
    manifest: dict[str, Any] = {}
    partial = False

    for name, (path, body) in ENDPOINTS.items():
        code, resp = fetch_endpoint(token, path, body)
        if code == 200:
            records = extract_records(resp, name)
            count = len(records) if records else (1 if resp else 0)
            out = RAW_DIR / f"{name}.json"
            out.write_text(json.dumps(resp, indent=2, default=str))
            print(f"[ok] {name}: {count} records -> {out.relative_to(REPO_ROOT)}")
            manifest[name] = {"status": "ok", "path": path, "count": count}
        elif code == -1:
            print(f"[err] {name}: connection error -- {resp}")
            manifest[name] = {"status": "connection_error", "detail": str(resp)}
            partial = True
        else:
            try:
                msg = resp.get("message", str(resp))[:120] if isinstance(resp, dict) else str(resp)[:120]
            except Exception:
                msg = str(resp)[:120]
            print(f"[{code}] {name}: {msg}")
            manifest[name] = {"status": "error", "code": code, "detail": msg}
            partial = True

    (RAW_DIR / "_manifest.json").write_text(
        json.dumps(
            {
                "pulled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "base_url": BASE_URL,
                "endpoints": manifest,
            },
            indent=2,
        )
    )
    return 2 if partial else 0


def main() -> None:
    token = load_env()
    if not probe(token):
        sys.exit(1)
    exit_code = pull_all(token)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
