# PRD: Pre-Computed Audio for Explanation Cards

## Context & Problem

### What We Have Today

When a student plays through Teach Me explanation cards, audio is generated in real-time:
1. Frontend calls `POST /text-to-speech` per line as the typewriter reveals text
2. Backend calls Google Cloud TTS (Chirp 3 HD) synchronously per request
3. Frontend caches audio blobs in a 30-entry in-memory Map
4. Complex prefetch/batch/timeout machinery tries to hide latency

Each card has pre-computed `lines[]` with `display` (markdown) and `audio` (TTS-friendly text). The audio *text* is already computed — but the audio *file* is generated live.

### What's Wrong

**TTS latency is 10-22 seconds per request.** Debug logs from a real session show:

```
prefetch OK "Welcome!" — 2112 bytes in 21955ms
prefetch OK "Hey! Today we learn..." — 12864 bytes in 21976ms
prefetch FAIL "Let's start, it will be fun!" — signal aborted after 15002ms
```

First-card audio takes 22 seconds. Many requests hit the 15s abort timeout. The student sees the title typed out, then stares at a frozen screen for 15 seconds before the safety timeout forces advancement.

**No amount of frontend optimization fixes this.** Removing `onstalled`/`onpause` handlers, adding batched prefetch, look-ahead caching — none of it matters when the TTS API takes 22 seconds to respond. The original bug analysis (PR #97) was chasing the wrong root cause.

**Redundant computation.** The audio for "What You Already Know" in Grade 4 Math is identical for every student. Regenerating it per-session wastes money and time.

**Concurrent requests make it worse.** Batch prefetching fires 3+ parallel TTS requests. The backend creates a gRPC client per request (fixed, but underlying API latency remains). Google Cloud TTS may throttle concurrent requests from the same project.

### Why This Matters

Audio is essential to the tutoring experience — it makes explanations feel like a real teacher talking. But if audio takes 15-22 seconds to arrive, the experience is worse than no audio at all. The student either waits in silence or the system skips the audio entirely.

---

## Solution Overview

Pre-compute TTS audio files during the explanation generation pipeline (offline) and store them on S3. At playback, the frontend fetches small MP3 files from S3/CloudFront (~100-500ms) instead of calling the TTS API in real-time (10-22s).

| Concept | Description |
|---------|-------------|
| **Pre-computed audio** | MP3 files generated offline for each `audio_text` line, stored on S3. |
| **S3 URL per line** | Each `ExplanationLine` gains an `audio_url` field pointing to its MP3. |
| **Instant playback** | Frontend fetches audio from S3 — fast CDN download, no TTS API call. |
| **Graceful fallback** | If `audio_url` is missing (dynamic content like simplifications), fall back to real-time TTS. |

---

## Requirements

### R1: Audio Generation in Explanation Pipeline

Extend the existing `ExplanationGeneratorService` to generate TTS audio after card content is finalized.

**Trigger:** Same as explanation generation — post-sync, via admin endpoint. Audio generation is the final step after generate + critique + refine.

**Input:** The finalized `ExplanationCardOutput` with its `lines[]` array.

**Output:** For each line, an MP3 file uploaded to S3. The line's `audio_url` field is populated with the S3 URL.

**Process per line:**
1. Call Google Cloud TTS with `line.audio` text
2. Upload resulting MP3 bytes to S3
3. Store S3 URL in the line data

**S3 key structure:**
```
audio/{guideline_id}/{variant_key}/{card_idx}/{line_idx}.mp3
```

**Error handling:** If TTS fails for a line, log the error and leave `audio_url` as null. The frontend falls back to real-time TTS for that line. The admin can retry later.

**Concurrency:** Process lines sequentially within a card (simple, reliable). Cards can be processed in parallel across topics if needed for bulk generation.

### R2: Data Model Extension

Add `audio_url: Optional[str]` to `ExplanationLine` / `ExplanationLineDTO`:

```python
class ExplanationLineOutput(BaseModel):
    display: str
    audio: str
    audio_url: Optional[str] = None  # S3 URL for pre-computed MP3
```

The field flows through the existing pipeline:
- Stored in `topic_explanations.cards_json` (JSONB — no migration needed)
- Returned to frontend via existing card/session APIs
- Frontend TypeScript `AudioLine` interface gains optional `audio_url` field

### R3: Frontend Playback from S3 URLs

When `audioLines[i].audio_url` exists, fetch the MP3 directly from S3 instead of calling `synthesizeSpeech()`.

```tsx
// In prefetchAudio or playLineAudio:
if (audioUrl) {
  const response = await fetch(audioUrl);
  return response.blob();
} else {
  return synthesizeSpeech(text, audioLang);  // fallback
}
```

This replaces the complex batch-prefetch/cache machinery for pre-computed cards. S3 downloads are fast enough that aggressive prefetching is unnecessary — but the existing prefetch logic can stay as a bonus.

### R4: Admin CLI / Endpoint for Bulk Generation

Provide a way to generate audio for existing topics that already have explanation cards but no audio URLs:

```
POST /admin/generate-audio/{chapter_id}
```

Or a CLI command:
```
python -m scripts.generate_audio --chapter-id <id>
```

**Behavior:**
- Iterate all `TopicExplanation` rows for the chapter
- For each variant's cards, generate audio for lines missing `audio_url`
- Skip lines that already have audio (idempotent)
- Report progress: `Generated audio for 47/52 lines (5 already had audio)`

### R5: Simplification Fallback

Simplifications are generated on-the-fly when a student clicks "explain simpler." These cards don't have pre-computed audio.

**Approach:** No change needed. Simplification cards already use the same `onBlockTyped → playLineAudio` pathway. Since their `lines[].audio_url` will be null, the frontend falls back to real-time TTS automatically. This is acceptable because:
- Simplifications are 1 card at a time (not 17 cards in bulk)
- The student is actively engaged (clicked a button, expects a brief wait)
- Low request volume — no concurrent pressure on TTS API

---

## What We Remove

Once all topics have pre-computed audio and the feature is stable:

1. **Batched prefetch effect** — S3 downloads are fast enough to not need it
2. **Look-ahead prefetching in onBlockStart** — same reason
3. **30-entry audio cache** — can be simplified to a simple URL→Blob map
4. **Complex safety timeouts** — S3 fetch + play is predictable, doesn't need 12s/15s safeguards
5. **Debug logging infrastructure** — the `debugLog` calls and log collector

These can be removed in a follow-up cleanup PR after the feature is validated.

---

## Non-Goals

- **Streaming audio** — MP3 files are small (5-15KB per line). Full download before play is fine.
- **Audio editing/trimming** — Use TTS output as-is. Quality tuning is done by choosing the right voice/model.
- **Per-student voice preferences** — All students get the same voice. Future feature if needed.
- **Audio for interactive-phase responses** — Teacher chat responses during practice still use real-time TTS. Different use case, lower volume.

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Time to first audio on card 1 | 15-22s | <1s |
| Audio availability across all lines | ~70% (timeouts) | ~100% |
| TTS API calls per student session | ~100+ | 0 (pre-computed cards) |
| Frontend audio code complexity | ~100 lines of prefetch/cache/timeout | ~20 lines fetch-and-play |

---

## Files Affected

| Layer | File | Change |
|-------|------|--------|
| Backend model | `book_ingestion_v2/services/explanation_generator_service.py` | Add audio generation step |
| Backend model | `tutor/models/messages.py` | Add `audio_url` to `ExplanationLineDTO` |
| Backend repo | `shared/repositories/explanation_repository.py` | No change (JSONB handles new field) |
| Backend API | New endpoint or extend existing admin API | Bulk audio generation trigger |
| Backend util | `shared/utils/s3_client.py` | Already has `upload_bytes()` — reuse |
| Backend TTS | `tutor/api/tts.py` | Reuse `_get_tts_client()` for pipeline |
| Frontend | `src/pages/ChatSession.tsx` | Prefer `audio_url` over `synthesizeSpeech` |
| Frontend | `src/components/TypewriterMarkdown.tsx` | Pass `audio_url` through interface |
| Frontend | `src/api.ts` | No change (S3 fetch is a plain `fetch()`) |
| Infra | S3 bucket policy | Allow public read for `audio/*` prefix (or use presigned URLs) |
