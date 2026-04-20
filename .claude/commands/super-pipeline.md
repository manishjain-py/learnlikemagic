# Super Pipeline — Regenerate All 6 Stages for One Topic

Runs the 6-stage post-sync topic pipeline (explanations → visuals ∥ check-ins ∥ practice-bank → audio-review → audio-synthesis) for a single topic, identified by natural language like "math grade 4 ch 1 topic 1". Always runs with `force=true` — all 6 stages are wiped and regenerated from scratch.

This wraps the bundled script at `.claude/scripts/super_pipeline.py`, which:
1. Resolves subject+grade → `book_id` via `GET /admin/v2/books`
2. Resolves chapter number → `chapter_id` via `GET /admin/v2/books/{book_id}`
3. Resolves topic index → `topic_key` via `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics`
4. POSTs to `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline` with `{quality_level, force: true}`
5. Polls `/pipeline` every 20s and prints one event line per state change

## Input parsing

Extract from the user's message:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `subject` | string | yes | e.g. `math`, `science`, `english`. Case-insensitive; aliases handled by the script. |
| `grade` | int 1-12 | yes | |
| `chapter` | int ≥ 1 | yes | 1-based position of the chapter in the book (by `chapter_number`). |
| `topic` | int ≥ 1 | yes | 1-based position of the topic within the chapter (by `sequence_order`). |
| `quality` | `fast` / `balanced` / `thorough` | no — default `balanced` | Controls review-refine rounds per stage. |

Examples:
- "Run super pipeline for math grade 2 ch 1 topic 3" → `subject=math grade=2 chapter=1 topic=3 quality=balanced`
- "Rerun super pipeline for science grade 4 chapter 5 topic 2 thorough" → `quality=thorough`
- "Regenerate math grade 2 ch 3 topic 1 fast" → `quality=fast`

If any required field is missing or ambiguous, ask the user before proceeding. Do NOT guess.

## Step 1 — Backend health check

Before anything else, verify the backend is up:

```bash
curl -sf http://localhost:8000/admin/v2/books?limit=1 > /dev/null
```

If this fails, tell the user:
> Backend not running on localhost:8000. Start it with `cd llm-backend && source venv/bin/activate && make run`, then try again.

Do NOT proceed.

## Step 2 — Confirm plan to user

Tell the user what's about to run in one short sentence, e.g.:
> Resolving `math grade 2 chapter 1 topic 3` and kicking off the super pipeline at `balanced` quality with `force=true`.

## Step 3 — Run via Monitor (streams each event as a notification)

Invoke the `Monitor` tool (load via ToolSearch if deferred):

```
Monitor(
  description: "super pipeline: <subject> grade <N> ch <C> topic <T>",
  command: "python3 /Users/manishjain/repos/learnlikemagic/.claude/scripts/super_pipeline.py run --subject <SUBJECT> --grade <GRADE> --chapter <CHAPTER> --topic <TOPIC> --quality <QUALITY> 2>&1",
  timeout_ms: 3600000,
  persistent: false
)
```

Notes:
- `2>&1` merges stderr (resolution errors, retry warnings) into the event stream so they aren't silently swallowed.
- `timeout_ms: 3600000` matches the script's 1-hour self-cap.
- `persistent: false` — the monitor ends when the script exits, as expected.

## Step 4 — Relay events to the user as they arrive

Each stdout line from the script becomes a notification. Translate them for the user (one user-facing message per incoming notification; batch only if several arrive in the same burst):

| Script event line | User-facing message |
|---|---|
| `[HH:MM:SS] BOOK id=… title=…` | Resolved book: `<title>` (id `<id>`) |
| `[HH:MM:SS] CHAPTER id=… number=N title=…` | Chapter #N: `<title>` |
| `[HH:MM:SS] TOPIC key=… title=…` | Topic: `<title>` (key `<key>`) |
| `[HH:MM:SS] KICKOFF quality=… force=true` | Kicking off pipeline (quality=…, force=true). |
| `[HH:MM:SS] RUNNING run_id=… stages=…` | Pipeline run `<id>` started; stages queued: … |
| `[HH:MM:SS] STATE explanations=X visuals=Y check_ins=Z practice_bank=W audio_review=V audio_synthesis=U` | Render as a compact 6-stage progress block:<br>`Progress:`<br>`  explanations     X`<br>`  visuals          Y`<br>`  check_ins        Z`<br>`  practice_bank    W`<br>`  audio_review     V`<br>`  audio_synthesis  U` |
| `[HH:MM:SS] ERROR stage=… msg=…` | Highlight failing stage; quote the message verbatim |
| `[HH:MM:SS] NOTHING_TO_RUN msg=…` | "All stages already done — nothing to do." |
| `[HH:MM:SS] DONE duration_sec=N` | "All 6 stages completed in Ns." |
| `[HH:MM:SS] FAILED stages=… duration_sec=N` | "Pipeline failed at: … after Ns." |
| `[HH:MM:SS] TIMEOUT …` | "Polling timed out after 1 hour; the pipeline may still be running server-side. I'll give you the IDs to resume polling." |

Keep each update short. The point is a readable heartbeat — not a log dump.

## Step 5 — Final summary when the monitor exits

When the script process exits (Monitor reports exit), send one final summary:

- **Exit 0 (success)**: topic identity (book/chapter/topic title), total duration, final stage states. Mention if any stage finished in `warning` state.
- **Exit 1 (failed)**: which stage(s) failed, the error message verbatim, and practical next steps (retry with `--quality thorough` for more review rounds, check logs, or inspect the admin dashboard for that topic).
- **Exit 2 (timeout)**: give the user the exact command to resume polling:
  ```
  python3 /Users/manishjain/repos/learnlikemagic/.claude/scripts/super_pipeline.py poll --book-id <ID> --chapter-id <ID> --topic-key <KEY>
  ```
- **Exit 3** (resolution error): relay the listing the script printed (available chapters / topics / books).
- **Exit 4** (kickoff HTTP error): show the backend response verbatim.
- **Exit 5** (backend unreachable): tell the user to start the backend.

## Notes

- Always `force=true` — that's the whole point of invoking this skill.
- Subject matching is case-insensitive with aliases (`math`→`Mathematics`, `sst`→`Social Studies`, etc.).
- If multiple books share (subject, grade), the script prints the candidates as stderr log lines and exits with code 3 — ask the user to pick, then re-invoke with `--book-id <id>` in place of subject/grade (you'll need to hand-edit the Monitor command since the skill only takes subject+grade today).
- The pipeline runs asynchronously in the backend (daemon thread). The script just observes — if the user cancels this skill, the backend keeps running.
- For stalled stages: the backend has a heartbeat-based stale detector; check the admin topic pipeline dashboard if a stage sits in `running` longer than ~10 minutes.
