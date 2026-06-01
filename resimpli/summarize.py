#!/usr/bin/env python3
"""Generate resimpli/memory.md from raw/*.json pulled by pull.py.

Design goals:
 - Defensive about field names (reSimpli's schema varies; use common synonyms).
 - Keep memory.md as the living doc: today's snapshot + delta vs yesterday.
 - Archive prior days under resimpli/snapshots/YYYY-MM-DD.md.
 - Surface actionable stuff: hot leads, stale leads, bottlenecks.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
MEMORY = ROOT / "memory.md"
SNAPSHOTS = ROOT / "snapshots"

# Field synonyms - reSimpli/CRM APIs use different names across versions
F_STATUS = ["status", "lead_status", "lead_status_name", "stage", "pipeline_stage"]
F_UPDATED = ["updated_at", "last_modified", "modified_at", "last_activity_at", "last_contact_at"]
F_CREATED = ["created_at", "created", "created_on"]
F_NAME = ["name", "full_name", "contact_name"]
F_FIRST = ["first_name", "firstname"]
F_LAST = ["last_name", "lastname"]
F_ADDRESS = ["address", "property_address", "street_address"]
F_CITY = ["city", "property_city"]
F_STATE = ["state", "property_state"]
F_MOTIVATION = ["motivation", "motivated", "motivation_level", "seller_motivation"]
F_SOURCE = ["source", "lead_source"]
F_NOTES = ["notes", "description", "last_note"]
F_PHONE = ["phone", "primary_phone", "phone_number"]
F_DISPOSITION = ["disposition", "lead_disposition"]

# Statuses that strongly suggest a deal is progressing
HOT_STATUSES = {"negotiating", "under contract", "contract sent", "offer made",
                "appointment set", "appointment", "walkthrough", "pending",
                "dd", "due diligence", "closing"}
# Statuses that represent dead/terminal - don't flag as stale
DEAD_STATUSES = {"dead", "lost", "closed lost", "unqualified", "not interested",
                 "dnc", "do not contact", "wrong number", "closed won", "closed",
                 "sold", "dispositioned"}


def pick(obj: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in obj and obj[k] not in (None, "", []):
            return obj[k]
        for actual in obj:
            if actual.lower() == k.lower() and obj[actual] not in (None, "", []):
                return obj[actual]
    return None


def parse_dt(v: Any) -> dt.datetime | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        try:
            return dt.datetime.fromtimestamp(v, tz=dt.timezone.utc)
        except (ValueError, OSError):
            return None
    s = str(v).strip()
    # ISO-ish formats
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(s[:26] if "." in s else s[:19], fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d
        except ValueError:
            continue
    return None


def load_leads() -> list[dict]:
    path = RAW_DIR / "leads.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "leads", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def display_name(lead: dict) -> str:
    name = pick(lead, F_NAME)
    if name:
        return str(name)
    first = pick(lead, F_FIRST) or ""
    last = pick(lead, F_LAST) or ""
    combined = f"{first} {last}".strip()
    return combined or f"Lead #{lead.get('id', '?')}"


def address_line(lead: dict) -> str:
    addr = pick(lead, F_ADDRESS) or ""
    city = pick(lead, F_CITY) or ""
    state = pick(lead, F_STATE) or ""
    parts = [p for p in [str(addr), ", ".join(p for p in [str(city), str(state)] if p)] if p]
    return " — ".join(parts)


def age_days(lead: dict) -> float | None:
    u = parse_dt(pick(lead, F_UPDATED)) or parse_dt(pick(lead, F_CREATED))
    if not u:
        return None
    return (dt.datetime.now(dt.timezone.utc) - u).total_seconds() / 86400


def status_of(lead: dict) -> str:
    s = pick(lead, F_STATUS)
    return str(s).strip() if s else "Unknown"


def is_hot(lead: dict) -> bool:
    s = status_of(lead).lower()
    if any(h in s for h in HOT_STATUSES):
        return True
    m = pick(lead, F_MOTIVATION)
    if m and str(m).lower() in {"high", "very high", "hot", "4", "5"}:
        return True
    return False


def is_dead(lead: dict) -> bool:
    s = status_of(lead).lower()
    return any(d in s for d in DEAD_STATUSES)


def bucketize(leads: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for l in leads:
        out.setdefault(status_of(l), []).append(l)
    return out


def fmt_lead(lead: dict) -> str:
    name = display_name(lead)
    addr = address_line(lead)
    stat = status_of(lead)
    age = age_days(lead)
    age_s = f"{age:.0f}d" if age is not None else "?"
    src = pick(lead, F_SOURCE) or ""
    parts = [f"**{name}**"]
    if addr:
        parts.append(addr)
    parts.append(f"_{stat}_")
    parts.append(f"last activity {age_s} ago")
    if src:
        parts.append(f"via {src}")
    return " — ".join(parts)


def load_prev_counts() -> dict[str, int]:
    """Parse yesterday's snapshot to compute deltas."""
    if not SNAPSHOTS.exists():
        return {}
    files = sorted(SNAPSHOTS.glob("*.md"))
    if not files:
        return {}
    text = files[-1].read_text()
    counts: dict[str, int] = {}
    # Look for "- <status>: <n>" lines in the By status section
    in_block = False
    for line in text.splitlines():
        if line.startswith("### By status"):
            in_block = True
            continue
        if in_block:
            if line.startswith("#") or (line.strip() == "" and counts):
                break
            m = re.match(r"\s*-\s+(.+?):\s+(\d+)", line)
            if m:
                counts[m.group(1).strip()] = int(m.group(2))
    # total
    m = re.search(r"Total leads:\s*(\d+)", text)
    if m:
        counts["__total__"] = int(m.group(1))
    return counts


def delta(cur: int, prev: int | None) -> str:
    if prev is None:
        return ""
    diff = cur - prev
    if diff == 0:
        return " (=)"
    return f" ({'+' if diff > 0 else ''}{diff})"


def render(leads: list[dict], manifest: dict) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    prev = load_prev_counts()
    buckets = bucketize(leads)
    total = len(leads)

    active = [l for l in leads if not is_dead(l)]
    hot = sorted(
        [l for l in active if is_hot(l)],
        key=lambda x: age_days(x) if age_days(x) is not None else 9e9,
    )[:10]

    stale = sorted(
        [l for l in active if (age_days(l) or 0) > 14 and not is_hot(l)],
        key=lambda x: -(age_days(x) or 0),
    )[:10]

    # Bottleneck: status with the largest share of active leads AND median age > 14d
    bottlenecks: list[tuple[str, int, float]] = []
    for status, group in buckets.items():
        group_active = [l for l in group if not is_dead(l)]
        if len(group_active) < 3:
            continue
        ages = [a for a in (age_days(l) for l in group_active) if a is not None]
        if not ages:
            continue
        ages.sort()
        median = ages[len(ages) // 2]
        if median > 14:
            bottlenecks.append((status, len(group_active), median))
    bottlenecks.sort(key=lambda x: (-x[1], -x[2]))

    lines: list[str] = []
    lines.append("# reSimpli Memory")
    lines.append("")
    lines.append(f"_Snapshot: {now.strftime('%Y-%m-%d %H:%M UTC')}_")
    pulled = manifest.get("pulled_at", "unknown") if manifest else "unknown"
    lines.append(f"_Data pulled: {pulled}_")
    lines.append("")
    lines.append("## Pipeline")
    lines.append("")
    lines.append(f"- **Total leads:** {total}{delta(total, prev.get('__total__'))}")
    lines.append(f"- **Active (non-terminal):** {len(active)}")
    lines.append(f"- **Hot (progressing):** {sum(1 for l in active if is_hot(l))}")
    lines.append("")
    lines.append("### By status")
    lines.append("")
    for status in sorted(buckets, key=lambda s: -len(buckets[s])):
        n = len(buckets[status])
        lines.append(f"- {status}: {n}{delta(n, prev.get(status))}")
    lines.append("")

    lines.append("## Hot leads (most likely to move)")
    lines.append("")
    if hot:
        for i, l in enumerate(hot, 1):
            lines.append(f"{i}. {fmt_lead(l)}")
            note = pick(l, F_NOTES)
            if note:
                lines.append(f"   - _note:_ {str(note)[:200].replace(chr(10), ' ')}")
    else:
        lines.append("_None detected by current heuristics. Review HOT_STATUSES in summarize.py "
                     "if your pipeline uses different names._")
    lines.append("")

    lines.append("## Bottlenecks")
    lines.append("")
    if bottlenecks:
        for status, count, median in bottlenecks[:5]:
            share = 100 * count / max(len(active), 1)
            lines.append(
                f"- **{status}** — {count} leads ({share:.0f}% of active), median age {median:.0f}d"
            )
    else:
        lines.append("_No stages show median age > 14 days with ≥3 leads. Pipeline flowing cleanly._")
    lines.append("")

    lines.append("## Stale / needs follow-up")
    lines.append("")
    if stale:
        for l in stale:
            lines.append(f"- {fmt_lead(l)}")
    else:
        lines.append("_No active leads older than 14 days without hot signals._")
    lines.append("")

    lines.append("## Raw data manifest")
    lines.append("")
    for endpoint, meta in (manifest.get("endpoints", {}) if manifest else {}).items():
        if meta.get("status") == "ok":
            lines.append(f"- `{endpoint}`: {meta.get('count', '?')} records (path: `{meta.get('path')}`)")
        else:
            lines.append(f"- `{endpoint}`: **missing** (tried: {meta.get('tried', [])})")
    lines.append("")

    return "\n".join(lines) + "\n"


def archive_previous() -> None:
    if not MEMORY.exists():
        return
    SNAPSHOTS.mkdir(exist_ok=True)
    # name archive by the date stamp IN the file (so re-runs same day overwrite)
    text = MEMORY.read_text()
    m = re.search(r"Snapshot:\s*(\d{4}-\d{2}-\d{2})", text)
    stamp = m.group(1) if m else dt.date.today().isoformat()
    shutil.copy(MEMORY, SNAPSHOTS / f"{stamp}.md")


def main() -> None:
    if not RAW_DIR.exists():
        raise SystemExit(f"ERROR: {RAW_DIR} doesn't exist. Run pull.py first.")
    manifest_path = RAW_DIR / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    leads = load_leads()
    archive_previous()
    MEMORY.write_text(render(leads, manifest))
    print(f"[ok] wrote {MEMORY.relative_to(ROOT.parent)} — {len(leads)} leads analyzed")


if __name__ == "__main__":
    main()
