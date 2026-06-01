#!/usr/bin/env python3
"""Post the daily reSimpli briefing to Slack — detailed edition.

Reads resimpli/memory.md and posts a rich Block Kit message to
$SLACK_WEBHOOK_URL with:
  - Pipeline snapshot + day-over-day deltas
  - Full status breakdown with changes
  - Hot leads — individual cards with status, age, notes, next action
  - Bottlenecks — each stage with count and median age
  - Stale leads — individual cards with days since contact
  - Top 3 to act on today
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "memory.md"
SNAPSHOTS = ROOT / "snapshots"


# ── helpers ─────────────────────────────────────────────────────────────────

def load_memory() -> str:
    if not MEMORY.exists():
        sys.exit(f"ERROR: {MEMORY} not found — run summarize.py first.")
    return MEMORY.read_text()


def parse_snapshot_date(text: str) -> str:
    m = re.search(r"Snapshot:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", text)
    return m.group(1) if m else "today"


def parse_pipeline(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, pat in [
        ("total",  r"\*\*Total leads:\*\*\s*([\d+\-= ()]+)"),
        ("active", r"\*\*Active \(non-terminal\):\*\*\s*(\d+)"),
        ("hot",    r"\*\*Hot \(progressing\):\*\*\s*(\d+)"),
    ]:
        m = re.search(pat, text)
        if m:
            out[label] = m.group(1).strip()
    return out


def parse_status_table(text: str) -> list[tuple[str, str]]:
    m = re.search(r"### By status\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).strip().splitlines():
        match = re.match(r"\s*-\s+(.+?):\s+(\d+.*)", line)
        if match:
            rows.append((match.group(1).strip(), match.group(2).strip()))
    return rows[:12]


def parse_lead_blocks(text: str, heading: str, max_leads: int = 8) -> list[dict]:
    pat = rf"## {re.escape(heading)}.*?\n(.*?)(?=\n## |\Z)"
    m = re.search(pat, text, re.DOTALL)
    if not m:
        return []
    leads = []
    current: dict | None = None
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        if re.match(r"^[\d]+\.\s+\*\*|^-\s+\*\*", line):
            if current:
                leads.append(current)
            current = {"raw": line, "note": ""}
            name_m = re.search(r"\*\*(.+?)\*\*", line)
            current["name"] = name_m.group(1) if name_m else "Unknown"
            parts = re.split(r" — ", line)
            current["address"] = parts[1].strip() if len(parts) > 1 else ""
            status_m = re.search(r"_(.+?)_", line)
            current["status"] = status_m.group(1) if status_m else ""
            age_m = re.search(r"last activity (\d+d) ago", line)
            current["age"] = age_m.group(1) if age_m else "?"
            src_m = re.search(r"via (.+?)$", line)
            current["source"] = src_m.group(1).strip() if src_m else ""
        elif line.startswith("- _note:_") and current:
            current["note"] = line.replace("- _note:_", "").strip()[:150]
        if len(leads) >= max_leads:
            break
    if current and len(leads) < max_leads:
        leads.append(current)
    return leads


def parse_bottlenecks(text: str) -> list[dict]:
    m = re.search(r"## Bottlenecks\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not m:
        return []
    results = []
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        bm = re.match(r"-\s+\*\*(.+?)\*\*\s+—\s+(\d+) leads \((\d+)% of active\), median age (\d+)d", line)
        if bm:
            results.append({"stage": bm.group(1), "count": bm.group(2), "pct": bm.group(3), "median_age": bm.group(4)})
    return results[:5]


def suggest_action(lead: dict) -> str:
    status = lead.get("status", "").lower()
    age = lead.get("age", "0d").replace("d", "")
    try:
        days = int(age)
    except ValueError:
        days = 0
    if any(s in status for s in ["contract sent", "contract"]):
        return "Follow up on contract — check if signed"
    elif any(s in status for s in ["negotiating", "offer"]):
        return "Call to push offer forward"
    elif any(s in status for s in ["appointment", "walkthrough"]):
        return "Confirm appointment / send reminder"
    elif any(s in status for s in ["under contract", "pending", "closing"]):
        return "Monitor closing — coordinate title/attorney"
    elif days > 14:
        return f"Re-engage — {days}d since last contact"
    else:
        return "Follow up call"


def lead_card(lead: dict, show_action: bool = False) -> str:
    name = lead.get("name", "Unknown")
    addr = lead.get("address", "")
    status = lead.get("status", "")
    age = lead.get("age", "?")
    note = lead.get("note", "")
    source = lead.get("source", "")
    lines = [f"*{name}*"]
    if addr:
        lines.append(f"📍 {addr}")
    detail = f"_{status}_ · {age} since contact"
    if source:
        detail += f" · via {source}"
    lines.append(detail)
    if note:
        lines.append(f"💬 _{note[:120]}_")
    if show_action:
        lines.append(f"➡️ {suggest_action(lead)}")
    return "\n".join(lines)


def divider() -> dict:
    return {"type": "divider"}

def header_block(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text}}

def section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def fields_block(field_list: list[str]) -> dict:
    return {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in field_list]}

def context_block(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def build_payload(text: str) -> dict:
    date = parse_snapshot_date(text)
    pipeline = parse_pipeline(text)
    status_rows = parse_status_table(text)
    hot_leads = parse_lead_blocks(text, "Hot leads (most likely to move)", max_leads=8)
    stale_leads = parse_lead_blocks(text, "Stale / needs follow-up", max_leads=6)
    bottlenecks = parse_bottlenecks(text)
    blocks: list[dict] = []
    blocks.append(header_block(f"📊 reSimpli Daily Briefing — {date}"))
    total = pipeline.get("total", "?")
    active = pipeline.get("active", "?")
    hot_count = pipeline.get("hot", "?")
    blocks.append(fields_block([f"*Total Leads*\n{total}", f"*Active*\n{active}", f"*Hot / Progressing*\n{hot_count}"]))
    if status_rows:
        blocks.append(divider())
        status_lines = "\n".join(f"• *{s}*: {n}" for s, n in status_rows)
        blocks.append(section(f"*Pipeline by Status*\n{status_lines}"))
    blocks.append(divider())
    blocks.append(section("*🔥 Hot Leads — Most Likely to Move*"))
    if hot_leads:
        for lead in hot_leads:
            blocks.append(section(lead_card(lead, show_action=True)))
    else:
        blocks.append(section("_No hot leads detected._"))
    top3 = hot_leads[:3] if hot_leads else stale_leads[:3]
    if top3:
        blocks.append(divider())
        top3_text = "*⚡ Top 3 to Act on Today*\n"
        for i, lead in enumerate(top3, 1):
            action = suggest_action(lead)
            top3_text += f"\n*{i}. {lead.get('name', '?')}* — {lead.get('address', '')} — _{lead.get('status', '')}_\n   {action}"
        blocks.append(section(top3_text))
    blocks.append(divider())
    blocks.append(section("*⚠️ Bottlenecks*"))
    if bottlenecks:
        for b in bottlenecks:
            blocks.append(section(f"*{b['stage']}* — {b['count']} leads ({b['pct']}% of active) · median age *{b['median_age']} days*\n_Leads sitting here too long. Review and push forward or kill._"))
    else:
        blocks.append(section("_No bottlenecks detected. Pipeline flowing well._"))
    blocks.append(divider())
    blocks.append(section("*🕰 Stale / Needs Follow-Up (>14 days)*"))
    if stale_leads:
        for lead in stale_leads:
            blocks.append(section(lead_card(lead, show_action=True)))
    else:
        blocks.append(section("_No stale active leads. Nice work._"))
    blocks.append(divider())
    blocks.append(context_block("Full pipeline detail in `resimpli/memory.md` · Snapshots in `resimpli/snapshots/` · Runs daily at 8 AM ET via GitHub Actions"))
    return {"blocks": blocks}


def main() -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        sys.exit("ERROR: SLACK_WEBHOOK_URL env var is not set.")
    text = load_memory()
    payload = build_payload(text)
    resp = requests.post(webhook_url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=10)
    if resp.status_code == 200 and resp.text == "ok":
        print("[ok] Slack message sent.")
    else:
        sys.exit(f"ERROR: Slack returned {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    main()
