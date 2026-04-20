#!/usr/bin/env python3
"""Run the 6-stage topic post-sync pipeline (super pipeline) for one topic.

Resolves subject+grade -> book_id, chapter_number -> chapter_id, topic_number
-> topic_key via the localhost admin API, kicks off the pipeline with
force=true, then polls status until all stages are done or any fails.

Each event is printed as a single stdout line so callers can stream/parse
incrementally. Human-readable log lines go to stderr.

Exit codes:
    0 = all stages completed (possibly with warnings)
    1 = one or more stages failed
    2 = polling hit the max-runtime cap (pipeline may still be running server-side)
    3 = resolution error (book/chapter/topic not found, or ambiguous)
    4 = kickoff error (HTTP non-2xx from /run-pipeline)
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

STAGE_ORDER = [
    "explanations",
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
    p = argparse.ArgumentParser(description="Run the 6-stage topic post-sync pipeline.")
    sub = p.add_subparsers(dest="mode", required=True)

    run = sub.add_parser("run", help="Resolve, kick off, and poll until done.")
    run.add_argument("--subject", help="e.g. 'Math' (ignored if --book-id given)")
    run.add_argument("--grade", type=int, help="e.g. 4 (ignored if --book-id given)")
    run.add_argument("--book-id", help="Skip subject+grade lookup; use this book id directly.")
    run.add_argument("--chapter", type=int, required=True, help="1-based chapter number")
    run.add_argument("--topic", type=int, required=True, help="1-based topic index within chapter")
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
