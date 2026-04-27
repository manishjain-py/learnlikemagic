"""
Baatcheet V2 Visualization Pass — read a generated dialogue, pick high-value
cards for visual aids, generate inline SVGs, and merge them back into the
dialogue JSON.

Standalone — calls `claude` CLI directly. Does not modify the original
dialogue.json (writes dialogue_with_visuals.json + visualizations.json).

Usage:
    python scripts/baatcheet_v2_visualize.py path/to/run-dir/
    python scripts/baatcheet_v2_visualize.py path/to/run-dir/ --effort medium
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "llm-backend" / "book_ingestion_v2" / "prompts"


def fill_placeholders(template: str, ctx: dict) -> str:
    out = template
    for key, val in ctx.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def call_claude(prompt: str, system_file: Path, effort: str, label: str, log_dir: Path, timeout: int = 1800) -> dict:
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--max-turns", "1",
        "--model", "claude-opus-4-7",
        "--effort", effort,
        "--append-system-prompt-file", str(system_file),
    ]
    clean_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{label}_user_prompt.txt").write_text(prompt)
    (log_dir / f"{label}_system_prompt.txt").write_text(system_file.read_text())

    print(f"[{label}] calling claude (effort={effort}, prompt_len={len(prompt)})...", flush=True)
    start = time.time()
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=clean_env)
    duration_s = time.time() - start

    if result.returncode != 0:
        (log_dir / f"{label}_stderr.txt").write_text(result.stderr)
        raise RuntimeError(f"[{label}] claude CLI exited {result.returncode}: {result.stderr[:500]}")

    (log_dir / f"{label}_raw_stdout.json").write_text(result.stdout)

    cli_envelope = json.loads(result.stdout)
    if cli_envelope.get("is_error"):
        raise RuntimeError(f"[{label}] claude returned error: {cli_envelope.get('result', '')[:500]}")

    response_text = cli_envelope.get("result", "")
    cost = cli_envelope.get("total_cost_usd")
    print(f"[{label}] done in {duration_s:.0f}s, response_len={len(response_text)}, cost=${cost:.2f}", flush=True)

    parsed = extract_json(response_text)
    if parsed is None:
        (log_dir / f"{label}_unparseable_response.txt").write_text(response_text)
        raise RuntimeError(f"[{label}] could not parse JSON from response (saved to log dir)")

    return {"parsed": parsed, "raw_text": response_text, "duration_s": duration_s, "cost_usd": cost}


def extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1:
            return None
        candidate = text[first:last + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def slim_dialogue_for_prompt(dialogue: dict) -> list:
    """Strip schema noise; keep just card_idx, type, speaker, lines, plus existing visual_intent."""
    out = []
    for c in dialogue.get("cards", []):
        slim = {
            "card_idx": c.get("card_idx"),
            "card_type": c.get("card_type"),
            "speaker": c.get("speaker"),
            "speaker_name": c.get("speaker_name"),
            "lines": [{"display": l.get("display", "")} for l in c.get("lines", [])],
        }
        if c.get("visual_intent"):
            slim["existing_visual_intent"] = c["visual_intent"]
        out.append(slim)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--topic-name", default=None, help="Override topic_name (defaults to run_summary.json)")
    parser.add_argument("--subject", default="Math")
    parser.add_argument("--grade", default="4")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    plan = json.loads((run_dir / "plan.json").read_text())
    dialogue = json.loads((run_dir / "dialogue.json").read_text())
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}

    topic_name = args.topic_name or summary.get("topic", "Baatcheet topic")

    ctx = {
        "topic_name": topic_name,
        "subject": args.subject,
        "grade": args.grade,
        "lesson_plan_json": json.dumps(plan, indent=2),
        "dialogue_cards_json": json.dumps(slim_dialogue_for_prompt(dialogue), indent=2),
    }

    user_prompt = fill_placeholders((PROMPTS_DIR / "baatcheet_visual_pass.txt").read_text(), ctx)
    system_file = PROMPTS_DIR / "baatcheet_visual_pass_system.txt"

    result = call_claude(user_prompt, system_file, args.effort, "03_visual_pass", run_dir, timeout=2400)
    visualizations = result["parsed"].get("visualizations", [])

    print(f"\nGot {len(visualizations)} visualizations")
    for v in visualizations:
        print(f"  card {v.get('card_idx')}: {v.get('visual_intent','')[:80]}")

    # Save raw visualizations
    (run_dir / "visualizations.json").write_text(json.dumps({
        "visualizations": visualizations,
        "duration_s": result["duration_s"],
        "cost_usd": result["cost_usd"],
        "effort": args.effort,
    }, indent=2))

    # Merge into dialogue cards
    by_idx = {v["card_idx"]: v for v in visualizations if "card_idx" in v}
    enriched_cards = []
    for c in dialogue.get("cards", []):
        new_c = dict(c)
        v = by_idx.get(c.get("card_idx"))
        if v:
            new_c["visual_intent"] = v.get("visual_intent", new_c.get("visual_intent"))
            new_c["visual_svg"] = v.get("svg", "")
            new_c["visual_why"] = v.get("why", "")
        enriched_cards.append(new_c)

    enriched = {"cards": enriched_cards}
    (run_dir / "dialogue_with_visuals.json").write_text(json.dumps(enriched, indent=2))

    print(f"\nWrote {run_dir / 'visualizations.json'}")
    print(f"Wrote {run_dir / 'dialogue_with_visuals.json'}")
    print(f"\nNext: python scripts/baatcheet_v2_render_html.py {run_dir} --visuals")


if __name__ == "__main__":
    main()
