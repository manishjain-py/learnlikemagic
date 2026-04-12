# Pre-Computed Audio — Progress Tracker

**PRD:** `docs/feature-development/pre-computed-audio/PRD.md`
**Branch:** `docs/audio-typewriter-bug-analysis` (to be renamed)
**Started:** 2026-04-12

---

## Phase 1: Backend — Data Model + Audio Generation Service

- [x] Add `audio_url` field to `ExplanationLineOutput` in `explanation_generator_service.py`
- [x] Add `audio_url` field to `ExplanationLineDTO` in `tutor/models/messages.py`
- [x] Create `AudioGenerationService` — takes lines[], calls TTS, uploads to S3, returns URLs
- [x] Wire audio generation into explanation pipeline (post-generate, after critique+refine)
- [x] Add admin endpoint `POST /books/{book_id}/sync/generate-audio` for bulk backfill
- [x] Verify `audio_url` flows through existing session/card APIs to frontend
- [x] Configure S3 bucket for public read on `audio/*` prefix + CORS

## Phase 2: Frontend — Playback from S3 URLs

- [x] Extend `AudioLine` TypeScript interface with optional `audio_url` field
- [x] Update `prefetchAudio` / `playLineAudio` to prefer `audio_url` over `synthesizeSpeech()`
- [x] Fallback to real-time TTS when `audio_url` is missing or S3 fetch fails
- [x] Test: pre-computed cards play audio from S3 with <1s latency
- [x] Test: cards with mixed lines (some with URL, some without) fall back to TTS correctly

## Phase 3: Backfill + Validation

- [x] Run audio generation for Grade 3 Math Ch1 Topic 1 (86/86 lines)
- [x] Verify audio plays correctly in a live Teach Me session
- [ ] Run bulk audio generation for all existing topics
- [ ] Test on mobile Safari + Chrome
- [ ] Investigate: some cards hit TTS instead of S3 (card_idx mismatch — titles lack audio_url by design, but some content lines also missing)

## Phase 4: Cleanup (follow-up PR)

- [ ] Remove batched prefetch effect
- [ ] Remove look-ahead prefetch in onBlockStart
- [ ] Remove debug logging (`debugLog`, `/tmp/log-collector.js`)
- [ ] Simplify safety timeouts (no longer need 12s/15s safeguards for S3)
- [ ] Remove `debugLog.ts` utility

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| S3 key format | `audio/{guideline_id}/{variant}/{card_idx}/{line_idx}.mp3` | Matches existing card hierarchy, easy to bulk-delete on regeneration |
| Access control | Public read on `audio/*` prefix | Audio content is not sensitive; avoids presigned URL complexity |
| Fallback | Real-time TTS when `audio_url` is null | Simplifications + new content work without pre-computation |
| Processing order | Sequential per card, parallel across topics | Simple, avoids TTS rate limits |
| File format | MP3 (same as current TTS output) | No format conversion needed |

---

## Investigation Log

**2026-04-12:** Debug logging revealed the real root cause. TTS requests take 10-22 seconds (not `onstalled`/`onpause` handlers as originally hypothesized in PR #97). Pre-computing audio eliminates the problem at the source rather than optimizing around it.

**2026-04-12 (later):** Phase 1+2 implemented and tested. Generated audio for 86 lines (Grade 3 Math, Ch1, "Thousands and Reading 4-Digit Numbers"). Live session test confirmed:
- S3 fetches: 270-900ms (vs 10-22s from TTS API)
- Cache hits after prefetch: 0ms
- TTS fallback for titles + uncached lines: 1.4-2.8s (acceptable — no concurrent pressure)
- Zero freezes, zero safety timeouts, smooth playback through all cards
- S3 CORS initially missing (caused "Failed to fetch") — fixed with `put-bucket-cors`
