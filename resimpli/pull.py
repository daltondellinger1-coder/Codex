#!/usr/bin/env python3
"""Pull reSimpli data and dump raw JSON to resimpli/raw/.

Authentication (two options — first one found is used):
  Option A – Email + Password (preferred, always works):
    Set RESIMPLI_EMAIL and RESIMPLI_PASSWORD env vars (or in .env).
    The script logs in fresh each run using a cookie-based session.

  Option B – Direct JWT Token:
    Set RESIMPLI_API_TOKEN to the full JWT value from
    dashboard.resimpli.com → Local Storage → "token".
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

# Endpoints: key = filename, value = (path, request_body)
ENDPOINTS: dict[str, tuple[str, dict]] = {
    "leads":         ("lead/listWithFilter",  {"page": 1, "perPage": 500}),
    "lead_statuses": ("mainStatus/list",      {}),
    "contacts":      ("contact/list",         {"page": 1, "perPage": 500}),
    "tasks":         ("task/list",            {"page": 1, "perPage": 500}),
    "appointments":  ("events/list",          {"page": 1, "perPage": 500}),
    "campaigns":     ("campaign/list",        {"page": 1, "perPage": 500}),
    "users":         ("user/getUsers",        {}),
}


# ── credential loading ────────────────────────────────────────────────────────

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


def load_credentials() -> tuple[str | None, str | None, str | None]:
    """Return (email, password, direct_jwt). At least one pair must be usable."""
    env = _read_dotenv()

    def get(key: str) -> str | None:
        return os.environ.get(key, "").strip() or env.get(key, "").strip() or None

    return get("RESIMPLI_EMAIL"), get("RESIMPLI_PASSWORD"), get("RESIMPLI_API_TOKEN")


# ── authentication ────────────────────────────────────────────────────────────

def login(session, email, password):
    url = BASE_URL + "user/login"
    try:
        r = session.post(
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
            print(f"[auth] login 200 top-level keys: {list(body.keys())}")
            data = body.get("data", {})
            if isinstance(data, dict):
                print(f"[auth] login data keys: {list(data.keys())}")
            cookies = dict(session.cookies)
            print(f"[auth] session cookies: {list(cookies.keys())}")
            print(f"[auth] Set-Cookie: {r.headers.get('Set-Cookie', 'none')}")

            def find_token(obj, path=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        cur = f"{path}.{k}"
                        if k.lower() in ("token", "accesstoken", "jwt", "authtoken",
                                         "bearertoken", "jwttoken", "id_token",
                                         "access_token", "auth_token") \
                                and isinstance(v, str) and len(v) > 20:
                            print(f"[auth] found token at {cur}")
                            return v
                        result = find_token(v, cur)
                        if result:
                            return result
                elif isinstance(obj, str) and len(obj) > 100 and obj.count(".") == 2:
                    print(f"[auth] found JWT-like string at {path}")
                    return obj
                return None

            jwt = find_token(body)
            if jwt:
                print("[auth] login successful — JWT found in body")
                return jwt

            for name, value in cookies.items():
                if len(value) > 50 and value.count(".") == 2:
                    print(f"[auth] found JWT in cookie '{name}'")
                    return value
                if name.lower() in ("token", "jwt", "accesstoken", "auth", "authtoken"):
                    print(f"[auth] found auth cookie '{name}'")
                    return value

            isTwoFactor = (isinstance(data, dict) and data.get("isTwoFactorAuth"))
            if not isTwoFactor and isinstance(data, dict) and data.get("email"):
                print("[auth] login succeeded via cookie/session auth")
                return "__session__"

            print(f"[auth] login 200 but no auth found: {json.dumps(body)[:800]}")

        except Exception as exc:
            print(f"[auth] login response parse error: {exc}")
    else:
        try:
            msg = r.json().get("message", r.text[:120])
        except Exception:
            msg = r.text[:120]
        print(f"[auth] login failed {r.status_code}: {msg}")

    return None


def get_session_and_jwt(email, password, direct_jwt):
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    if email and password:
        result = login(session, email, password)
        if result:
            return session, result
        sys.exit("ERROR: Login with RESIMPLI_EMAIL/RESIMPLI_PASSWORD failed.")

    if direct_jwt:
        print("[auth] using RESIMPLI_API_TOKEN directly")
        return session, direct_jwt

    sys.exit(
        "ERROR: No credentials found. Set RESIMPLI_EMAIL+RESIMPLI_PASSWORD or RESIMPLI_API_TOKEN."
    )


# ── API helpers ───────────────────────────────────────────────────────────────

def make_headers(jwt):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if jwt and jwt != "__session__":
        h["Authorization"] = f"Bearer {jwt}"
    return h


def probe(session, jwt):
    url = BASE_URL + "user/get_user_detail"
    try:
        r = session.post(url, headers=make_headers(jwt), json={}, timeout=15)
    except requests.RequestException as exc:
        print(f"[probe] connection error: {exc}")
        return False

    if r.status_code == 200:
        print("[probe] auth valid ✓")
        return True

    try:
        msg = r.json().get("message", r.text[:120])
    except Exception:
        msg = r.text[:120]

    print(f"[probe] {r.status_code}: {msg}")
    if r.status_code == 401:
        print("HINT: Session inactive. Ensure RESIMPLI_EMAIL+RESIMPLI_PASSWORD are set.")
    return False


def fetch_endpoint(session, jwt, path, body):
    url = BASE_URL + path
    try:
        r = session.post(url, headers=make_headers(jwt), json=body, timeout=30)
    except requests.RequestException as exc:
        return -1, str(exc)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def extract_records(body):
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


# ── main pull ─────────────────────────────────────────────────────────────────

def pull_all(session, jwt):
    RAW_DIR.mkdir(exist_ok=True)
    manifest = {}
    partial = False

    for name, (path, body) in ENDPOINTS.items():
        code, resp = fetch_endpoint(session, jwt, path, body)
        if code == 200:
            records = extract_records(resp)
            count = len(records) if records else (1 if resp else 0)
            out = RAW_DIR / f"{name}.json"
            out.write_text(json.dumps(resp, indent=2, default=str))
            print(f"[ok] {name}: {count} records → {out.relative_to(REPO_ROOT)}")
            manifest[name] = {"status": "ok", "path": path, "count": count}
        elif code == -1:
            print(f"[err] {name}: connection error — {resp}")
            manifest[name] = {"status": "connection_error", "detail": str(resp)}
            partial = True
        else:
            try:
                msg = (resp.get("message", str(resp))[:120]
                       if isinstance(resp, dict) else str(resp)[:120])
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


def main():
    email, password, direct_jwt = load_credentials()
    session, jwt = get_session_and_jwt(email, password, direct_jwt)

    if not probe(session, jwt):
        sys.exit(1)

    exit_code = pull_all(session, jwt)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
