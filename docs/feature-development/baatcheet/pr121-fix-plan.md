# Baatcheet — PR #121 Fix Plan

**Date:** 2026-04-25
**PR:** https://github.com/manishjain-py/learnlikemagic/pull/121
**Branch:** `pr121-review` (merging into `feat/baatcheet-conversational-teach-me`)
**Source:** consolidates Claude Code review (`claude-code-review-feedback.md`) and Codex review (`codex-code-review-feedback.md`).

Both reviewers independently caught the same #1 blocker (`Session.teach_me_mode` ORM mismatch). Codex caught two additional critical UX breakages (auto-play, missing CTA). Claude Code caught a placeholder leak (`{topic_name}`) and a status-tile blind spot. All four together break the V1 ship; the rest can defer.

---

## Critical (must fix before merge)

### F1. `Session` ORM model is missing `teach_me_mode` → entire chooser 500s

**Files:**
- `llm-backend/shared/models/entities.py:45-69`
- `llm-backend/tutor/services/session_service.py:472, 784`
- `llm-backend/db.py` (new backfill helper)

**Symptom:** `GET /sessions/teach-me-options` raises `AttributeError` at SQLAlchemy filter construction. Sub-chooser breaks. Every Baatcheet session row carries column-default `'explain'` regardless of actual submode → `/teach-me-options` filter never finds Baatcheet sessions → resume CTA never shows for Baatcheet.

**Changes:**

1. Add column to ORM `Session` class (after `is_paused`):
   ```python
   teach_me_mode = Column(String, nullable=True, default='explain')
   ```

2. Persist on insert in `_persist_session` (line 472):
   ```python
   db_record = SessionModel(
       ...
       mode=session.mode,
       teach_me_mode=session.teach_me_mode if session.mode == "teach_me" else None,
       ...
   )
   ```

3. Persist on CAS update in `_persist_session_state` (line 784):
   ```python
   .values(
       ...
       mode=session.mode,
       teach_me_mode=session.teach_me_mode if session.mode == "teach_me" else None,
       ...
   )
   ```

4. Add a backfill UPDATE in `_apply_sessions_teach_me_mode_column` after the column-add step — derive `teach_me_mode` from `state_json` for rows already created on this branch:
   ```sql
   UPDATE sessions
   SET teach_me_mode = state_json::jsonb->>'teach_me_mode'
   WHERE mode = 'teach_me'
     AND state_json::jsonb->>'teach_me_mode' IS NOT NULL
     AND (teach_me_mode IS NULL OR teach_me_mode = 'explain');
   ```

**Verify:**
- `python -c "from shared.models.entities import Session; print(Session.teach_me_mode)"` returns a column object, not AttributeError.
- Create paused Explain + paused Baatcheet for same `(user, guideline)` → both coexist (PRD §FR-4).
- `GET /sessions/teach-me-options?guideline_id=...` returns 200 with both submode states.

---

### F2. Welcome card never auto-plays + personalized audio race

**File:** `llm-frontend/src/components/teach/BaatcheetViewer.tsx:60-94, 110-123`

**Symptom:** `useState<Set<number>>(() => new Set([initialCardIdx]))` seeds card 0 as already-visited. Playback effect line 94 bails on `if (!isFirstVisit) return;`. The welcome card's TTS never plays. Even if it did, `usePersonalizedAudio` is async — the playback effect can run before the blob exists, line 123 silently skips, never retries.

**Changes:**

1. Remove the `initialCardIdx` from the initial `visited` set:
   ```tsx
   const [visited, setVisited] = useState<Set<number>>(() => new Set());
   ```
   The post-effect at lines 158-165 already marks-visited after first playback; that's the right place.

2. Make the playback effect await blob availability for personalized cards. Either:
   - **Option A (cheap):** poll `getClientAudioBlob` for up to ~3s before falling through:
     ```tsx
     if (currentCard.includes_student_name) {
       blob = getClientAudioBlob(personalizedAudioKey(currentCard.card_id, lineIdx));
       if (!blob) {
         for (let i = 0; i < 30 && !blob; i++) {
           await new Promise(r => setTimeout(r, 100));
           if (cancelled) return;
           blob = getClientAudioBlob(personalizedAudioKey(currentCard.card_id, lineIdx));
         }
       }
     }
     ```
   - **Option B (cleaner):** expose a `personalizedAudioReady: Set<string>` from `usePersonalizedAudio` and gate the playback effect on it.

   Option A is the lower-risk V1 fix; Option B is the right shape for the eventual ChatSession refactor.

**Verify:** start a fresh Baatcheet session → welcome card audio plays automatically with the student's name materialized.

---

### F3. No "Let's Practice" CTA on Baatcheet completion (PRD §FR-35)

**Files:**
- `llm-frontend/src/components/teach/BaatcheetViewer.tsx:276-295`
- `llm-frontend/src/pages/ChatSession.tsx:1307-1318`

**Symptom:** On the summary card the Next button is disabled (`cardIdx >= totalCards - 1`). No "Let's Practice" affordance. ChatSession's `dialogue_phase` early-return bypasses Explain's existing completion panel. Student dead-ends.

**Changes:**

1. Pass an `onComplete` callback into `BaatcheetViewer` from ChatSession:
   ```tsx
   <BaatcheetViewer
     ...
     onComplete={() => setIsComplete(true)}
   />
   ```

2. In `BaatcheetViewer`, fire `onComplete` when summary becomes visible (alongside the existing `mark_complete` POST):
   ```tsx
   useEffect(() => {
     if (currentCard?.card_type === 'summary' && !completed) {
       setCompleted(true);
       persistProgress(cardIdx, true);
       onComplete?.();
     }
     ...
   }, [cardIdx]);
   ```

3. Keep the BaatcheetViewer-rendered carousel, but render the existing completion panel (Practice CTA + summary tile) above or below the viewer when `isComplete` flips. Reuse the same component path Explain uses.

Alternative: render the completion CTA inline inside BaatcheetViewer when `currentCard.card_type === 'summary'`. Less code shared with Explain but contained.

**Verify:** complete a Baatcheet dialogue → see the Practice CTA + summary tile, identical to Explain's completion behavior.

---

### F4. Audio synthesis status tile excludes dialogue clip counts

**File:** `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py:558-599`

**Symptom:** `_stage_audio_synthesis` only counts variant A clips. A topic with full variant A audio + missing dialogue audio reads `done`. Super-run's `stages_to_run_from_status` skips Stage 10 → dialogue cards ship without MP3s. PR description's claim ("the audio_synthesis tile reports both variant A and dialogue clip counts") is false.

**Change:** add a parallel sum over the dialogue (after the explanations loop, before the state derivation):

```python
from shared.repositories.dialogue_repository import DialogueRepository

dialogue = DialogueRepository(self.db).get_by_guideline_id(guideline_id)
if dialogue and dialogue.cards_json:
    dt, dw = AudioGenerationService.count_dialogue_audio_items(dialogue.cards_json)
    total_clips += dt
    clips_with_audio += dw
```

The `count_dialogue_audio_items` method already exists at `audio_generation_service.py:391` — just unused.

**Verify:** topic with full variant A audio + freshly generated dialogue (no MP3s yet) → audio_synthesis tile reads `ready` or `warning`, not `done`. Trigger super-run → Stage 10 fires → dialogue MP3s land in `audio/{guideline_id}/dialogue/...`.

---

## Should fix in V1 (real bugs, not blockers)

### F5. `{topic_name}` outside welcome card plays as literal "{topic_name}"

**Files:**
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_generation_system.txt:49`
- `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py:180-191` (validator)

**Symptom:** System prompt explicitly authorizes `{topic_name}` outside the welcome card ("can also appear; it is materialised at runtime"). But only `{student_name}`-flagged cards skip pre-rendering — `{topic_name}`-only cards get TTS'd verbatim. Audio plays "open-curly-brace topic-name close-curly-brace."

**Change (cheapest):** restrict `{topic_name}` to the welcome card. The welcome card is server-prepended anyway, so the LLM has no business emitting it elsewhere.

1. Drop line 49 of the system prompt or rewrite to:
   > `{topic_name}` is **only** allowed on the server-prepended welcome card. Never use it in the cards you produce.

2. Add a validator rule:
   ```python
   for li, line in enumerate(c.lines):
       for placeholder in ("{topic_name}",):
           if placeholder in line.audio or placeholder in line.display:
               issues.append(
                   f"card {c.card_idx} line {li}: '{placeholder}' is reserved for the "
                   f"welcome card (server-prepended) — remove from LLM-generated cards"
               )
   ```

**Verify:** validator catches a hand-crafted `{topic_name}` in a non-welcome card; pre-existing dialogues regenerate clean.

---

### F6. Banned audio patterns not enforced inside check-in fields

**File:** `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py:172-178, 196-209`

**Symptom:** `_BANNED_AUDIO_PATTERNS` (markdown bold, naked equals, emoji) is walked over `c.lines[i].audio` only. Check-in fields are checked only for `{student_name}`. Markdown / emoji can land in `check_in.audio_text`, `hint`, `success_message`, `reveal_text`, `statement` and get synthesized.

**Change:** extend the existing check-in walk (currently lines 196-209) to also run banned-pattern checks:

```python
if c.check_in:
    ci = c.check_in
    check_in_audio_fields = {
        "instruction": ci.instruction,
        "hint": ci.hint,
        "success_message": ci.success_message,
        "audio_text": ci.audio_text,
        "reveal_text": ci.reveal_text or "",
        "statement": ci.statement or "",
    }
    for field_name, field_text in check_in_audio_fields.items():
        if not field_text:
            continue
        if "{student_name}" in field_text:
            issues.append(
                f"card {c.card_idx}: '{{student_name}}' found inside check_in.{field_name} "
                f"— not allowed (V1 pre-renders check-in audio statically)"
            )
        for pat in _BANNED_AUDIO_PATTERNS:
            if pat.search(field_text):
                issues.append(
                    f"card {c.card_idx}: banned pattern in check_in.{field_name} "
                    f"(/{pat.pattern}/)"
                )
```

While there, validate `activity_type` against the 11 supported values from `CheckInDispatcher` so an unsupported shape never reaches the frontend.

**Verify:** validator catches `**bold**` in `check_in.audio_text` and `▶` in `check_in.hint`. Existing dialogues pass.

---

### F7. Opt-in audio review can't apply `check_in_text` revisions on dialogues

**Files:**
- `llm-backend/book_ingestion_v2/services/audio_text_review_service.py:343-362`
- `llm-backend/book_ingestion_v2/services/baatcheet_audio_review_service.py:79-126`

**Symptom:** `_apply_revisions` for `kind == "check_in_text"` drift-checks against top-level `card["audio_text"]`. Variant A check-in cards have that top-level field; dialogue check-in cards do not (audio lives inside `check_in.audio_text` only). Every `check_in_text` revision drift-fails. The advertised safety valve is a no-op for the most defect-prone field.

**Change:** in `BaatcheetAudioReviewService.review_guideline`, before invoking `_inner._review_card`, mirror `check_in.audio_text` to a temporary top-level `audio_text` on dialogue check-in cards. After `_apply_revisions`, strip the temporary field if untouched:

```python
def review_guideline(self, guideline, ...):
    ...
    for card in cards:
        # Mirror check_in audio for the drift guard
        if card.get("card_type") == "check_in" and card.get("check_in"):
            card["audio_text"] = card["check_in"].get("audio_text")

        try:
            card_output = self._inner._review_card(card, guideline)
            ...
            applied = self._inner._apply_revisions(card, valid)
            ...
        finally:
            # Drop the temporary mirror — the line apply path mirrored it back
            if card.get("card_type") == "check_in":
                card.pop("audio_text", None)
```

(The mirror back is already done by `_apply_revisions` line 357-362.)

**Verify:** generate a dialogue with intentionally awkward `check_in.audio_text`, run `POST /review-baatcheet-audio`, verify the LLM proposes a revision and `_apply_revisions` actually applies it (no drift-mismatch warning in logs).

---

## Pre-existing / parity gaps worth addressing

### F8. Coverage source / mastery_estimates mismatch (both modes)

**File:** `llm-backend/tutor/services/session_service.py:611-637`, `tutor/models/session_state.py:291-298`

`_finalize_baatcheet_session` writes display titles into `concepts_covered_set`. `coverage_percentage` intersects with `study_plan.get_concepts()`, which holds concept tokens. Empty intersection → 0% coverage in both modes. The PR's "identical coverage" claim is true only because both contribute zero.

Fix in a parity pass — pick one canonical source (`study_plan.get_concepts()`) and have both `_finalize_baatcheet_session` AND `_finalize_explain_session` seed `concepts_covered_set` from it. Existing-data implication: replay-time resume of pre-fix sessions will show wrong coverage; acceptable since coverage was already wrong.

Defer if scope-bounded; otherwise land alongside the V1 fixes since the change is small.

### F9. Banned-pattern emoji range gap (parity with `audio_text_review`)

**File:** `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py:67`, `audio_text_review_service.py` (same regex)

Current `[☀-➿\U0001F300-\U0001FAFF]` covers U+2600–U+27BF + U+1F300–U+1FAFF. Misses U+2300–U+25FF (Misc Technical, e.g. `⏰`, `▶`, `□`). Widen both regexes to `[⌀-➿\U0001F300-\U0001FAFF]` (U+2300+).

---

## Deferred (don't block merge, track separately)

| Item | Source | Why defer |
|------|--------|-----------|
| ChatSession.tsx refactor (Step 21) | impl-plan | PR explicitly deferred; large risk surface |
| `usePersonalizedAudio` re-runs on cards-ref change | Claude C2 | Currently stable; defensive, not actively buggy |
| Validator asymmetry — `{student_name}` in audio without display | Claude C4 | Defensible per PRD; add comment explaining instead |
| Dead localStorage-fallback branch in ChatSession | Claude C5 | Harmless; will rewrite with refactor |
| `record_card_progress` monotonicity check | Claude C6 | Debounce handles 99%; CAS handles concurrent writes |
| `source_explanation_id` plain-String vs FK | Codex #8 | Cosmetic; debug-only field |
| Stale dialogue regen → cascade visuals | Codex #7 (visual half) | Self-heals via `upsert` delete-then-insert; audio half resolves with F4 |
| Validator doesn't walk activity-data arrays | Claude N1 | Display-only (not TTS'd); belt-and-suspenders |
| Card-level `audio_url` field never populated | Claude N7 | Drop from schema in cleanup pass |
| `_replay_dialogue_personalization` "friend" fallback | Claude N9 | Intended |
| Migration helper warnings + always-rebuild index | Claude N10/N11 | Cosmetic |
| `_build_welcome_card_pydantic` ignores `guideline` | Claude N4 | Pre-existing nit |
| Visual prompt missing chapter/subject context | Claude N8 | Speculative; verify after pilot |
| ChatSession Explain nav → `postCardProgress` wiring | Codex #3 long-term | Lands with refactor |
| Bulk "Regenerate all stale dialogues" admin button | impl-plan §10.2 | Optional in V1 |
| "Review Baatcheet audio" admin UI button | impl-plan §10.2 | Backend ready; UI deferred |

---

## Tests to add (currently zero coverage)

The plan §9.1 specified ~25 tests; none committed. Minimum set to land before merge:

1. **ORM round-trip** — create a Baatcheet session, query `SessionModel.teach_me_mode`, assert `'baatcheet'`. Would have caught F1 immediately.
2. **`/teach-me-options` integration** — paused Explain + paused Baatcheet for same `(user, guideline)` → both returned with separate progress.
3. **Validator coverage** — 5 new failure modes from the post-review-fix commit + the new banned-pattern walk + the `{topic_name}` rule.
4. **Hash invariants** — `audio_url` / `pixi_code` / `visual_explanation` mutations don't change hash; line text mutation does.
5. **Voice routing** — speaker=peer → Aoede; speaker=tutor → Kore; absent speaker → tutor (variant A backwards compat).
6. **`/text-to-speech` allowlist** — `voice_role: "garbage"` returns 422.
7. **Pipeline status with dialogue audio missing** — variant A audio done, dialogue audio missing → audio_synthesis state ≠ `done`.
8. **BaatcheetViewer initial-card auto-play** — fresh session renders, audio playback effect fires for card 0 (no skip).
9. **Baatcheet completion CTA renders** — summary card visible → Practice CTA in DOM.

---

## Verification sequence (pre-merge)

1. `cd llm-backend && source venv/bin/activate && python db.py --migrate` — confirm column added, index rebuilt, backfill ran.
2. `python -c "from shared.models.entities import Session; print(Session.teach_me_mode)"` — confirm ORM column present.
3. Create Baatcheet session via API → query `SELECT teach_me_mode FROM sessions WHERE id = ?` → returns `'baatcheet'`.
4. `GET /sessions/teach-me-options?guideline_id=...` returns 200.
5. Browser smoke: open a topic → Teach Me → sub-chooser renders → tap Baatcheet → welcome card auto-plays with student's actual name → walk to summary → Practice CTA visible → tap → land in Practice.
6. Browser regression: Explain mode walk-through unchanged.
7. Admin smoke: variant A regen on a topic that has a dialogue → baatcheet_dialogue tile shows stale warning → click Regenerate → tile clears → audio_synthesis tile shows `ready` (not `done`) → click Generate Audio → dialogue MP3s land.
8. Curl: `POST /text-to-speech {"voice_role": "garbage"}` → 422.
9. Validator unit tests pass.

---

## Order of work

Sequential dependency graph:

```
F1 (ORM column) ──┬──► F4 (audio status)  ──► full pipeline retest
                  ├──► F5 (topic_name)     ──► regen one topic + verify
                  ├──► F6 (banned patterns)
                  └──► F7 (audio review)

F2 (auto-play)    ──► browser smoke
F3 (CTA)          ──► browser smoke (after F2)
```

F1 first — it gates the chooser and is verified-broken at runtime. F2/F3 are independent frontend fixes. F4 is independent backend; do alongside F1. F5–F7 are validators / status / review — all can land in one commit.

Tests land alongside their fix, not as a separate pass.
