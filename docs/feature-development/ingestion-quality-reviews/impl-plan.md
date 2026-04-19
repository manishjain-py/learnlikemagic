# Tech Implementation Plan: Ingestion Quality Review Stages

**PRD:** `docs/feature-development/ingestion-quality-reviews/PRD.md`
**Patterns mirrored from:**
- `ExplanationGeneratorService` (`llm-backend/book_ingestion_v2/services/explanation_generator_service.py`)
- `CheckInEnrichmentService` + review-refine (`docs/feature-development/check-in-review-refine/impl-plan.md`)
- `AudioGenerationService` + `/generate-audio` endpoint (`llm-backend/book_ingestion_v2/services/audio_generation_service.py`, `api/sync_routes.py:476`)
- `AnimationEnrichmentService` (`llm-backend/book_ingestion_v2/services/animation_enrichment_service.py`)

---

## 1. Overview

Two new review passes added to the ingestion pipeline. Phase 1 (Audio Text Review) ships first as an independent shippable unit. Phase 2 (Visual Rendering Review) ships in a follow-up PR. Each phase is self-contained and rollbackable on its own.

### Phase 1 dataflow

```
[today]
stage 5 generate  → cards with audio text + inline AudioGenerationService call → MP3s on S3
stage 8 check-ins → cards with audio_text
stage 6 /generate-audio → idempotent re-synth of missing MP3s (rarely used)

[after Phase 1]
stage 5 generate  → cards with audio text only (no inline MP3 call)
stage 8 check-ins → cards with audio_text
NEW: audio text review → surgical revisions list per card, applied in place, clears audio_url on changed lines
stage 6 /generate-audio → synthesizes MP3s; soft guardrail if no prior review job for scope
```

### Phase 2 dataflow (within existing stage 7)

```
decide_and_spec → code_gen → validate → review-refine N rounds → [NEW post-refine gate:
  render in Playwright → extract bounds → IoU overlap check → if overlap, one extra targeted
  refine round with collision report → re-render → re-check → if still overlap, set
  layout_warning=true] → store
```

No DB schema changes. No new tables. All persistence is via existing JSONB fields (`cards_json`, `visual_explanation` sub-object, `stage_snapshots_json` on jobs).

---

## 2. Phase 1 — Audio Text Review

### 2.1 Files changed

#### Backend

| File | Change |
|------|--------|
| `llm-backend/book_ingestion_v2/services/audio_text_review_service.py` | **NEW** — per-card LLM reviewer, surgical revisions, write-back, `audio_url` invalidation |
| `llm-backend/book_ingestion_v2/prompts/audio_text_review.txt` | **NEW** — user prompt template with `{topic_title}`, `{grade}`, `{language}`, `{card_json}`, `{output_schema}` placeholders |
| `llm-backend/book_ingestion_v2/prompts/audio_text_review_system.txt` | **NEW** — system instructions + schema for claude_code `--append-system-prompt-file` path |
| `llm-backend/book_ingestion_v2/constants.py` | Add `V2JobType.AUDIO_TEXT_REVIEW = "v2_audio_text_review"` |
| `llm-backend/book_ingestion_v2/services/explanation_generator_service.py` | **Remove** inline `AudioGenerationService` call at lines 194–199 |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | Add `POST /generate-audio-review`, `GET /audio-review-jobs/latest`; modify `POST /generate-audio` to return soft-guardrail warning when no prior review exists |
| `llm-backend/tests/unit/test_audio_text_review.py` | **NEW** — unit tests for service, validation, write-back |

#### Frontend

| File | Change |
|------|--------|
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | Add `generateAudioReview(bookId, opts)`, `getLatestAudioReviewJob(bookId, opts)`, extend `generateAudio` return type with soft-guardrail flag |
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | Add "Review audio" button on each chapter row (next to the existing "Audio" button); extend "Audio" button click handler to show confirmation dialog when soft-guardrail flag set |
| `llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx` | Add a per-topic "Review audio" trigger alongside existing per-topic actions |

#### Docs

| File | Change |
|------|--------|
| `docs/principles/book-ingestion-pipeline.md` | Renumber stages; document audio text review as stage 6, audio synthesis moves to stage 9 (tail of pipeline) |
| `docs/technical/book-guidelines.md` | Add "Audio Text Review" section parallel to existing "Audio Generation (TTS)"; update pipeline diagram |

### 2.2 New service: `audio_text_review_service.py`

Mirrors the structure of `CheckInEnrichmentService`: per-variant entry point, LLM call, validation, write-back, `stage_snapshots_json` capture.

```python
"""Review audio text strings in explanation and check-in cards.

Surgical rewrites only: no display edits, no line reshape. Runs after stage 5
(explanations) and stage 8 (check-ins), before stage 6 (MP3 synthesis).

Per-card LLM call → revisions list → drop invalid revisions → apply valid ones →
clear audio_url on changed lines so next stage-6 run re-synthesizes only those.
"""
import json
import logging
import re
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field

from shared.services.llm_service import LLMService, LLMServiceError
from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import attributes

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_REVIEW_PROMPT = (_PROMPTS_DIR / "audio_text_review.txt").read_text()
_REVIEW_SYSTEM_FILE = str(_PROMPTS_DIR / "audio_text_review_system.txt")

LLM_CONFIG_KEY = "audio_text_review"   # Falls back to "explanation_generator" if missing
FALLBACK_CONFIG_KEY = "explanation_generator"

# Banned patterns in revised_audio (validated before accepting a revision)
_BANNED_PATTERNS = [
    re.compile(r"\*\*"),                # markdown bold
    re.compile(r"(?<![a-zA-Z])=(?![a-zA-Z])"),  # standalone "="
    re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]"),  # emoji
]


class AudioLineRevision(BaseModel):
    """One audio-string rewrite."""
    card_idx: int = Field(description="1-based card index")
    line_idx: Optional[int] = Field(
        default=None,
        description="0-based line index within the card. NULL for check-in cards (single audio_text).",
    )
    kind: Literal["explanation_line", "check_in"] = Field(description="Card type")
    original_audio: str = Field(description="Current audio string (for audit)")
    revised_audio: str = Field(description="New audio string")
    reason: str = Field(description="Why this revision — cite the specific defect class")


class CardReviewOutput(BaseModel):
    """LLM output per card: zero or more revisions."""
    card_idx: int = Field(description="1-based card index")
    revisions: list[AudioLineRevision] = Field(
        default_factory=list,
        description="Empty list if card is clean; otherwise one entry per changed line.",
    )
    notes: str = Field(default="", description="Optional free-form reviewer commentary (for logs)")


class AudioTextReviewService:
    """Service entry point for audio text review stage."""

    def __init__(self, db: DBSession, llm: Optional[LLMService] = None):
        self.db = db
        self.repo = ExplanationRepository(db)
        self.llm = llm or LLMService.from_db(db, LLM_CONFIG_KEY, fallback_key=FALLBACK_CONFIG_KEY)

    def review_guideline(
        self,
        guideline: TeachingGuideline,
        *,
        variant_keys: Optional[list[str]] = None,
        heartbeat_fn: Optional[callable] = None,
        stage_collector: Optional[list] = None,
    ) -> dict:
        """Review all variants (or a subset) for a guideline.

        Returns {"reviewed": int, "revised_cards": int, "skipped": int, "failed": int, "errors": [str]}.
        """
        explanations = self.repo.get_by_guideline_id(guideline.id)
        if variant_keys:
            explanations = [e for e in explanations if e.variant_key in variant_keys]

        result = {"reviewed": 0, "revised_cards": 0, "skipped": 0, "failed": 0, "errors": []}
        for explanation in explanations:
            try:
                per_variant = self._review_variant(
                    explanation, guideline,
                    heartbeat_fn=heartbeat_fn, stage_collector=stage_collector,
                )
                result["reviewed"] += per_variant["cards_reviewed"]
                result["revised_cards"] += per_variant["cards_revised"]
            except Exception as e:
                result["failed"] += 1
                result["errors"].append(f"{guideline.topic_title}/{explanation.variant_key}: {e}")
                logger.exception(f"Audio text review failed for {guideline.id}/{explanation.variant_key}")
        return result

    def review_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        *,
        job_service=None,
        job_id: Optional[str] = None,
    ) -> dict:
        """Review every guideline in a chapter (or book). Drives progress on a job."""
        query = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            from shared.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(self.db).get_by_id(chapter_id)
            if chapter:
                query = query.filter(TeachingGuideline.chapter_key == f"chapter-{chapter.chapter_number}")
        guidelines = query.all()

        stage_collector: list = []
        completed = 0
        failed = 0
        errors: list[str] = []

        def _hb():
            if job_service and job_id:
                job_service.heartbeat(job_id)

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(job_id, current_item=topic, completed=completed, failed=failed)
            try:
                per_guideline = self.review_guideline(
                    guideline, heartbeat_fn=_hb, stage_collector=stage_collector,
                )
                if per_guideline["failed"] > 0:
                    failed += 1
                    errors.extend(per_guideline["errors"])
                else:
                    completed += 1
            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {e}")
                logger.exception(f"Audio text review failed for {guideline.id}")

        if job_service and job_id and stage_collector:
            job_service.append_stage_snapshots(job_id, stage_collector)

        return {
            "completed": completed, "failed": failed,
            "errors": errors[:10], "stage_snapshot_count": len(stage_collector),
        }

    # ─── Internals ────────────────────────────────────────────────────────

    def _review_variant(
        self,
        explanation: TopicExplanation,
        guideline: TeachingGuideline,
        *,
        heartbeat_fn: Optional[callable] = None,
        stage_collector: Optional[list] = None,
    ) -> dict:
        """Review every card in a variant. Return counts."""
        cards = explanation.cards_json or []
        cards_reviewed = 0
        cards_revised = 0
        any_change = False

        for card in cards:
            if heartbeat_fn:
                heartbeat_fn()

            card_output = self._review_card(card, guideline)
            cards_reviewed += 1

            if not card_output or not card_output.revisions:
                self._collect_snapshot(
                    stage_collector, guideline, explanation, card,
                    revisions=[], applied_count=0,
                )
                continue

            valid = [r for r in card_output.revisions if self._validate_revision(r)]
            applied = self._apply_revisions(card, valid)
            if applied > 0:
                cards_revised += 1
                any_change = True

            self._collect_snapshot(
                stage_collector, guideline, explanation, card,
                revisions=card_output.revisions, applied_count=applied,
            )

        if any_change:
            attributes.flag_modified(explanation, "cards_json")
            self.db.commit()

        return {"cards_reviewed": cards_reviewed, "cards_revised": cards_revised}

    def _review_card(
        self,
        card: dict,
        guideline: TeachingGuideline,
    ) -> Optional[CardReviewOutput]:
        """Call LLM on a single card."""
        topic = guideline.topic_title or guideline.topic
        grade = str(guideline.grade) if guideline.grade else "3"
        language = (guideline.metadata_json or {}).get("language", "en")

        # Strip `audio_url` before sending to the reviewer — not useful context, reduces tokens
        card_for_prompt = self._strip_audio_urls(card)

        prompt = (_REVIEW_PROMPT
            .replace("{topic_title}", topic)
            .replace("{grade}", grade)
            .replace("{language}", language)
            .replace("{card_json}", json.dumps(card_for_prompt, indent=2))
            .replace("{output_schema}", json.dumps(CardReviewOutput.model_json_schema(), indent=2))
        )

        system_file = _REVIEW_SYSTEM_FILE if self.llm.provider == "claude_code" else None

        try:
            response = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=CardReviewOutput.model_json_schema(),
                schema_name="CardReviewOutput",
                system_file=system_file,
            )
            parsed = self.llm.parse_json_response(response["output_text"])
            return CardReviewOutput.model_validate(parsed)
        except (LLMServiceError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Audio text review LLM call failed for {topic} card {card.get('card_idx')}: {e}")
            return None

    def _validate_revision(self, rev: AudioLineRevision) -> bool:
        """Drop revisions whose revised_audio still contains banned patterns."""
        text = rev.revised_audio.strip()
        if not text:
            logger.info(f"Dropping empty revision for card_idx={rev.card_idx}")
            return False
        for pattern in _BANNED_PATTERNS:
            if pattern.search(text):
                logger.info(
                    f"Dropping revision for card_idx={rev.card_idx} line_idx={rev.line_idx} "
                    f"— banned pattern in revised_audio"
                )
                return False
        return True

    def _apply_revisions(self, card: dict, revisions: list[AudioLineRevision]) -> int:
        """Apply valid revisions to the card dict in place. Clear audio_url on changed lines.

        Returns number of revisions actually applied.
        """
        applied = 0
        for rev in revisions:
            if rev.kind == "check_in":
                if card.get("card_type") != "check_in":
                    continue
                if card.get("audio_text") != rev.original_audio:
                    continue  # drift; don't apply
                card["audio_text"] = rev.revised_audio
                applied += 1
            else:  # explanation_line
                lines = card.get("lines") or []
                if rev.line_idx is None or rev.line_idx >= len(lines):
                    continue
                line = lines[rev.line_idx]
                if line.get("audio") != rev.original_audio:
                    continue  # drift
                line["audio"] = rev.revised_audio
                line["audio_url"] = None  # invalidate MP3 so stage 6 re-synths only this line
                applied += 1
        return applied

    def _strip_audio_urls(self, card: dict) -> dict:
        """Deep copy with audio_url stripped from every line."""
        import copy
        out = copy.deepcopy(card)
        for line in (out.get("lines") or []):
            line.pop("audio_url", None)
        return out

    def _collect_snapshot(
        self,
        stage_collector: Optional[list],
        guideline: TeachingGuideline,
        explanation: TopicExplanation,
        card: dict,
        *,
        revisions: list,
        applied_count: int,
    ) -> None:
        if stage_collector is None:
            return
        stage_collector.append({
            "guideline_id": guideline.id,
            "topic_title": guideline.topic_title or guideline.topic,
            "variant_key": explanation.variant_key,
            "card_idx": card.get("card_idx"),
            "card_type": card.get("card_type"),
            "stage": "audio_text_review",
            "revisions_proposed": [r.model_dump() if hasattr(r, "model_dump") else r for r in revisions],
            "revisions_applied": applied_count,
        })
```

**Design notes:**

- **Drift guard** — `_apply_revisions` compares `original_audio` against the current card value before overwriting. If the reviewer's view is stale (e.g., admin edited the card between review start and apply), the revision is silently dropped. Prevents clobbering concurrent edits.
- **`audio_url` invalidation is the contract with stage 6** — `AudioGenerationService` already skips lines with `audio_url` set (`audio_generation_service.py:82`). Clearing the URL on revised lines makes re-synthesis automatic and idempotent.
- **Validation is aggressive** — bans markdown, emoji, and equations-with-`=` that should never appear in spoken text. Not exhaustive (reviewer can still produce subtle issues), but catches the canonical defect class that motivated the feature.

### 2.3 Prompts

#### `audio_text_review.txt`

```
You are reviewing audio text for a Grade {grade} student learning about {topic_title}.

A card has TWO parallel representations:
- `display`: what the student sees on screen (may include markdown, symbols, equations)
- `audio`: what the student hears spoken aloud (pure words only, natural speech)

Your job is to review each `audio` string for defects and emit a surgical revisions list.
Untouched lines pass through unchanged — only emit a revision if the audio is genuinely defective.

## Target language

{language}  (en = English, hi = Hindi, hinglish = mix)

## Defect checklist (revise if any apply)

1. **Symbols/markdown leak** — "5+3=8", "**bold**", emoji, LaTeX
2. **Visual-only reference** — "as you can see in the diagram" when the line shouldn't reference visuals
3. **Pacing** — single-line audio >35 words that will run on when spoken
4. **Cross-line redundancy within this card** — line 2 audio re-states exactly what line 1 already said
5. **Math phrasing** — "5 + 3" written as characters instead of natural speech ("five plus three")
6. **Language-specific** — for hi/hinglish: Indian place-value reading ("one lakh twenty-three thousand", not "one hundred twenty-three thousand"); avoid English words in hi-only strings

## What you MUST NOT do

- Do NOT edit `display` text. It is shown as-is.
- Do NOT split, merge, or drop lines. Each line's audio maps to one TTS file.
- Do NOT rewrite for teaching quality, tone, or style. Stage 5's review-refine owns those.
- Do NOT touch a line unless it genuinely has a defect. Over-rewriting is worse than under-rewriting.

## Card

{card_json}

## Output schema (strict JSON)

{output_schema}

Return a `CardReviewOutput`. If every audio string is clean, return `revisions: []`. Otherwise,
one entry per changed line. Always set `original_audio` to EXACTLY the current value.
```

#### `audio_text_review_system.txt`

Static instructions + schema for claude_code `--append-system-prompt-file`. Same body as `audio_text_review.txt` minus the dynamic placeholders (`{topic_title}`, `{grade}`, `{language}`, `{card_json}`). Only the `{output_schema}` block (which is stable across calls) and the checklist rules. Follows the pattern of `explanation_review_refine_system.txt` + `visual_decision_and_spec_system.txt`.

### 2.4 Stage-5 inline MP3 call removal

`llm-backend/book_ingestion_v2/services/explanation_generator_service.py` lines 192–199 (see earlier read):

```python
# REMOVE THIS BLOCK:
# Generate TTS audio and upload to S3 (best-effort — lines
# without audio_url fall back to real-time TTS on the frontend)
try:
    from book_ingestion_v2.services.audio_generation_service import AudioGenerationService
    audio_svc = AudioGenerationService()
    audio_svc.generate_for_cards(cards_dicts, guideline.id, config["key"])
except Exception as audio_err:
    logger.warning(f"Audio generation failed for {topic}/{config['key']}, cards saved without audio: {audio_err}")
```

Cards are saved without MP3s. Admin then runs audio text review → MP3 synthesis. Existing `force` regeneration pathway is unaffected — force regenerates the explanation cards but does not auto-produce MP3s.

**Migration concern:** existing topics that already have MP3s stay intact (we don't modify `audio_url` on unrelated lines). The removal only changes behavior for NEW regenerations.

### 2.5 `constants.py` changes

```python
class V2JobType(str, Enum):
    OCR = "v2_ocr"
    ...
    CHECK_IN_ENRICHMENT = "v2_check_in_enrichment"
    AUDIO_TEXT_REVIEW = "v2_audio_text_review"   # NEW
    PRACTICE_BANK_GENERATION = "v2_practice_bank_generation"
```

### 2.6 API routes

Add to `sync_routes.py`, modeled on `/generate-audio` (lines 476–546) and `_run_audio_generation` (549–623):

```python
@router.post("/generate-audio-review", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_audio_review(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope review"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic review"),
    db: Session = Depends(get_db),
):
    """Review audio text strings in explanation + check-in cards. Applies surgical revisions.

    Runs as a background job. Requires explanations (and optionally check-ins) to already exist.
    Clears audio_url on revised lines so next /generate-audio run re-synthesizes only those.
    """
    from book_ingestion_v2.api.processing_routes import run_in_background_v2
    from shared.models.entities import TeachingGuideline

    # same guideline/chapter resolution as /generate-audio ...
    job_service = ChapterJobService(db)
    job_id = job_service.acquire_lock(
        book_id=book_id,
        chapter_id=lock_chapter_id,
        job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
        total_items=total_items,
    )
    run_in_background_v2(_run_audio_text_review, job_id, book_id, chapter_id or "", guideline_id or "")
    return job_service.get_job(job_id)


def _run_audio_text_review(
    db: Session, job_id: str, book_id: str, chapter_id: str, guideline_id: str = "",
):
    from book_ingestion_v2.services.audio_text_review_service import AudioTextReviewService
    job_service = ChapterJobService(db)
    try:
        service = AudioTextReviewService(db)
        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(TeachingGuideline.id == guideline_id).first()
            result = service.review_guideline(guideline) if guideline else {"failed": 1, "errors": ["guideline not found"]}
        else:
            result = service.review_chapter(book_id, chapter_id or None, job_service=job_service, job_id=job_id)
        final_status = "completed" if result.get("failed", 0) == 0 else "completed_with_errors"
        job_service.release_lock(job_id, status=final_status, detail=json.dumps(result))
    except Exception as e:
        logger.error(f"Audio text review job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


@router.get("/audio-review-jobs/latest", response_model=Optional[ProcessingJobResponse])
def get_latest_audio_review_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None),
    guideline_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Mirrors /explanation-jobs/latest for audio text review job scope."""
    # same scope resolution as other job lookup endpoints
    ...
```

### 2.7 Stage-6 soft guardrail

Modify the existing `POST /generate-audio` in `sync_routes.py` to check for a prior completed review job for the same scope. When missing and the admin hasn't set `confirm_skip_review=true`, return a 409 with a descriptive detail so the frontend can show a confirm dialog.

```python
@router.post("/generate-audio", ...)
def generate_audio(
    book_id: str,
    chapter_id: Optional[str] = Query(None),
    guideline_id: Optional[str] = Query(None),
    confirm_skip_review: bool = Query(False, description="Skip soft guardrail that requires a prior audio text review job"),
    db: Session = Depends(get_db),
):
    # (existing scoping logic)

    # NEW: soft guardrail
    if not confirm_skip_review:
        latest_review = ChapterJobService(db).get_latest_by_type(
            book_id=book_id, chapter_id=lock_chapter_id,
            job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
        )
        if latest_review is None or latest_review.status not in ("completed", "completed_with_errors"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "no_audio_review",
                    "message": "No completed audio text review job found for this scope. Run audio review first, or pass confirm_skip_review=true to skip.",
                    "requires_confirmation": True,
                },
            )
    # (existing job lock + background dispatch)
```

**Deviation from the PRD's original "HTTP 200 with warning flag":** we use HTTP 409 instead because it fits FastAPI/HTTPException idioms; the frontend dialog reads the `requires_confirmation: true` flag from the response detail and re-calls with `confirm_skip_review=true`. Same UX, cleaner backend semantics.

`ChapterJobService.get_latest_by_type` is a thin addition mirroring existing `get_latest_job` but filtered by `job_type`. Place in `chapter_job_service.py`.

### 2.8 Frontend changes

#### `adminApiV2.ts`

```typescript
export async function generateAudioReview(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-audio-review${qs}`,
    { method: 'POST' }
  );
}

export async function getLatestAudioReviewJob(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2 | null> {
  // mirrors getLatestExplanationJob
}

// Extend generateAudio to support the soft-guardrail confirm flow:
export async function generateAudio(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; confirmSkipReview?: boolean },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.confirmSkipReview) params.set('confirm_skip_review', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(`/admin/v2/books/${bookId}/generate-audio${qs}`, { method: 'POST' });
}
```

#### `BookV2Detail.tsx`

- Add a `[Review audio]` button next to the existing `[Audio]` button on each chapter row.
- Click handler calls `generateAudioReview(id, { chapterId: ch.id })`, polls via the same `startJobPolling` pattern.
- Modify existing `handleGenerateAudio` to catch 409-with-`requires_confirmation`; when caught, open a confirm dialog ("No audio text review has run for this chapter. Proceed anyway?"), and on confirm re-call with `confirmSkipReview: true`.

```tsx
const handleGenerateAudio = async (ch: ChapterResponseV2) => {
  if (!id) return;
  try {
    const job = await generateAudio(id, { chapterId: ch.id });
    setAudioJobs(prev => ({ ...prev, [ch.id]: job }));
    startAudioPolling(ch.id);
  } catch (err: any) {
    if (err?.status === 409 && err?.detail?.code === "no_audio_review") {
      const ok = confirm(
        "No audio text review has run for this chapter. The MP3s will be synthesized on unreviewed text. Proceed anyway?"
      );
      if (ok) {
        const job = await generateAudio(id, { chapterId: ch.id, confirmSkipReview: true });
        setAudioJobs(prev => ({ ...prev, [ch.id]: job }));
        startAudioPolling(ch.id);
      }
    } else {
      setError(err instanceof Error ? err.message : 'Audio generation failed');
    }
  }
};
```

#### `ExplanationAdmin.tsx`

Add a per-topic `[Review audio]` button alongside existing per-topic actions, scoped by `guidelineId`. Same pattern as chapter-level.

### 2.9 Tests

`llm-backend/tests/unit/test_audio_text_review.py`:

1. **`test_review_card_returns_empty_revisions_for_clean_card`** — mock LLM returns `CardReviewOutput(card_idx=1, revisions=[])`; assert `_apply_revisions` is a no-op; card unchanged.
2. **`test_review_card_applies_symbol_leak_fix`** — mock LLM returns a revision changing `"5+3=8"` → `"five plus three equals eight"`; assert line's `audio` updated and `audio_url` cleared.
3. **`test_apply_revisions_clears_audio_url_only_on_changed_lines`** — card with 3 lines (2 with `audio_url` set); reviewer revises line 1 only; assert line 1 has `audio_url=None`, line 2 still has its URL, line 3 unchanged.
4. **`test_validate_revision_drops_banned_patterns`** — construct revisions with `revised_audio` containing `**bold**`, `x=5`, emoji; assert each returns `False` from `_validate_revision`.
5. **`test_apply_revisions_drops_on_drift`** — mock reviewer output has `original_audio="old text"` but card line's audio is actually `"other text"`; assert revision is NOT applied (drift guard).
6. **`test_review_card_returns_none_on_llm_error`** — mock LLM raises `LLMServiceError`; assert `_review_card` returns `None`; assert `_review_variant` continues with remaining cards.
7. **`test_check_in_revision_applies_to_audio_text_field`** — mock LLM returns revision with `kind="check_in"`, `line_idx=None`; assert card's top-level `audio_text` is updated (not `lines[].audio`).
8. **`test_stage_snapshots_capture_revisions`** — run `_review_variant` with a stage_collector; assert entries have `stage="audio_text_review"`, `revisions_proposed` count matches, `revisions_applied` count matches.

Mock pattern: `unittest.mock.patch` on `LLMService.call` and `LLMService.parse_json_response`, matching existing test style in `test_check_in_enrichment.py`.

**Manual verification steps:**
1. Ingest / sync a known test chapter with defective audio text (handcrafted fixture with `"5+3=8"`).
2. Click `[Review audio]` on the chapter in BookV2Detail.
3. Poll job → completed; open stage viewer; confirm `revised_audio="five plus three equals eight"` with reason.
4. Click `[Audio]` (stage 6). Confirm no soft guardrail since review is complete.
5. Check S3: only lines with revised audio have new MP3s (by timestamp); other MP3s unchanged.

### 2.10 Phase 1 implementation order

Natural commit boundaries:

| Commit | What | Depends on |
|---|---|---|
| `feat: add V2JobType.AUDIO_TEXT_REVIEW constant` | `constants.py` | — |
| `feat: add audio text review prompt files` | `audio_text_review.txt`, `_system.txt` | — |
| `feat: add AudioTextReviewService` | new service file | Prompts |
| `feat: wire /generate-audio-review endpoint + background task` | `sync_routes.py` | Service |
| `feat: wire /audio-review-jobs/latest endpoint` | `sync_routes.py` | Endpoint |
| `feat: stage-6 soft guardrail + chapter_job_service.get_latest_by_type` | `sync_routes.py`, `chapter_job_service.py` | — |
| `refactor: remove inline MP3 synth from stage 5` | `explanation_generator_service.py` | Review endpoint working end-to-end |
| `feat: audio review frontend — API client + BookV2Detail trigger + soft-guardrail dialog` | frontend files | Backend endpoints |
| `feat: audio review per-topic trigger on ExplanationAdmin` | `ExplanationAdmin.tsx` | API client |
| `test: audio text review service unit tests` | new test file | Service |
| `docs: update principles + technical docs for new pipeline ordering` | docs | All backend work |

**Refactor is intentionally last in the backend sequence** — we don't want stage 5 to break production before the reviewer is available end-to-end. Admin can manually run `/generate-audio` (existing endpoint) to cover the gap.

---

## 3. Phase 2 — Visual Rendering Review

### 3.1 Files changed

#### Backend

| File | Change |
|------|--------|
| `llm-backend/book_ingestion_v2/services/visual_render_harness.py` | **NEW** — Playwright wrapper: render code, extract bounds, screenshot |
| `llm-backend/book_ingestion_v2/services/visual_overlap_detector.py` | **NEW** — pure-Python utility: bounds list → overlap report |
| `llm-backend/book_ingestion_v2/services/animation_enrichment_service.py` | Add post-refine gate calling render harness + overlap detector; one extra targeted refine round; set `layout_warning` on retry exhaustion |
| `llm-backend/book_ingestion_v2/prompts/visual_code_generation.txt` | Add ONE general rule (no templates) about crowded adjacent elements |
| `llm-backend/book_ingestion_v2/prompts/visual_code_review_refine.txt` | Add `{collision_report}` placeholder for the targeted refine round |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | Extend `/visual-status` response with `layout_warning_count` per topic |
| `llm-backend/tests/unit/test_visual_overlap_detector.py` | **NEW** — pure-python unit tests |
| `llm-backend/tests/integration/test_visual_render_harness.py` | **NEW** — integration test that actually drives Playwright |

#### Frontend

| File | Change |
|------|--------|
| `llm-frontend/src/features/admin/pages/VisualRenderPreview.tsx` | **NEW** — admin-only preview route that boots Pixi directly (no sandboxed iframe), exposes `window.__pixiApp`, signals ready via `data-pixi-state` attribute |
| `llm-frontend/src/App.tsx` | Add route `/admin/visual-render-preview` |
| `llm-frontend/src/components/VisualExplanation.tsx` | Render subdued chip when `visual.layout_warning === true` |
| `llm-frontend/src/api.ts` | Extend `VisualExplanation` type with `layout_warning?: boolean` |
| `llm-frontend/src/features/admin/pages/TopicsAdmin.tsx` | Render badge on topics with `layout_warning_count > 0` |

#### Docs

| File | Change |
|------|--------|
| `docs/technical/book-guidelines.md` | Add "Visual Rendering Review" subsection inside the Visual Enrichment section |

### 3.2 Preventive prompt change

`visual_code_generation.txt` — add ONE bullet to the existing rules section. Exact wording (to be tuned, but scoped):

> **Avoid crowding.** When positioning multiple adjacent text elements (group labels, axis ticks, legend items), ensure horizontal spacing. If the visible label would be wider than its region, use shorter wording (e.g. `"Lakhs"` instead of `"Lakhs Period"`) or move the label to a separate line below the region.

No templates. No prescriptive layouts. Revert is one-line if quality regresses.

### 3.3 New admin preview route

`llm-frontend/src/features/admin/pages/VisualRenderPreview.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Admin-only preview route for the Visual Rendering Review pipeline.
 *
 * Differences from student-facing VisualExplanation.tsx:
 * - Mounts Pixi directly on the page (no sandboxed iframe) so Playwright
 *   can call window.__pixiApp.stage from page.evaluate().
 * - Signals render state via a `data-pixi-state` attribute on the canvas container
 *   for Playwright to await.
 *
 * Admin-only — relies on route-level auth. Never exposed to students.
 */
export default function VisualRenderPreview() {
  const [params] = useSearchParams();
  const code = atob(params.get('code') || '');
  const outputType = params.get('output_type') || 'static_visual';
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const canvasRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    let app: any;
    (async () => {
      try {
        // @ts-ignore
        const PIXI = (await import('pixi.js')).default ?? (await import('pixi.js'));
        app = new PIXI.Application();
        await app.init({ width: 500, height: 350, backgroundColor: 0x1a1a2e, antialias: true });
        canvasRef.current!.appendChild(app.canvas);
        (window as any).__pixiApp = app;
        const fn = new Function('app', 'PIXI', code);
        fn(app, PIXI);
        // For animated visuals, wait for the 2+s end-state pause to settle.
        const waitMs = outputType === 'animated_visual' ? 8000 : 500;
        setTimeout(() => setState('ready'), waitMs);
      } catch (e: any) {
        setState('error');
        (window as any).__pixiError = e?.message || String(e);
      }
    })();
    return () => { app?.destroy?.(); };
  }, [code, outputType]);

  return <div ref={canvasRef} data-pixi-state={state} style={{ width: 500, height: 350 }} />;
}
```

**Deviation:** student-facing `VisualExplanation.tsx` uses a sandboxed iframe for XSS mitigation. The admin preview route mounts Pixi directly because (a) Playwright can't easily reach into a sandboxed iframe's `window` object, and (b) admin is running trusted LLM output in their own browser session. The Pixi rendering itself is identical — only the security wrapper differs. Document this trade-off in the file header.

Add route to `App.tsx`:

```tsx
<Route path="/admin/visual-render-preview" element={<VisualRenderPreview />} />
```

### 3.4 Render harness

`llm-backend/book_ingestion_v2/services/visual_render_harness.py`:

```python
"""Render Pixi code in headless Chrome, extract bounds + screenshot.

Uses playwright-python. Points at http://localhost:3000/admin/visual-render-preview
(the admin preview route). Fidelity-close-enough to the student-facing sandboxed
iframe: Pixi rendering is identical, only the security wrapper differs.
"""
import base64
import logging
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

FRONTEND_URL = "http://localhost:3000"
RENDER_TIMEOUT_MS = 30_000


class ObjectBounds(BaseModel):
    type: Literal["Text", "Graphics", "Container", "Sprite"]
    text: Optional[str] = None          # populated for Text
    bounds: dict                         # {x, y, width, height}
    alpha: float = 1.0
    dense: bool = False                  # Graphics w/ non-transparent fill


class RenderResult(BaseModel):
    ok: bool
    bounds: list[ObjectBounds] = []
    screenshot_path: Optional[str] = None
    error: Optional[str] = None


class VisualRenderHarness:
    """Per-call: boot browser, render code, extract bounds, screenshot. Serial; not thread-safe."""

    def render(
        self,
        pixi_code: str,
        *,
        output_type: Literal["static_visual", "animated_visual"] = "static_visual",
        screenshot_path: Optional[Path] = None,
    ) -> RenderResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return RenderResult(ok=False, error="playwright not installed")

        encoded = base64.b64encode(pixi_code.encode()).decode()
        url = f"{FRONTEND_URL}/admin/visual-render-preview?code={encoded}&output_type={output_type}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 800, "height": 600})
                page = context.new_page()
                page.goto(url, timeout=RENDER_TIMEOUT_MS)
                # Wait for preview component to signal ready
                page.wait_for_selector('[data-pixi-state="ready"]', timeout=RENDER_TIMEOUT_MS)

                # Walk the Pixi display tree
                raw_bounds = page.evaluate("""() => {
                  const app = window.__pixiApp;
                  if (!app) return [];
                  const results = [];
                  function walk(obj) {
                    if (!obj.visible) return;
                    const b = obj.getBounds();
                    const entry = {
                      type: obj.constructor.name,
                      alpha: obj.alpha,
                      bounds: { x: b.x, y: b.y, width: b.width, height: b.height },
                    };
                    if (obj.constructor.name === 'Text') entry.text = obj.text;
                    if (obj.constructor.name === 'Graphics') {
                      // Dense if any fill is non-transparent
                      entry.dense = (obj.fillStyle?.alpha ?? 1) > 0;
                    }
                    results.push(entry);
                    (obj.children || []).forEach(walk);
                  }
                  app.stage.children.forEach(walk);
                  return results;
                }""")

                if screenshot_path:
                    page.locator('[data-pixi-state="ready"]').screenshot(path=str(screenshot_path))

                context.close()
                browser.close()

                bounds = [ObjectBounds(**b) for b in raw_bounds]
                return RenderResult(ok=True, bounds=bounds, screenshot_path=str(screenshot_path) if screenshot_path else None)
        except Exception as e:
            logger.exception(f"Render harness failed: {e}")
            return RenderResult(ok=False, error=str(e))
```

**`playwright-python`** goes in `requirements.txt`. Install via `pip install playwright && playwright install chromium`. Document in `docs/technical/dev-workflow.md`.

**Dependency:** requires frontend dev server running on `localhost:3000`. Document this as a prerequisite for running visual enrichment jobs. If the harness fails to reach the URL, the post-refine gate logs a warning and passes through the original code WITHOUT setting `layout_warning=true` (don't false-flag when the check itself failed).

### 3.5 Overlap detector

`llm-backend/book_ingestion_v2/services/visual_overlap_detector.py`:

```python
"""Pure-python IoU overlap detection over a bounds list.

No browser, no Playwright — just geometry.
"""
from typing import Optional
from pydantic import BaseModel

from book_ingestion_v2.services.visual_render_harness import ObjectBounds

DEFAULT_IOU_THRESHOLD = 0.05


class OverlapPair(BaseModel):
    a_index: int
    b_index: int
    a_label: str
    b_label: str
    iou: float
    a_bounds: dict
    b_bounds: dict


def detect_overlaps(
    bounds: list[ObjectBounds],
    *,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> list[OverlapPair]:
    """Return text-on-text and text-on-dense-graphics overlaps above the IoU threshold."""
    candidates: list[int] = []
    for i, obj in enumerate(bounds):
        if obj.type == "Text":
            candidates.append(i)
        elif obj.type == "Graphics" and obj.dense:
            candidates.append(i)

    overlaps: list[OverlapPair] = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = bounds[candidates[i]], bounds[candidates[j]]
            # Only check if at least one is Text (don't flag graphics-on-graphics)
            if a.type != "Text" and b.type != "Text":
                continue
            iou = _iou(a.bounds, b.bounds)
            if iou > iou_threshold:
                overlaps.append(OverlapPair(
                    a_index=candidates[i],
                    b_index=candidates[j],
                    a_label=a.text or f"{a.type}",
                    b_label=b.text or f"{b.type}",
                    iou=round(iou, 3),
                    a_bounds=a.bounds,
                    b_bounds=b.bounds,
                ))
    return overlaps


def _iou(a: dict, b: dict) -> float:
    """Intersection-over-union of two axis-aligned rects. Uses min(area_a, area_b) in denominator,
    so a label fully inside a box returns IoU=1.0."""
    ax1, ay1, aw, ah = a["x"], a["y"], a["width"], a["height"]
    bx1, by1, bw, bh = b["x"], b["y"], b["width"], b["height"]
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    smaller = min(aw * ah, bw * bh)
    return intersection / smaller if smaller > 0 else 0.0


def format_collision_report(overlaps: list[OverlapPair]) -> str:
    """Format overlaps as a natural-language prompt fragment for the targeted refine round."""
    if not overlaps:
        return "(no overlaps detected)"
    lines = []
    for o in overlaps:
        a_desc = f"Text '{o.a_label}'" if o.a_label else f"object[{o.a_index}]"
        b_desc = f"Text '{o.b_label}'" if o.b_label else f"object[{o.b_index}]"
        lines.append(
            f"- {a_desc} at ({o.a_bounds['x']:.0f},{o.a_bounds['y']:.0f},{o.a_bounds['width']:.0f}w,{o.a_bounds['height']:.0f}h) "
            f"overlaps {b_desc} at ({o.b_bounds['x']:.0f},{o.b_bounds['y']:.0f},{o.b_bounds['width']:.0f}w,{o.b_bounds['height']:.0f}h) "
            f"— IoU {o.iou}"
        )
    return "\n".join(lines)
```

### 3.6 Integration into stage 7

`animation_enrichment_service.py` — modify `_enrich_variant` (lines 281–287 area) to add the post-refine gate just before storing `visual_explanation`:

```python
# (existing review-refine loop, lines 261-279)
for round_num in range(1, review_rounds + 1):
    ...

# NEW: post-refine overlap gate
pixi_code, layout_warning = self._overlap_gate(
    pixi_code, decision, card, guideline,
)

card["visual_explanation"] = {
    "output_type": decision.decision,
    "title": decision.title,
    "visual_summary": decision.visual_summary,
    "visual_spec": decision.visual_spec,
    "pixi_code": pixi_code,
    "layout_warning": layout_warning,   # NEW
}
```

Add `_overlap_gate` method:

```python
def _overlap_gate(
    self,
    pixi_code: str,
    decision,
    card: dict,
    guideline,
) -> tuple[str, bool]:
    """Render → detect overlap → if overlap, one extra targeted refine round → re-check.

    Returns (final_code, layout_warning). layout_warning=True means overlap persists
    after the extra round; we store the code anyway.
    """
    from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
    from book_ingestion_v2.services.visual_overlap_detector import detect_overlaps, format_collision_report

    harness = VisualRenderHarness()
    result = harness.render(pixi_code, output_type=decision.decision)
    if not result.ok:
        logger.warning(f"Render harness failed for card {decision.card_idx}: {result.error} — skipping overlap check, not flagging")
        return pixi_code, False   # don't false-flag when harness itself fails

    overlaps = detect_overlaps(result.bounds)
    if not overlaps:
        return pixi_code, False

    # One extra targeted refine round with collision report
    collision_report = format_collision_report(overlaps)
    logger.info(f"Overlap detected on card {decision.card_idx}: {len(overlaps)} pairs; running targeted refine")
    refined = self._review_and_refine_code(
        decision, card, guideline, pixi_code,
        collision_report=collision_report,   # NEW arg
    )
    if not refined or not self._validate_code(refined):
        return pixi_code, True

    # Re-render, re-check
    result2 = harness.render(refined, output_type=decision.decision)
    if not result2.ok:
        return refined, True   # rendered once clean, can't verify fix; mark warning

    overlaps2 = detect_overlaps(result2.bounds)
    if overlaps2:
        logger.info(f"Overlap persists on card {decision.card_idx} after targeted refine; storing with layout_warning=true")
        return refined, True

    return refined, False
```

Extend `_review_and_refine_code` to accept an optional `collision_report` and append it to the prompt when provided:

```python
def _review_and_refine_code(
    self,
    decision: VisualDecision,
    card: dict,
    guideline: TeachingGuideline,
    current_code: str,
    *,
    collision_report: Optional[str] = None,
) -> Optional[str]:
    ...
    prompt = _REVIEW_REFINE_PROMPT.replace(..., current_code)
    prompt = prompt.replace("{collision_report}", collision_report or "(none)")
    ...
```

And add `{collision_report}` placeholder to `visual_code_review_refine.txt`, e.g. inside the checklist:

> **4b. Specific overlaps detected** — if a collision report is provided below, fix these overlapping pairs specifically:
>
> {collision_report}

### 3.7 Student-facing chip

`llm-frontend/src/components/VisualExplanation.tsx` — render a subdued chip when `visual.layout_warning === true`. Placement: small line below the canvas, muted color, small font.

```tsx
{visual.layout_warning && (
  <div style={{
    fontSize: 12, color: '#888', marginTop: 6, fontStyle: 'italic',
    textAlign: 'center', padding: '4px 8px',
  }}>
    Note: this picture might have some overlap — we're improving it.
  </div>
)}
```

Extend the `VisualExplanation` type in `api.ts`:

```typescript
export interface VisualExplanation {
  output_type: 'static_visual' | 'animated_visual' | 'no_visual';
  title: string;
  visual_summary: string;
  visual_spec: string;
  pixi_code: string;
  layout_warning?: boolean;   // NEW
  // ... any existing fields
}
```

### 3.8 Admin observability

Extend `/visual-status` response in `sync_routes.py` to compute and return `layout_warning_count` per topic. Requires walking `cards_json` for each variant:

```python
def _count_layout_warnings(explanation: TopicExplanation) -> int:
    return sum(
        1 for card in (explanation.cards_json or [])
        if (card.get("visual_explanation") or {}).get("layout_warning") is True
    )
```

Update `TopicsAdmin.tsx` to render a small amber badge on topic rows where `layout_warning_count > 0`.

### 3.9 Tests

#### Pure-python unit tests (`test_visual_overlap_detector.py`)

1. **`test_no_overlap_when_bounds_disjoint`** — two Text objects far apart; assert `detect_overlaps` returns `[]`.
2. **`test_text_on_text_overlap_detected`** — two Text objects with 50% bbox overlap; assert returned pair, IoU > threshold.
3. **`test_text_on_dense_graphics_detected`** — Text inside a dense Graphics rect; assert overlap reported.
4. **`test_text_on_transparent_graphics_not_flagged`** — Text inside a Graphics with `dense=False`; assert no overlap.
5. **`test_graphics_on_graphics_not_flagged`** — two dense Graphics overlapping; assert no overlap (we only flag pairs with at least one Text).
6. **`test_threshold_configurable`** — 3% overlap is flagged at threshold 0.02, not at default 0.05.
7. **`test_format_collision_report_empty`** — empty list returns "(no overlaps detected)".
8. **`test_format_collision_report_includes_coords`** — formatted output contains IoU value and bbox coords.

#### Integration tests (`test_visual_render_harness.py`)

Require localhost frontend + Playwright installed. Skip if `SKIP_RENDER_TESTS=1` or frontend not reachable.

1. **`test_render_clean_visual_returns_bounds`** — render a known-clean Pixi code sample with 3 well-spaced text labels; assert `ok=True`, 3 Text objects in bounds, `detect_overlaps` returns `[]`.
2. **`test_render_overlapping_visual_detects_collision`** — render the place-value-periods reproduction code; assert `detect_overlaps` returns ≥ 1 pair with the colliding labels.
3. **`test_render_timeout_on_bad_code`** — render code that throws at runtime; assert `ok=False` within 30s.
4. **`test_render_harness_unreachable_frontend`** — point harness at `http://localhost:9999`; assert `ok=False` with clear error; no false positives.

#### Stage 7 end-to-end

In a manual QA script (not automated): run stage 7 on a fixture topic known to produce overlapping visuals; assert that in the resulting `cards_json`, either the visual has `layout_warning=false` (LLM fixed it) or `layout_warning=true` (flag set after retry exhaustion). Never silently stores overlap without a flag.

### 3.10 Phase 2 implementation order

| Commit | What | Depends on |
|---|---|---|
| `feat: visual_overlap_detector pure-python utility + tests` | new file + unit tests | — |
| `feat: VisualRenderPreview admin route` | new page + App.tsx route | — |
| `feat: visual_render_harness (Playwright wrapper)` | new service | Admin preview route running |
| `chore: add playwright to requirements; install docs` | `requirements.txt`, dev-workflow.md | — |
| `feat: stage 7 post-refine gate + layout_warning flag` | `animation_enrichment_service.py`, prompt update | Harness + detector |
| `feat: add one general rule to visual_code_generation prompt` | prompt file | — |
| `feat: student-facing layout_warning chip + type extension` | `VisualExplanation.tsx`, `api.ts` | Backend writes flag |
| `feat: /visual-status layout_warning_count + admin badge` | `sync_routes.py`, `TopicsAdmin.tsx` | Backend writes flag |
| `test: visual render harness integration tests` | new file | Harness |
| `docs: Visual Rendering Review section in book-guidelines.md` | docs | All backend work |

---

## 4. Cross-cutting

### 4.1 LLM config

Add a row to the seed data or admin-docs for LLM config keys:

| Key | Fallback | Model recommendation |
|---|---|---|
| `audio_text_review` | `explanation_generator` | Haiku or Sonnet; low reasoning effort (narrow task) |

### 4.2 Documentation updates

1. `docs/principles/book-ingestion-pipeline.md` — renumber stages:
   - 6 becomes Audio Text Review (NEW)
   - Visual Enrichment stays at 7 (post-refine gate is an internal sub-step)
   - Check-in Enrichment stays at 8
   - Practice Bank stays at 9
   - Audio Synthesis (was stage 6) moves to stage 10 at the tail

2. `docs/technical/book-guidelines.md`:
   - New "Audio Text Review" section parallel to "Audio Generation (TTS)"
   - New "Visual Rendering Review" subsection inside "Visual Enrichment (PixiJS)"
   - Update pipeline diagram
   - Add LLM config key row for `audio_text_review`

3. `docs/technical/ai-agent-files.md` — no changes (no new agent files).

### 4.3 Rollback plans

**Phase 1:**
- Revert the stage-5 inline-MP3 removal (one-line revert).
- Job type + endpoints remain harmless if admin doesn't trigger them.
- Stage-6 soft guardrail is a single check block — one-function revert.

**Phase 2:**
- Set post-refine gate to always skip (`return pixi_code, False` at top of `_overlap_gate`).
- Revert preventive prompt rule.
- Hide student-facing chip by conditionally returning null.
- Three tiny reverts.

### 4.4 Deployment considerations

Ingestion pipeline runs on localhost per `feedback_ingestion_localhost.md`. No AWS changes for Phase 1. For Phase 2, Playwright + Chromium must be installed on the admin machine (`playwright install chromium`) and frontend dev server must be running when visual enrichment jobs execute — documented in dev-workflow.md.

---

## 5. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stage-5 regeneration path breaks after removing inline MP3 call | Low | High | Integration test + manual verification before merge; commit order puts refactor last |
| Audio reviewer over-rewrites (touches clean lines) | Medium | Medium | Gold-set success criterion; surgical revisions format makes this observable per card |
| Validator banned-patterns list is incomplete | Medium | Low | Easy to extend; logs drops; no data loss |
| Playwright flakiness (localhost unreachable, browser hang) | Medium | Medium | 30s timeout; render failure doesn't set warning flag; pipeline continues |
| Preventive prompt degrades visual quality | Low | Medium | Smoke test 10 existing topics; single-line revert available |
| `getBounds()` returns unexpected values for Container/Sprite | Low | Low | Treat only Text + dense-Graphics as overlap candidates; other types ignored |
| Admin forgets to start frontend dev server before running stage 7 | High | Low | Clear error message from harness; documented in dev-workflow.md |
| XSS risk in admin preview route (direct Pixi mount, no sandbox) | Low | Low | Admin-only route behind existing admin auth; admin runs trusted LLM output in their own session |

---

## 6. Out of Scope (explicit)

- STT loopback verification of MP3s (future opt-in phase)
- Vision LLM review of rendered visuals (future phase)
- Auto-chaining of stages
- Backfill automation for existing books
- Cross-card flow review for audio (stays per-card)
- Audio reshape (split/merge/drop lines)
- Display text edits
- New agent files
- Visual review for check-in card visuals (currently check-ins don't carry `visual_explanation`)
