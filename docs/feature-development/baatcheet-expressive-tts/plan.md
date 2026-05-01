# Baatcheet Expressive TTS — Implementation Plan

Switch all student-facing TTS from Google Chirp 3 HD (flat, robotic) to **ElevenLabs v3** with **per-line emotion tags authored by the dialogue generator (baatcheet only)**. Provider-switchable via admin config; ElevenLabs is the new default. **All audio surfaces in V1**: baatcheet dialogues, explanation cards, check-ins, and runtime personalized synthesis.

## Status — 2026-05-01

**PRs #1–#6 implemented and merged-ready in [#138](https://github.com/manishjain-py/learnlikemagic/pull/138)** (branch `feat/tts-elevenlabs-impl`, cut off `main`). Default provider stays `google_tts` in this PR — admin can flip to `elevenlabs` via the new TTS Config page without redeploy.

| Phase | Status | Landed in |
|---|---|---|
| #1 Inline EL synthesis path + `TTS_PROVIDER` setting | ✅ done | #138 |
| #2 `Emotion` enum + `ExplanationLine.emotion` field | ✅ done | #138 |
| #3 V2 dialogue generator emits per-line emotion (baatcheet only) | ✅ done | #138 |
| #4 Voice-settings auto-keying (steady ↔ expressive presets) | ✅ done | #138 (default flip deferred to #7) |
| #5 Runtime TTS branching in `tutor/api/tts.py` | ✅ done | #138 |
| #6 Admin config UI toggle (`/admin/tts-config`) | ✅ done | #138 |
| #7 Terraform secrets + cutover deploy + bulk re-render | ⏳ pending | next PR |

**What landed on top after review:** `6f94bcf` addresses four reviewer findings — `TTSProviderError` propagates out of per-line catches (no power-through on EL outage); `TimeoutError` caught explicitly in retry loops; the `tts` row is hidden + write-refused on `/admin/llm-config` so it can't be overwritten with an LLM provider; dropped a dead `self.voice` attribute. 12 regression tests added.

**Bundling decision (vs. plan's original phasing).** The plan had each row as a separate PR. We bundled #1–#6 into a single PR because (a) several phases are too small to justify their own review, (b) the cutover (#7) has external blockers — EL Pro tier provisioned, API key in Terraform — that would have held everything if collapsed in. Default still `google_tts` in #138 means the bundle lands safely without committing to the cutover.

### Next steps — PR #7 cutover

Order of operations matters here; doing them out of order risks an outage window or quota exhaustion:

1. **Provision the EL Pro plan** ($99/mo, 500K chars/mo) on the org account *before* anything code-related. Bulk re-render alone consumes a meaningful slice of monthly quota.
2. **Add `ELEVENLABS_API_KEY` and `TTS_PROVIDER=elevenlabs` to the Terraform `secrets` module** — wiring already sketched in [#137 plan §Terraform/secrets](#terraform--secrets). `terraform apply` brings the new env into ECS task definitions on next deploy.
3. **Flip the env-level default** in `Settings.tts_provider` from `"google_tts"` to `"elevenlabs"` (one-line config change in `llm-backend/config.py`) so any environment without an admin DB row picks EL.
4. **Bulk re-render the audio library.** Trigger the Stage 5/5b/audio-synth force-rerun for every guideline:
   - 1 baatcheet dialogue currently in prod (Place Value, Grade 4)
   - All variant A explanation card libraries (across approved guidelines)
   - All check-ins (synthesized in-place per check-in card)
   - Operationally: cap parallelism so we don't hit the per-minute rate limit; the bulk job is mostly serial today which is fine.
5. **Operational smoke test.** Hit `/api/text-to-speech` with `voice_role=tutor` and `voice_role=peer`; load a topic; verify dialogue + explanation MP3s sound expressive on tagged lines and steady on `emotion=None` lines.
6. **Monitor for 48h.** Watch ECS error rate, S3 audio sizes (expect ~3–5× larger MP3s), India TTFB on the runtime endpoint.

Rollback in this PR is just an admin toggle flip (`elevenlabs → google_tts` on `/admin/tts-config`) — but cached S3 audio is not regenerated automatically, so a flip serves the existing EL-rendered library until the next stage rerun.

### Deferred to V2+ (unchanged from plan)

Per-line emotion on explanation cards; provider-namespaced S3 paths for instant-flip rollback; cost-guard / pre-flight char-budget; listen-test automation; Cartesia or third providers; Hinglish voice cast; voice cloning.

### Notes for the next implementer

- The admin override resolution lives in `shared/services/tts_config_service.py:resolve_tts_provider(db)`. Always pass a `db` session when constructing `AudioGenerationService` from a route handler — env-only resolution is the fallback path for workers without DB access.
- `Emotion` is a `str, Enum` and serializes cleanly into JSONB; `_card_output_to_dict` uses `model_dump(mode="json")` to keep that round-trip explicit. The Pydantic `field_validator(mode="before")` on `ExplanationLine.emotion` and `DialogueLineOutput.emotion` canonicalizes synonyms and drops out-of-vocab to `None`.
- `TTSProviderError` is the contract between provider failures and stage callers. Don't widen the per-line `except` back to `Exception` — that's exactly what the review caught.
- The bake-off scripts (`tools/tts-bakeoff/`) are still on the parent branch (#137) — kept reusable for the next provider evaluation but not landed to `main`.

## Context

- **Symptom.** Baatcheet voices sound robotic. Same prosody whether tutor is praising, posing a trap question, or empathising with a confused student. Explanation cards have the same flatness but it's less obvious because they're monologue.
- **Root cause is not just the provider.** The lesson plan already authors a rich `move` grammar (hook, fall, articulate, reframe, …) but that intent never reaches synthesis. Chirp 3 HD has no SSML / emotion control either way, so the missing emotion metadata + flat provider compound.
- **Bake-off (this branch).** Rendered the one production baatcheet dialogue ("Reading and Writing 5- and 6-Digit Numbers", Grade 4, 39 cards) twice: Google baseline vs ElevenLabs v3 with audio tags derived from move grammar. ElevenLabs was meaningfully better on every emotional beat (warm hook, hesitant fall, aha-callback, reframe pair, proud close). User-confirmed: ship it.
- **Scope.** Initially scoped to baatcheet only; expanded during planning to cover all audio surfaces (explanation cards, check-ins, runtime). Cost ratio (5x) is accepted; Pro tier ($99/mo, 500K chars) provisioned from V1.
- **Voice cast (locked by audition).** Mr. Verma = `Sekhar — Warm & Energetic` (`81uXfTrZ08xcmV31Rvrb`); Meera = `Amara — Calm & Intellectual Narrator` (`IEBxKtmsE9KTrXUwNazR`). Both Indian-English from the ElevenLabs shared library. ElevenLabs prohibits actual child voices industry-wide (CSAM/scam/consent risk), so Meera is an adult voice performing a youthful character — same approach as animation studios.

Bake-off artifacts (this branch): `tools/tts-bakeoff/*.py`. MP3 outputs were emailed for the listen-test and live in `reports/baatcheet-tts-bakeoff/` locally (gitignored).

## Locked decisions

| | |
|---|---|
| Default TTS provider | **ElevenLabs v3** |
| Switchable to | `google_tts` (kept as fallback via admin toggle) |
| Tutor voice (EL) | Sekhar — `81uXfTrZ08xcmV31Rvrb` |
| Peer voice (EL) | Amara — `IEBxKtmsE9KTrXUwNazR` |
| Tutor voice (Google) | `en-IN-Chirp3-HD-Orus` (existing) |
| Peer voice (Google) | `en-IN-Chirp3-HD-Leda` (existing) |
| Emotion source | **LLM-authored at dialogue generation** (inline in V2 generator, single LLM call) |
| Emotion granularity | **Per-line** on `ExplanationLine` |
| Emotion vocabulary | **Strict 11-value enum** (closed set; synonyms normalized; out-of-vocab rejected). **No tutor/peer split enforced** — both speakers can use any value. |
| Emotion scope | **Baatcheet only.** Explanation cards stay `emotion=None`. |
| Voice settings | **Auto-keyed by emotion presence**: emotion set → expressive preset (`stability=0.5, similarity_boost=0.75, style=0.4, use_speaker_boost=true` from bake-off); `emotion=None` → steady preset (high stability, low style; values picked during PR #4). |
| Audio surface scope | **EL everywhere**: baatcheet + explanation cards + check-ins + runtime synthesis. |
| Existing audio handling | **Re-render entire library on deploy** (one-time; baatcheet dialogue + all explanation card libraries + check-ins). |
| Failure handling | **Fail topic stage on persistent EL failure.** Adapter retries 3× with backoff, then propagates error. **No fallback to Google** for individual lines. |
| Rollback | **None for MVP.** EL outage = audio outage, accepted. Admin can flip provider for *future* ingestion runs but cached S3 audio is not re-rendered automatically. |
| Cost guard | **None.** EL API's quota-exceeded error is the enforcement. Stages fail on quota exhaustion. |
| Quality gate (cutover) | **Operational smoke test only.** Synthesis runs, runtime endpoint works, admin toggle works. **No human listen-test gate.** |
| API key handling | Standard pattern: `.env` locally, Terraform secrets module in prod, mirroring `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| Config UI | Admin dashboard provider toggle, mirroring the `TUTOR_LLM_PROVIDER` pattern |

## Architecture

### Provider routing

**No new module, no factory pattern.** The two synthesis sites that already exist get inline branching:

- `llm-backend/book_ingestion_v2/services/audio_generation_service.py` — batch synthesis for ingestion (baatcheet + explanation cards + check-ins)
- `llm-backend/tutor/api/tts.py` — runtime synthesis for `{student_name}` cards

Each site reads `settings.tts_provider` and dispatches to either Google or ElevenLabs synthesis. The provider-routing logic is duplicated across the two sites — accepted MVP-mode complexity, ~30 lines per site. If a third provider is added later (Cartesia, etc.), refactor to a shared helper at that point.

### Configuration layer

Mirrors `TUTOR_LLM_PROVIDER` exactly.

| Setting | Default | Notes |
|---|---|---|
| `TTS_PROVIDER` (env) | `elevenlabs` | bootstrap default after PR #4 |
| `ELEVENLABS_API_KEY` (env) | `<sensitive>` | required when provider=elevenlabs |
| `GOOGLE_CLOUD_TTS_API_KEY` (env) | existing | required when provider=google_tts |

Admin dashboard exposes a single dropdown — "TTS Provider" — that writes to the same admin-config table the LLM provider toggle uses. Resolution order: admin DB row → env var → hard default `elevenlabs`. Same pattern the codebase already uses for LLM providers.

Voice IDs are **not** admin-editable in V1 — they live as constants alongside Orus/Leda in `audio_generation_service.py:46-47` today. V2 task: lift to admin config if we want per-topic or per-grade voice routing.

### Schema change

Add `emotion: Optional[Emotion]` to `ExplanationLine` (`shared/repositories/explanation_repository.py:75-78`). Pydantic field; nullable; validated against a closed canonical vocabulary.

```python
# shared/repositories/explanation_repository.py
class ExplanationLine(BaseModel):
    display: str
    audio: str
    emotion: Optional[Emotion] = None   # NEW — only populated for baatcheet lines
```

```python
# new: shared/types/emotion.py
class Emotion(str, Enum):
    WARM = "warm"
    CURIOUS = "curious"
    ENCOURAGING = "encouraging"
    GENTLE = "gentle"
    PROUD = "proud"
    EMPATHETIC = "empathetic"
    CALM = "calm"
    EXCITED = "excited"
    HESITANT = "hesitant"
    CONFUSED = "confused"
    TIRED = "tired"
```

`ExplanationLine` is stored inside `topic_dialogues.cards_json` and `topic_explanations.cards_json` (both JSONB). **No SQL migration needed** — JSONB tolerates the new optional field. Backward-compatible.

The validator canonicalizes synonyms (`warmly` → `warm`, `joyful` → `excited`) and rejects everything else with a logged warning + fallback to `None`. **Both tutor and peer can use any of the 11 values** — no role-based restriction in the validator. Prompt-level guidance can suggest typical fits per role, but the schema accepts any value for either speaker.

### Dialogue generator change (baatcheet only)

Stage 5a (`book_ingestion_v2/stages/baatcheet_dialogue.py` + the V2 designed-lesson generator) currently emits cards with `lines: [{display, audio}]`. Update the V2 prompt so each line additionally carries `emotion` from the canonical vocabulary, picked by the model based on the line's pedagogical intent + speaker. **Single LLM call** generates `display` + `audio` + `emotion` + move grammar together — full context, contextually-fit emotion choices.

Prompt addendum (sketch):

> For every line in `lines`, set `emotion` to one of: `warm`, `curious`, `encouraging`, `gentle`, `proud`, `empathetic`, `calm`, `excited`, `hesitant`, `confused`, `tired`. Pick from the line's intent — the tutor's praise after a student insight is `warm`; Meera's first wrong guess on a trap-set is `hesitant`; the tutor's response to "my head is spinning" is `empathetic`. Use `None` for routine/instructional lines that don't carry emotional weight.

Stage 5b (`baatcheet_audio_review`) adds a validation pass that checks emotions are from the canonical set, drops invalid values to `None`.

**Explanation card generator is untouched in V1.** Explanation card lines stay `emotion=None` and render with the steady voice preset. Adding per-line emotion to explanation cards is a V2 task.

### Audio synthesis

`AudioGenerationService` (`book_ingestion_v2/services/audio_generation_service.py`) currently hardcodes Google. Refactor:

1. At init, read `settings.tts_provider` (no factory).
2. `_synthesize()` branches on provider:
   - `elevenlabs` → `_synthesize_elevenlabs(text, speaker, emotion, language)`
   - `google_tts` → existing Chirp 3 HD code path, preserved as `_synthesize_google(...)`
3. ElevenLabs path:
   - If `emotion` is set → prepend `[emotion]` to text, use **expressive voice settings** (`stability=0.5, similarity_boost=0.75, style=0.4, use_speaker_boost=true` — bake-off values).
   - If `emotion` is `None` → no tag, use **steady voice settings** (high stability ~0.7, low style ~0.2 — exact values picked during PR #4 testing).
4. Same `voice_id` constants for tutor/peer regardless of emotion.
5. S3 keys unchanged: `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3` for baatcheet; existing positional keys for explanation cards. Deterministic so re-render is idempotent.

**Scope (changed during planning):** all three sub-paths — explanation cards (variant A), baatcheet, and check-ins — go through the EL path in V1. The earlier "explanation cards stay Google" carveout was removed to deliver consistent voice quality across surfaces. Cost implication: Pro tier ($99/mo) provisioned from V1, not deferred.

### Runtime TTS

`tutor/api/tts.py` POST `/api/text-to-speech` (used for `includes_student_name=True` cards at runtime) gets the same inline branching as `audio_generation_service.py`. Both surfaces (baatcheet personalized, explanation card personalized) hit EL.

**Latency caveat.** ElevenLabs v3 from us-east-1 → India is 500ms+ vs Google's ~200ms. Personalized cards can't be prefetched (need student name at session start). Accepted: 5% of cards have `{student_name}`, the pedagogical tone of personalized openers ("Hello Manish, ready to learn?") benefits from the warm EL voice more than it suffers from the +300ms.

### Error handling

ElevenLabs adapter retries on transient errors (rate limit, 5xx) with exponential backoff (3 attempts, 5s base). On persistent failure during ingestion, **propagate the error and fail the synthesis stage**. The topic doesn't proceed; admin retries the stage when EL is healthy.

**No fallback to Google for individual lines.** A topic's audio is internally consistent (every line on the same provider) or the topic is flagged as failed. Mixed-provider dialogues are not allowed.

Runtime synthesis follows the same pattern — `/api/text-to-speech` returns an error response on persistent EL failure; frontend handles audio failure as it does today.

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

## Phasing — each row was originally one landable PR

> **Implementation note (2026-05-01).** Rows #1–#6 were bundled into a single PR (#138) for review velocity; default `TTS_PROVIDER` stays `google_tts` in that PR, and the env-flip from #4 was deferred into #7 alongside the cutover. Original phasing kept below for traceability — the "Status" section at the top of this doc has the current state.

| # | PR | Land sequence | Status | Notes |
|---|---|---|---|---|
| 1 | **Inline EL synthesis path + `TTS_PROVIDER` setting** | First | ✅ #138 | `_synthesize_elevenlabs` lives alongside Google in `audio_generation_service.py`. `Settings.tts_provider` + `elevenlabs_api_key` wired. Default still `google_tts` for safety. Mocked-HTTP unit tests for the EL path. No factory, no shared module. |
| 2 | **Emotion field on `ExplanationLine`** | Independent | ✅ #138 | `shared/types/emotion.py` (11-value enum + synonym normalizer). Pydantic field + `field_validator(mode="before")` on `ExplanationLine` and `DialogueLineOutput`. No SQL migration (JSONB). Backward compatible. Both speakers can use any value (no role split enforced). |
| 3 | **V2 dialogue generator emits emotion (baatcheet only)** | Depends on #2 | ✅ #138 | V2 prompt updated (schema + craft section explaining the 11-value vocab and per-line authoring). Audio review pass canonicalizes via the shared validator. Explanation card generator untouched. |
| 4 | **Synthesis uses emotion + voice-settings auto-keying** | Depends on #1, #2 | ✅ #138 (default flip deferred) | `_synthesize_elevenlabs` picks expressive vs steady preset based on `emotion` presence (`0.5/0.75/0.4/true` vs `0.7/0.75/0.2/true`). Applies to baatcheet + explanation cards + check-ins. **Default flip from `google_tts` → `elevenlabs` moved into #7** so the bundle lands without committing to the cutover. |
| 5 | **Runtime TTS gets inline branching** | Depends on #1 | ✅ #138 | Same dispatch logic in `tutor/api/tts.py`. Personalized cards now route via the resolved provider. Steady preset only at runtime (no per-line emotion on `{student_name}` openers, by design). |
| 6 | **Admin config UI toggle** | Independent | ✅ #138 | `/admin/tts-config` page with single dropdown. Backed by `llm_config` row keyed `'tts'`. `LLMConfigService` filters/refuses `'tts'` so the row can't leak into `/admin/llm-config`. |
| 7 | **Terraform secrets + cutover deploy + bulk re-render** | Last | ⏳ pending | Add `ELEVENLABS_API_KEY` + `TTS_PROVIDER=elevenlabs` to prod env via Terraform secrets module. Flip the env-level default in `Settings`. **Re-render entire audio library** (1 dialogue + all explanation card libraries + check-ins). Smoke test runtime synthesis. No human listen-test gate. **External blocker: EL Pro plan ($99/mo) provisioned.** |

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **Pro tier quota exhaustion (500K chars/mo)** — full library re-render approaches monthly quota in one job | High | No automated guard. EL API quota error fails the stage; admin upgrades plan or waits for monthly reset. **Operational discipline:** don't trigger casual full-library re-renders. |
| **EL outage = system-wide audio outage** — no fallback path | Med | Accepted MVP risk. Stages fail on persistent EL failure; admin retries when healthy. Runtime synth returns errors; frontend handles audio failure as today. |
| **PR #7 cutover with no listen-test gate** — bake-off is the only quality validation | Med | Bake-off rendered the production Place Value dialogue end-to-end and was approved. Steady preset for explanation cards is untested at scale; iterate post-ship if specific lines sound bad. |
| **v3 non-determinism** — same input produces slightly different output across renders | Low | Use `seed` voice setting parameter when API supports it. Re-render of a topic refreshes the whole library; minor drift across re-renders is cosmetic. |
| **Indian pronunciation drift** on terms like *lakh*, *crore*, *chapati*, *dadi*, names like *Manish* / *Meera* | Med | Existing `_TTS_PRONUNCIATION_FIXES` in `audio_generation_service.py` is provider-agnostic — it edits text before synthesis. Currently empty. Populate reactively when problems are heard post-ship. |
| **Voice consistency across cards** (tutor sounds slightly different at card 7 vs card 31) | Low | Single `voice_id` + locked voice settings should produce consistent voice. Bake-off didn't surface a problem. |
| **Runtime TTS latency** (+300ms India) on personalized cards | Low | Accepted. 5% of cards affected. Pedagogical benefit of warm EL voice on openers outweighs latency. |
| **Audio file size** — EL MP3s are ~3–5x larger than Google | Low | S3 cost increase is rounding error. Bandwidth to India: monitor TTFB; existing prefetch in `audioController.ts` (60-entry blob cache) absorbs it. |
| **Admin flips to `google_tts`** after dialogues were authored with emotion | Low | Google synthesis path ignores the `emotion` field by design. No data corruption; just flat audio for that synthesis run. |

## Out of scope (V2+)

- **Per-line emotion on explanation cards.** V1 explanation cards render with EL voice but `emotion=None`; the steady preset gives them smoothness without affect. Adding emotion authoring to the explanation card generator is a V2 task.
- **Rollback infrastructure.** Provider-namespaced S3 paths, instant-flip rollback, audio-version tracking.
- **Cost guard / pre-flight char-budget check.** Build only if quota exhaustion becomes recurring.
- **Listen-test automation** — autoresearch-style quality scoring across the audio library.
- **Per-topic / per-grade voice routing.** Voice IDs hardcoded in V1.
- **Cartesia or third providers.** Plug-in via the same dispatch interface when needed.
- **Hinglish content.** The current dataset is Indian-English; Hinglish would require a separate voice cast and prompt updates.
- **Voice cloning** of a real teacher voice (legal/IP overhead).
- **Streaming TTS** for a "live tutor" mode (only matters if we move off pre-compute).
- **Frontend display of emotion** (e.g., colored speech bubbles). Audio-only V1.

## Open items for PR #4

- **Pick steady preset values** for `emotion=None` lines. Likely high stability (~0.7), lower style (~0.2), `similarity_boost=0.75`, `use_speaker_boost=true`. Tune against an explanation card sample during PR #4.
- **Lock expressive preset values** as bake-off used them: `0.5/0.75/0.4/true`. May want different `style` weights per voice (Sekhar more energetic, Amara more calm) — confirm during PR #4.
- **Audit V2 prompt insertion point** for the emotion field. The V2 prompt is already long; keep the emotion instruction block minimal and well-placed.

## Success criteria

1. Production audio renders with ElevenLabs v3 by default after PR #7; admin toggle returns to Google in one click (for *future* ingestion runs — cached S3 audio is not auto-refreshed on flip).
2. Existing audio library (1 baatcheet dialogue + all explanation card libraries + check-ins) is regenerated without errors on first deploy. No human listen-test gate.
3. Future ingestion runs author per-line emotion for baatcheet dialogues; explanation cards continue to use the steady preset with `emotion=None`.
4. Switching admin config to `google_tts` produces flat-but-functional audio (same as today's behavior).
5. ElevenLabs API outage causes ingestion stage failures (acceptable MVP behavior — no graceful degradation).
