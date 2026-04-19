"""Manual gold eval for AudioTextReviewService.

Measures the PRD success criteria that unit tests cannot:
- SC2: >=80% defect catch on the defective fixture set
- SC3: >=90% no-false-rewrite on the clean fixture set

Runs against the LLM configured for 'audio_text_review' in the DB (or
fallback 'explanation_generator'). Costs money — do not add to CI.

Usage:
    cd llm-backend
    source venv/bin/activate
    python tests/manual/audio_review_gold_eval.py
    python tests/manual/audio_review_gold_eval.py --set defective
    python tests/manual/audio_review_gold_eval.py --limit 5

Output: per-card pass/fail, then overall percentages + SC2/SC3 verdict.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "audio_review"
DEFECTIVE_JSON = FIXTURES_DIR / "defective_set.json"
CLEAN_JSON = FIXTURES_DIR / "clean_set.json"

SC2_THRESHOLD = 0.80
SC3_THRESHOLD = 0.90


def _build_service(language: str = "en"):
    """Spin up AudioTextReviewService with a real LLMService from DB config."""
    from book_ingestion_v2.services.audio_text_review_service import (
        AudioTextReviewService,
    )
    from config import get_settings
    from database import get_db_manager
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService

    settings = get_settings()
    db = get_db_manager().get_session()

    llm_config_svc = LLMConfigService(db)
    try:
        config = llm_config_svc.get_config("audio_text_review")
    except Exception:
        config = llm_config_svc.get_config("explanation_generator")
    print(
        f"Using LLM provider={config['provider']} model={config['model_id']} "
        f"(component={config.get('component_key', '?')})"
    )

    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )
    return AudioTextReviewService(db, llm_service, language=language)


def _stub_guideline(topic: str, grade: int = 3):
    g = MagicMock()
    g.topic_title = topic
    g.topic = topic
    g.grade = grade
    g.id = "gold-eval"
    return g


def _eval_defective(service, fixtures, limit: int | None = None) -> dict:
    cards = fixtures["cards"]
    if limit:
        cards = cards[:limit]

    total = len(cards)
    caught = 0
    per_card_results = []

    for fx in cards:
        defect_class = fx["defect_class"]
        card = fx["card"]
        fixture_language = fx.get("language")

        # Swap language temporarily for hinglish fixtures
        original_language = service.language
        if fixture_language:
            service.language = fixture_language

        output = service._review_card(card, _stub_guideline(card.get("title", "")))
        service.language = original_language

        did_catch = output is not None and len(output.revisions) > 0
        if did_catch:
            caught += 1

        per_card_results.append({
            "card_idx": card.get("card_idx"),
            "defect_class": defect_class,
            "caught": did_catch,
            "revision_count": len(output.revisions) if output else 0,
        })
        mark = "PASS" if did_catch else "MISS"
        print(f"  [{mark}] card {card.get('card_idx')} ({defect_class})")

    ratio = caught / total if total > 0 else 0.0
    return {
        "total": total,
        "caught": caught,
        "ratio": ratio,
        "sc2_pass": ratio >= SC2_THRESHOLD,
        "per_card": per_card_results,
    }


def _eval_clean(service, fixtures, limit: int | None = None) -> dict:
    cards = fixtures["cards"]
    if limit:
        cards = cards[:limit]

    total = len(cards)
    clean_outputs = 0
    per_card_results = []

    for card in cards:
        output = service._review_card(card, _stub_guideline(card.get("title", "")))
        is_empty = output is not None and len(output.revisions) == 0
        if is_empty:
            clean_outputs += 1

        per_card_results.append({
            "card_idx": card.get("card_idx"),
            "clean_output": is_empty,
            "revision_count": len(output.revisions) if output else -1,
        })
        mark = "PASS" if is_empty else "OVER-REWRITE"
        print(f"  [{mark}] card {card.get('card_idx')} (title={card.get('title', '?')[:30]})")

    ratio = clean_outputs / total if total > 0 else 0.0
    return {
        "total": total,
        "clean_outputs": clean_outputs,
        "ratio": ratio,
        "sc3_pass": ratio >= SC3_THRESHOLD,
        "per_card": per_card_results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--set",
        choices=["defective", "clean", "both"],
        default="both",
        help="Which fixture set to evaluate",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on number of cards")
    args = parser.parse_args()

    service = _build_service()

    overall_pass = True

    if args.set in ("defective", "both"):
        print("\n=== Defective set (SC2: catches known defects) ===")
        with open(DEFECTIVE_JSON) as f:
            fixtures = json.load(f)
        result = _eval_defective(service, fixtures, args.limit)
        print(
            f"\nDefect catch rate: {result['caught']}/{result['total']} "
            f"({result['ratio']:.1%}) — SC2 threshold {SC2_THRESHOLD:.0%}"
        )
        print(f"SC2 verdict: {'PASS' if result['sc2_pass'] else 'FAIL'}")
        overall_pass = overall_pass and result["sc2_pass"]

    if args.set in ("clean", "both"):
        print("\n=== Clean set (SC3: no false rewrites) ===")
        with open(CLEAN_JSON) as f:
            fixtures = json.load(f)
        result = _eval_clean(service, fixtures, args.limit)
        print(
            f"\nClean pass rate: {result['clean_outputs']}/{result['total']} "
            f"({result['ratio']:.1%}) — SC3 threshold {SC3_THRESHOLD:.0%}"
        )
        print(f"SC3 verdict: {'PASS' if result['sc3_pass'] else 'FAIL'}")
        overall_pass = overall_pass and result["sc3_pass"]

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
