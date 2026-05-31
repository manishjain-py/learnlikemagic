# Super Pipeline — Regenerate All Stages for One Topic

Runs the **full post-sync topic pipeline — all 10 stages of the topic DAG** — for a single topic, identified by natural language like "math grade 4 ch 1 topic 1". Always runs with `force=true` — every stage is wiped and regenerated from scratch.

Everything hangs off `explanations`; the server runs stages in dependency order:

```
explanations
├─ baatcheet_dialogue ─┬─ baatcheet_visuals
│                      └─ baatcheet_audio_review → baatcheet_audio_synthesis
├─ visuals
├─ check_ins
├─ practice_bank
└─ audio_review → audio_synthesis
```

The DAG is the single source of truth (`book_ingestion_v2/dag/topic_pipeline_dag.py`); if stages are added there, this skill picks them up automatically (the script appends any unknown stage to the heartbeat).

## Two modes

- **Full pipeline (default):** all 10 stages, `force=true`. Use when the user wants the whole topic regenerated.
- **Single stage (`--stage`):** re-run ONE stage and **cascade to its descendants**. Use when the user names a specific stage — e.g. *"run baatcheet review for math g4 ch1 topic1"*. This goes through the guideline-keyed cascade API — the same engine as the admin DAG dashboard's per-node rerun. Rerunning a stage marks its downstream descendants stale and re-runs them too (`baatcheet_audio_review` → also `baatcheet_audio_synthesis`; `explanations` → effectively the whole tree). The stage's **upstream** deps must already be `done`, or the rerun is rejected (409). It does **not** touch upstream or unrelated branches.

This wraps the bundled script at `.claude/scripts/super_pipeline.py`, which:
1. Resolves subject+grade → `book_id` via `GET /admin/v2/books`
2. Resolves chapter number → `chapter_id` via `GET /admin/v2/books/{book_id}`
3. Resolves topic index → `topic_key` via `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics`
4. **Full pipeline:** POSTs `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline` with `{quality_level, force: true}`, then polls `/pipeline` every 20s.
5. **Single stage:** resolves `guideline_id` (from `/pipeline`), POSTs `/admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun` with `{quality_level, force: true}`, then polls `/admin/v2/topics/{guideline_id}/dag` every 20s (cascade-aware completion — see Notes). One event line per state change either way.

## Input parsing

Extract from the user's message:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `subject` | string | yes | e.g. `math`, `science`, `english`. Case-insensitive; aliases handled by the script. |
| `grade` | int 1-12 | yes | |
| `chapter` | int ≥ 1 | yes | 1-based position of the chapter in the book (by `chapter_number`). |
| `topic` | int ≥ 1 | yes | 1-based position of the topic within the chapter (by `sequence_order`). |
| `quality` | `fast` / `balanced` / `thorough` | no — default `balanced` | Controls review-refine rounds per stage. |
| `stage` | string | no | If the user names a specific stage, resolve it to a canonical id and run single-stage mode (`--stage`). Omit for the full pipeline. |

**Canonical stage ids** (pass to `--stage`): `explanations`, `baatcheet_dialogue`, `baatcheet_visuals`, `baatcheet_audio_review`, `baatcheet_audio_synthesis`, `visuals`, `check_ins`, `practice_bank`, `audio_review`, `audio_synthesis`.

Map the user's words to one id yourself. Common phrasings: "baatcheet review" → `baatcheet_audio_review`; "baatcheet audio" / "baatcheet voice" → `baatcheet_audio_synthesis`; "baatcheet dialogue" / "the conversation" → `baatcheet_dialogue`; "practice" → `practice_bank`; "check-ins" → `check_ins`; "narration" / "the audio" → `audio_synthesis`; "audio review" → `audio_review`; "animations" → `visuals`. If the phrasing could mean two stages, ask before running. (The script also normalizes spaces/hyphens and a few aliases, but resolve to a canonical id when you can.)

Examples:
- "Run super pipeline for math grade 2 ch 1 topic 3" → `subject=math grade=2 chapter=1 topic=3 quality=balanced` (full)
- "Rerun super pipeline for science grade 4 chapter 5 topic 2 thorough" → `quality=thorough` (full)
- "Run baatcheet review for math grade 4 ch 1 topic 1" → `subject=math grade=4 chapter=1 topic=1 stage=baatcheet_audio_review` (single stage + cascade)
- "Regenerate just the practice bank for science g3 ch2 t1" → `stage=practice_bank`

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

For single-stage mode, name the stage and the cascade, e.g.:
> Resolving `math grade 4 chapter 1 topic 1` and re-running `baatcheet_audio_review` (cascades to `baatcheet_audio_synthesis`) at `balanced` quality.

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
- **Single-stage mode:** append `--stage <STAGE_ID>` (a canonical id) to the command. Omit it for a full run. Everything else (resolution, polling, exit codes) is identical.
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
| `[HH:MM:SS] GUIDELINE id=…` | (single-stage) Resolved guideline `<id>`. |
| `[HH:MM:SS] KICKOFF quality=… force=true` | (full) Kicking off the full pipeline (quality=…, force=true). |
| `[HH:MM:SS] KICKOFF stage=… quality=… force=true` | (single-stage) Re-running `<stage>` (quality=…, force=true). |
| `[HH:MM:SS] RUNNING run_id=… stages=…` | (full) Pipeline run `<id>` started; stages queued: … |
| `[HH:MM:SS] RERUN cascade_id=… running=… pending=…` | (single-stage) Cascade started; running `<running>`, will also refresh: `<pending>`. |
| `[HH:MM:SS] STATE explanations=… baatcheet_dialogue=… baatcheet_visuals=… baatcheet_audio_review=… baatcheet_audio_synthesis=… visuals=… check_ins=… practice_bank=… audio_review=… audio_synthesis=…` | Render as a compact 10-stage progress block (one line per stage, in the order shown), e.g.:<br>`Progress:`<br>`  explanations               done`<br>`  baatcheet_dialogue         running`<br>`  baatcheet_visuals          ready`<br>`  baatcheet_audio_review     ready`<br>`  baatcheet_audio_synthesis  ready`<br>`  visuals                    done`<br>`  check_ins                  done`<br>`  practice_bank              done`<br>`  audio_review               done`<br>`  audio_synthesis            ready`<br>(If the script reports a stage not listed here, show it too — the DAG has grown.) |
| `[HH:MM:SS] ERROR stage=… msg=…` | Highlight failing stage; quote the message verbatim |
| `[HH:MM:SS] NOTHING_TO_RUN msg=…` | "All stages already done — nothing to do." |
| `[HH:MM:SS] DONE duration_sec=N` | Full: "All 10 stages completed in Ns." Single-stage: "`<stage>` + cascade completed in Ns." |
| `[HH:MM:SS] FAILED stages=… duration_sec=N` | "Failed at: … after Ns." (`cascade_halted_incomplete` = the cascade stopped before finishing; check the dashboard.) |
| `[HH:MM:SS] TIMEOUT …` | "Polling timed out after 1 hour; the pipeline may still be running server-side. I'll give you the IDs to resume polling." |

Keep each update short. The point is a readable heartbeat — not a log dump.

## Step 5 — Final summary when the monitor exits

When the script process exits (Monitor reports exit), send one final summary:

- **Exit 0 (success)**: topic identity (book/chapter/topic title), total duration, final stage states. Mention if any stage finished in `warning` state.
- **Exit 1 (failed)**: which stage(s) failed, the error message verbatim, and practical next steps (retry with `--quality thorough` for more review rounds, check logs, or inspect the admin dashboard for that topic). In single-stage mode only the named stage + its descendants ran; the rest of the topic is untouched.
- **Exit 2 (timeout)**: give the user the exact command to resume polling:
  ```
  python3 /Users/manishjain/repos/learnlikemagic/.claude/scripts/super_pipeline.py poll --book-id <ID> --chapter-id <ID> --topic-key <KEY>
  ```
  (That resumes the full-pipeline `/pipeline` view; for a single-stage cascade, point the user at the admin DAG dashboard for the topic instead.)
- **Exit 3** (resolution error): relay the listing the script printed (available chapters / topics / books). Also fires on an unknown `--stage` value — the script prints the valid stage ids.
- **Exit 4** (kickoff HTTP error): show the backend response verbatim. In single-stage mode this is usually a 409 — `upstream_not_done` (the stage's prerequisite isn't `done`; offer to run that upstream or the full pipeline first), `cascade_active` (a cascade is already running for this topic; wait or cancel it), or `stage_running` (that stage is mid-run).
- **Exit 5** (backend unreachable): tell the user to start the backend.

## Notes

- Always `force=true` — that's the whole point of invoking this skill.
- **Single-stage mode** reuses the admin DAG dashboard's cascade engine: rerunning a stage refreshes it **plus all downstream descendants** (upstream and unrelated branches are left alone). The script polls `/admin/v2/topics/{guideline_id}/dag` and finishes when the cascade clears with every cascade-set stage `done` — the server drops the cascade object on success *and* on halt, so the script reads per-stage state to tell them apart. Targeting `explanations` effectively rebuilds the whole topic, so prefer the default full mode for that.
- Subject matching is case-insensitive with aliases (`math`→`Mathematics`, `sst`→`Social Studies`, etc.).
- If multiple books share (subject, grade), the script prints the candidates as stderr log lines and exits with code 3 — ask the user to pick, then re-invoke with `--book-id <id>` in place of subject/grade (you'll need to hand-edit the Monitor command since the skill only takes subject+grade today).
- The pipeline runs asynchronously in the backend (daemon thread). The script just observes — if the user cancels this skill, the backend keeps running.
- For stalled stages: the backend has a heartbeat-based stale detector; check the admin topic pipeline dashboard if a stage sits in `running` longer than ~10 minutes.
