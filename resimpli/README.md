# reSimpli data extraction

Daily pipeline that pulls reSimpli CRM data, summarizes it, and keeps a
living memory file at `resimpli/memory.md`.

## Setup (one-time)

```sh
pip install -r resimpli/requirements.txt
cp .env.example .env
# Edit .env and paste your reSimpli API token (Profile → API Token in the app)
```

## Daily run

```sh
python resimpli/pull.py        # fetches raw JSON into resimpli/raw/
python resimpli/summarize.py   # regenerates resimpli/memory.md
```

Inside a Claude Code session, just run `/resimpli-daily`.

## What gets pulled

`pull.py` probes reSimpli's API on first run to find the working base URL +
auth header combo, then caches it to `resimpli/.cache.json`. It attempts to
fetch these endpoints:

- leads, contacts, tasks, appointments, campaigns, lead_statuses, users

If reSimpli's actual endpoint paths differ, edit `ENDPOINTS` in `pull.py`.
Missing endpoints are reported but don't fail the run.

## What the summary surfaces

`summarize.py` reads `raw/leads.json` and generates `memory.md` with:

- **Pipeline counts** by status, with day-over-day deltas
- **Hot leads** — statuses like "Negotiating", "Under Contract", "Appointment
  Set", or motivation flags set to high
- **Bottlenecks** — stages holding >3 active leads with median age >14 days
- **Stale leads** — active leads untouched >14 days without hot signals

Heuristic status lists (`HOT_STATUSES`, `DEAD_STATUSES`) are at the top of
`summarize.py`. Tune them to match your pipeline's actual status names.

## Files

| Path | Committed | Purpose |
|------|-----------|---------|
| `resimpli/pull.py` | yes | API extraction |
| `resimpli/summarize.py` | yes | Memory file generator |
| `resimpli/memory.md` | yes | Living daily summary |
| `resimpli/snapshots/*.md` | yes | Archived prior-day summaries |
| `resimpli/raw/*.json` | **no** (gitignored) | Raw API dumps |
| `resimpli/.cache.json` | **no** (gitignored) | Probed API config |
| `.env` | **no** (gitignored) | API token |
