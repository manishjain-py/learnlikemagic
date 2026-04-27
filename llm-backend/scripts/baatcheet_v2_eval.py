"""
Baatcheet V2 Eval — score a generated dialogue against the V2 rubric.

Reads plan.json + dialogue.json, prints mechanical metrics + a rendered
markdown card-by-card breakdown for human qualitative judgement.

Usage:
    python scripts/baatcheet_v2_eval.py path/to/run-dir/
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


TUTOR_INTERJECTIONS = [
    "aha", "wow", "high five", "spot on", "got it", "brilliant",
    "perfect", "exactly", "let me ask you", "yes!", "great",
]
STUDENT_SOUNDS = [
    "hmm", "umm", "oh wait", "ohhh", "wait!", "oh!",
    "uh", "ah", "got it", "no way",
]


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def card_full_text(card: dict) -> str:
    return " ".join(line.get("display", "") for line in card.get("lines", []))


def find_substring_hits(text: str, needles: list[str]) -> list[str]:
    text_l = text.lower()
    hits = []
    for n in needles:
        if n in text_l:
            hits.append(n)
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="Path to run output directory containing plan.json and dialogue.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    plan = json.loads((run_dir / "plan.json").read_text())
    dialogue = json.loads((run_dir / "dialogue.json").read_text())
    cards = dialogue.get("cards", [])

    # ---- Plan-side metrics ----
    misconceptions = plan.get("misconceptions", [])
    spine = plan.get("spine", {})
    materials = plan.get("concrete_materials", [])
    macro = plan.get("macro_structure", [])
    card_plan = plan.get("card_plan", [])

    move_counts = Counter(slot["move"] for slot in card_plan)
    target_counts = Counter(slot["target"] for slot in card_plan)
    speaker_counts = Counter(slot["speaker"] for slot in card_plan)

    # ---- Dialogue-side metrics ----
    total_cards = len(cards)
    type_counts = Counter(c.get("card_type", "?") for c in cards)
    speaker_card_counts = Counter(c.get("speaker") or c.get("card_type") for c in cards)

    tutor_text_total = " ".join(card_full_text(c) for c in cards if c.get("speaker") == "tutor")
    peer_text_total = " ".join(card_full_text(c) for c in cards if c.get("speaker") == "peer")

    tutor_words = word_count(tutor_text_total)
    peer_words = word_count(peer_text_total)
    talk_ratio = tutor_words / peer_words if peer_words else float("inf")

    word_per_card = []
    overlong_tutor = []
    overlong_peer = []
    for c in cards:
        wc = word_count(card_full_text(c))
        word_per_card.append((c.get("card_idx"), c.get("card_type"), wc))
        if c.get("speaker") == "tutor" and wc > 40:
            overlong_tutor.append((c.get("card_idx"), wc))
        if c.get("speaker") == "peer" and wc > 25:
            overlong_peer.append((c.get("card_idx"), wc))

    interjection_hits = find_substring_hits(tutor_text_total, TUTOR_INTERJECTIONS)
    student_sound_hits = find_substring_hits(peer_text_total, STUDENT_SOUNDS)

    # ---- Spine threading (substring search of spine particulars) ----
    spine_situation = (spine.get("situation") or "").lower()
    particulars = [p.lower() for p in spine.get("particulars", [])]
    spine_callback_cards = []
    for c in cards:
        text = card_full_text(c).lower()
        for p in particulars:
            tokens = [t for t in p.split() if len(t) > 3]
            if any(t in text for t in tokens):
                spine_callback_cards.append(c.get("card_idx"))
                break
    spine_callback_cards = sorted(set(spine_callback_cards))

    # ---- Misconception cycle completeness check (plan-side) ----
    cycle_completeness = {}
    for m in misconceptions:
        mid = m["id"]
        cycle_slots = [s for s in card_plan if s.get("target") == mid]
        moves_in_cycle = [s["move"] for s in cycle_slots]
        has_trap = "trap-set" in moves_in_cycle
        has_fall = "fall" in moves_in_cycle
        has_resolve = ("student-act" in moves_in_cycle) or ("funnel" in moves_in_cycle) or ("observe" in moves_in_cycle)
        has_articulate = "articulate" in moves_in_cycle
        cycle_completeness[mid] = {
            "name": m["name"],
            "card_count": len(cycle_slots),
            "trap-set": has_trap,
            "fall": has_fall,
            "resolve_concrete_or_funnel": has_resolve,
            "articulate": has_articulate,
            "complete": has_trap and has_fall and has_resolve and has_articulate,
            "moves": moves_in_cycle,
        }

    # ---- Move variety / consecutive moves ----
    plan_moves = [s["move"] for s in card_plan]
    distinct_moves = set(plan_moves)
    consecutive_same = []
    allowed_pairs = {("trap-set", "fall"), ("articulate", "callback"), ("student-act", "observe")}
    for i in range(len(plan_moves) - 1):
        a, b = plan_moves[i], plan_moves[i + 1]
        if a == b:
            consecutive_same.append((card_plan[i]["slot"], a))

    # ---- Closing card check ----
    last_card = cards[-1] if cards else {}
    last_card_text = card_full_text(last_card).lower()
    misconception_words_in_close = []
    for m in misconceptions:
        keys = [m["name"].lower()] + [w for w in m["description"].lower().split() if len(w) > 5]
        # Look for at least one distinctive content word from the misconception
        if any(k in last_card_text for k in keys[:5]):
            misconception_words_in_close.append(m["id"])
    spine_close_hit = any(p in last_card_text for p in particulars)

    # ---- Output ----
    print("=" * 70)
    print(f"BAATCHEET V2 EVAL — {run_dir.name}")
    print("=" * 70)
    print()
    print(f"Topic: {dialogue.get('topic') or '(in plan)'}\n")
    print(f"--- Plan ---")
    print(f"  Misconceptions: {len(misconceptions)}")
    for m in misconceptions:
        print(f"    {m['id']}: {m['name']}")
    print(f"  Spine situation: {spine.get('situation', '')[:100]}")
    print(f"  Spine particulars: {len(spine.get('particulars', []))}")
    print(f"  Concrete materials: {len(materials)}")
    print(f"  Macro structure phases: {len(macro)}")
    print(f"  Card plan slots: {len(card_plan)}")
    print()

    print(f"--- Move grammar (from plan) ---")
    print(f"  Distinct moves: {len(distinct_moves)} — {sorted(distinct_moves)}")
    print(f"  Move counts: {dict(sorted(move_counts.items(), key=lambda x: -x[1]))}")
    print(f"  Speaker mix: {dict(speaker_counts)}")
    print(f"  Consecutive same-move pairs (excluding allowed): "
          f"{[(s,m) for (s,m) in consecutive_same if not any((m, plan_moves[card_plan.index(next(c for c in card_plan if c['slot']==s))+1]) in allowed_pairs for _ in [0])]}")
    print()

    print(f"--- Misconception cycles ---")
    for mid, info in cycle_completeness.items():
        flag = "OK" if info["complete"] else "INCOMPLETE"
        print(f"  {mid} [{flag}] cards={info['card_count']} moves={info['moves']}")
    print()

    print(f"--- Dialogue surface ---")
    print(f"  Total cards: {total_cards}")
    print(f"  Card types: {dict(type_counts)}")
    print(f"  Tutor words total: {tutor_words}")
    print(f"  Peer  words total: {peer_words}")
    print(f"  Talk ratio (tutor:peer): {talk_ratio:.2f}:1")
    print(f"  Overlong tutor cards (>40w): {overlong_tutor}")
    print(f"  Overlong peer  cards (>25w): {overlong_peer}")
    print()

    print(f"--- Voice texture ---")
    print(f"  Tutor interjections found ({len(interjection_hits)}): {interjection_hits}")
    print(f"  Student sounds found     ({len(student_sound_hits)}): {student_sound_hits}")
    print()

    print(f"--- Threading ---")
    print(f"  Cards referencing spine particulars: {spine_callback_cards}")
    print(f"  Threading count: {len(spine_callback_cards)} (target ≥3)")
    print()

    print(f"--- Closing card ---")
    print(f"  Last card slot: {last_card.get('card_idx')}")
    print(f"  Last card type: {last_card.get('card_type')}")
    print(f"  Misconceptions referenced in close: {misconception_words_in_close}")
    print(f"  Spine particular in close: {spine_close_hit}")
    print()

    # ---- Score against rubric ----
    print("=" * 70)
    print("RUBRIC SCORES (1=absent, 5=exemplary)")
    print("=" * 70)

    scores = {}
    notes = {}

    # 1. Spine threading
    threads = len(spine_callback_cards)
    if threads >= 5:
        scores["1_spine_threaded"] = 5; notes["1_spine_threaded"] = f"{threads} callback cards"
    elif threads >= 3:
        scores["1_spine_threaded"] = 4; notes["1_spine_threaded"] = f"{threads} callback cards"
    elif threads >= 2:
        scores["1_spine_threaded"] = 3; notes["1_spine_threaded"] = f"{threads} callback cards (target ≥3)"
    elif threads >= 1:
        scores["1_spine_threaded"] = 2; notes["1_spine_threaded"] = "spine barely referenced"
    else:
        scores["1_spine_threaded"] = 1; notes["1_spine_threaded"] = "no spine threading detected"

    # 2. Misconception cycles complete
    complete = sum(1 for info in cycle_completeness.values() if info["complete"])
    if complete == len(misconceptions) and complete >= 3:
        scores["2_misconception_cycles"] = 5
    elif complete == len(misconceptions):
        scores["2_misconception_cycles"] = 4
    elif complete >= 1:
        scores["2_misconception_cycles"] = 3
    else:
        scores["2_misconception_cycles"] = 1
    notes["2_misconception_cycles"] = f"{complete}/{len(misconceptions)} cycles structurally complete"

    # 3. Closing takeaways
    if len(misconception_words_in_close) >= len(misconceptions) and spine_close_hit:
        scores["3_close_takeaways"] = 5
    elif len(misconception_words_in_close) >= 2 and spine_close_hit:
        scores["3_close_takeaways"] = 4
    elif len(misconception_words_in_close) >= 2:
        scores["3_close_takeaways"] = 3
    elif len(misconception_words_in_close) >= 1:
        scores["3_close_takeaways"] = 2
    else:
        scores["3_close_takeaways"] = 1
    notes["3_close_takeaways"] = f"{len(misconception_words_in_close)} misconception refs + {'spine' if spine_close_hit else 'no spine'} in close"

    # 4. Card count 30-40
    if 30 <= total_cards <= 40:
        scores["4_card_count"] = 5
    elif 28 <= total_cards <= 42:
        scores["4_card_count"] = 4
    elif 25 <= total_cards <= 45:
        scores["4_card_count"] = 3
    else:
        scores["4_card_count"] = 1
    notes["4_card_count"] = f"{total_cards} cards"

    # 5. Move variety
    if len(distinct_moves) >= 10:
        scores["5_move_variety"] = 5
    elif len(distinct_moves) >= 7:
        scores["5_move_variety"] = 4
    elif len(distinct_moves) >= 5:
        scores["5_move_variety"] = 3
    else:
        scores["5_move_variety"] = 1
    notes["5_move_variety"] = f"{len(distinct_moves)} distinct moves"

    # 6. Student-act moments
    student_act_count = move_counts.get("student-act", 0)
    if student_act_count >= 3:
        scores["6_student_act"] = 5
    elif student_act_count == 2:
        scores["6_student_act"] = 4
    elif student_act_count == 1:
        scores["6_student_act"] = 2
    else:
        scores["6_student_act"] = 1
    notes["6_student_act"] = f"{student_act_count} student-act moves"

    # 7. Consecutive moves
    bad_consecutive = []
    for i in range(len(plan_moves) - 1):
        a, b = plan_moves[i], plan_moves[i + 1]
        if a == b and (a, b) not in allowed_pairs:
            bad_consecutive.append((card_plan[i]["slot"], a))
    if not bad_consecutive:
        scores["7_no_consecutive_moves"] = 5
    elif len(bad_consecutive) <= 2:
        scores["7_no_consecutive_moves"] = 3
    else:
        scores["7_no_consecutive_moves"] = 2
    notes["7_no_consecutive_moves"] = f"{len(bad_consecutive)} consecutive same-move pairs"

    # 8. Tiny-beat pacing
    overlong_total = len(overlong_tutor) + len(overlong_peer)
    if overlong_total == 0:
        scores["8_tiny_beats"] = 5
    elif overlong_total <= 2:
        scores["8_tiny_beats"] = 4
    elif overlong_total <= 5:
        scores["8_tiny_beats"] = 3
    else:
        scores["8_tiny_beats"] = 2
    notes["8_tiny_beats"] = f"{len(overlong_tutor)} tutor + {len(overlong_peer)} peer overlong"

    # 9. Tutor interjections
    if len(interjection_hits) >= 5:
        scores["9_tutor_interjections"] = 5
    elif len(interjection_hits) >= 3:
        scores["9_tutor_interjections"] = 4
    elif len(interjection_hits) >= 2:
        scores["9_tutor_interjections"] = 3
    else:
        scores["9_tutor_interjections"] = 1
    notes["9_tutor_interjections"] = f"{len(interjection_hits)} different interjections"

    # 10. Student sounds
    if len(student_sound_hits) >= 5:
        scores["10_student_sounds"] = 5
    elif len(student_sound_hits) >= 3:
        scores["10_student_sounds"] = 4
    elif len(student_sound_hits) >= 2:
        scores["10_student_sounds"] = 3
    else:
        scores["10_student_sounds"] = 1
    notes["10_student_sounds"] = f"{len(student_sound_hits)} different sounds"

    print()
    for k, v in sorted(scores.items()):
        print(f"  [{v}/5] {k}: {notes[k]}")
    print()
    avg = sum(scores.values()) / len(scores)
    pass_count = sum(1 for v in scores.values() if v >= 4)
    fail_count = sum(1 for v in scores.values() if v <= 2)
    print(f"  AVERAGE: {avg:.2f}/5")
    print(f"  ≥4 dimensions: {pass_count}/{len(scores)}")
    print(f"  ≤2 dimensions: {fail_count}/{len(scores)}")

    if fail_count == 0 and avg >= 4.0:
        print("\n  VERDICT: PASS — V2 shape is recognizably present")
    elif avg >= 3.5:
        print("\n  VERDICT: PARTIAL — most dimensions land; targeted iteration needed")
    else:
        print("\n  VERDICT: FAIL — architecture not landing; prompt needs rework")

    # ---- Render markdown for human read ----
    md_lines = [f"# Dialogue render — {run_dir.name}\n"]
    md_lines.append(f"## Plan summary\n")
    md_lines.append(f"- **Spine:** {spine.get('situation', '')}")
    md_lines.append(f"- **Particulars:** {', '.join(spine.get('particulars', []))}")
    md_lines.append(f"- **Misconceptions:**")
    for m in misconceptions:
        md_lines.append(f"  - **{m['id']}:** {m['name']} — *{m.get('description', '')[:120]}*")
    md_lines.append(f"- **Materials:** {', '.join(mat.get('item','') for mat in materials)}")
    md_lines.append("")
    md_lines.append(f"## Cards\n")
    plan_by_slot = {s["slot"]: s for s in card_plan}
    for c in cards:
        slot = c.get("card_idx")
        plan_slot = plan_by_slot.get(slot, {})
        move = plan_slot.get("move", "?")
        target = plan_slot.get("target", "")
        speaker = c.get("speaker_name") or c.get("card_type", "?")
        md_lines.append(f"**Card {slot}** — `{c.get('card_type')}` | move: `{move}` | target: `{target}` | speaker: `{speaker}`")
        for line in c.get("lines", []):
            md_lines.append(f"  - {line.get('display','')}")
        if c.get("visual_intent"):
            md_lines.append(f"  - *visual:* {c['visual_intent']}")
        if c.get("check_in"):
            ci = c["check_in"]
            md_lines.append(f"  - *check-in ({ci.get('activity_type')}):* {ci.get('instruction','')}")
        md_lines.append("")

    (run_dir / "rendered.md").write_text("\n".join(md_lines))
    (run_dir / "eval_scores.json").write_text(json.dumps({"scores": scores, "notes": notes, "average": avg}, indent=2))
    print(f"\nMarkdown render: {run_dir / 'rendered.md'}")
    print(f"Scores JSON: {run_dir / 'eval_scores.json'}")


if __name__ == "__main__":
    main()
