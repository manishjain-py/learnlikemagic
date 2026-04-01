#!/usr/bin/env python3
"""
A/B Comparison: Explanation Generation Prompt

Compares old (committed) vs new (modified) explanation_generation.txt
across multiple topics with multiple iterations, then generates an
HTML comparison report.

Usage:
    cd llm-backend
    ./venv/bin/python -m autoresearch.explanation_quality.compare_prompts
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────

TOPICS = [
    "5d308551-cdbd-40d4-8001-c82902b47ca4",  # Understanding Place Value
    "a477516c-6b80-406b-9b39-279d3e755998",  # Comparing and Ordering Numbers
    "08ffca67-f71d-40b4-b60d-658bc688f74d",  # 3-Digit Addition: Regrouping
    "39113564-0314-429d-9d41-b1a615694f35",  # Ordinals and Number Properties
    "717497ed-62fd-4f18-8127-a41cbb1261b9",  # Building and Patterns in Numbers
]

ITERATIONS = 2
VARIANT_CONFIG = {"key": "A", "label": "Single", "approach": "analogy-driven with real-world examples"}
DIMENSIONS = ["simplicity", "concept_clarity", "examples_and_analogies", "structure_and_flow", "overall_effectiveness"]

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPORT_DIR = Path(__file__).parent / "evaluation" / "runs"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_old_prompt() -> str:
    # Path must be relative to repo root for git show
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    ).stdout.strip()
    rel_path = str(PROJECT_ROOT / "book_ingestion_v2/prompts/explanation_generation.txt").replace(repo_root + "/", "")
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        print(f"ERROR: Could not read old prompt from git: {result.stderr}")
        sys.exit(1)
    return result.stdout


def get_new_prompt() -> str:
    return (PROJECT_ROOT / "book_ingestion_v2/prompts/explanation_generation.txt").read_text()


def get_prompt_diff() -> str:
    result = subprocess.run(
        ["git", "diff", "--", "book_ingestion_v2/prompts/explanation_generation.txt"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    return result.stdout.strip() or "(no diff)"


def load_guideline(topic_id: str) -> dict:
    from database import get_db_manager
    from shared.models.entities import TeachingGuideline

    db = get_db_manager().session_factory()
    try:
        g = db.query(TeachingGuideline).filter(TeachingGuideline.id == topic_id).first()
        if not g:
            print(f"ERROR: Topic {topic_id} not found")
            sys.exit(1)
        return {
            "id": g.id,
            "topic_title": g.topic_title or g.topic,
            "subject": g.subject,
            "grade": g.grade,
            "guideline": g.guideline or g.description or "",
            "prior_topics_context": g.prior_topics_context,
        }
    finally:
        db.close()


def run_single(topic_id: str, guideline: dict, review_rounds: int = 0) -> dict:
    """Generate + evaluate explanation cards with optional review-refine rounds.

    Args:
        review_rounds: 0 = generate only, N = generate + N review-refine passes.
    """
    import book_ingestion_v2.services.explanation_generator_service as gen_svc
    from autoresearch.explanation_quality.evaluation.config import ExplanationEvalConfig
    from autoresearch.explanation_quality.evaluation.evaluator import ExplanationEvaluator
    from database import get_db_manager
    from shared.models.entities import TeachingGuideline as TG

    db = get_db_manager().session_factory()
    try:
        config = ExplanationEvalConfig.from_db(
            db, topic_id=topic_id,
            topic_title=guideline["topic_title"],
            grade=guideline["grade"],
            subject=guideline["subject"],
        )
        # Direct API for batch reliability (both groups use same model)
        config.generator_provider = "openai"
        config.generator_model = "gpt-4o"
        config.evaluator_provider = "openai"
        config.evaluator_model = "gpt-4o"
    finally:
        db.close()

    # Generate cards (with or without review-refine rounds)
    db = get_db_manager().session_factory()
    try:
        guideline_obj = db.query(TG).filter(TG.id == topic_id).first()
        llm = config.create_llm_service("generator")
        service = gen_svc.ExplanationGeneratorService(db, llm)

        cards_list, _summary = service._generate_variant(
            guideline_obj, VARIANT_CONFIG, review_rounds=review_rounds,
        )

        if cards_list is None:
            return _crash_result("Generation returned None")

        cards = [c.model_dump() for c in cards_list]
    except Exception as e:
        return _crash_result(str(e))
    finally:
        db.close()

    # Evaluate
    evaluator = ExplanationEvaluator(config)
    try:
        evaluation = evaluator.evaluate(
            cards=cards,
            topic_title=guideline["topic_title"],
            grade=guideline["grade"],
            subject=guideline["subject"],
            guideline_text=guideline["guideline"],
        )
    except Exception as e:
        return _crash_result(f"Evaluation failed: {e}")

    scores = evaluation.get("scores", {})
    avg = sum(scores.values()) / len(scores) if scores else 0

    return {
        "status": "ok",
        "scores": scores,
        "avg_score": avg,
        "card_count": len(cards),
        "problems": evaluation.get("problems", [])[:5],
        "summary": evaluation.get("summary", ""),
        "dimension_analysis": evaluation.get("dimension_analysis", {}),
    }


def _crash_result(error: str) -> dict:
    return {
        "status": "crash", "scores": {}, "avg_score": 0,
        "card_count": 0, "problems": [], "summary": "", "error": error,
        "dimension_analysis": {},
    }


def avg_scores(results: list[dict]) -> dict:
    """Average scores across multiple OK results."""
    ok = [r for r in results if r["status"] == "ok"]
    if not ok:
        return {"avg_score": 0, "scores": {d: 0 for d in DIMENSIONS}}
    scores = {}
    for dim in DIMENSIONS:
        vals = [r["scores"].get(dim, 0) for r in ok]
        scores[dim] = sum(vals) / len(vals) if vals else 0
    avg = sum(scores.values()) / len(scores)
    return {"avg_score": avg, "scores": scores}


# ── HTML Report ───────────────────────────────────────────────────────────────

def delta_color(val: float) -> str:
    if val > 0.05:
        return "#22c55e"
    if val < -0.05:
        return "#ef4444"
    return "#9ca3af"


def fmt_delta(val: float) -> str:
    sign = "+" if val > 0 else ""
    color = delta_color(val)
    return f'<span style="color:{color};font-weight:bold">{sign}{val:.2f}</span>'


def generate_html_report(all_results: dict, prompt_diff: str, elapsed_min: float) -> Path:
    """Build consolidated HTML comparison report."""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    # Aggregate across all topics
    all_before = []
    all_after = []
    for tid, data in all_results.items():
        all_before.extend(data["before"])
        all_after.extend(data["after"])

    agg_before = avg_scores(all_before)
    agg_after = avg_scores(all_after)
    overall_delta = agg_after["avg_score"] - agg_before["avg_score"]

    # Build per-topic rows
    topic_rows = ""
    for tid, data in all_results.items():
        title = data["guideline"]["topic_title"]
        b = avg_scores(data["before"])
        a = avg_scores(data["after"])
        d = a["avg_score"] - b["avg_score"]
        topic_rows += f"""
        <tr>
            <td style="text-align:left">{title}</td>
            <td>{b['avg_score']:.2f}</td>
            <td>{a['avg_score']:.2f}</td>
            <td>{fmt_delta(d)}</td>
        </tr>"""

    # Per-dimension aggregate rows
    dim_rows = ""
    for dim in DIMENSIONS:
        b_val = agg_before["scores"].get(dim, 0)
        a_val = agg_after["scores"].get(dim, 0)
        d = a_val - b_val
        label = dim.replace("_", " ").title()
        dim_rows += f"""
        <tr>
            <td style="text-align:left">{label}</td>
            <td>{b_val:.2f}</td>
            <td>{a_val:.2f}</td>
            <td>{fmt_delta(d)}</td>
        </tr>"""

    # Per-topic detail sections
    detail_sections = ""
    for tid, data in all_results.items():
        title = data["guideline"]["topic_title"]
        b_avg = avg_scores(data["before"])
        a_avg = avg_scores(data["after"])
        d = a_avg["avg_score"] - b_avg["avg_score"]

        # Iteration rows
        iter_rows = ""
        for i, (br, ar) in enumerate(zip(data["before"], data["after"]), 1):
            b_s = br["avg_score"] if br["status"] == "ok" else "CRASH"
            a_s = ar["avg_score"] if ar["status"] == "ok" else "CRASH"
            if br["status"] == "ok" and ar["status"] == "ok":
                it_d = ar["avg_score"] - br["avg_score"]
                iter_rows += f"<tr><td>Iter {i}</td><td>{b_s:.2f} ({br['card_count']} cards)</td><td>{a_s:.2f} ({ar['card_count']} cards)</td><td>{fmt_delta(it_d)}</td></tr>"
            else:
                iter_rows += f"<tr><td>Iter {i}</td><td>{b_s}</td><td>{a_s}</td><td>—</td></tr>"

        # Dimension breakdown
        dim_detail = ""
        for dim in DIMENSIONS:
            b_v = b_avg["scores"].get(dim, 0)
            a_v = a_avg["scores"].get(dim, 0)
            dd = a_v - b_v
            dim_detail += f"<tr><td style='text-align:left'>{dim.replace('_',' ').title()}</td><td>{b_v:.1f}</td><td>{a_v:.1f}</td><td>{fmt_delta(dd)}</td></tr>"

        # Problems summary (from last iteration of each)
        before_problems = ""
        after_problems = ""
        for r in data["before"]:
            if r["status"] == "ok" and r["problems"]:
                for p in r["problems"][:3]:
                    sev = p.get("severity", "?")
                    sev_color = {"critical": "#ef4444", "major": "#f59e0b", "minor": "#6b7280"}.get(sev, "#6b7280")
                    before_problems += f'<li><span style="color:{sev_color};font-weight:bold">[{sev.upper()}]</span> {p.get("title", "")} — {p.get("description", "")[:100]}</li>'
                break
        for r in data["after"]:
            if r["status"] == "ok" and r["problems"]:
                for p in r["problems"][:3]:
                    sev = p.get("severity", "?")
                    sev_color = {"critical": "#ef4444", "major": "#f59e0b", "minor": "#6b7280"}.get(sev, "#6b7280")
                    after_problems += f'<li><span style="color:{sev_color};font-weight:bold">[{sev.upper()}]</span> {p.get("title", "")} — {p.get("description", "")[:100]}</li>'
                break

        detail_sections += f"""
        <div style="margin:24px 0;padding:16px;border:1px solid #e5e7eb;border-radius:8px">
            <h3 style="margin:0 0 12px 0">{title} <span style="font-size:14px;font-weight:normal">({fmt_delta(d)})</span></h3>
            <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:12px">
                <thead><tr style="background:#f9fafb"><th>Iteration</th><th>Before</th><th>After</th><th>Delta</th></tr></thead>
                <tbody>{iter_rows}</tbody>
            </table>
            <details style="margin-bottom:8px">
                <summary style="cursor:pointer;font-weight:600;font-size:14px">Dimension Breakdown</summary>
                <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px">
                    <thead><tr style="background:#f9fafb"><th style="text-align:left">Dimension</th><th>Before</th><th>After</th><th>Delta</th></tr></thead>
                    <tbody>{dim_detail}</tbody>
                </table>
            </details>
            <details>
                <summary style="cursor:pointer;font-weight:600;font-size:14px">Key Problems</summary>
                <div style="display:flex;gap:24px;font-size:13px;margin-top:8px">
                    <div style="flex:1"><strong>Before:</strong><ul style="margin:4px 0">{before_problems or '<li>None</li>'}</ul></div>
                    <div style="flex:1"><strong>After:</strong><ul style="margin:4px 0">{after_problems or '<li>None</li>'}</ul></div>
                </div>
            </details>
        </div>"""

    # Escape diff for HTML
    import html as html_mod
    diff_escaped = html_mod.escape(prompt_diff)

    # Status badge
    if overall_delta > 0.1:
        badge = '<span style="background:#22c55e;color:white;padding:4px 12px;border-radius:4px;font-weight:bold">IMPROVED</span>'
    elif overall_delta < -0.1:
        badge = '<span style="background:#ef4444;color:white;padding:4px 12px;border-radius:4px;font-weight:bold">REGRESSED</span>'
    else:
        badge = '<span style="background:#9ca3af;color:white;padding:4px 12px;border-radius:4px;font-weight:bold">NEUTRAL</span>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Explanation Prompt A/B Comparison</title>
<style>
    body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1f2937; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 18px; margin-top: 32px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 12px; border-bottom: 1px solid #e5e7eb; text-align: center; }}
    th {{ background: #f9fafb; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
    pre {{ background: #f9fafb; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 12px; line-height: 1.5; }}
    .hero {{ display: flex; align-items: center; gap: 16px; margin: 24px 0; }}
    .hero-score {{ font-size: 48px; font-weight: bold; }}
    .hero-label {{ font-size: 14px; color: #6b7280; }}
</style></head><body>

<h1>Review-Refine A/B Comparison {badge}</h1>
<p style="color:#6b7280;font-size:14px">
    {now.strftime("%B %d, %Y %H:%M")} &middot;
    {len(TOPICS)} topics &middot;
    {ITERATIONS} iterations each &middot;
    {elapsed_min:.1f} min total
</p>

<div class="hero">
    <div>
        <div class="hero-label">Before (avg)</div>
        <div class="hero-score">{agg_before['avg_score']:.2f}</div>
    </div>
    <div style="font-size:36px;color:#9ca3af">&rarr;</div>
    <div>
        <div class="hero-label">After (avg)</div>
        <div class="hero-score" style="color:{delta_color(overall_delta)}">{agg_after['avg_score']:.2f}</div>
    </div>
    <div style="font-size:28px;margin-left:8px">{fmt_delta(overall_delta)}</div>
</div>

<h2>Per-Topic Summary</h2>
<table>
    <thead><tr><th style="text-align:left">Topic</th><th>Before</th><th>After</th><th>Delta</th></tr></thead>
    <tbody>{topic_rows}</tbody>
    <tfoot>
        <tr style="font-weight:bold;border-top:2px solid #1f2937">
            <td style="text-align:left">Aggregate</td>
            <td>{agg_before['avg_score']:.2f}</td>
            <td>{agg_after['avg_score']:.2f}</td>
            <td>{fmt_delta(overall_delta)}</td>
        </tr>
    </tfoot>
</table>

<h2>Per-Dimension Aggregate</h2>
<table>
    <thead><tr><th style="text-align:left">Dimension</th><th>Before</th><th>After</th><th>Delta</th></tr></thead>
    <tbody>{dim_rows}</tbody>
</table>

<h2>Topic Details</h2>
{detail_sections}

<h2>Prompt Diff</h2>
<pre>{diff_escaped}</pre>

</body></html>"""

    # Save
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"comparison_{timestamp}.html"
    report_path.write_text(html)

    # Also save raw JSON for further analysis
    json_path = REPORT_DIR / f"comparison_{timestamp}.json"
    # Serialize results (strip non-serializable bits)
    serializable = {}
    for tid, data in all_results.items():
        serializable[tid] = {
            "topic_title": data["guideline"]["topic_title"],
            "before": data["before"],
            "after": data["after"],
        }
    json_path.write_text(json.dumps({
        "timestamp": now.isoformat(),
        "topics": serializable,
        "aggregate_before": agg_before,
        "aggregate_after": agg_after,
        "overall_delta": overall_delta,
    }, indent=2, default=str))

    return report_path


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="A/B comparison for explanation quality")
    parser.add_argument("--before-rounds", type=int, default=0, help="Review-refine rounds for 'before' group (default: 0)")
    parser.add_argument("--after-rounds", type=int, default=2, help="Review-refine rounds for 'after' group (default: 2)")
    args = parser.parse_args()

    before_rounds = args.before_rounds
    after_rounds = args.after_rounds

    t0 = time.time()
    prompt_diff = get_prompt_diff()

    # Load guidelines
    guidelines = {}
    for tid in TOPICS:
        guidelines[tid] = load_guideline(tid)

    total_runs = len(TOPICS) * ITERATIONS * 2
    run_count = 0

    all_results = {}

    before_label = f"generate only" if before_rounds == 0 else f"generate + {before_rounds} review"
    after_label = f"generate only" if after_rounds == 0 else f"generate + {after_rounds} review"

    print(f"\n{'='*70}")
    print(f"  Review-Refine A/B Comparison")
    print(f"  Before: {before_label} | After: {after_label}")
    print(f"  Topics: {len(TOPICS)} | Iterations: {ITERATIONS} | Total runs: {total_runs}")
    print(f"{'='*70}\n")

    for tid in TOPICS:
        title = guidelines[tid]["topic_title"]
        all_results[tid] = {"before": [], "after": [], "guideline": guidelines[tid]}

        print(f"\n--- {title} ---")

        for i in range(1, ITERATIONS + 1):
            # Before
            run_count += 1
            print(f"  [{run_count}/{total_runs}] {before_label} iter {i} ... ", end="", flush=True)
            result = run_single(tid, guidelines[tid], review_rounds=before_rounds)
            all_results[tid]["before"].append(result)
            if result["status"] == "ok":
                print(f"{result['avg_score']:.1f}/10 ({result['card_count']} cards)")
            else:
                print(f"CRASH: {result.get('error', '?')}")

            # After
            run_count += 1
            print(f"  [{run_count}/{total_runs}] {after_label} iter {i} ... ", end="", flush=True)
            result = run_single(tid, guidelines[tid], review_rounds=after_rounds)
            all_results[tid]["after"].append(result)
            if result["status"] == "ok":
                print(f"{result['avg_score']:.1f}/10 ({result['card_count']} cards)")
            else:
                print(f"CRASH: {result.get('error', '?')}")

    elapsed = time.time() - t0
    elapsed_min = elapsed / 60

    print(f"\n{'='*70}")
    print(f"  All {total_runs} runs complete in {elapsed_min:.1f} min")
    print(f"{'='*70}")

    # Quick summary to console
    for tid, data in all_results.items():
        title = data["guideline"]["topic_title"]
        b = avg_scores(data["before"])
        a = avg_scores(data["after"])
        d = a["avg_score"] - b["avg_score"]
        sign = "+" if d > 0 else ""
        print(f"  {title:.<45} {b['avg_score']:.2f} → {a['avg_score']:.2f} ({sign}{d:.2f})")

    # Generate report
    report_path = generate_html_report(all_results, prompt_diff, elapsed_min)

    print(f"\n  HTML report: {report_path}")
    print(f"  JSON data:   {report_path.with_suffix('.json')}")


if __name__ == "__main__":
    main()
