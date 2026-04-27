"""
Baatcheet V2 Experiment Harness — Standalone

Two-stage generation: lesson plan -> dialogue cards.
Calls `claude` CLI directly (no project imports). Hardcoded test topic.
Outputs to llm-backend/scripts/baatcheet_v2_outputs/<topic>/.

Usage:
    cd llm-backend && source venv/bin/activate
    python scripts/baatcheet_v2_experiment.py
    python scripts/baatcheet_v2_experiment.py --effort medium
    python scripts/baatcheet_v2_experiment.py --skip-plan --plan-file path/to/plan.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "llm-backend" / "book_ingestion_v2" / "prompts"
OUT_ROOT = REPO_ROOT / "llm-backend" / "scripts" / "baatcheet_v2_outputs"

# ---- Hardcoded test topic (matches the V1 test topic for comparability) ----

TEST_TOPIC = {
    "topic_name": "The Water Cycle",
    "subject": "Science",
    "grade": "4",
    "guideline_text": (
        "Teach Grade 4 students how water moves between land, sky, and back as a continuous cycle. "
        "They should understand:\n"
        "- Evaporation: liquid water turns into invisible vapour when warmed by the sun (or any heat). "
        "Happens at any temperature, not only when water boils — wet clothes drying on the terrace are evaporating.\n"
        "- Condensation: water vapour cools and turns back into tiny water droplets, "
        "forming clouds in the sky and dew on cold surfaces (like a cold glass of water on a hot day).\n"
        "- Precipitation: when droplets in clouds join together and become heavy enough, they fall as rain "
        "(or snow, hail).\n"
        "- The cycle: rain flows into rivers, soaks into the ground, collects in lakes and seas — "
        "then evaporation begins again. The same water moves around forever. Nothing is created or destroyed.\n"
        "- Everyday Indian examples: wet clothes drying on the terrace, kitchen kettle steam, "
        "the cold glass that 'sweats' on a hot day, monsoon rain filling the lake near home."
    ),
    "key_concepts_list": (
        "- Three forms of water in everyday life: liquid (river, rain, glass of water), "
        "invisible vapour (in the air around us), tiny droplets (clouds, dew, fog)\n"
        "- Evaporation: liquid water becomes invisible vapour; happens whenever the sun (or any heat) warms water\n"
        "- Condensation: vapour becomes tiny droplets when cooled — clouds form when warm air rises and cools; "
        "dew forms on a cold glass\n"
        "- Precipitation: many tiny droplets join into bigger drops; when heavy enough they fall as rain\n"
        "- The cycle is continuous: rain → rivers → seas → evaporation → clouds → rain again. "
        "The same water, different forms."
    ),
    "misconceptions_list": (
        "- Evaporation only happens when water boils on the stove (so wet clothes drying on the terrace, "
        "a wet bathroom floor drying, or a puddle shrinking after rain are not 'evaporation' to the student — "
        "they think those are different things).\n"
        "- Clouds are made of cotton or smoke (they look fluffy from below, so students imagine cotton — "
        "but cotton cannot rain; clouds are billions of tiny water droplets, which is why they can fall as rain).\n"
        "- Water 'disappears' from a puddle and rain 'comes from the sky' (failure to track that the same "
        "water keeps moving around — the puddle's water becomes invisible vapour that rises up; "
        "rain water came from a lake or sea that evaporated)."
    ),
    "variant_a_cards_json": "[]",
    "prior_topics_section": "",
    "lesson_plan_json": "",  # filled in stage 2
}

SLUG = "water-cycle-class4"


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


def fill_placeholders(template: str, ctx: dict) -> str:
    out = template
    for key, val in ctx.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def call_claude(prompt: str, system_file: Path, effort: str, label: str, log_dir: Path, timeout: int = 1800) -> dict:
    """Call claude CLI with prompt via stdin. Return parsed JSON envelope."""
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

    print(f"[{label}] calling claude (effort={effort}, prompt_len={len(prompt)}, system_file={system_file.name})...", flush=True)
    start = time.time()
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=clean_env,
    )
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

    return {
        "parsed": parsed,
        "raw_text": response_text,
        "duration_s": duration_s,
        "cost_usd": cost,
    }


def extract_json(text: str):
    """Pull a JSON object out of model output (handles fenced code, prefix prose)."""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--plan-effort", default=None, help="Effort for plan stage (defaults to --effort)")
    parser.add_argument("--dialogue-effort", default=None, help="Effort for dialogue stage (defaults to --effort)")
    parser.add_argument("--skip-plan", action="store_true", help="Reuse existing plan from --plan-file")
    parser.add_argument("--plan-file", default=None)
    parser.add_argument("--run-label", default=None, help="Override the timestamped run label")
    args = parser.parse_args()

    plan_effort = args.plan_effort or args.effort
    dialogue_effort = args.dialogue_effort or args.effort

    label = args.run_label or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / SLUG / label
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}", flush=True)

    ctx = dict(TEST_TOPIC)

    # ---- Stage 1: lesson plan ----
    if args.skip_plan and args.plan_file:
        plan_path = Path(args.plan_file)
        plan = json.loads(plan_path.read_text())
        print(f"Loaded existing plan from {plan_path}", flush=True)
        plan_meta = {"reused": True, "source": str(plan_path)}
    else:
        plan_user = fill_placeholders(read_prompt("baatcheet_lesson_plan_generation.txt"), ctx)
        plan_system_file = PROMPTS_DIR / "baatcheet_lesson_plan_generation_system.txt"
        plan_result = call_claude(plan_user, plan_system_file, plan_effort, "01_plan", out_dir)
        plan = plan_result["parsed"]
        plan_meta = {
            "reused": False,
            "duration_s": plan_result["duration_s"],
            "cost_usd": plan_result["cost_usd"],
        }

    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    print(f"Plan saved: {out_dir / 'plan.json'}", flush=True)
    print(f"  misconceptions: {len(plan.get('misconceptions', []))}", flush=True)
    print(f"  card_plan slots: {len(plan.get('card_plan', []))}", flush=True)
    print(f"  spine.situation: {plan.get('spine', {}).get('situation', '')[:80]}", flush=True)

    # ---- Stage 2: dialogue cards ----
    ctx["lesson_plan_json"] = json.dumps(plan, indent=2)
    dialogue_user = fill_placeholders(read_prompt("baatcheet_dialogue_generation.txt"), ctx)
    dialogue_system_file = PROMPTS_DIR / "baatcheet_dialogue_generation_system.txt"
    dialogue_result = call_claude(dialogue_user, dialogue_system_file, dialogue_effort, "02_dialogue", out_dir, timeout=2400)
    dialogue = dialogue_result["parsed"]

    (out_dir / "dialogue.json").write_text(json.dumps(dialogue, indent=2))

    cards = dialogue.get("cards", [])
    print(f"Dialogue saved: {out_dir / 'dialogue.json'}", flush=True)
    print(f"  card count: {len(cards)}", flush=True)

    summary = {
        "topic": TEST_TOPIC["topic_name"],
        "run_label": label,
        "plan_effort": plan_effort,
        "dialogue_effort": dialogue_effort,
        "plan_meta": plan_meta,
        "dialogue": {
            "duration_s": dialogue_result["duration_s"],
            "cost_usd": dialogue_result["cost_usd"],
            "card_count": len(cards),
        },
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nRun summary saved: {out_dir / 'run_summary.json'}", flush=True)
    print(f"\n--- Card preview (first 5) ---", flush=True)
    for c in cards[:5]:
        speaker = c.get("speaker_name") or c.get("card_type", "?")
        lines = c.get("lines", [])
        first_line = lines[0]["display"] if lines else ""
        print(f"  [{c.get('card_idx')}] ({c.get('card_type')}) {speaker}: {first_line[:80]}", flush=True)


if __name__ == "__main__":
    main()
