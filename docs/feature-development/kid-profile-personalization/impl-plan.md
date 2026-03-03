# Tech Implementation Plan: Kid Profile Enrichment & Deep Personalization

**Date:** 2026-03-03
**Status:** Draft
**PRD:** `docs/feature-development/kid-profile-personalization/PRD.md`
**Author:** Tech Impl Plan Generator + Manish

---

## 1. Overview

This feature adds a rich, structured kid profile (9 sections of interests, learning styles, personality traits, etc.), uses an LLM to derive a "Kid Personality" from that data, and injects the personality into every teaching interaction — system prompts, welcome messages, and exam questions. The implementation adds two new DB tables (`kid_enrichment_profiles`, `kid_personalities`), new CRUD + personality-derivation endpoints in the `auth` module (since they're profile-scoped), a new frontend enrichment page at `/profile/enrichment`, and targeted changes to the tutor's prompt construction and exam generation. Existing users with no enrichment data experience zero change — the current personalization block is preserved as a fallback.

---

## 2. Architecture Changes

### System Diagram

```
Frontend                           Backend (auth module)              Backend (tutor module)
────────                           ──────────────────                 ─────────────────────
EnrichmentPage.tsx                 PUT /profile/enrichment            SessionService
  ├─ 9 section forms               ├─ Pydantic validation              ├─ _build_student_context_from_profile()
  ├─ PersonalityCard               ├─ EnrichmentRepository.upsert()     │   now loads tutor_brief + personality_json
  └─ saves per-section             ├─ compute inputs_hash              │
                                   ├─ if hash changed →               MasterTutorAgent
GET /profile/personality             BackgroundTask:                    ├─ _build_personalization_block()
  └─ returns latest personality       sleep(5s) → re-check hash         │   now uses tutor_brief when available
                                      → PersonalityService.generate()  │
                                      → LLM call (sanitization)        ExamService
                                      → store in kid_personalities      └─ generate_questions()
                                                                           now adds personality context
```

### New Modules / Major Changes

**New files (backend):**
- `auth/repositories/enrichment_repository.py` — CRUD for `kid_enrichment_profiles`
- `auth/repositories/personality_repository.py` — CRUD for `kid_personalities`
- `auth/services/enrichment_service.py` — enrichment save logic + personality trigger
- `auth/services/personality_service.py` — LLM-based personality derivation
- `auth/models/enrichment_schemas.py` — Pydantic request/response schemas for enrichment + personality
- `auth/api/enrichment_routes.py` — API routes for `/profile/enrichment` and `/profile/personality`
- `auth/prompts/personality_prompts.py` — personality derivation prompt

**New files (frontend):**
- `pages/EnrichmentPage.tsx` — main enrichment page with 9 sections + personality card
- `components/enrichment/` — section components (ChipSelector, PeopleEditor, PersonalityTraits, etc.)

**Modified files (backend):**
- `shared/models/entities.py` — two new ORM models (`KidEnrichmentProfile`, `KidPersonality`)
- `db.py` — migration function for new tables + LLM config seeding
- `main.py` — register new router
- `tutor/models/messages.py` — add `tutor_brief`, `personality_json` to `StudentContext`
- `tutor/agents/master_tutor.py` — update `_build_personalization_block()`
- `tutor/services/session_service.py` — load personality in `_build_student_context_from_profile()`
- `tutor/services/exam_service.py` — inject personality context into exam prompt
- `tutor/prompts/exam_prompts.py` — add personality section to prompt
- `tutor/prompts/orchestrator_prompts.py` — add personality to welcome prompt

**Modified files (frontend):**
- `App.tsx` — add `/profile/enrichment` route
- `api.ts` — new API functions
- `pages/ProfilePage.tsx` — remove `about_me`, add enrichment CTA card

**Decision:** Enrichment and personality code lives in the `auth/` module (not a new top-level module) because the API paths are `/profile/*` and the data is fundamentally profile data. The tutor module only *reads* the derived personality at session start — it doesn't own it.

---

## 3. Database Changes

### New Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `kid_enrichment_profiles` | Raw enrichment data from parents (1 per kid) | `id` UUID PK, `user_id` UUID FK→users UNIQUE, `interests` JSONB, `my_world` JSONB, `learning_styles` JSONB, `motivations` JSONB, `strengths` JSONB, `growth_areas` JSONB, `personality_traits` JSONB, `favorite_media` JSONB, `favorite_characters` JSONB, `memorable_experience` TEXT(500), `aspiration` TEXT(200), `parent_notes` TEXT(1000), `attention_span` VARCHAR (`short`/`medium`/`long`), `pace_preference` VARCHAR (`slow`/`balanced`/`fast`), `created_at` TIMESTAMP, `updated_at` TIMESTAMP |
| `kid_personalities` | LLM-derived personality versions | `id` UUID PK, `user_id` UUID FK→users, `personality_json` JSONB, `tutor_brief` TEXT, `status` VARCHAR (`generating`/`ready`/`failed`), `inputs_hash` VARCHAR, `generator_model` VARCHAR, `version` INT, `created_at` TIMESTAMP |

### Relationships
```
users ──1:1──► kid_enrichment_profiles  (UNIQUE constraint on user_id)
users ──1:N──► kid_personalities        (versioned, latest = active)
```

### Indexes
- `kid_enrichment_profiles`: unique index on `user_id`
- `kid_personalities`: composite index on `(user_id, version DESC)` for fetching latest

### Migration Plan

In `db.py`, add a migration function following the existing pattern. The ORM models are defined in `shared/models/entities.py` (same file as all other ORM models), so `Base.metadata.create_all()` — which already runs at the top of `migrate()` — will create the tables automatically when they don't exist. The migration function handles the LLM config seeding:

```python
def _apply_kid_enrichment_tables(engine):
    """Create kid_enrichment_profiles and kid_personalities tables + seed LLM config.

    Tables are created by Base.metadata.create_all() (the ORM models are in entities.py).
    This function handles the LLM config seed for existing deployments where
    _LLM_CONFIG_SEEDS won't run (it only seeds when the table is empty).
    """
    # Seed personality_derivation config for existing deployments
    # (new deployments get it via _LLM_CONFIG_SEEDS)
    with Session(engine) as session:
        existing = session.query(LLMConfig).filter_by(
            component_key="personality_derivation"
        ).first()
        if not existing:
            # Copy provider/model from the tutor config
            tutor_config = session.query(LLMConfig).filter_by(
                component_key="tutor"
            ).first()
            if tutor_config:
                session.add(LLMConfig(
                    component_key="personality_derivation",
                    provider=tutor_config.provider,
                    model_id=tutor_config.model_id,
                    description="Kid personality derivation from enrichment profile",
                ))
                session.commit()
                logger.info("Seeded personality_derivation LLM config (copied from tutor)")
```

Also add `"personality_derivation"` to `_LLM_CONFIG_SEEDS` for fresh deployments (using the tutor's default provider/model).

**Decision:** ORM models live in `shared/models/entities.py` — matching the existing convention where every ORM model is defined there. This ensures `Base.metadata.create_all()` picks them up automatically without needing explicit `__table__.create()` calls. The LLM config seed is done explicitly in the migration function (not just in `_LLM_CONFIG_SEEDS`) because the seed list only runs on empty tables — existing deployments would miss it.

**No data backfill needed.** Both tables start empty. Existing users simply have no enrichment profile — the fallback behavior (current personalization block) handles them.

---

## 4. Backend Changes

### 4.1 Auth Module — Enrichment & Personality

#### ORM Models (`shared/models/entities.py`)

Add both models to the existing `entities.py` file alongside all other ORM models:

```python
class KidEnrichmentProfile(Base):
    __tablename__ = "kid_enrichment_profiles"
    id = Column(String, primary_key=True)          # UUID
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    interests = Column(JSONB, nullable=True)        # string[]
    my_world = Column(JSONB, nullable=True)         # {name, relationship}[]
    learning_styles = Column(JSONB, nullable=True)  # string[]
    motivations = Column(JSONB, nullable=True)      # string[]
    strengths = Column(JSONB, nullable=True)        # string[]
    growth_areas = Column(JSONB, nullable=True)     # string[]
    personality_traits = Column(JSONB, nullable=True) # {trait, value}[]
    favorite_media = Column(JSONB, nullable=True)   # string[]
    favorite_characters = Column(JSONB, nullable=True) # string[]
    memorable_experience = Column(Text, nullable=True)
    aspiration = Column(Text, nullable=True)
    parent_notes = Column(Text, nullable=True)
    attention_span = Column(String, nullable=True)  # short/medium/long
    pace_preference = Column(String, nullable=True) # slow/balanced/fast
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class KidPersonality(Base):
    __tablename__ = "kid_personalities"
    id = Column(String, primary_key=True)           # UUID
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    personality_json = Column(JSONB, nullable=True)
    tutor_brief = Column(Text, nullable=True)
    status = Column(String, default="generating")   # generating/ready/failed
    inputs_hash = Column(String, nullable=True)
    generator_model = Column(String, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=func.now())
    # Index: (user_id, version DESC)
```

#### Pydantic Schemas (`auth/models/enrichment_schemas.py`)

```python
# --- Enrichment ---

VALID_RELATIONSHIPS = Literal[
    "Mom", "Dad", "Brother", "Sister", "Grandparent",
    "Cousin", "Uncle", "Aunt", "Friend", "Neighbor", "Teacher", "Pet"
]

# Alphanumeric + spaces + common diacritics (Hindi/Indian names)
NAME_PATTERN = r'^[\w\s\u0900-\u097F\u00C0-\u024F\.\'-]+$'

class MyWorldEntry(BaseModel):
    name: str = Field(max_length=50, pattern=NAME_PATTERN)
    relationship: VALID_RELATIONSHIPS

class PersonalityTrait(BaseModel):
    trait: str
    value: str

class EnrichmentProfileRequest(BaseModel):
    """Partial update — all fields optional."""
    interests: Optional[list[str]] = None
    my_world: Optional[list[MyWorldEntry]] = Field(default=None, max_length=15)
    learning_styles: Optional[list[str]] = None
    motivations: Optional[list[str]] = None
    strengths: Optional[list[str]] = None
    growth_areas: Optional[list[str]] = None
    personality_traits: Optional[list[PersonalityTrait]] = None
    favorite_media: Optional[list[str]] = None
    favorite_characters: Optional[list[str]] = None
    memorable_experience: Optional[str] = Field(default=None, max_length=500)
    aspiration: Optional[str] = Field(default=None, max_length=200)
    parent_notes: Optional[str] = Field(default=None, max_length=1000)
    attention_span: Optional[Literal["short", "medium", "long"]] = None
    pace_preference: Optional[Literal["slow", "balanced", "fast"]] = None

class EnrichmentProfileResponse(BaseModel):
    """Full profile — nulls for unfilled sections."""
    interests: Optional[list[str]]
    my_world: Optional[list[MyWorldEntry]]
    learning_styles: Optional[list[str]]
    motivations: Optional[list[str]]
    strengths: Optional[list[str]]
    growth_areas: Optional[list[str]]
    personality_traits: Optional[list[PersonalityTrait]]
    favorite_media: Optional[list[str]]
    favorite_characters: Optional[list[str]]
    memorable_experience: Optional[str]
    aspiration: Optional[str]
    parent_notes: Optional[str]
    attention_span: Optional[str]
    pace_preference: Optional[str]
    personality_status: Optional[str]  # generating/ready/failed/none
    sections_filled: int  # 0-9 count for progress indicator
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

# --- Personality ---
class PersonalityResponse(BaseModel):
    personality_json: Optional[dict]
    tutor_brief: Optional[str]
    status: str  # generating/ready/failed/none
    updated_at: Optional[datetime]
```

#### API Layer (`auth/api/enrichment_routes.py`)

| Endpoint | Method | Path | Purpose |
|----------|--------|------|---------|
| get_enrichment | GET | `/profile/enrichment` | Get kid's enrichment profile (empty object if none) |
| update_enrichment | PUT | `/profile/enrichment` | Create or update (partial), triggers personality regen |
| get_personality | GET | `/profile/personality` | Get latest derived personality + status |
| regenerate_personality | POST | `/profile/personality/regenerate` | Force regeneration (debug) |

All endpoints require `Depends(get_current_user)`.

**PUT `/profile/enrichment` response shape:**
```json
{
  "personality_status": "generating" | "unchanged" | "none",
  "sections_filled": 5
}
```

**Decision:** The PUT response is minimal (status + count) rather than echoing the full profile back. The frontend already has the data it just sent — it only needs to know if regeneration was triggered.

#### Repository Layer (`auth/repositories/enrichment_repository.py`)

**`EnrichmentRepository`**
- `get_by_user_id(user_id) → Optional[KidEnrichmentProfile]`
- `upsert(user_id, **fields) → KidEnrichmentProfile` — get-or-create, then `setattr` for each provided field
- `get_all_fields_as_dict(user_id) → dict` — returns all enrichment fields as a dict (for hash computation)

**`PersonalityRepository`** (`auth/repositories/personality_repository.py`)
- `create(user_id, inputs_hash, generator_model) → KidPersonality` — creates with `status="generating"`, auto-increments version
- `get_latest(user_id) → Optional[KidPersonality]` — order by `version DESC`, limit 1
- `get_latest_ready(user_id) → Optional[KidPersonality]` — same but filters `status="ready"`
- `update_status(personality_id, status, personality_json=None, tutor_brief=None)` — updates after LLM call completes
- `get_latest_hash(user_id) → Optional[str]` — returns `inputs_hash` of latest personality (for skip check)

#### Service Layer (`auth/services/enrichment_service.py`)

**`EnrichmentService`**
```python
def __init__(self, db: Session):
    self.db = db
    self.enrichment_repo = EnrichmentRepository(db)
    self.personality_repo = PersonalityRepository(db)
    self.user_repo = UserRepository(db)
```

- `get_profile(user_id) → EnrichmentProfileResponse` — fetches enrichment + latest personality status, computes `sections_filled`
- `update_profile(user_id, request: EnrichmentProfileRequest) → dict` — upserts enrichment, computes inputs_hash, returns `{"personality_status": ..., "sections_filled": ...}`
- `compute_inputs_hash(user_id) → str` — builds canonical JSON from enrichment + basic profile fields (name, age, grade, board, about_me), returns SHA256
- `should_regenerate(user_id, new_hash) → bool` — compares with latest personality's `inputs_hash`
- `has_meaningful_data(profile) → bool` — returns True if at least 1 of the 9 main sections has data. Session preferences alone (attention_span, pace_preference) are not sufficient to trigger personality generation.

**`sections_filled` mapping** — DB columns → 9 PRD sections:

| Section # | PRD Section | Columns Checked (non-null and non-empty) |
|-----------|-------------|------------------------------------------|
| 1 | Interests & Hobbies | `interests` |
| 2 | My World | `my_world` |
| 3 | How They Learn | `learning_styles` |
| 4 | What Motivates | `motivations` |
| 5 | Superpowers | `strengths` |
| 6 | Areas to Grow | `growth_areas` |
| 7 | Personality | `personality_traits` |
| 8 | Favorites & Fun Facts | any of: `favorite_media`, `favorite_characters`, `memorable_experience`, `aspiration` |
| 9 | Parent's Notes | `parent_notes` |

A section counts as "filled" if its column(s) contain non-null, non-empty data. Section 8 counts as filled if *any* of its 4 columns has data.

#### Service Layer (`auth/services/personality_service.py`)

**`PersonalityService`**
```python
def __init__(self, db: Session):
    self.db = db
    self.enrichment_repo = EnrichmentRepository(db)
    self.personality_repo = PersonalityRepository(db)
    self.user_repo = UserRepository(db)
    # LLM config loaded from DB
    config = LLMConfigService(db).get_config("personality_derivation")
    self.llm = LLMService(api_key=..., provider=config["provider"], model_id=config["model_id"])
```

- `generate_personality(user_id) → KidPersonality` — the core method:
  1. Load enrichment profile + basic user fields
  2. Re-compute inputs_hash (debounce: re-check after 5s sleep)
  3. If hash matches latest personality, skip (return existing)
  4. Create a new `kid_personalities` row with `status="generating"`
  5. Build derivation prompt from all raw inputs
  6. Call LLM with strict JSON schema for the 10-field personality + tutor brief
  7. Parse and validate output
  8. Update row with `status="ready"`, `personality_json`, `tutor_brief`
  9. On failure: update row with `status="failed"`
- `get_latest_personality(user_id) → Optional[PersonalityResponse]`
- `force_regenerate(user_id) → KidPersonality` — bypasses hash check

#### Personality Derivation Prompt (`auth/prompts/personality_prompts.py`)

A single `PERSONALITY_DERIVATION_PROMPT` template that:
1. Instructs the LLM to synthesize a kid personality from raw parent-provided data
2. Includes the sanitization boundary instructions (per PRD R2)
3. Specifies the exact 10-field JSON output schema + tutor brief
4. Includes rules for handling sparse inputs, contradictions, and no-hallucination
5. Includes sensitivity guidance for `people_to_reference` (prefer friends/siblings over parents for sharing problems, pets always safe)

**Output JSON schema:**
```json
{
  "teaching_approach": "string",
  "example_themes": ["string"],
  "people_to_reference": [{"name": "string", "context": "string"}],
  "communication_style": "string",
  "encouragement_strategy": "string",
  "pace_guidance": "string",
  "strength_leverage": "string",
  "growth_focus": "string",
  "things_to_avoid": "string",
  "fun_hooks": "string",
  "tutor_brief": "string (150-200 words compact prose)"
}
```

**Decision:** `tutor_brief` is generated in the same LLM call as the structured JSON (not a separate call). The derivation prompt asks for both outputs. This is more efficient (one LLM call) and ensures consistency between the JSON and the brief.

#### Debounce Mechanism

The PUT endpoint triggers personality regeneration via FastAPI's `BackgroundTasks`:

```python
@router.put("/profile/enrichment")
async def update_enrichment(
    request: EnrichmentProfileRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = EnrichmentService(db)
    result = service.update_profile(user.id, request)

    if result["personality_status"] == "generating":
        background_tasks.add_task(
            _debounced_regenerate, user.id, result["inputs_hash"]
        )

    return result


def _debounced_regenerate(user_id: str, expected_hash: str):
    """Sleep 5s, re-check hash, then regenerate if still needed."""
    import time
    time.sleep(5)

    # Use db_manager.session_scope() for proper lifecycle management
    # (commit on success, rollback on error, always closes)
    from database import get_db_manager
    with get_db_manager().session_scope() as db:
        service = EnrichmentService(db)
        current_hash = service.compute_inputs_hash(user_id)
        if current_hash != expected_hash:
            # Parent saved again within 5s — a newer task will handle it
            return

        # Only regenerate if at least 1 of the 9 main sections has data
        profile = service.enrichment_repo.get_by_user_id(user_id)
        if not profile or not service.has_meaningful_data(profile):
            return

        personality_service = PersonalityService(db)
        personality_service.generate_personality(user_id)
```

**Decision:** Simple `time.sleep(5)` in a background task thread. Uses `db_manager.session_scope()` (the existing context manager in `database.py`) instead of `next(get_db())` — this properly handles commit/rollback/close lifecycle. The inputs_hash re-check handles dedup: if a second save happened within 5s, its background task will see a different hash and the final regeneration runs only once. The `has_meaningful_data()` check prevents triggering LLM generation when only session preferences (attention_span/pace_preference) are filled and no actual enrichment sections have content.

---

### 4.2 Tutor Module — Personality Integration

#### `StudentContext` Changes (`tutor/models/messages.py`)

Add two fields:
```python
class StudentContext(BaseModel):
    # ... existing fields ...
    tutor_brief: Optional[str] = Field(default=None)
    personality_json: Optional[dict] = Field(default=None)
```

#### Session Creation (`tutor/services/session_service.py`)

In `_build_student_context_from_profile()`, after building the basic `StudentContext`, load the personality:

```python
def _build_student_context_from_profile(self, user_id, request):
    user = UserRepository(self.db).get_by_id(user_id)
    if not user or not user.grade or not user.board:
        return StudentContext(grade=request.student.grade, ...)

    # Load personality (if exists)
    from auth.repositories.personality_repository import PersonalityRepository
    personality_repo = PersonalityRepository(self.db)
    personality = personality_repo.get_latest_ready(user_id)

    tutor_brief = None
    personality_json = None
    preferred_examples = ["food", "sports", "games"]  # default

    if personality:
        tutor_brief = personality.tutor_brief
        personality_json = personality.personality_json
        if personality_json and personality_json.get("example_themes"):
            preferred_examples = personality_json["example_themes"]

    return StudentContext(
        grade=user.grade,
        board=user.board,
        language_level="simple" if (user.age and user.age <= 10) else "standard",
        preferred_examples=preferred_examples,
        student_name=user.preferred_name or user.name,
        student_age=user.age,
        about_me=user.about_me,
        text_language_preference=user.text_language_preference or 'en',
        audio_language_preference=user.audio_language_preference or 'en',
        tutor_brief=tutor_brief,
        personality_json=personality_json,
    )
```

#### System Prompt Personalization (`tutor/agents/master_tutor.py`)

Replace `_build_personalization_block()`:

```python
@staticmethod
def _build_personalization_block(ctx) -> str:
    # If tutor_brief exists, use it (rich personality)
    if getattr(ctx, 'tutor_brief', None):
        return f"## Student Personality Profile\n{ctx.tutor_brief}\n"

    # Fallback: current minimal personalization
    lines = []
    if getattr(ctx, 'student_name', None):
        lines.append(f"The student's name is {ctx.student_name}. Address them by name.")
    if getattr(ctx, 'student_age', None):
        lines.append(f"The student is {ctx.student_age} years old.")
    if getattr(ctx, 'about_me', None):
        lines.append(f"About the student: {ctx.about_me}")
    if not lines:
        return ""
    return "## Student Profile\n" + "\n".join(lines) + "\n"
```

**Decision:** The heading changes from "Student Profile" to "Student Personality Profile" when the tutor brief is used. This signals to the LLM that the personalization data is richer and more detailed.

#### Welcome Message (`tutor/orchestration/orchestrator.py`)

**Note:** The current welcome message prompts (`WELCOME_MESSAGE_PROMPT`, `generate_clarify_welcome()`, `generate_exam_welcome()`) have *no* student name or personality context — they only pass `grade`, `topic_name`, `language_level`, `preferred_examples`, and language instructions. This is a **new addition**, not an augmentation of existing personalization.

In `generate_welcome_message()`, append personality context to the prompt:

```python
# After existing prompt construction, before LLM call:
if session.student_context.tutor_brief:
    prompt += (
        f"\n\nStudent Personality:\n{session.student_context.tutor_brief}\n\n"
        "Use this personality to make the welcome message feel personal and tailored. "
        "Address the student by name."
    )
elif session.student_context.student_name:
    prompt += f"\n\nThe student's name is {session.student_context.student_name}. Address them by name."
```

Similarly for `generate_clarify_welcome()` and `generate_exam_welcome()`. The `elif` ensures even non-enrichment users get name-based welcome messages (a minor improvement over current behavior).

#### Exam Question Personalization (`tutor/services/exam_service.py` + `tutor/prompts/exam_prompts.py`)

Add a `{personalization_section}` template variable to `EXAM_QUESTION_GENERATION_PROMPT`. This is cleaner than string concatenation — the template is self-documenting and the variable defaults to empty when no personality exists.

**Prompt change** (`exam_prompts.py`): Add at the end of the template, before the output instructions:

```
{personalization_section}
```

**Service change** (`exam_service.py`): Build the personalization section and pass it as a template variable:

```python
def _build_exam_personalization(self, session: SessionState) -> str:
    """Build personalization section for exam question generation."""
    pj = session.student_context.personality_json
    if not pj:
        return ""

    names = []
    for p in pj.get("people_to_reference", []):
        names.append(f"- {p['name']} ({p['context']})")
    themes = pj.get("example_themes", [])

    return (
        "\n## Personalization (use in ~30-50% of questions, not all)\n"
        f"Student's name: {session.student_context.student_name}\n"
        f"Interests/themes: {', '.join(themes)}\n"
        f"People to reference in problems:\n" + "\n".join(names) + "\n"
        "Use these naturally in word problem scenarios. "
        "Keep core mathematical rigor — only the window dressing is personalized. "
        "Don't personalize every question — use generic Indian names/contexts for the rest."
    )
```

Pass to `render()`:
```python
prompt = EXAM_QUESTION_GENERATION_PROMPT.render(
    ...,  # existing params
    personalization_section=self._build_exam_personalization(session),
)
```

The `_retry_with_fewer` method also passes this parameter (it re-renders the prompt, so it gets the same personalization).

**Decision:** Using a template variable instead of string concatenation. The template is self-documenting — you can see that `{personalization_section}` exists by reading the prompt file. The variable defaults to `""` when no personality exists, so the no-personalization path is clean. Both the primary and retry paths pass the same parameter.

---

### 4.3 Profile Route Changes

In `auth/api/profile_routes.py`, trigger personality regeneration when basic profile fields change:

```python
@router.put("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # ... existing update logic ...

    # If name/age/grade/board changed and enrichment exists, trigger regen
    personality_triggering_fields = {'name', 'preferred_name', 'age', 'grade', 'board'}
    changed_fields = {k for k, v in request.dict(exclude_unset=True).items() if v is not None}
    if changed_fields & personality_triggering_fields:
        enrichment_repo = EnrichmentRepository(db)
        if enrichment_repo.get_by_user_id(user.id):
            enrichment_service = EnrichmentService(db)
            new_hash = enrichment_service.compute_inputs_hash(user.id)
            if enrichment_service.should_regenerate(user.id, new_hash):
                background_tasks.add_task(_debounced_regenerate, user.id, new_hash)
```

---

## 5. Frontend Changes

### New Pages

| Route | Component | Purpose |
|-------|-----------|---------|
| `/profile/enrichment` | `EnrichmentPage.tsx` | 9-section enrichment form + personality card |

### Modified Pages

| Component | Changes |
|-----------|---------|
| `ProfilePage.tsx` | Remove `about_me` textarea, add "Help us know {name} better" CTA card linking to `/profile/enrichment`. Add migration banner for users with `about_me` but no enrichment. **Note:** The CTA card is a pure navigation link (`navigate('/profile/enrichment')`) — no API call needed. The `about_me` migration check uses `user.about_me` from `AuthContext` (already available). The existing `ProfilePage` uses raw `fetch()` instead of `apiFetch()` — follow the same pattern for any new API calls on this page. |
| `App.tsx` | Add route: `<Route path="/profile/enrichment" element={<ProtectedRoute><EnrichmentPage /></ProtectedRoute>} />` |

### New Components

**`pages/EnrichmentPage.tsx`** — Main page. Manages:
- Fetches enrichment profile on mount via `GET /profile/enrichment`
- 9 collapsible section cards (accordion pattern, one open at a time)
- Progress indicator (X of 9 sections filled)
- Auto-save on section blur/close (PUT with just that section's fields)
- `PersonalityCard` at the bottom
- Back button to `/profile`

**`components/enrichment/ChipSelector.tsx`** — Reusable multi-select chip component.
- Props: `options: string[]`, `selected: string[]`, `onChange`, `allowCustom: boolean`
- Renders chips as buttons, toggles selection on click
- "Add your own" chip opens a text input when `allowCustom=true`
- Used by Sections 1, 3, 4, 5, 6

**`components/enrichment/PeopleEditor.tsx`** — Repeating card for Section 2 (My World).
- Name text input + Relationship dropdown per entry
- "Add another" button (max 15)
- Delete button per entry

**`components/enrichment/PersonalitySliders.tsx`** — Binary choice pairs for Section 7.
- Each pair rendered as two buttons (left vs right)
- Active choice highlighted

**`components/enrichment/FavoritesSection.tsx`** — Section 8 with tag inputs + textarea.
- Tag input: type + Enter to add, click X to remove
- Textarea for memorable experience (char counter, max 500)
- Text input for aspiration

**`components/enrichment/PersonalityCard.tsx`** — Read-only card showing derived personality.
- Fetches `GET /profile/personality` on mount
- **Status states:**
  - `ready` → Renders friendly sections from `personality_json`: "How we'll teach", "Examples we'll use", etc. Shows "Last updated" timestamp.
  - `generating` → Shows the previous personality (if any) with an "Updating..." badge. If no previous personality, shows a spinner with "Creating {name}'s learning profile..."
  - `failed` → Shows "We couldn't generate the profile — try again" message with a "Retry" button that calls `POST /profile/personality/regenerate`. If a previous `ready` personality exists, shows it with a "Last update failed — retry?" banner.
  - `none` (no enrichment data yet) → Shows motivational prompt: "Fill in a few sections above and we'll create a personalized learning profile for {name}!"

**`components/enrichment/SessionPreferences.tsx`** — Attention span + pace preference.
- Single-select chip groups

**`components/enrichment/SectionCard.tsx`** — Wrapper component for each section.
- Collapsible (accordion behavior)
- Section title + helper text
- Filled/empty indicator icon
- onClick toggles open/close

### API Client Changes (`api.ts`)

```typescript
// Enrichment
export async function getEnrichmentProfile(): Promise<EnrichmentProfileResponse> { ... }
export async function updateEnrichmentProfile(data: Partial<EnrichmentProfileRequest>): Promise<{ personality_status: string; sections_filled: number }> { ... }

// Personality
export async function getPersonality(): Promise<PersonalityResponse> { ... }
export async function regeneratePersonality(): Promise<void> { ... }
```

Plus corresponding TypeScript interfaces matching the Pydantic schemas.

### State Management

No new React Context needed. The enrichment page manages its own local state. The personality data is fetched on-demand (no global caching required since it's only displayed on the enrichment page and loaded into `StudentContext` server-side at session start).

### CSS

All new styles added to `App.css` using the existing naming convention:
- `.enrichment-*` prefix for the enrichment page
- `.chip-*` prefix for chip selectors
- `.personality-card-*` prefix for the personality card
- Reuse existing color palette (`#667eea` / `#764ba2` gradient, status colors)

---

## 6. LLM Integration

### Personality Derivation

**Agent:** Not a formal `BaseAgent` subclass — this is a one-shot LLM call in `PersonalityService`, similar to how `ExamService.generate_questions()` works. No need for the agent framework since there's no multi-turn interaction.

**Prompt design:** Single prompt that receives all raw profile data and produces both the structured personality JSON and the tutor brief in one call.

**Structured output:** Uses strict JSON schema mode (same pattern as exam generation). The schema enforces the 10 personality fields + tutor_brief.

**Model:** Configured via `llm_config` table with component key `"personality_derivation"`. Default seed: same provider/model as the `"tutor"` component.

**Decision:** Using the same model as the tutor ensures the personality brief is written in a style the tutor model understands well. The personality derivation is a one-shot summarization task that doesn't need a more powerful model.

### Cost and Latency

- **Input tokens:** ~500-1500 tokens (profile data) + ~800 tokens (prompt instructions) = ~1300-2300 tokens
- **Output tokens:** ~400-600 tokens (10 JSON fields + 200-word brief)
- **Estimated cost:** ~$0.01-0.03 per derivation (varies by model)
- **Latency:** 5-10 seconds (acceptable — runs in background, not blocking UI)
- **Frequency:** Only on profile changes (rare — parents fill this once, maybe update occasionally)
- **No caching needed** — inputs_hash check prevents redundant regeneration

---

## 7. Configuration & Environment

### New Environment Variables

None. The personality derivation model is configured via the `llm_config` DB table, same as all other LLM components.

### Config Changes

No changes to `config.py`. LLM config seeding handled in two places:

1. **`_LLM_CONFIG_SEEDS`** (for fresh deployments): Add a `"personality_derivation"` entry using the same provider/model as the `"tutor"` seed.
2. **`_apply_kid_enrichment_tables()`** migration (for existing deployments): Copies provider/model from the existing `tutor` config row (see Section 3, Migration Plan).

This ensures the config row exists regardless of whether the deployment is new or existing. The admin can change the model post-deployment via the LLM Config admin page.

---

## 8. Implementation Order

Order rationale: Database first → Repository → Service → API → Frontend. Each layer depends on the one below. Phase 1 (CRUD) is fully testable without LLM. Phase 2 (LLM derivation) builds on stored data. Phase 3 (tutor integration) requires personalities to exist. Phase 4 (polish) is independent improvements.

### Phase 1: Profile Collection (Frontend + Backend CRUD)

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1.1 | ORM models for new tables | `shared/models/entities.py` | — | Run `python db.py --migrate`, verify tables exist |
| 1.2 | DB migration function | `db.py` | 1.1 | `python db.py --migrate` creates both tables |
| 1.3 | Pydantic schemas | `auth/models/enrichment_schemas.py` | — | Unit test validation rules |
| 1.4 | Enrichment repository | `auth/repositories/enrichment_repository.py` | 1.1 | Unit test with in-memory DB |
| 1.5 | Enrichment service (CRUD only, no personality trigger yet) | `auth/services/enrichment_service.py` | 1.3, 1.4 | Unit test: save/load enrichment data |
| 1.6 | API routes (GET/PUT enrichment) | `auth/api/enrichment_routes.py`, `main.py` | 1.5 | curl / Swagger: create + fetch enrichment |
| 1.7 | Frontend API functions | `llm-frontend/src/api.ts` | 1.6 | Manual: call from browser console |
| 1.8 | Enrichment page (all 9 sections + session prefs) | `llm-frontend/src/pages/EnrichmentPage.tsx`, `components/enrichment/*` | 1.7 | Manual: fill sections, verify saves |
| 1.9 | Add route + navigation | `App.tsx`, `ProfilePage.tsx` | 1.8 | Manual: navigate from Profile → Enrichment |
| 1.10 | Remove `about_me` from Profile, add migration banner | `ProfilePage.tsx` | 1.9 | Manual: verify `about_me` gone, banner shows for existing users |

### Phase 2: Personality Derivation (LLM Processing)

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 2.1 | Personality repository | `auth/repositories/personality_repository.py` | 1.1 | Unit test with in-memory DB |
| 2.2 | Personality derivation prompt | `auth/prompts/personality_prompts.py` | — | Review prompt text |
| 2.3 | Personality service (LLM call + hash logic) | `auth/services/personality_service.py` | 2.1, 2.2 | Unit test with mocked LLM; integration test with real LLM |
| 2.4 | Wire debounced trigger into enrichment PUT | `auth/api/enrichment_routes.py`, `auth/services/enrichment_service.py` | 2.3 | Save enrichment → verify personality row created after 5s |
| 2.5 | Personality API (GET + POST regenerate) | `auth/api/enrichment_routes.py` | 2.3 | curl: GET personality after enrichment save |
| 2.6 | Seed LLM config (both `_LLM_CONFIG_SEEDS` and migration function) | `db.py` | — | Verify `personality_derivation` row in `llm_config` (both fresh DB and existing DB) |
| 2.7 | Frontend: PersonalityCard on enrichment page | `components/enrichment/PersonalityCard.tsx`, `EnrichmentPage.tsx` | 2.5 | Manual: fill enrichment → wait → see personality card |

### Phase 3: Teaching Personalization (Tutor Integration)

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 3.1 | Add `tutor_brief`, `personality_json` to StudentContext | `tutor/models/messages.py` | — | Unit test: model accepts new fields |
| 3.2 | Load personality in session creation | `tutor/services/session_service.py` | 2.1, 3.1 | Unit test: verify StudentContext has personality |
| 3.3 | Update `_build_personalization_block()` | `tutor/agents/master_tutor.py` | 3.1 | Unit test: verify tutor brief used when present, fallback when not |
| 3.4 | Update welcome messages | `tutor/orchestration/orchestrator.py` | 3.1 | Integration test: welcome message with personality |
| 3.5 | Update exam question generation (add `{personalization_section}` template var) | `tutor/services/exam_service.py`, `tutor/prompts/exam_prompts.py` | 3.1 | Integration test: exam questions use kid's names/interests |
| 3.6 | Remove hardcoded `preferred_examples` default path | `tutor/services/session_service.py` | 3.2 | Unit test: verify examples come from personality when available |

### Phase 4: Polish

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 4.1 | Trigger personality regen on basic profile changes | `auth/api/profile_routes.py` | 2.3 | Change name → verify personality regenerated |
| 4.2 | Home screen prompt for empty enrichment | `llm-frontend/src/pages/SubjectSelect.tsx` or `LearnLayout.tsx` | 1.6 | Manual: new user sees prompt |
| 4.3 | Attention span → session length warnings | `tutor/orchestration/orchestrator.py` or `tutor/agents/master_tutor.py` | 3.2 | Integration test: long session triggers gentle reminder |

---

## 9. Testing Plan

### Unit Tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_enrichment_repository_upsert` | Create and update enrichment profile | In-memory SQLite DB |
| `test_enrichment_repository_partial_update` | Only provided fields are updated, others unchanged | In-memory DB |
| `test_personality_repository_versioning` | Multiple versions created, latest fetched correctly | In-memory DB |
| `test_personality_repository_latest_ready` | Only `status=ready` personalities are returned | In-memory DB |
| `test_enrichment_schema_validation` | Pydantic rejects invalid data (too-long strings, invalid enums) | None |
| `test_enrichment_schema_partial` | All fields optional, partial updates work | None |
| `test_my_world_name_validation` | Name max 50 chars, alphanumeric+diacritics only, rejects special chars | None |
| `test_my_world_relationship_validation` | Relationship must be one of the 12 valid options, rejects invalid values | None |
| `test_my_world_max_entries` | List rejects >15 entries | None |
| `test_text_field_max_length` | `memorable_experience` max 500, `aspiration` max 200, `parent_notes` max 1000 | None |
| `test_sections_filled_count` | Correct count: section 8 counts as filled when any of its 4 fields has data | None |
| `test_has_meaningful_data` | Returns False when only session prefs filled, True when any main section filled | None |
| `test_compute_inputs_hash_deterministic` | Same inputs produce same hash, different inputs produce different hash | Mock repo |
| `test_compute_inputs_hash_includes_basic_fields` | Hash changes when name/age/grade change | Mock repo |
| `test_personality_service_skips_unchanged` | No LLM call when inputs_hash matches | Mock LLM, mock repo |
| `test_personality_service_generates` | LLM called, output parsed and stored | Mock LLM returning fixture |
| `test_personality_service_handles_failure` | Status set to `failed` on LLM error | Mock LLM raising exception |
| `test_build_personalization_block_with_tutor_brief` | Returns tutor brief when available | None |
| `test_build_personalization_block_fallback` | Returns minimal block when no tutor brief | None |
| `test_student_context_loads_personality` | `_build_student_context_from_profile` populates tutor_brief and personality_json | Mock repos |
| `test_preferred_examples_from_personality` | `preferred_examples` comes from `personality_json.example_themes` | Mock repos |
| `test_preferred_examples_default_fallback` | Default `["food", "sports", "games"]` when no personality | Mock repos |

### Integration Tests

| Test | What it Verifies |
|------|------------------|
| `test_enrichment_crud_api` | PUT then GET enrichment returns saved data |
| `test_enrichment_partial_update_api` | Two PUTs with different sections, GET returns both |
| `test_personality_generation_end_to_end` | Save enrichment → personality generated → GET returns ready personality |
| `test_personality_card_after_enrichment` | GET personality returns structured JSON matching expected schema |
| `test_session_with_personality` | Create session for user with personality → verify system prompt includes tutor brief |

### Manual Verification

1. **Enrichment page flow:** Navigate Profile → "Help us know {name} better" → fill 3+ sections → save → see "Updating..." badge → refresh → see personality card
2. **Minimal data:** Fill only interests (1 section) → verify personality card says "learning style preferences not yet known"
3. **Fallback:** Start a session as a user with no enrichment → verify old-style personalization block in prompts (check server logs)
4. **Personalized session:** Fill enrichment → start teach_me session → verify welcome message uses kid's name and personality traits
5. **Personalized exam:** Fill enrichment with friends' names → start exam → verify some questions use those names
6. **about_me migration:** As a user with existing `about_me` → go to enrichment page → see migration banner → accept → verify parent_notes pre-filled

---

## 10. Deployment Considerations

### Migration Order

1. Deploy backend with new migration code first → `python db.py --migrate` creates the two new tables
2. Deploy the `personality_derivation` LLM config seed (happens automatically in migration)
3. Deploy frontend changes

The migration is purely additive (new tables, no column changes to existing tables), so it's safe to deploy alongside code changes.

### Infrastructure Changes

- No new infra resources needed
- No new environment variables
- The `personality_derivation` LLM config row is seeded automatically
- Admin can change the model via the existing LLM Config admin page

### Rollback Plan

- **Backend rollback:** Revert to previous Docker image. New tables remain but are unused. No data loss — enrichment data is preserved.
- **Frontend rollback:** Revert to previous S3 deployment. The enrichment route simply disappears from the frontend.
- **No breaking changes:** Existing sessions, profiles, and tutor behavior are unaffected. The tutor brief fallback path ensures sessions work identically when no personality exists.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Personality derivation LLM produces poor/inconsistent output | Medium | Medium | Strict JSON schema enforces structure. Prompt includes detailed examples and rules. Manual review of first few outputs before wider rollout. |
| Prompt injection via free-text fields (parent_notes, memorable_experience) | Low | High | LLM acts as sanitization boundary — raw text never reaches tutor prompt. Derivation prompt includes explicit anti-injection instructions. Character limits bound the attack surface. |
| Debounce race condition (two background tasks both proceed) | Low | Low | Inputs hash re-check after 5s sleep prevents stale regeneration. Worst case: two personality versions created (both correct), latest wins. |
| Tutor brief too long, inflating per-turn token costs | Low | Medium | Prompt instructs 150-200 words (~200-250 tokens). Monitor output length. Can add a truncation guard in `_build_personalization_block()`. |
| Large enrichment page UI complexity, mobile usability | Medium | Medium | Accordion pattern keeps one section visible at a time. Test on mobile early. Chip selectors minimize typing. |
| Background task fails silently (App Runner restarts, OOM) | Low | Low | Personality card shows "Updating..." → parent can refresh. Force-regenerate endpoint available. Status tracking in DB reveals failures. |

---

## 12. Open Questions

1. **About_me migration UX:** Should the migration banner on the enrichment page auto-fill parent_notes, or just show the old `about_me` text and let the parent decide which section it belongs in? (PRD says pre-fill Section 9 — implementing as specified.)

2. **Enrichment page for multiple children:** The current system is one account per child. If the parent has multiple children, they'd need to log into each child's account to fill enrichment. No changes needed for now, but worth noting.

3. **Rate limiting on personality regeneration:** Should we limit how often a parent can trigger regeneration? Currently bounded by the 5s debounce, hash check, and minimum-data threshold — rapid saves produce at most one regeneration per distinct data state. Likely sufficient.
