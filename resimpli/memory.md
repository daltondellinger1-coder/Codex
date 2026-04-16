# reSimpli Memory

_No snapshot yet. Run the pull + summarize pipeline once to populate this file._

## How this works

This file is the living daily summary of your reSimpli pipeline. It gets
regenerated each time `resimpli/summarize.py` runs (after `pull.py` fetches
fresh data from the API).

Yesterday's snapshot is archived under `resimpli/snapshots/<date>.md` so
deltas can be computed without needing a database.

To update manually:

```
python resimpli/pull.py && python resimpli/summarize.py
```

Or, in Claude Code, run the `/resimpli-daily` slash command.
