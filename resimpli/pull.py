#!/usr/bin/env python3
"""Pull reSimpli data and dump raw JSON to resimpli/raw/.

Authentication (two options - first one found is used):
  Option A - Email + Password (preferred, always works):
    Set RESIMPLI_EMAIL and RESIMPLI_PASSWORD env vars (or in .env).
    The script logs in fresh each run and obtains a JWT automatically.

  Option B - Direct JWT Token:
    Set RESIMPLI_API_TOKEN to the full JWT value from
    dashboard.resimpli.com -> Local Storage -> "token".
    Works until the session becomes inactive (~30 days without use).

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

ENDPOINTS: dict[str, tuple[str, dict]] = {
    "leads":         ("lead/listWithFilter",  {"page": 1, "perPage": 500}),
    "lead_statuses": ("mainStatus/list",      {}),
    "contacts":      ("contact/list",         {"page": 1, "perPage": 500}),
    "tasks":         ("task/list",            {"page": 1, "perPage": 500}),
    "appointments":  ("events/list",          {"page": 1, "perPage": 500}),
    "campaigns":     ("campaign/list",        {"page": 1, "perPage": 500}),
    "users":         ("user/getUsers",        {}),
}


def _read_dotenv() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_credentials() -> tuple:
    env = _read_dotenv()
    def get(key: str):
        return os.environ.get(key, "").strip() or env.get(key, "").strip() or None
    return get("RESIMPLI_EMAIL"), get("RESIMPLI_PASSWORD"), get("RESIMPLI_API_TOKEN")


def login(email: str, password: str):
    url = BASE_URL + "user/login"
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"email": email, "password": password},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[auth] login request failed: {exc}")
        return None

    if r.status_code == 200:
        try:
            body = r.json()
            jwt = (
                body.get("data", {}).get("token")
                or body.get("token")
                or body.get("data", {}).get("accessToken")
                or body.get("accessToken")
            )
            if jwt:
                print("[auth] login successful - fresh JWT obtained")
                return jwt
            else:
                print(f"[auth] login 200 but no token in response: {json.dumps(body)[:200]}")
        except Exception as exc:
            print(f"[auth] login response parse error: {exc}")
    else:
        try:
            msg = r.json().get("message", r.text[:120])
        except Exception:
            msg = r.text[:120]
        print(f"[auth] login failed {r.status_code}: {msg}")
    return None


def get_jwt(email, password, direct_jwt) -> str:
    if email and password:
        jwt = login(email, password)
        if jwt:
            return jwt
        sys.exit("ERROR: Login with RESIMPLI_EMAIL/RESIMPLI_PASSWORD failed.")

    if direct_jwt:
        print("[auth] using RESIMPLI_API_TOKEN directly as Bearer JWT")
        return direct_jwt

    sys.exit(
        "ERROR: No credentials found. Set one of:\n"
        "  A) RESIMPLI_EMAIL + RESIMPLI_PASSWORD  (logs in fresh each run)\n"
        "  B) RESIMPLI_API_TOKEN = full JWT from dashboard.resimpli.com Local Storage -> 'token'"
    )


def make_headers(jwt: str) -> dict:
    return {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def probe(jwt: str) -> bool:
    url = BASE_URL + "user/get_user_detail"
    try:
        r = requests.post(url, headers=make_headers(jwt), json={}, timeout=15)
    except requests.RequestException as exc:
        print(f"[probe] connection error: {exc}")
        return False
    if r.status_code == 200:
        print("[probe] JWT valid - authenticated OK")
        return True
    try:
        msg = r.json().get("message", r.text[:120])
    except Exception:
        msg = r.text[:120]
    print(f"[probe] {r.status_code}: {msg}")
    if r.status_code == 401:
        print("HINT: Add RESIMPLI_EMAIL and RESIMPLI_PASSWORD as GitHub Secrets for fresh login each run.")
    return False


def fetch_endpoint(jwt: str, path: str, body: dict) -> tuple:
    url = BASE_URL + path
    try:
        r = requests.post(url, headers=make_headers(jwt), json=body, timeout=30)
    except requests.RequestException as exc:
        return -1, str(exc)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def extract_records(body: Any) -> list:
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


def pull_all(jwt: str) -> int:
    RAW_DIR.mkdir(exist_ok=True)
    manifest: dict[str, Any] = {}
    partial = False
    for name, (path, body) in ENDPOINTS.items():
        code, resp = fetch_endpoint(jwt, path, body)
        if code == 200:
            records = extract_records(resp)
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
                msg = (resp.get("message", str(resp))[:120] if isinstance(resp, dict) else str(resp)[:120])
            except Exception:
                msg = str(resp)[:120]
            print(f"[{code}] {name}: {msg}")
            manifest[name] = {"status": "error", "code": code, "detail": msg}
            partial = True

    (RAW_DIR / "_manifest.json").write_text(
        json.dumps({"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "base_url": BASE_URL, "endpoints": manifest}, indent=2)
    )
    return 2 if partial else 0


def main() -> None:
    email, password, direct_jwt = load_credentials()
    jwt = get_jwt(email, password, direct_jwt)
    if not probe(jwt):
        sys.exit(1)
    sys.exit(pull_all(jwt))


if __name__ == "__main__":
    main()
