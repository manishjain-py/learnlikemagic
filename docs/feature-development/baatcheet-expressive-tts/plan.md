# Baatcheet Expressive TTS — Implementation Plan

Switch baatcheet audio from Google Chirp 3 HD (flat, robotic) to **ElevenLabs v3** with **per-line emotion tags authored by the dialogue generator**. Provider-switchable via admin config; ElevenLabs is the new default. Apply to baatcheet only (V1).

## Context

- **Symptom.** Baatcheet voices sound robotic. Same prosody whether tutor is praising, posing a trap question, or empathising with a confused student.
- **Root cause is not just the provider.** The lesson plan already authors a rich `move` grammar (hook, fall, articulate, reframe, …) but that intent never reaches synthesis. Chirp 3 HD has no SSML / emotion control either way, so the missing emotion metadata + flat provider compound.
- **Bake-off (this branch).** Rendered the one production baatcheet dialogue ("Reading and Writing 5- and 6-Digit Numbers", Grade 4, 39 cards) twice: Google baseline vs ElevenLabs v3 with audio tags derived from move grammar. ElevenLabs was meaningfully better on every emotional beat (warm hook, hesitant fall, aha-callback, reframe pair, proud close). User-confirmed: ship it.
- **Voice cast (locked by audition).** Mr. Verma = `Sekhar — Warm & Energetic` (`81uXfTrZ08xcmV31Rvrb`); Meera = `Amara — Calm & Intellectual Narrator` (`IEBxKtmsE9KTrXUwNazR`). Both Indian-English from the ElevenLabs shared library. ElevenLabs prohibits actual child voices industry-wide (CSAM/scam/consent risk), so Meera is an adult voice performing a youthful character — same approach as animation studios.

Bake-off artifacts (this branch): `tools/tts-bakeoff/*.py`. MP3 outputs were emailed for the listen-test and live in `reports/baatcheet-tts-bakeoff/` locally (gitignored).

## Locked decisions

| | |
|---|---|
| Default TTS provider | **ElevenLabs v3** |
| Switchable to | `google_tts` (current implementation, kept as fallback) |
| Tutor voice (EL) | Sekhar — `81uXfTrZ08xcmV31Rvrb` |
| Peer voice (EL) | Amara — `IEBxKtmsE9KTrXUwNazR` |
| Tutor voice (Google) | `en-IN-Chirp3-HD-Orus` (existing) |
| Peer voice (Google) | `en-IN-Chirp3-HD-Leda` (existing) |
| Emotion source | **LLM-authored at dialogue generation** (option b — not derived from move grammar) |
| Emotion granularity | **Per-line** on `ExplanationLine` |
| Existing dialogue handling | **Re-render on deploy** (one-time, ~5K chars; only 1 dialogue exists) |
| Scope | Baatcheet only in V1 (explanation cards, check-ins remain Google flat) |
| API key handling | Standard pattern: `.env` locally, Terraform secrets module in prod, mirroring `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| Config UI | Admin dashboard provider toggle, mirroring the `TUTOR_LLM_PROVIDER` pattern |

## Architecture

### Provider abstraction

New module `llm-backend/shared/services/tts/`:

```
shared/services/tts/
├── __init__.py
├── base.py                     # TtsProvider protocol
├── google_tts_adapter.py       # wraps existing Chirp 3 HD calls
├── elevenlabs_tts_adapter.py   # new — v3 with audio tags
└── factory.py                  # resolve(provider_name) → TtsProvider
```

`TtsProvider` protocol (proposed):

```python
class TtsProvider(Protocol):
    name: ClassVar[str]            # "google_tts" | "elevenlabs"
    supports_emotion: ClassVar[bool]

    def synthesize(
        self,
        text: str,
        speaker: Literal["tutor", "peer"],
        emotion: Optional[str] = None,
        language: str = "en",
    ) -> bytes:
        """Return MP3 bytes. Adapters that don't support emotion ignore the param."""
```

### Configuration layer

Mirrors `TUTOR_LLM_PROVIDER` exactly.

| Setting | Default | Notes |
|---|---|---|
| `TTS_PROVIDER` (env) | `elevenlabs` | bootstrap default |
| `ELEVENLABS_API_KEY` (env) | `<sensitive>` | required when provider=elevenlabs |
| `GOOGLE_CLOUD_TTS_API_KEY` (env) | existing | required when provider=google_tts |

Admin dashboard exposes a single dropdown — "TTS Provider" — that writes to the same admin-config table the LLM provider toggle uses. Resolution order: admin DB row → env var → hard default `elevenlabs`. Same pattern the codebase already uses for LLM providers.

Voice IDs are **not** admin-editable in V1 — they live as constants in the adapter modules, the same way Orus/Leda live in `audio_generation_service.py:46-47` today. V2 task: lift to admin config if we want per-topic or per-grade voice routing.

### Schema change

Add `emotion: Optional[str]` to `ExplanationLine` (`shared/repositories/explanation_repository.py:75-78`). Pydantic field; nullable; validated against a closed canonical vocabulary.

```python
# shared/repositories/explanation_repository.py
class ExplanationLine(BaseModel):
    display: str
    audio: str
    emotion: Optional[Emotion] = None   # NEW
```

```python
# new: shared/types/emotion.py
class Emotion(str, Enum):
    # tutor-side
    WARM = "warm"
    CURIOUS = "curious"
    ENCOURAGING = "encouraging"
    GENTLE = "gentle"
    PROUD = "proud"
    EMPATHETIC = "empathetic"
    CALM = "calm"
    EXCITED = "excited"             # also valid for peer (aha)
    # peer-side
    HESITANT = "hesitant"
    CONFUSED = "confused"
    TIRED = "tired"
```

`ExplanationLine` is stored inside `topic_dialogues.cards_json` (JSONB). **No SQL migration needed** — JSONB tolerates the new optional field. Backward-compatible.

The LLM is allowed to emit emotion words outside this set (v3 interprets natural language in `[brackets]` regardless), but our normalizer canonicalizes synonyms (`warmly` → `warm`, `joyful` → `excited`) and rejects everything else with a logged warning + fallback to `None`. This keeps emission flexible while making downstream code, validation, and tests deterministic.

### Dialogue generator change

Stage 5a (`book_ingestion_v2/stages/baatcheet_dialogue.py` + the underlying generator service) currently emits cards with `lines: [{display, audio}]`. Update the generator prompt so each line additionally carries `emotion` from the canonical vocabulary, picked by the model based on the line's pedagogical intent + speaker.

Prompt addendum (sketch):

> For every line in `lines`, set `emotion` to one of: `warm`, `curious`, `encouraging`, `gentle`, `proud`, `empathetic`, `calm`, `excited` (tutor) / `hesitant`, `confused`, `tired`, `excited`, `curious`, `warm` (peer). Pick from the line's intent — for example, the tutor's praise after a student insight is `warm`; Meera's first wrong guess on a trap-set is `hesitant`; the tutor's response to "my head is spinning" is `empathetic`. Use `None` for routine/instructional lines that don't carry emotional weight.

Stage 5b (`baatcheet_audio_review`) adds a validation pass that checks emotions are from the canonical set, drops invalid values to `None`.

### Audio synthesis change (stage 5c)

`AudioGenerationService` (`book_ingestion_v2/services/audio_generation_service.py`) currently hardcodes Google. Refactor:

1. At init, resolve provider via factory: `self.tts = tts_factory.resolve(settings.tts_provider)`.
2. `_synthesize()` becomes `self.tts.synthesize(text, speaker, emotion, language)`.
3. For ElevenLabs path: adapter prepends `[emotion]` to text, calls v3 with the right `voice_id`.
4. For Google path: adapter ignores `emotion`, calls existing Chirp 3 HD code (preserves variant A and check-in audio behaviour exactly).
5. S3 keys unchanged: `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3`. Deterministic so re-render is idempotent.

**Important:** the `topic_explanations` audio (variant A explanation cards) and check-in audio remain on the Google path in V1. ElevenLabs only affects baatcheet dialogue lines. This keeps the rollout contained and avoids a 5x cost jump on the larger explanation-cards dataset.

### Runtime TTS change

`tutor/api/tts.py` POST `/api/text-to-speech` (used for `includes_student_name=True` cards at runtime) routes through the same factory.

**Latency caveat.** ElevenLabs v3 from us-east-1 → India is 500ms+ vs Google's ~200ms. The frontend `audioController.ts` already prefetches blobs and tolerates ~800ms; runtime TTS hits *after* the user navigates so the user sees a longer initial pause on personalized cards (5% of cards have `{student_name}`). Monitor; if it's a real UX regression, fall back the runtime path to Google via a separate `TTS_PROVIDER_RUNTIME` env override. Not implementing the override in V1 — only adding it if monitoring shows a problem.

### Error handling

ElevenLabs adapter retries on transient errors (rate limit, 5xx) with exponential backoff (3 attempts, 5s base). On persistent failure during ingestion, **fall back to Google for that line with a logged warning**, rather than failing the whole topic. Mismatched provenance is acceptable for the rare error case; failing 39 cards because line 27 hit a 503 is not.

The fallback path is intentional, not silent: log line, emit a metric, surface in stage status. Same pattern as `claude_code_adapter.py`'s retry loop.

### Terraform / secrets

Mirror existing API-key wiring in `infra/terraform/variables.tf:56-78` and `infra/terraform/main.tf:44-51`:

```hcl
# variables.tf
variable "elevenlabs_api_key" {
  description = "ElevenLabs API key (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tts_provider" {
  description = "TTS provider: google_tts or elevenlabs"
  type        = string
  default     = "elevenlabs"
}

# main.tf — wire into secrets module
elevenlabs_api_key = var.elevenlabs_api_key
tts_provider       = var.tts_provider
```

Update `infra/terraform/modules/secrets/` to expose `ELEVENLABS_API_KEY` + `TTS_PROVIDER` to ECS task env. Update `terraform.tfvars.example` with placeholder.

### Backend `Settings`

Add to whatever the equivalent of `get_settings()` returns (the function used at `audio_generation_service.py:94`):

```python
tts_provider: str = "elevenlabs"
elevenlabs_api_key: str | None = None
```

## Phasing — each row is one landable PR

| # | PR | Land sequence | Notes |
|---|---|---|---|
| 1 | **Provider abstraction + adapters** (no behaviour change) | First | New `shared/services/tts/` module. Default factory still resolves Google for safety until cutover. Unit tests with mocked HTTP. |
| 2 | **Emotion field on `ExplanationLine`** | Independent | Pydantic + canonical vocab + normalizer. No SQL migration (JSONB). Backward compatible — old rows have `emotion=None` and render with no tag. |
| 3 | **Dialogue generator emits emotion** | Depends on #2 | Update generator prompt + tests. Doesn't affect synthesis yet — emotion is just stored. |
| 4 | **Synthesis stage routes by provider + uses emotion** | Depends on #1, #2 | Refactor `AudioGenerationService`. ElevenLabs adapter consumes emotion as audio tag. Provider still env-switchable; default flips to `elevenlabs`. |
| 5 | **Runtime TTS routes by provider** | Depends on #1 | `tutor/api/tts.py` factory wiring. Personalized cards now use EL by default. |
| 6 | **Admin config UI toggle** | Independent | Mirror LLM provider dropdown. |
| 7 | **Terraform secrets + cutover deploy** | Last | Add `ELEVENLABS_API_KEY` + `TTS_PROVIDER=elevenlabs` to prod env. Re-render the 1 existing dialogue. Smoke test runtime synthesis. |

PRs 2–6 can land in parallel after #1. The cutover is #7 — that's where we flip the default and bulk-rerender.

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| ElevenLabs starter tier (40K chars/mo) is too small for bulk rerender | Med | Currently only 1 dialogue exists, so this is a non-issue for V1. **Action item: upgrade to Pro plan (~$99/mo, 500K chars) before scaling beyond ~10 dialogues.** Add a pre-flight char-budget check in stage 5c that aborts gracefully if monthly quota would be exceeded. |
| v3 non-determinism — same input produces slightly different output across renders | Low | Use the `seed` voice setting parameter (when API supports it) for stability. For one-time renders this is mostly cosmetic. |
| Audio file size — EL MP3s are ~3–5x larger than Google (higher bitrate) | Low | S3 cost increase is rounding error (~$0.30/mo for full library). Bandwidth to India: monitor TTFB; existing prefetch in `audioController.ts` (60-entry blob cache) absorbs it. |
| Indian pronunciation drift on terms like *lakh*, *crore*, *chapati*, *dadi* | Med | Existing `_TTS_PRONUNCIATION_FIXES` in `audio_generation_service.py` is provider-agnostic — it edits text before synthesis. Reuse it for EL. Listen-test the rerendered library before flipping default. |
| Voice consistency across cards (tutor sounds slightly different at card 7 vs card 31) | Low | Single Text-to-Dialogue call would solve this but breaks per-line S3 storage. Per-line synthesis with same `voice_id` + locked `voice_settings` is acceptable; the bake-off render didn't surface a problem. |
| Runtime TTS latency on personalized `{student_name}` cards | Med | Monitor. `TTS_PROVIDER_RUNTIME=google` override is a stub — implement only if real complaints. Worst case: keep Google for runtime, EL for ingestion. |
| Admin flips to `google_tts` after dialogues were authored with emotion | Low | Google adapter ignores the `emotion` field by design. No data corruption; just flat audio for that synthesis run. |
| ElevenLabs API outage during a rerender batch | Med | Adapter retries with backoff; persistent failure falls back to Google for that line + logs. Topic still completes. |
| Cost ramp surprise | Med | Add a per-stage `chars_synthesized` metric. Surface monthly EL spend in admin dashboard. |

## Out of scope (V2+)

- Apply emotion to **explanation cards** (variant A). Currently Google-only via the same `AudioGenerationService` paths. Emotion field already exists once #2 lands; flipping explanation cards to EL is a config + cost decision.
- Per-topic / per-grade voice routing. Voice IDs hardcoded in V1.
- **Cartesia** as a third provider (faster TTFA, native Hinglish). Plug-in via the same adapter interface when needed.
- Hinglish content. The current dataset is Indian-English; Hinglish would require a separate voice cast and prompt updates.
- Voice cloning of a real teacher voice (legal/IP overhead).
- Streaming TTS for a "live tutor" mode (only matters if we move off pre-compute, not on the roadmap).
- Frontend display of emotion (e.g., colored speech bubbles). Audio-only V1.

## Open items for the implementer

- **Confirm canonical Emotion vocabulary** with a quick listen-test on 3–4 v3 renders before locking. v3 may interpret `[gentle]` differently than expected; if it sounds the same as `[calm]`, drop one.
- **Pick the seed voice setting** (`stability`, `similarity_boost`, `style`, `use_speaker_boost`) for production. Bake-off used `0.5 / 0.75 / 0.4 / true`. May want different defaults per voice (Sekhar is more energetic, Amara is more calm — they probably want different `style` weights).
- **Audit the existing dialogue generator's V2 prompt** (`docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md`) for the right insertion point for the emotion field. Keep prompt edits minimal — the V2 prompt is already long.

## Success criteria

1. Production baatcheet renders with ElevenLabs v3 by default; admin toggle returns to Google in one click.
2. Existing Place Value dialogue is regenerated with emotion tags on first deploy. Listen-test passes (warm hook, hesitant fall, empathetic reframe, proud close all land).
3. Future baatcheet dialogues authored by ingestion automatically carry per-line emotion.
4. Switching admin config to `google_tts` produces flat-but-functional audio (same as today).
5. ElevenLabs API outage doesn't break ingestion — Google fallback kicks in and stages complete.
