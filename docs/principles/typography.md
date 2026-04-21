# Principles: Typography

**Scope:** Student-facing UI. Grade 3-8 readers on phones. ESL Indian students. Long reading sessions.

**Why this matters:** Typography is the single largest determinant of reading fluency, cognitive load, and learning speed on this app. Students spend 70%+ of session time reading tutor explanations, question stems, and options. Every size/weight/colour choice costs or earns comprehension. Nothing here is decorative preference — each attribute is tuned to a measurable reading task.

---

## 1. Audience constraints (what makes this hard)

| Constraint | Consequence for type |
|---|---|
| Grade 3-8 (age 8-14) reading skill variance | Must support slowest reader in the band — decode speed matters |
| ESL, Indian English context | Familiar letterforms; no idioms; no ornate letters (see `easy-english.md`) |
| Mobile-first (320-440px viewport, held 25-35cm from eye) | Body min 16px — anything smaller fails at arm's length |
| Long sessions (20-45 min) | Reading fatigue is real — generous line-height, ample measure, strong contrast |
| Low-end Android + variable screen quality | No hairline weights; rely on weight + size, not weight alone, for hierarchy |
| Reading-to-learn, not reading-for-pleasure | Content surface gets largest type; UI chrome gets smaller |
| Touch input, no hover | No micro-labels assumed readable on hover — every label must stand on its own |

---

## 2. Research foundations

| Claim | Source | Our application |
|---|---|---|
| 16px is the floor for mobile body text at arm's length | Nielsen Norman Group; Material Design; iOS HIG | No student-facing content text below 1rem |
| Sans-serif with open counters reads fastest for elementary students (Roboto/Arial-class) | *Format Readability on Children's Reading Speed*, MDPI 2024 | Inter for UI; Lexend for long-form reading prose |
| Lexend significantly improves words-correct-per-minute for Grade 3 readers | Shaver-Troup & Jockin, Lexend research | Use Lexend Deca for explanation prose, question stems |
| Line-height 1.5-1.8 optimal for mobile body | NN/G mobile typography | Body prose 1.6; long-form 1.65 |
| Wider letter-spacing improves reading accuracy ~2x in struggling readers | Dyslexia spacing studies | +0.01em on long-form prose |
| Line length 50-75 chars is the "sweet spot" | Baymard, NN/G | Prose measure ≤ 600px at body size |
| Handwritten/cursive fonts slow elementary reading | Cursive readability studies | Caveat restricted to decorative labels only — never body or stems |
| WCAG 2.2 AA: 4.5:1 contrast for body, 3:1 for large text (≥18pt) | W3C WCAG 2.2 | All text passes 4.5:1; no `#999` on white |
| No one font is optimal for every child | MDPI 2024 multi-font study | System respects user's OS Dynamic Type scaling — we use `rem`, never `px` on text |
| 14px + 1.5 line-height optimal for children's learning apps per one eye-tracking study (n=161) | PMC 10151978 | We go slightly higher (16/18px) to cover variable screen quality on low-end Android |

---

## 3. Core decisions

These are the load-bearing choices. Every other rule derives from them.

### D1. Primary body font = Inter. Primary reading font = Lexend Deca.

- **Inter** — UI chrome, labels, buttons, navigation, metadata. Reliable, familiar, excellent on all screens, already loaded.
- **Lexend Deca** — long-form explanation prose and question stems. Evidence-backed for Grade 3+ reading fluency. Neutral enough to coexist with Inter.
- **JetBrains Mono** — formulas, code, numerical insets only.
- **Caveat** — decorative *only*: page-title flourish, card-type labels (chalkboard aesthetic). Never body, never question stems, never options, never instructions.

### D2. One modular size scale. Eight values. Semantic aliases.

Primitive tokens — **prototyped** in `llm-frontend/mockups/chalkboard/tokens.css:59-66`, but **not yet in the live runtime**. Phase 1 of the rollout adds these to `llm-frontend/src/App.css` `:root` (the live token layer):

```
--fs-xs:   0.75rem  (12px)
--fs-sm:   0.875rem (14px)
--fs-md:   1rem     (16px)
--fs-lg:   1.125rem (18px)
--fs-xl:   1.375rem (22px)
--fs-2xl:  1.75rem  (28px)
--fs-3xl:  2.25rem  (36px)
--fs-4xl:  3rem     (48px)
```

Semantic role tokens layered on top (also new in Phase 1):

```
--type-caption       = --fs-xs    /* timestamps, metadata only — NEVER student content */
--type-label         = --fs-sm    /* UI labels, breadcrumbs, mode badges */
--type-body          = --fs-md    /* secondary UI text, card subtitles */
--type-body-reading  = --fs-lg    /* tutor explanation prose — primary reading surface */
--type-stem          = --fs-lg    /* question stems, instructions */
--type-option        = --fs-md    /* answer options, check-in choices */
--type-card-title    = --fs-xl    /* explanation card titles, section headers */
--type-page-title    = --fs-2xl   /* screen titles (Subject Select, etc.) */
--type-display       = --fs-3xl   /* celebration / completion moments */
--type-spotlight     = --fs-2xl   /* typewriter reveal mode */
```

### D3. Three weights only. 400 / 600 / 700.

- **400** = body, prose, paragraphs, secondary labels
- **600** = card titles, emphasized terms, breadcrumb-current, CTA labels on secondary pills
- **700** = page titles, primary CTA, celebration moments, score emphasis

Drop `font-weight: 500` entirely — it adds low-signal variation without building hierarchy.

### D4. Line-height by role, not by default.

| Text role | line-height | Why |
|---|---|---|
| Long-form explanation prose (`--type-body-reading`) | **1.65** | Research-backed for struggling-reader fluency |
| Question stem / instruction | **1.55** | Dense, re-read often — needs air but not loose |
| Body UI / card subtitles | **1.5** | WCAG sweet spot |
| Option button label | **1.4** | Usually 1-2 lines, compact but readable |
| Card titles, section headers | **1.3** | Headline tightness |
| Page titles, display | **1.15-1.2** | Visual weight comes from size |
| Caption / label chrome | **1.4** | Avoid cramped stack |

### D5. Letter-spacing discipline.

| Context | tracking |
|---|---|
| All body prose | `0` (default) |
| Long-form reading prose | `+0.005em` (very subtle, dyslexia research) |
| All-caps labels (CARD TYPE, NEXT button) | `+0.05em` |
| All-caps large display | `+0.02em` |
| Handwritten (Caveat) decorative | `0` |
| **Never** | negative tracking on any student content |

### D6. Minimum size floor = 1rem (16px) for any student content.

Student content = tutor prose, question stems, answer options, check-in text, feedback messages, score text. UI chrome (timestamps, breadcrumbs, incidental metadata) may go to `--fs-sm` (14px). Nothing student-facing goes below `--fs-xs` (12px) ever — and 12px is reserved for things like decorative subject-card pill labels, not readable text.

### D7. Contrast floor = WCAG AA (4.5:1 normal; 3:1 large).

- Body on white: **`#1F1F1F`** or **`#333`** (≥ 12:1) — current `--color-text: #333` is fine.
- Secondary on white: **`#5A5A5A`** (≥ 7:1). The current `--color-text-secondary: #666` (~5.7:1) is borderline; acceptable for non-content UI, not for prose.
- Muted: **`--color-text-muted: #999`** fails 4.5:1 at ~2.85:1. **Ban for any student content or any text carrying meaning**. Allowed only for pure visual hierarchy separators (e.g., divider dot glyphs).
- White on chalkboard-green (`#F4F4EF` on `#2F4A3C`): ~9.2:1 — passes. Pastel chalk colours on the board are **accent only** (not for prose — check each pairing against 4.5:1 for the role).

### D8. Measure (line length) ≤ 600px for prose; ≤ 520px for long-form reading.

Current `--content-max-width: 600px` is correct for UI; explanation cards should have an inner prose-measure cap of 520px to keep lines at 55-65 characters at `--fs-lg`.

### D9. Always `rem`, never `px`, on any user-visible text.

Respects user's OS text-size preference (iOS Dynamic Type, Android font scaling). A kid whose parent set a larger OS font size must get bigger app text automatically.

---

## 4. Role → token mapping (every student-facing text role)

This is the master map. Every new text element must pick a row from this table. If a new role doesn't fit, the role is wrong — not the table.

### Auth & onboarding

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| App name / logo wordmark | `--type-display` | 700 | 1.15 | Inter or Caveat (decor) | Brand moment |
| Onboarding question (e.g., "What's your name?") | `--type-stem` | 600 | 1.55 | Lexend Deca | Kid parses & answers — reading task |
| Input placeholder | `--type-body` | 400 | 1.4 | Inter | UI chrome |
| Input value (what kid types) | `--type-stem` | 600 | 1.4 | Lexend Deca | Their content — big and clear |
| Grade-select option label | `--type-card-title` | 600 | 1.3 | Inter | Large tap target needs matching text |
| "Next" / primary CTA | `--type-body` upper | 700 | 1.3 | Inter | All-caps +0.05em tracking |
| "Skip for now" link | `--type-body` | 600 | 1.4 | Inter | Secondary CTA, not a caption |
| Error message | `--type-body` | 600 | 1.5 | Inter | Must be easy to read immediately; colour `--color-error` |

### Selection screens (Subject / Chapter / Topic / Mode)

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| Page title ("What should we learn?") | `--type-page-title` | 600 | 1.25 | Inter (Caveat only when title is ≤1 word per §5.8) | Anchors screen |
| Selection card label (subject/topic name) | `--type-card-title` | 600 | 1.3 | Inter | Tap target + content — largest UI item |
| Card subtitle (e.g., chapter summary) | `--type-body` | 400 | 1.5 | Inter | Context, not primary |
| "What you'll learn" section header | `--type-label` upper | 600 | 1.3 | Inter | All-caps +0.05em tracking |
| Chapter summary body prose | `--type-body-reading` | 400 | 1.65 | Lexend Deca | Actual reading |
| Breadcrumb link | `--type-label` | 400 | 1.4 | Inter | Nav chrome |
| Breadcrumb current (selected) | `--type-label` | 600 | 1.4 | Inter | Emphasis by weight, not size |
| Progress caption ("3 of 8") | `--type-label` | 600 | 1.4 | Inter tabular-nums | Glance info |

### Learning session — explanation cards

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| Card-type badge ("CONCEPT", "EXAMPLE") | `--type-caption` upper | 600 | 1.4 | Inter, +0.05em tracking | Genre label, not readable content |
| Card title ("The Pattern: Groups of 10") | `--type-card-title` | 600 | 1.3 | Inter or Caveat (chalkboard) | Anchor of card |
| Explanation body prose | `--type-body-reading` | 400 | 1.65 | **Lexend Deca** | Primary reading surface — biggest single gain |
| Emphasised term inside prose (**10 ones**) | inherit size | 700 | inherit | inherit | Bold, not italic, not size change |
| Parchment/formula inset body | inherit | 400 | 1.5 | JetBrains Mono | Differentiates formula from prose |
| Typewriter spotlight block (ChatSession TW mode) | `--type-spotlight` | 600 | 1.45 | Lexend Deca | One block at a time — large, calm |
| "I didn't understand" escape-hatch link | `--type-body` | 600 | 1.4 | Inter | Secondary action — visible but not loud |
| Primary nav button ("NEXT") | `--type-body` upper | 700 | 1.3 | Inter, +0.05em tracking | All-caps, pill |
| Secondary nav button ("BACK") | `--type-body` upper | 600 | 1.3 | Inter, +0.05em tracking | Lighter pill |

### Learning session — check-in / practice activities

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| Question stem / activity instruction | `--type-stem` | 600 | 1.55 | **Lexend Deca** | Central reading task |
| Answer option label (pick_one, true_false, check-in) | `--type-option` | 400 | 1.45 | Lexend Deca | Must be bigger than current 0.95rem — multi-line often |
| Match-pairs item text | `--type-option` | 400 | 1.45 | Lexend Deca | Same as option |
| Fill-blank inline blank | `--type-stem` | 700 | inherit | Lexend Deca | Emphasized blank, underline + bold |
| Sort-buckets bucket label | `--type-label` upper | 600 | 1.3 | Inter, +0.05em tracking | Category label |
| Sequence slot number | `--type-body` | 700 | 1.1 | Inter tabular-nums | Count, not prose |
| Feedback message ("Nice work!", "Not quite") | `--type-stem` | 600 | 1.55 | Lexend Deca | Reads as tutor voice — warm, visible |
| Hint / "Try again" caption | `--type-body` | 400 | 1.5 | Lexend Deca | Secondary but still readable |

### Results / report card / history

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| Celebration headline ("Great job today!") | `--type-display` | 700 | 1.15 | Caveat (decor) or Inter | Moment |
| Subject row label | `--type-card-title` | 600 | 1.3 | Inter | List item title |
| Score / count large display | `--type-display` | 700 | 1.1 | Inter tabular-nums | Numeric focus — display-sized; apply `.tabular-nums` |
| Timestamp / relative date | `--type-caption` | 400 | 1.4 | Inter | Meta chrome — may use `#5A5A5A` |
| Mode badge ("PRACTICE", "TEACH") pill | `--type-caption` upper | 700 | 1 | Inter, +0.05em tracking | Chip |

### Profile / enrichment

| Role | Token | Weight | Line-height | Font | Rationale |
|---|---|---|---|---|---|
| Section title | `--type-card-title` | 600 | 1.3 | Inter | Anchor |
| Chip/selector label | `--type-body` | 600 | 1.4 | Inter | Tap target |
| Helper text ("Pick up to 3") | `--type-body` | 400 | 1.5 | Inter | Guidance |

---

## 5. Content-type playbooks

### 5.1 Explanation prose (the primary reading surface)

**Biggest single win.** This is where the tutor's actual teaching lands. Today it's 1.05rem Inter; we recommend `--type-body-reading` (1.125rem / 18px) Lexend Deca, line-height 1.65, max-width 520px, letter-spacing +0.005em.

- Bold key terms (`<strong>`) for scanning cues — but no more than 2-3 per paragraph. (Reference: the chalkboard design bolds `10 ones`, `1 ten`.)
- Inset blocks (formulas, examples) switch to JetBrains Mono at 0.95em of the prose size to clearly signal "this is a worked example, not prose".
- Typewriter spotlight: one block at a time at `--type-spotlight` (28px) — the single largest body-content size on any screen. Line-height 1.45 because it's centred and short.

### 5.2 Question stems

**Parsed under time pressure; re-read if wrong.** Use `--type-stem` (18px) Lexend Deca, weight 600, line-height 1.55. *Never* Caveat / handwritten — decoding cost is too high for a task-critical read.

If chalkboard aesthetic requires a handwritten feel, apply Caveat to the *card chrome* (the card type label, the card corner doodles) — leave the stem in a legible sans.

### 5.3 Answer options / choices

Each option is a tap target with short text. Must be:

- `--type-option` (16px) minimum. Today's 0.95rem (15.2px) is borderline; at 16px plus line-height 1.45, multi-line options breathe.
- Weight 400 (regular). Selected state uses weight 600, not colour-only, so the change is perceivable for red-green colourblind users.
- Never > 3 lines at default viewport. If longer, the item shouldn't be a single option — it should be a separate card or be broken up.
- Tap target ≥ 44 × 44 px around the text (Apple HIG, WCAG 2.5.8 enhanced).

### 5.4 Card titles & list items

- `--type-card-title` (22px) weight 600 line-height 1.3.
- No subtitle smaller than `--type-body` (16px) if the subtitle is content (e.g., "today's chapter summary"). Subtitles that are metadata (timestamps) may use `--type-label` (14px).

### 5.5 Labels / CTAs / buttons

- Primary CTA: `--type-body` (16px) **UPPERCASE** weight 700 tracking +0.05em. All-caps chosen for visual authority, not size — keeps CTA compact while readable.
- Secondary CTA: same size/case, weight 600.
- Icon-only buttons must still have a visible label at `--type-label` (14px) within the tap target or as a chip beneath the icon, unless the icon is universally understood (home, back arrow).
- Breadcrumbs: `--type-label` (14px). Current-position breadcrumb uses weight 600; others 400.

### 5.6 Math / code / mono

- JetBrains Mono at 0.95em of the surrounding prose size. A formula inside 18px prose renders at 17.1px mono.
- Tabular figures on numeric displays (scores, streaks, timers): `font-variant-numeric: tabular-nums;` — prevents digit jitter during score updates.
- Equation displays (multi-line formulas) inside parchment inset: 1em of surrounding prose, line-height 1.5.

### 5.7 Error / feedback / toasts

- Error message: `--type-body` weight 600, line-height 1.5, colour `--color-error` (on light bg must pass 4.5:1 — current `#e53e3e` on white = ~4.6:1, marginal; prefer `#C4302B` for better safety).
- Success / celebration: `--type-stem` weight 600; may be colour `--color-success` only if paired with icon — colour alone does not carry meaning.
- Toast vertical layout: title `--type-body` 600 + body `--type-body` 400. Don't shrink toast text to `--type-label` just because the toast is small.

### 5.8 Decorative (Caveat handwritten)

Allowed:
- App logo / app-title flourish
- Page-title flourish on low-density screens (e.g., "Topics" on topic select, **one word only** — multi-word page titles must be Inter)
- Card-type label on the chalkboard card ("Concept", "Example") — all-caps is optional; may be title-case in Caveat
- Celebration display ("Great job!") — one line, maximum 4-5 words

Not allowed:
- Question stems (research: decoding cost)
- Option labels (speed-critical)
- Explanation body prose (fatigue)
- Error / feedback (clarity-critical)
- Anything < 20px Caveat regardless of role — the font loses legibility at small sizes

---

## 6. Accessibility floor (all non-negotiable)

| Check | Rule |
|---|---|
| Body contrast | ≥ 4.5:1 on background |
| Large text (≥ 18pt / 24px, or 14pt+ bold) contrast | ≥ 3:1 |
| Minimum student-content size | 1rem (16px) |
| Line-height on prose | ≥ 1.5 |
| Line length | 45-75 chars, measure ≤ 600px |
| Colour alone for meaning | Never — pair with weight, icon, or position |
| Dynamic Type | All text in `rem`; no `px` |
| Tap targets | ≥ 44 × 44 px around any tappable text |
| Font loading | `font-display: swap` (already correct) — FOIT forbidden |
| Prefers-reduced-motion | Typewriter reveal skips animation per OS setting |

---

## 7. Font loading & performance

Four font families cost real bytes on the first load — especially on low-end Android in India, one of our stated audience constraints (§1). The plan must be explicit about payload, fallbacks, and render behaviour.

### 7.1 What we load

| Family | Role | Weights to load | Why |
|---|---|---|---|
| Inter | UI chrome | 400, 600, 700 | Three weights map exactly to D3 |
| Lexend Deca | Reading prose & stems | 400, 600, 700 | Same three weights; D3 bans 500 |
| Caveat | Decorative only | 600, 700 | Only used for display labels / celebration — no body text |
| JetBrains Mono | Formulas / code | 400 | Single weight — our educational formulas/code surfaces don't need emphasis; add 700 later only if a concrete surface demands it |

Weight 500 is banned universally by D3 — do not load it for any family. This saves ~15-25KB per family on the critical path and keeps the hierarchy rule uniform.

### 7.2 Loading strategy

- **`font-display: swap`** on every family — already correct in `index.html`. Forbid FOIT.
- **Preconnect** to `fonts.googleapis.com` and `fonts.gstatic.com` — already correct.
- **Preload** the single highest-traffic weight of the reading font: `<link rel="preload" as="font" type="font/woff2" href="…lexend-deca-400.woff2" crossorigin>`. Explanation prose mounts on every session; this reduces the Lexend pop-in on first paint.
- **Variable fonts preferred** where available (Inter variable, Lexend variable). One HTTP request replaces three static weights.
- **Subsetting:** Google Fonts default subset is Latin. Keep as-is; we do not yet ship Hindi/Tamil/Telugu. When we do, switch to the appropriate `unicode-range` CSS to avoid double-loading.

### 7.3 Fallback behaviour — comprehension must not depend on web fonts

If Lexend Deca fails to load (slow 3G, CDN outage, extension blocking), the reading surface falls through to `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif` — all of which satisfy the "open-counter sans" requirement from D1. Comprehension should degrade gracefully, not collapse. Same reasoning for Caveat: if the handwritten font doesn't load, the surface falls through to Inter — visually flatter but perfectly legible.

### 7.4 Acceptance criteria for typography rollout

- LCP on `ChatSession` explanation-card-mount: ≤ 2.5s on simulated Fast 3G throttle.
- CLS attributable to font swap: ≤ 0.05 (measure per-screen; Lexend swap is the biggest risk).
- Total font payload for the student surface on cold load: ≤ 150KB compressed (budget — reject any new font that breaks this ceiling).
- No surface remains blank (FOIT) for > 100ms waiting on a font.

### 7.5 Self-hosting tradeoff (future work, not Phase 1)

Google Fonts add latency in India (CDN RTT to closest edge varies). If post-rollout measurement shows consistent first-paint lag attributable to font fetches, self-host Lexend Deca variable from the same origin as the app. Deferred — measure first.

---

## 8. Anti-patterns (what not to do)

1. **Caveat for anything the student has to *read to answer*.** Question stems, options, instructions — always sans-serif.
2. **More than one new size per screen.** If a screen already uses `--type-body-reading`, a fifth size like `0.82rem` is not allowed — promote it to an existing token.
3. **Size-as-hierarchy.** A card with 8 sizes (today's ChatSession) signals chaos, not structure. Three sizes is usually enough: (a) title, (b) body, (c) meta.
4. **Colour as the only hierarchy signal.** Grey-ing text does not create hierarchy for colourblind students — use size/weight.
5. **Font weight 500 mixed with 400/600.** You get 500 + the distinction is imperceptible — drop it.
6. **Body prose with line-height < 1.5.** Comprehension drops; fatigue rises.
7. **Tight letter-spacing on prose.** Never negative; never ≤-0.01em on anything the kid reads.
8. **Text smaller than 12px anywhere.** Even for chrome — just eliminate the label.
9. **All-caps for sentences.** ALL-CAPS FOR A FULL SENTENCE COSTS ~13-20% READING SPEED. All-caps reserved for ≤3-word labels.
10. **Hard-coded `px` sizes on user-visible text.** Always `rem`. Only non-text (borders, shadows, paddings) should use `px`.

---

## 9. How to apply this to new components

Before writing `font-size: 0.87rem`, answer:

1. What **role** is this text in Section 4's mapping?
2. What **token** does the role map to?
3. Is the **weight** one of {400, 600, 700}?
4. Is **line-height** set per the role's row in Section 3 D4?
5. Does the colour pass **4.5:1** on its background?
6. Is the font family correct per D1 (Inter for UI, Lexend for reading prose, JBMono for formulas, Caveat for decor only)?

If yes to all six, ship. If any gap, the component is wrong — not the rule.

---

## References

- Nielsen Norman Group — [Typography for Glanceable Reading](https://www.nngroup.com/articles/glanceable-fonts/)
- Shaver-Troup & Jockin — Lexend variable typeface; [lexend.com](https://www.lexend.com/)
- *Format Readability on Children's Reading Speed* — MDPI Education 2024; [readabilitymatters.org](https://readabilitymatters.org/articles/research-highlight-the-influence-of-format-readability-on-childrens-reading-speed-and-comprehension)
- *Optimised font size and viewing time for online learning in young children* — PMC10151978 (n=161 eye-tracking study)
- W3C — [WCAG 2.2 Success Criterion 1.4.3 Contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
- Smashing Magazine — [Reference Guide for Typography in Mobile Web Design](https://www.smashingmagazine.com/2018/06/reference-guide-typography-mobile-web-design/)
- British Dyslexia Association — dyslexia-friendly style guidance (letter-spacing, weight, sans-serif)
- Apple HIG — iOS Dynamic Type
- Google Material — Type scale

---

## Cross-references

- `docs/principles/ux-design.md` — parent UX principles (mobile-first, warm language, minimal typing)
- `docs/principles/easy-english.md` — content-level language rules for Indian ESL readers
- `docs/principles/how-to-explain.md` — what the prose says (this doc governs how it looks)
- `docs/feature-development/typography-redesign/gap-analysis.md` — specific fixes to current codebase
- `docs/feature-development/kid-friendly-ui-redesign/design-brief.md` — chalkboard redesign this aligns with
