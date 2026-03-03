# PRD: Kid Profile Enrichment & Deep Personalization

## Context & Problem

### What We Have Today
The student profile collects 6 fields: name, preferred_name, age, grade, board, about_me (free text). The tutor uses these minimally — it addresses the kid by name, adjusts language complexity by age, and injects the about_me text verbatim into the system prompt.

The `preferred_examples` field exists in code but is hardcoded to `["food", "sports", "games"]` — never collected from the student. Study plans are identical for all students. Exam questions use generic Indian names. The tutoring experience feels the same for every kid.

### Why This Matters
This is the core differentiator. A tutor who knows that Arjun loves cricket, struggles with word problems, learns best through stories, gets motivated by challenges, and has a best friend named Rohan — that tutor can teach in a fundamentally different way than a generic one. "If Arjun and Rohan are sharing 12 cricket cards equally..." is a different experience from "If A and B have 12 objects..."

### Desired Outcome
- Parents can fill in a rich, structured profile about their child (on the kid's device, sitting with them)
- An LLM processes all raw inputs into a structured "Kid Personality" — the single source of truth for understanding the child
- Every teaching interaction (lessons, examples, encouragement, exams) is deeply personalized using this personality
- Parents can see the derived personality as a "Here's what we understand about your child" card (read-only — they edit the raw inputs to change it)

---

## Requirements

### R1: Kid Profile Enrichment Page

A dedicated page accessible from the existing Profile page via a prominent card/button ("Help us know {name} better" or similar). The page collects structured information across 8 sections. All fields are optional. The page should feel warm and conversational — not like a clinical form.

**UX Principles:**
- One section visible at a time (accordion or scrollable cards), not a giant form
- Chip/tag selectors over free-text wherever possible (minimal typing)
- Each section has a friendly title and a short helper line explaining why we're asking
- Parent can fill sections in any order, save anytime, come back later
- Progress indicator showing how many sections are filled

#### Section 1: Interests & Hobbies
*"What does {name} enjoy doing?"*

- Multi-select chips from predefined list: Cricket, Football, Basketball, Drawing, Painting, Reading, Gaming, Music, Dance, Cooking, Science experiments, Animals/Pets, Cycling, Swimming, Puzzles, Building/Lego, Watching cartoons/movies, Crafts, Photography, Coding
- "Add your own" chip that opens a text input for custom interests
- Store as: `string[]`

#### Section 2: My World (People & Pets)
*"Tell us about the important people in {name}'s life — we'll use their names in examples and stories."*

- Repeating card pattern: each entry has Name (text) + Relationship (select: Mom, Dad, Brother, Sister, Grandparent, Cousin, Uncle, Aunt, Friend, Neighbor, Teacher, Pet)
- "Add another" button
- Max 15 entries (practical limit)
- Store as: `{name: string, relationship: string}[]`

#### Section 3: How {name} Learns Best
*"Every child learns differently. What works best for {name}?"*

- Multi-select from:
  - "Seeing pictures, diagrams, and visuals" (visual)
  - "Step-by-step explanations" (structured)
  - "Trying things and figuring it out" (exploratory)
  - "Connecting to real life examples" (contextual)
  - "Stories and narratives" (narrative)
  - "Hands-on activities and doing" (kinesthetic)
- Store as: `string[]` (the parenthetical tags)

#### Section 4: What Motivates {name}
*"What makes {name}'s eyes light up when learning?"*

- Multi-select from:
  - "Loves challenges and competing" (challenge)
  - "Lights up with praise and encouragement" (praise)
  - "Wants to know why this matters in real life" (relevance)
  - "Enjoys creating and being imaginative" (creative)
  - "Likes earning rewards and achievements" (achievement)
  - "Loves helping and teaching others" (social)
- Store as: `string[]`

#### Section 5: {name}'s Superpowers
*"What comes naturally to {name}? What are they proud of?"*

- Multi-select chips: Quick thinker, Creative, Great memory, Good with numbers, Strong reader, Problem solver, Storyteller, Artistic, Curious, Patient, Good listener, Detail-oriented
- "Add your own" for custom entries
- Store as: `string[]`

#### Section 6: Areas to Grow
*"What does {name} find challenging? No judgment — this helps us focus our support."*

- Multi-select chips: Staying focused for long, Showing work/steps, Word problems, Memorizing facts, Writing answers, Reading comprehension, Speed/time pressure, Math calculations, Understanding abstract concepts, Getting started on tasks
- "Add your own" for custom entries
- Store as: `string[]`

#### Section 7: {name}'s Personality
*"Help us match our teaching style to {name}'s temperament."*

- Slider-style OR binary-choice pairs (pick one from each pair):
  - "Takes time to warm up" ←→ "Outgoing right away"
  - "Likes to take their time" ←→ "Likes to go fast"
  - "Asks lots of questions" ←→ "Figures things out quietly"
  - "Gets frustrated easily" ←→ "Patient and persistent"
  - "Loves routine and predictability" ←→ "Loves surprises and variety"
- Store as: `{trait: string, value: string}[]` (e.g., `{trait: "pace", value: "slow"}`)

#### Section 8: Favorites & Fun Facts
*"The fun stuff! These help us make learning feel personal."*

- Favorite movies/shows (tag input): `string[]`
- Favorite books/characters (tag input): `string[]`
- "Tell us about a trip, experience, or story they love to talk about" (textarea, max 500 chars): `string`
- "What does {name} want to be when they grow up?" (text input): `string`

#### Section 9: Parent's Notes
*"Anything else we should know? Tips from the expert — you!"*

- Single textarea (max 1000 chars)
- Placeholder: "E.g., 'She learns faster in the morning', 'He gets anxious during tests', 'She loves it when you relate things to cooking'..."
- Store as: `string`

#### Session Preferences (sub-section or separate)
- Attention span: Short (10-15 min) / Medium (15-25 min) / Long (25+ min) — single select chips
- Pace preference: "Slow and thorough" / "Balanced" / "Fast-paced" — single select

---

### R2: LLM-Derived Kid Personality

When the parent saves the enriched profile (or any section of it), trigger an LLM processing step that derives a structured "Kid Personality" from all available raw inputs. This personality is the single source of truth consumed by the tutor.

#### Input
All raw profile fields: basic info (name, age, grade, board, school), all 9 enrichment sections, existing about_me, language preferences.

#### Output — Structured Personality JSON
The LLM produces a structured JSON with these fields:

```
{
  "teaching_approach": "Use visual diagrams and step-by-step breakdowns. Arjun learns best when he can see the structure. Lead with a concrete example before the abstract rule.",

  "example_themes": ["cricket", "space", "gaming", "cooking with mom"],

  "people_to_reference": [
    {"name": "Rohan", "context": "best friend, use in partnership/sharing problems"},
    {"name": "Didi", "context": "older sister, use in comparison/bigger-number contexts"},
    {"name": "Bruno", "context": "pet dog, use in fun/counting contexts"}
  ],

  "communication_style": "Keep it energetic and slightly playful. Use short sentences. He responds well to cricket metaphors ('that's a six!'). Okay to use emojis sparingly.",

  "encouragement_strategy": "Lead with challenge-based motivation ('Can you crack this tricky one?'). Follow successes with specific praise ('You spotted the pattern — great thinking!'). Avoid generic 'good job'.",

  "pace_guidance": "He likes to go fast but sometimes rushes through steps. Gently slow him down on multi-step problems by asking him to explain his thinking. Keep sessions to 15-20 minutes max.",

  "strength_leverage": "He's a quick thinker and loves patterns. Use pattern-recognition as an entry point for new concepts. His storytelling ability can help with word problems — ask him to narrate the problem.",

  "growth_focus": "Word problems and showing work. He gets the answer but can't explain how. Use his cricket love: 'If you were coaching Rohan, how would you explain this step?' to practice articulation.",

  "things_to_avoid": "Don't rush through explanations even though he seems to want speed — he sometimes nods along without understanding. Avoid timed pressure initially. Don't use 'this is easy' framing — it makes him feel bad when he gets it wrong.",

  "fun_hooks": "References to his favorite show (Doraemon gadgets as metaphors), his dream of being an astronaut (space-themed word problems), his dog Bruno (counting/sharing contexts)."
}
```

#### Regeneration Rules
- Regenerate when any enrichment section is created or updated
- Regenerate when basic profile fields (name, age, grade) change
- Keep the previous personality version for comparison (soft versioning — store last 2)
- The personality is regenerated as a whole, not patched incrementally (LLM sees everything fresh)

#### Storage
- New `kid_personality` table: `id`, `user_id` (FK), `raw_inputs_hash` (to detect changes), `personality_json`, `generator_model`, `version`, `created_at`
- Or: a `personality_json` TEXT column on the `users` table + a `kid_personality_versions` table for history
- The simpler option (column on users + history table) is preferred

---

### R3: Personality Card (Parent-Facing)

On the enrichment profile page, show a "Here's what we understand about {name}" card that displays the derived personality in a friendly, readable format.

- Rendered from the structured JSON, not raw JSON
- Organized as friendly sections: "How we'll teach", "Examples we'll use", "What motivates {name}", "What we'll focus on"
- Read-only — parents edit the raw input sections to change it
- Shows a "Last updated" timestamp
- If no personality has been derived yet (no enrichment data), show a motivational prompt: "Fill in a few sections above and we'll create a personalized learning profile for {name}!"

---

### R4: Deep Personalization in Teaching

Inject the kid personality into every teaching interaction.

#### 4a: Master Tutor System Prompt
Replace the current minimal personalization block:
```
## Student Profile
The student's name is {name}. They are {age} years old.
About: {about_me}
Examples: {preferred_examples}
```

With a rich personality-driven block:
```
## Student Personality Profile
{full personality JSON — all fields}
```

The LLM already knows how to use structured context. The personality JSON is self-documenting (field names explain themselves). No need to convert to prose — that would lose precision.

#### 4b: Welcome Message
The session welcome message should use the personality to set tone immediately. E.g., "Hey Arjun! Ready to crack some fractions today? Let's see if you can beat your last score!" (challenge-motivated kid) vs "Hi Priya! We're going to explore fractions today using some really cool drawings. No rush — let's take it step by step!" (visual learner, slow-paced).

#### 4c: Exam Question Generation
Update the exam question generation prompt to include:
- Names from `people_to_reference` for word problem characters
- Interests from `example_themes` for problem contexts
- Keep core mathematical rigor — only the window dressing is personalized
- Example: "Arjun and Rohan are dividing 24 cricket cards equally among 4 friends..." instead of "A and B divide 24 objects among 4 people..."

#### 4d: Preferred Examples (Remove Hardcode)
- Remove the hardcoded `["food", "sports", "games"]` default for `preferred_examples`
- Populate from `personality.example_themes` when available
- Fall back to current default only when no personality exists

#### 4e: Pacing Integration
- Use `personality.pace_guidance` alongside the existing dynamic pacing system
- The dynamic system (mastery-based) overrides personality preferences when there's a conflict (e.g., kid prefers fast but is struggling → slow down)
- Attention span preference informs session length warnings

---

### R5: Navigation & Access

- Add a prominent card on the existing Profile page: "Help us know {name} better" → navigates to `/profile/enrichment`
- The enrichment page is a standalone page, not embedded in the profile form
- Back button returns to Profile page
- Optional: Add a subtle prompt on the home screen for users who haven't filled any enrichment data: "{name}'s learning profile is empty — help us personalize their experience!"
- The personality card (R3) appears at the bottom of the enrichment page

---

## Data Model

### New: `kid_enrichment_profiles` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK → users | UNIQUE (one profile per kid) |
| interests | JSONB | `string[]` |
| my_world | JSONB | `{name, relationship}[]` |
| learning_styles | JSONB | `string[]` |
| motivations | JSONB | `string[]` |
| strengths | JSONB | `string[]` |
| growth_areas | JSONB | `string[]` |
| personality_traits | JSONB | `{trait, value}[]` |
| favorite_media | JSONB | `string[]` |
| favorite_characters | JSONB | `string[]` |
| memorable_experience | TEXT | |
| aspiration | TEXT | |
| parent_notes | TEXT | |
| attention_span | VARCHAR | `short` / `medium` / `long` |
| pace_preference | VARCHAR | `slow` / `balanced` / `fast` |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### New: `kid_personalities` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK → users | |
| personality_json | JSONB | The derived personality (R2 output) |
| inputs_hash | VARCHAR | SHA256 of all raw inputs — skip regeneration if unchanged |
| generator_model | VARCHAR | e.g., `gpt-4o` |
| version | INT | Auto-increment per user_id |
| created_at | TIMESTAMP | |

Index: `(user_id, version DESC)` for fetching latest.

### Changes to `StudentContext`

Add:
```python
personality: Optional[dict] = None  # The full derived personality JSON
enrichment: Optional[dict] = None   # Raw enrichment data (for exam question gen)
```

---

## API Endpoints

### Enrichment Profile CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/profile/enrichment` | Get kid's enrichment profile (or 404 if none) |
| PUT | `/profile/enrichment` | Create or update enrichment profile (partial updates supported) |

PUT accepts any subset of the enrichment fields. Only provided fields are updated. After a successful PUT, trigger personality regeneration asynchronously.

### Kid Personality

| Method | Path | Description |
|--------|------|-------------|
| GET | `/profile/personality` | Get latest derived personality (for the card UI) |
| POST | `/profile/personality/regenerate` | Force regeneration (admin/debug use) |

---

## Implementation Phases

### Phase 1: Profile Collection (Frontend + Backend CRUD)
- Database migration for `kid_enrichment_profiles`
- Backend: enrichment repository, service, API routes
- Frontend: enrichment page with all 9 sections, navigation from Profile page
- No LLM processing yet — just data collection and storage

### Phase 2: Personality Derivation (LLM Processing)
- Database migration for `kid_personalities`
- Backend: personality generation service with LLM prompt
- Trigger on enrichment profile save
- Frontend: personality card on enrichment page

### Phase 3: Teaching Personalization (Tutor Integration)
- Enrich `StudentContext` with personality data at session start
- Update master tutor system prompt with full personality block
- Update welcome message generation
- Update exam question generation prompt
- Remove hardcoded `preferred_examples` default

### Phase 4: Polish
- Home screen prompt for empty enrichment profiles
- Personality regeneration on basic profile changes (name, age, grade)
- Session length warnings based on attention span preference

---

## Out of Scope (For Now)
- Separate parent accounts / parent dashboard
- Personalized study plan structure (different steps per kid) — plans stay per-topic, personalization is runtime
- Adaptive personality updates based on session behavior (future: tutor learns about the kid over time)
- Multi-language support for the enrichment page itself (English only for now)
- Profile sharing between parents/co-parents
