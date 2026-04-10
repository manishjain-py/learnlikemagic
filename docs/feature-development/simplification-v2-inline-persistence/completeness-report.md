# Completeness Report: Simplification v2

## Database Changes
- [x] `student_topic_cards` table — ORM model in entities.py, UNIQUE(user_id, guideline_id, variant_key), explanation_id stale guard
- [x] Migration — handled by Base.metadata.create_all()

## Backend — Repository
- [x] `student_topic_cards_repository.py` — get, get_most_recent, upsert (no independent commit), delete_stale

## Backend — Prompt + Agent
- [x] `SIMPLIFY_CARD_PROMPT` — returns lines[] instead of flat content
- [x] `SimplifiedCardOutput` + `SimplifiedCardLine` models — lines field, content/audio_text derived

## Backend — Service
- [x] `simplify_card()` write path — upserts to student_topic_cards after session persist
- [x] `simplify_card()` response — append_to_card instead of insert_card
- [x] `create_new_session()` read path — checks for saved variant preference
- [x] `create_new_session()` pre-load — attaches saved simplifications to cards
- [x] `_switch_variant_internal()` — restores/clears saved simplifications for target variant

## Backend — API
- [x] Replay merge — attaches simplifications inline (card.simplifications[]) instead of inserting separate cards

## Frontend — Logic
- [x] Card index fix — removed -1 offset, uses currentSlideIdx directly
- [x] ExplanationCard.simplifications type added
- [x] handleSimplifyCard — append_to_card handler, no splice, no index change
- [x] simplifyJustAdded state for typewriter control
- [x] Auto-scroll to new section
- [x] Slide type includes simplifications field

## Frontend — Rendering
- [x] Inline simplification sections with separator text
- [x] TypewriterMarkdown for each simplification (animated for new, skipped for pre-loaded)
- [x] VisualExplanation for each simplification
- [x] Loading skeleton with shimmer animation

## Frontend — CSS
- [x] .inline-simplification, .simplification-separator styles
- [x] .skeleton-line + shimmer animation
- [x] Removed stale .simplify-options CSS

## Tests
- [x] 15 existing tests updated for new response format
- [x] test_student_topic_cards_upsert (create + append)
- [x] test_student_topic_cards_per_variant (separate rows)
- [x] test_student_topic_cards_stale_explanation (reset on mismatch)
- [x] All 21 tests passing

## Summary
12/12 implementation steps complete. 21/21 tests passing.
