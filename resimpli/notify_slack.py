#\!/usr/bin/env python3
"""Post the daily reSimpli briefing to Slack.

Reads resimpli/memory.md (already written by summarize.py) and POSTs a
tight summary to $SLACK_WEBHOOK_URL using Slack's Block Kit format.

Required env var:
    SLACK_WEBHOOK_URL  â Slack Incoming Webhook URL
                         (Settings â Integrations â Incoming Webhooks in Slack,
                          or stored as a GitHub Secret named SLACK_WEBHOOK_URL)
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


def load_memory() -> str:
    if not MEMORY.exists():
        sys.exit(f"ERROR: {MEMORY} not found â run summarize.py first.")
    return MEMORY.read_text()


def parse_section(text: str, heading: str) -> list[str]:
    """Return bullet lines under a ## heading."""
    pattern = rf"## {re.escape(heading)}.*?\n(.*?)(?=\n## |\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return []
    block = m.group(1).strip()
    lines = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            # Strip markdown bold/italic for Slack mrkdwn
            clean = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)  # **x** â *x*
            clean = re.sub(r"_(.+?)_", r"_\1_", clean)       # already Slack-compatible
            lines.append(clean)
        if len(lines) >= 5:
            break
    return lines


def parse_pipeline(text: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for label, pattern in [
        ("total",  r"Total leads:\*\*\s*([\d+\-= ()]+)"),
        ("active", r"Active \(non-terminal\):\*\*\s*(\d+)"),
        ("hot",    r"Hot \(progressing\):\*\*\s*(\d+)"),
    ]:
        m = re.search(pattern, text)
        if m:
            info[label] = m.group(1).strip()
    return info


def parse_snapshot_date(text: str) -> str:
    m = re.search(r"Snapshot:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", text)
    return m.group(1) if m else "today"


def build_payload(text: str) -> dict:
    date = parse_snapshot_date(text)
    pipeline = parse_pipeline(text)
    hot_lines = parse_section(text, "Hot leads (most likely to move)")
    stale_lines = parse_section(text, "Stale / needs follow-up")
    bottleneck_lines = parse_section(text, "Bottlenecks")

    def bullet_block(lines: list[str], fallback: str) -> str:
        if not lines:
            return f"_{fallback}_"
        return "\n".join(lines[:5])

    total_str = pipeline.get("total", "?")
    active_str = pipeline.get("active", "?")
    hot_str = pipeline.get("hot", "?")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"ð reSimpli Daily â {date}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total leads*\n{total_str}"},
                {"type": "mrkdwn", "text": f"*Active*\n{active_str}"},
                {"type": "mrkdwn", "text": f"*Hot*\n{hot_str}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*ð¥ Hot leads*\n{bullet_block(hot_lines, 'No hot leads detected.')}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*â ï¸ Bottlenecks*\n{bullet_block(bottleneck_lines, 'No bottlenecks detected.')}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*ð° Stale / needs follow-up*\n{bullet_block(stale_lines, 'No stale leads.')}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Full detail in `resimpli/memory.md` on the repo.",
                }
            ],
        },
    ]

    return {"blocks": blocks}


def main() -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        sys.exit("ERROR: SLACK_WEBHOOK_URL env var is not set.")

    text = load_memory()
    payload = build_payload(text)

    resp = requests.post(
        webhook_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=10,
    )

    if resp.status_code == 200 and resp.text == "ok":
        print("[ok] Slack message sent.")
    else:
        sys.exit(f"ERROR: Slack returned {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    main()
