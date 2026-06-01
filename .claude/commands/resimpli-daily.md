---
description: Pull fresh reSimpli data, regenerate memory.md, and surface what changed
---

Run the daily reSimpli routine:

1. **Check prerequisites.** Confirm `.env` exists at the repo root and
   `RESIMPLI_API_TOKEN` is set. If missing, stop and tell the user to add it.

2. **Pull fresh data.**
   ```
   python resimpli/pull.py
   ```
   If `pull.py` exits non-zero, read its output, diagnose, and either fix the
   endpoint list in `pull.py` or report the blocker to the user. Do not
   proceed to summarize on a hard failure.

3. **Regenerate the memory file.**
   ```
   python resimpli/summarize.py
   ```

4. **Compare against yesterday.** Read `resimpli/memory.md` and the most
   recent file in `resimpli/snapshots/`. In 3-6 bullets, tell the user:
   - **What's new**: leads that appeared since yesterday
   - **What's moving**: leads whose status progressed toward close
   - **What's stuck**: leads that went stale or bottlenecks that grew
   - **Top 3 to act on today**: specific leads, with the specific next action
     (call, send contract, follow-up, dispo). Pull names/addresses from
     `memory.md` — do not invent.

5. **Commit the update** to the branch with a message like
   `resimpli: daily snapshot YYYY-MM-DD`. Include `resimpli/memory.md` and any
   new file under `resimpli/snapshots/`. Do **not** add `resimpli/raw/` or
   `.env` (they're gitignored; verify with `git status` before committing).

6. **Push** to the current branch.

Keep the final user-facing summary tight — bullets, not paragraphs. The full
detail lives in `memory.md`; your job is to highlight what changed and what
deserves attention today.
