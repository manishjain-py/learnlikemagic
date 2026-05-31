#!/usr/bin/env python3
"""Run the full topic post-sync pipeline (super pipeline) for one topic.

This is the complete topic DAG — all 10 stages: explanations; baatcheet
dialogue, visuals, audio-review, audio-synthesis; visuals; check-ins;
practice bank; and audio-review, audio-synthesis. The server runs them in
dependency order (everything hangs off explanations); this script resolves
IDs, kicks off with force=true, and streams status.

Resolves subject+grade -> book_id, chapter_number -> chapter_id, topic_number
-> topic_key via the localhost admin API, kicks off the pipeline with
force=true, then polls status until all stages are done or any fails.

`run --stage <stage_id>` instead re-runs a SINGLE DAG stage and cascades to
its descendants (via the guideline-keyed cascade API) — e.g. refresh
`baatcheet_audio_review` (which also re-runs `baatcheet_audio_synthesis`)
without rebuilding the other stages. The stage's upstream deps must already
be `done`, or the rerun is rejected.

Each event is printed as a single stdout line so callers can stream/parse
incrementally. Human-readable log lines go to stderr.

Exit codes:
    0 = all stages completed (possibly with warnings)
    1 = one or more stages failed
    2 = polling hit the max-runtime cap (pipeline may still be running server-side)
    3 = resolution error (book/chapter/topic/stage not found, or ambiguous)
    4 = kickoff error (HTTP non-2xx from /run-pipeline or the stage-rerun endpoint)
    5 = backend unreachable
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "http://localhost:8000"
POLL_INTERVAL_SEC = 20
MAX_RUNTIME_SEC = 60 * 60  # 1 hour cap

# Display order for the STATE heartbeat — matches the canonical DAG declaration
# order in book_ingestion_v2/dag/topic_pipeline_dag.py (explanations is the root;
# every other stage depends on it directly or transitively).
STAGE_ORDER = [
    "explanations",
    "baatcheet_dialogue",
    "baatcheet_visuals",
    "baatcheet_audio_review",
    "baatcheet_audio_synthesis",
    "visuals",
    "check_ins",
    "practice_bank",
    "audio_review",
    "audio_synthesis",
]

SUBJECT_ALIASES = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "science": "Science",
    "english": "English",
    "hindi": "Hindi",
    "evs": "EVS",
    "social": "Social Studies",
    "socialstudies": "Social Studies",
    "sst": "Social Studies",
    "socialscience": "Social Science",
}


def emit(line: str) -> None:
    """Print one event line to stdout (for callers to stream)."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {line}", flush=True)


def log(line: str) -> None:
    """Print a log line to stderr (for humans debugging)."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {line}", file=sys.stderr, flush=True)


def http_get(path: str, timeout: int = 30) -> dict:
    url = f"{BASE}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def http_post(path: str, body: dict, timeout: int = 30) -> dict:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


STAGE_INPUT_ALIASES = {
    # Free-form phrasings that don't normalize cleanly to a canonical id.
    # ("baatcheet review" has no "audio" token, so spell the mapping out.)
    "baatcheet_review": "baatcheet_audio_review",
    "baatcheet_synthesis": "baatcheet_audio_synthesis",
}


def normalize_stage(raw: str) -> str | None:
    """Map a free-form stage name to a canonical DAG stage_id, or None.

    Accepts spaces/hyphens ("Baatcheet Audio Review", "audio-synthesis")
    plus a few aliases; validates against STAGE_ORDER (the DAG stages).
    """
    n = raw.strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in n:
        n = n.replace("__", "_")
    n = STAGE_INPUT_ALIASES.get(n, n)
    return n if n in STAGE_ORDER else None


def _norm(s: str) -> str:
    return s.strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _subject_matches(user_input: str, db_subject: str) -> bool:
    u, d = _norm(user_input), _norm(db_subject)
    if u == d:
        return True
    alias = SUBJECT_ALIASES.get(u)
    if alias and _norm(alias) == d:
        return True
    return u in d or d in u


def check_backend() -> None:
    try:
        http_get("/admin/v2/books?limit=1", timeout=5)
    except Exception as e:
        log(f"Backend unreachable at {BASE}: {e}")
        log(f"Start it with: cd llm-backend && source venv/bin/activate && make run")
        sys.exit(5)


def resolve_book(subject: str, grade: int) -> dict:
    resp = http_get("/admin/v2/books?limit=500")
    books = resp.get("books", [])
    matches = [
        b for b in books
        if b.get("grade") == grade and _subject_matches(subject, b.get("subject", ""))
    ]
    if not matches:
        pairs = sorted({(b.get("subject"), b.get("grade")) for b in books})
        listing = ", ".join(f"{s} grade {g}" for s, g in pairs) or "(no books)"
        log(f"No book matches subject={subject!r} grade={grade}.")
        log(f"Available: {listing}")
        sys.exit(3)
    if len(matches) > 1:
        log(f"Multiple books match subject={subject!r} grade={grade}:")
        for b in matches:
            log(
                f"  - id={b['id']} title={b.get('title')!r} "
                f"author={b.get('author')!r} edition_year={b.get('edition_year')}"
            )
        log("Re-run with --book-id <id> to disambiguate.")
        sys.exit(3)
    return matches[0]


def resolve_book_by_id(book_id: str) -> dict:
    try:
        return http_get(f"/admin/v2/books/{urllib.parse.quote(book_id)}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log(f"Book not found: {book_id}")
            sys.exit(3)
        raise


def resolve_chapter(book_id: str, chapter_num: int) -> dict:
    detail = http_get(f"/admin/v2/books/{urllib.parse.quote(book_id)}")
    chapters = sorted(
        detail.get("chapters", []), key=lambda c: c.get("chapter_number", 0)
    )
    match = next(
        (c for c in chapters if c.get("chapter_number") == chapter_num), None
    )
    if not match:
        listing = ", ".join(
            f"#{c.get('chapter_number')} {c.get('chapter_title')!r}"
            for c in chapters
        ) or "(no chapters)"
        log(f"No chapter #{chapter_num} in book {book_id}.")
        log(f"Available chapters: {listing}")
        sys.exit(3)
    return match


def resolve_topic(book_id: str, chapter_id: str, topic_num: int) -> dict:
    resp = http_get(
        f"/admin/v2/books/{urllib.parse.quote(book_id)}"
        f"/chapters/{urllib.parse.quote(chapter_id)}/topics"
    )
    topics = sorted(
        resp.get("topics", []),
        key=lambda t: (t.get("sequence_order") or 0, t.get("topic_key") or ""),
    )
    if not topics:
        log(f"Chapter {chapter_id} has no topics.")
        sys.exit(3)
    if topic_num < 1 or topic_num > len(topics):
        listing = ", ".join(
            f"#{i+1} {t.get('topic_title')!r} (key={t.get('topic_key')})"
            for i, t in enumerate(topics)
        )
        log(f"Topic #{topic_num} out of range. Chapter has {len(topics)} topics.")
        log(f"Available topics: {listing}")
        sys.exit(3)
    return topics[topic_num - 1]


def kickoff(book_id: str, chapter_id: str, topic_key: str, quality: str) -> dict:
    path = (
        f"/admin/v2/books/{urllib.parse.quote(book_id)}"
        f"/chapters/{urllib.parse.quote(chapter_id)}"
        f"/topics/{urllib.parse.quote(topic_key)}/run-pipeline"
    )
    try:
        return http_post(path, {"quality_level": quality, "force": True})
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        log(f"Kickoff failed: HTTP {e.code} — {body}")
        sys.exit(4)


def fetch_status(book_id: str, chapter_id: str, topic_key: str) -> dict:
    path = (
        f"/admin/v2/books/{urllib.parse.quote(book_id)}"
        f"/chapters/{urllib.parse.quote(chapter_id)}"
        f"/topics/{urllib.parse.quote(topic_key)}/pipeline"
    )
    return http_get(path, timeout=15)


def format_state_line(stages: list[dict]) -> str:
    by_id = {s["stage_id"]: s for s in stages}
    parts = []
    for sid in STAGE_ORDER:
        s = by_id.get(sid)
        if not s:
            parts.append(f"{sid}=?")
        else:
            parts.append(f"{sid}={s['state']}")
    # Surface any server-reported stage not in STAGE_ORDER, so a newly added
    # DAG stage is never silently hidden from the heartbeat.
    for sid, s in by_id.items():
        if sid not in STAGE_ORDER:
            parts.append(f"{sid}={s['state']}")
    return "STATE " + " ".join(parts)


def poll_loop(book_id: str, chapter_id: str, topic_key: str) -> int:
    start = time.time()
    last_states: dict[str, str] = {}
    first = True
    while True:
        if time.time() - start > MAX_RUNTIME_SEC:
            emit(f"TIMEOUT after {int(time.time() - start)}s — pipeline may still be running server-side")
            return 2
        try:
            status = fetch_status(book_id, chapter_id, topic_key)
        except urllib.error.HTTPError as e:
            log(f"Status fetch failed: HTTP {e.code}; retrying in {POLL_INTERVAL_SEC}s")
            time.sleep(POLL_INTERVAL_SEC)
            continue
        except Exception as e:
            log(f"Status fetch error: {e}; retrying in {POLL_INTERVAL_SEC}s")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        stages = status.get("stages", [])
        cur = {s["stage_id"]: s["state"] for s in stages}
        if first or cur != last_states:
            emit(format_state_line(stages))
            # If a stage has a new error, surface it too
            for s in stages:
                prev_state = last_states.get(s["stage_id"])
                err = s.get("last_job_error")
                if s["state"] == "failed" and err and prev_state != "failed":
                    emit(f"ERROR stage={s['stage_id']} msg={err!r}")
            last_states = cur
            first = False

        states = list(cur.values())
        if all(st in ("done", "warning") for st in states):
            elapsed = int(time.time() - start)
            emit(f"DONE duration_sec={elapsed}")
            return 0
        if any(st == "failed" for st in states):
            failed = [sid for sid, st in cur.items() if st == "failed"]
            elapsed = int(time.time() - start)
            emit(f"FAILED stages={','.join(failed)} duration_sec={elapsed}")
            return 1
        time.sleep(POLL_INTERVAL_SEC)


def resolve_guideline_id(book_id: str, chapter_id: str, topic_key: str) -> str:
    """Look up the topic's guideline_id (the key the cascade API uses)."""
    status = fetch_status(book_id, chapter_id, topic_key)
    gid = status.get("guideline_id")
    if not gid:
        log(f"Could not resolve guideline_id for topic {topic_key!r}.")
        sys.exit(3)
    return gid


def kickoff_stage(guideline_id: str, stage_id: str, quality: str) -> dict:
    """POST the single-stage cascade rerun (force=true)."""
    path = (
        f"/admin/v2/topics/{urllib.parse.quote(guideline_id)}"
        f"/stages/{urllib.parse.quote(stage_id)}/rerun"
    )
    try:
        return http_post(path, {"quality_level": quality, "force": True})
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # 409 = cascade already active / upstream not done / stage running;
        # 400 = unknown stage; 404 = guideline missing.
        log(f"Stage rerun failed: HTTP {e.code} — {body}")
        sys.exit(4)


def fetch_dag(guideline_id: str) -> dict:
    path = f"/admin/v2/topics/{urllib.parse.quote(guideline_id)}/dag"
    return http_get(path, timeout=15)


def _stage_errors(
    book_id: str, chapter_id: str, topic_key: str, failed_ids: set[str]
) -> dict:
    """Best-effort error text for failed stages — DAG rows carry none, so
    read /pipeline, which surfaces last_job_error."""
    try:
        status = fetch_status(book_id, chapter_id, topic_key)
    except Exception:
        return {}
    return {
        s["stage_id"]: s["last_job_error"]
        for s in status.get("stages", [])
        if s["stage_id"] in failed_ids and s.get("last_job_error")
    }


def poll_cascade(
    guideline_id: str,
    cascade_set: set[str],
    book_id: str,
    chapter_id: str,
    topic_key: str,
) -> int:
    """Poll the DAG endpoint until the rerun cascade settles.

    The server drops the cascade object the moment it ends (success OR
    halt), so completion is judged from per-stage state: every cascade-set
    stage done/warning and not stale -> success; any cascade-set stage
    failed -> failure. The live `cascade` field drives the heartbeat and
    surfaces non-stage halt reasons (lock collision, etc.) while it lasts.
    """
    start = time.time()
    last_states: dict[str, str] = {}
    first = True
    active_seen = False
    while True:
        if time.time() - start > MAX_RUNTIME_SEC:
            emit(f"TIMEOUT after {int(time.time() - start)}s — cascade may still be running server-side")
            return 2
        try:
            dag = fetch_dag(guideline_id)
        except urllib.error.HTTPError as e:
            log(f"DAG fetch failed: HTTP {e.code}; retrying in {POLL_INTERVAL_SEC}s")
            time.sleep(POLL_INTERVAL_SEC)
            continue
        except Exception as e:
            log(f"DAG fetch error: {e}; retrying in {POLL_INTERVAL_SEC}s")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        stages = dag.get("stages", [])
        cascade = dag.get("cascade")
        cur = {s["stage_id"]: s["state"] for s in stages}
        stale = {s["stage_id"]: bool(s.get("is_stale")) for s in stages}
        if first or cur != last_states:
            emit(format_state_line(stages))
            last_states = cur
            first = False

        # Failure — any cascade-set stage ended `failed`.
        failed = sorted(sid for sid in cascade_set if cur.get(sid) == "failed")
        if failed:
            errs = _stage_errors(book_id, chapter_id, topic_key, set(failed))
            for sid in failed:
                if sid in errs:
                    emit(f"ERROR stage={sid} msg={errs[sid]!r}")
            emit(f"FAILED stages={','.join(failed)} duration_sec={int(time.time() - start)}")
            return 1

        if cascade is not None:
            active_seen = True
            # Non-stage halt: lock_collision / internal_error / no_ready_stages.
            halt = cascade.get("halted_at")
            if halt and halt not in cascade_set:
                emit(f"FAILED stages={halt} duration_sec={int(time.time() - start)}")
                return 1
        else:
            done = all(cur.get(sid) in ("done", "warning") for sid in cascade_set)
            none_stale = not any(stale.get(sid) for sid in cascade_set)
            if done and none_stale:
                emit(f"DONE duration_sec={int(time.time() - start)}")
                return 0
            if active_seen:
                # Cascade vanished without every stage settling — a halt we
                # didn't catch live. Report instead of hanging to the cap.
                emit(f"FAILED stages=cascade_halted_incomplete duration_sec={int(time.time() - start)}")
                return 1
            # else: pre-registration window — keep polling.

        time.sleep(POLL_INTERVAL_SEC)


def cmd_run(args: argparse.Namespace) -> int:
    check_backend()

    if args.book_id:
        book = resolve_book_by_id(args.book_id)
    else:
        book = resolve_book(args.subject, args.grade)
    emit(
        f"BOOK id={book['id']} title={book.get('title')!r} "
        f"subject={book.get('subject')} grade={book.get('grade')}"
    )

    chapter = resolve_chapter(book["id"], args.chapter)
    emit(
        f"CHAPTER id={chapter['id']} number={chapter['chapter_number']} "
        f"title={chapter.get('chapter_title')!r}"
    )

    topic = resolve_topic(book["id"], chapter["id"], args.topic)
    emit(
        f"TOPIC key={topic['topic_key']} title={topic.get('topic_title')!r} "
        f"sequence_order={topic.get('sequence_order')}"
    )

    # Single-stage cascade rerun (--stage): re-run one DAG stage and let the
    # cascade engine refresh its downstream descendants. Goes through the
    # guideline-keyed cascade API, not the full-pipeline orchestrator.
    if getattr(args, "stage", None):
        stage_id = normalize_stage(args.stage)
        if stage_id is None:
            log(f"Unknown stage {args.stage!r}. Valid stages: {', '.join(STAGE_ORDER)}")
            sys.exit(3)
        guideline_id = resolve_guideline_id(book["id"], chapter["id"], topic["topic_key"])
        emit(f"GUIDELINE id={guideline_id}")
        emit(f"KICKOFF stage={stage_id} quality={args.quality} force=true")
        resp = kickoff_stage(guideline_id, stage_id, args.quality)
        running = resp.get("running")
        pending = resp.get("pending", [])
        if not running and not pending:
            emit(f"NOTHING_TO_RUN msg={resp.get('message', 'nothing to run')!r}")
            return 0
        cascade_set = set(pending) | ({running} if running else set()) or {stage_id}
        emit(
            f"RERUN cascade_id={resp.get('cascade_id')} running={running} "
            f"pending={','.join(sorted(pending))}"
        )
        return poll_cascade(
            guideline_id, cascade_set, book["id"], chapter["id"], topic["topic_key"]
        )

    emit(f"KICKOFF quality={args.quality} force=true")
    resp = kickoff(book["id"], chapter["id"], topic["topic_key"], args.quality)
    run_id = resp.get("pipeline_run_id")
    stages_to_run = resp.get("stages_to_run", [])
    if not stages_to_run:
        emit(f"NOTHING_TO_RUN msg={resp.get('message', 'all stages already done')!r}")
        return 0
    emit(f"RUNNING run_id={run_id} stages={','.join(stages_to_run)}")

    return poll_loop(book["id"], chapter["id"], topic["topic_key"])


def cmd_poll_only(args: argparse.Namespace) -> int:
    check_backend()
    emit(f"POLL_ONLY book={args.book_id} chapter={args.chapter_id} topic={args.topic_key}")
    return poll_loop(args.book_id, args.chapter_id, args.topic_key)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the full topic post-sync pipeline (all 10 DAG stages).")
    sub = p.add_subparsers(dest="mode", required=True)

    run = sub.add_parser("run", help="Resolve, kick off, and poll until done.")
    run.add_argument("--subject", help="e.g. 'Math' (ignored if --book-id given)")
    run.add_argument("--grade", type=int, help="e.g. 4 (ignored if --book-id given)")
    run.add_argument("--book-id", help="Skip subject+grade lookup; use this book id directly.")
    run.add_argument("--chapter", type=int, required=True, help="1-based chapter number")
    run.add_argument("--topic", type=int, required=True, help="1-based topic index within chapter")
    run.add_argument(
        "--stage",
        help=(
            "Re-run ONLY this DAG stage and cascade to its descendants "
            "(e.g. baatcheet_audio_review). Omit to run the full pipeline."
        ),
    )
    run.add_argument(
        "--quality",
        choices=["fast", "balanced", "thorough"],
        default="balanced",
    )
    run.set_defaults(func=cmd_run)

    poll = sub.add_parser("poll", help="Poll status for known IDs without kicking off.")
    poll.add_argument("--book-id", required=True)
    poll.add_argument("--chapter-id", required=True)
    poll.add_argument("--topic-key", required=True)
    poll.set_defaults(func=cmd_poll_only)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "run" and not args.book_id and not (args.subject and args.grade is not None):
        parser.error("Either --book-id OR (--subject AND --grade) is required for `run`.")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
