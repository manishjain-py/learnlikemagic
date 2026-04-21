# Typography Gap Analysis

**Reference:** [`docs/principles/typography.md`](../../principles/typography.md) — the research-backed strategy this gap analysis is measured against.
**Scope:** Student-facing screens only. Admin/devtools excluded.
**Codebase snapshot:** 2026-04-21, branch `main`.

---

## 1. Summary

| Dimension | Strategy target | Current state | Gap |
|---|---|---|---|
| Distinct font sizes in use | 8 primitive tokens | **31 distinct values** (0.65 → 2.5 rem) | ~23 unscaled values to consolidate |
| Reading-content font | Lexend Deca | Inter (everywhere) | Lexend not loaded at all |
| Body prose size | 1.125rem (18px) | 1.05rem (16.8px) | -0.075rem; undershoot on primary reading surface |
| Option / choice size | 1rem min | 0.95rem (15.2px) | Below floor on every practice + check-in capture |
| Line-height on prose | 1.65 | 1.6 | Close, small bump |
| Line-height on options | 1.45 | 1.3 | Tight; multi-line options cramp |
| Weights in use | {400, 600, 700} | {400, 500, 600, 700} | Drop 500 |
| Contrast `#999` usage | Banned for content | Used via `--color-text-muted` | Replace or delete references in student-facing surfaces |
| Caveat for question stems | Banned (decoding cost) | Planned in chalkboard redesign (1.45rem) | Change chalkboard plan before it ships |
| Size scale primitives (`--fs-*`) | Live in `App.css` `:root` | **Only in `mockups/chalkboard/tokens.css`** — not in runtime | Copy the scale into `App.css` `:root` (Phase 1) |
| Semantic role tokens (`--type-*`) | Live in `App.css` `:root` | Do not exist anywhere | Add (Phase 1) |
| Tabular numerals on scores/timers | Required | None | Add `.tabular-nums` utility (Phase 1) |
| Monospace family on formula insets | `var(--font-mono)` (JetBrains Mono, already loaded) | `'Courier New'` on one surface; **missing** on spotlight `<pre>` | Replace system fallback with `--font-mono` |
| Chalkboard practice CSS rules aligned with strategy | All of `App.css:7400-7660` | ~16 rules; ~7 direct P0 violations (including handwritten bucket labels) | Per-rule pass in Phase 3/4 |

---

## 2. Priority matrix

Fixes are ranked by **learning impact × reach**. A bug on the primary reading surface that every student hits every session = P0. A 0.7rem badge on one legacy screen = P3.

| P | Definition | Examples |
|---|---|---|
| P0 | Directly degrades reading fluency on primary content surface. Every student, every session. | Body prose undersize + wrong font; option sizes; Caveat on stems; handwritten bucket labels; chalkboard practice surface inventory |
| P1 | Degrades comprehension on secondary content surface. Most students, most sessions. | Practice feedback undersize; line-height on options; muted-colour contrast fails; fixed-px surfaces that break Dynamic Type |
| P2 | Visual chaos / inconsistency. Doesn't fail comprehension but undermines design trust and future maintenance. | 31-size scale; weight 500 sprinkled; ChatSession 8-size overload; `Courier New` instead of `--font-mono`; spotlight `<pre>` inherits sans |
| P3 | Chrome polish. Low single-student impact. | Badge micro-sizes; breadcrumb size variance |

---

## 3. P0 violations (fix before anything else)

### P0.1 — Explanation prose is too small and in the wrong font

- **Where:** `llm-frontend/src/App.css` ~line 2648 — `.explanation-card-content` at `1.05rem / Inter / line-height 1.6`.
- **Also:** `TypewriterMarkdown.tsx` spotlight at `1.6rem Inter / 1.5`.
- **Strategy says:** `--type-body-reading` = `1.125rem / Lexend Deca / 1.65`; spotlight = `--type-spotlight` = `1.75rem Lexend / 1.45`.
- **Why it matters:** This is the single most-read surface in the app. Every minute of the tutor talking lands here. Research (MDPI 2024 children's reading speed; Lexend WCPM study) shows 18px Lexend beats 16.8px Inter for Grade 3-8 readers — and ESL students benefit most.
- **Fix:** Depends on Phase 1 infrastructure. Once `--font-reading` and `--type-body-reading` / `--type-spotlight` are in `App.css` `:root` (see §7.1, §7.2), apply `font-family: var(--font-reading); font-size: var(--type-body-reading); line-height: 1.65;` to `.explanation-card-content` and the spotlight equivalents. Cannot be done without Phase 1 — the primitive `--fs-*` tokens don't yet exist in the live CSS.

### P0.2 — Caveat planned for practice question stems

- **Where:** `App.css` ~line 7268 — `.chalkboard-active .practice-question-text { font-family: var(--font-hand); font-size: 1.45rem; }`.
- **Strategy says:** Question stems must be Lexend Deca (never Caveat/handwritten). Caveat reserved for decorative labels and celebration only.
- **Why it matters:** Cursive/handwritten fonts measurably slow elementary reading. On a question stem the student has to parse *fast* to answer, every decoding millisecond compounds across a 20-question practice set.
- **Fix:** Keep chalkboard aesthetic by applying Caveat to the card's *type label* and *card corners* only. Stem goes to `--type-stem` Lexend Deca on the chalkboard surface (white on green passes 9:1 contrast).
- **Urgency:** This lands with the chalkboard rollout. Catch it **before** chalkboard migrates any student screen.

### P0.3 — In-session check-in family (ChatSession) — shared base + incomplete chalkboard override

This is a **distinct surface** from the `/practice/*` chalkboard practice routes (see P0.6) and from legacy non-chalkboard surfaces. It is the check-in activity rendered **inside ChatSession during a live tutoring session**, dispatched by `llm-frontend/src/components/CheckInDispatcher.tsx:39` across all 11 activity types (`TrueFalseActivity`, `SortBucketsActivity`, `MatchActivity`, etc.).

All 11 activity components share the `.checkin-*` base classes at `App.css:3269-3453`, plus per-activity classes like `.tf-*`, `.fill-*`, `.sort-*`, `.seq-*`. The chalkboard aesthetic applies overrides at `App.css:4310-4505`, but those overrides **only change colour / border / font-family (to Inter)** — they do NOT fix sizes, weights, line-heights, or switch to the reading font. So when a student is in a chalkboard-themed Teach-Me session and a check-in pops up, the text is still on the old undersized Inter path.

| App.css line | Selector | Current | Strategy role | Violation | Severity |
|---|---|---|---|---|---|
| 3279-3285 | `.checkin-instruction` | Inter 1.05rem w600 / 1.4 | `--type-stem` Lexend 1.125rem 1.55 w600 | Size under stem-spec; wrong font for a reading task | P0 |
| 3293-3307 | `.checkin-option-btn` | Inter 0.95rem / 1.3 | `--type-option` 1rem Lexend 1.45 w400 | Undersize; tight leading; wrong font | P0 |
| 3326-3335 | `.checkin-hint` | 0.9rem / 1.4 | `--type-body` 1rem Lexend | Student feedback undersize | P0 |
| 3345-3353 | `.checkin-success-message` | 0.95rem / 1.4 | `--type-body` 1rem Lexend | Student feedback undersize | P0 |
| 3374-3384 | `.tf-statement` | Inter 1.1rem w500 / 1.5 | `--type-stem` Lexend 1.125rem 1.55 w600 | Weight 500 banned; wrong font (student reads & judges) | P0 |
| 3391-3405 | `.tf-btn` | Inter 1rem w600 | `--type-option` 1rem Lexend 1.45 | Size OK but wrong font; line-height unset | P1 |
| 3428-3435 | `.fill-sentence` | Inter 1.05rem w500 / 1.6 | `--type-stem` Lexend 1.125rem 1.55 w600 | Weight 500 banned; wrong font | P0 |
| 3355-3366 | `.checkin-continue-btn` | gradient 1rem w600 | `--type-body` upper 700 | OK sizewise; Phase 5 consolidation swap to token | P2 |
| 4310-4324 | `.chalkboard-active .checkin-option-btn / .tf-btn / .sort-item / .seq-item / .error-step / .odd-item / .predict-option / .eliminate-option / .match-item / .swipe-btn` | Sets `font-family: var(--font-body)` (Inter) + colours only | Must **also** set `font-family: var(--font-reading)` on stem-bearing surfaces AND apply token-based sizes/line-heights | **Incomplete** — override doesn't undo the base-rule issues | P0 |
| 4395-4400 | `.chalkboard-active .tf-statement` | Colour-only override | Must also set Lexend font + `--type-stem` + weight 600 | Colour-only | P0 |
| 4403-4406 | `.chalkboard-active .fill-sentence` | Colour-only override | Must also set Lexend font + `--type-stem` + weight 600 | Colour-only | P0 |

**Why it matters:** Every Teach-Me and Clarify session spawns check-ins. This is one of the **highest-traffic reading surfaces in the app** after explanation prose. If Phase 2 fixes explanation prose but leaves the check-ins on Inter 0.95rem/1.3, the reading experience is inconsistent and the practice-decode cost persists.

**Fix approach:** Two-part.
1. **Base rules (applies everywhere — legacy + chalkboard):** Update `App.css:3269-3453` so `.checkin-*`, `.tf-*`, `.fill-*` rules use `--type-*` tokens, line-heights per role, `--font-reading` on stem/instruction/statement surfaces, and drop all weight 500.
2. **Chalkboard overrides (`App.css:4310-4505`):** The current overrides are colour-only. Add explicit `font-family: var(--font-reading);` to the reading surfaces (`.tf-statement`, `.fill-sentence`, `.checkin-instruction` when inside `.chalkboard-active`) and confirm the base-rule sizes/line-heights are already correct so overrides do not need to restate them.

**Rollout sequencing:** This is Phase 3 (legacy check-in pass) **and** Phase 4 (chalkboard pass). Both phases must touch the same file region; bundle into one PR or risk one phase reverting the other.

### P0.6 — Chalkboard practice surface — full per-rule inventory

The chalkboard-active practice CSS at `App.css:7400-7660` has **~16 independent text rules**. Many carry student content and violate the strategy floor or role map. This is far more than "two shared classes" — Phase 3's rollout estimate must reflect this.

| App.css line | Selector | Current | Strategy role | Violation | Severity |
|---|---|---|---|---|---|
| 7477-7484 | `.chalkboard-active .practice-bucket-label` | **Caveat (`--font-hand`)** 1.1rem w600 | `--type-label` upper, Inter, 600 | **Wrong font — handwritten for UI label (role-map violation)** | P0 |
| 7418-7431 | `.chalkboard-active .practice-pair-item` | Inter 0.88rem | `--type-option` 1rem Lexend 1.45 | Student content below 1rem floor; wrong font | P0 |
| 7485-7494 | `.chalkboard-active .practice-bucket-item` | Inter 0.82rem | `--type-option` 1rem Lexend 1.45 | Student content 13.1px, well below floor | P0 |
| 7502-7513 | `.chalkboard-active .practice-item-chip` | Inter 0.82rem | `--type-option` 1rem Lexend 1.45 | Student content chip below floor | P0 |
| 7520-7535 | `.chalkboard-active .practice-swipe-card` | Inter 1.05rem w500 | `--type-option` 1rem Lexend | Wrong font; weight 500 banned by D3 | P0 |
| 7597-7609 | `.chalkboard-active .practice-seq-row` | Inter 0.88rem | `--type-option` 1rem Lexend 1.45 | Sequence item (student content) below floor | P0 |
| 7640-7652 | `.chalkboard-active .practice-freeform-textarea` | Inter 0.95rem, 1.5 LH | `--type-stem` 1.125rem Lexend 1.55 | Kid's typed answer — undersize; wrong font | P0 |
| 7446-7456 | `.chalkboard-active .practice-pair-summary` | Inter 0.82rem | `--type-body` 1rem | Student-visible feedback summary below floor | P1 |
| 7569-7577 | `.chalkboard-active .practice-swipe-undo` | Inter **11px** | `--type-caption` 12px min | Fixed-px below 12px floor; breaks Dynamic Type | P1 |
| 7583-7594 | `.chalkboard-active .practice-swipe-undo-btn` | Inter **11px** | `--type-caption` 12px min | Same as above | P1 |
| 7495-7501 | `.chalkboard-active .practice-bucket-empty` | **12px** (fixed) | `--type-caption` 0.75rem | Fixed-px not rem; breaks Dynamic Type | P2 |
| 7536-7545 | `.chalkboard-active .practice-swipe-empty` | **14px** (fixed) | `--type-label` 0.875rem | Fixed-px not rem | P2 |
| 7610-7622 | `.chalkboard-active .practice-seq-num` | **12px** (fixed) w700 | tabular-nums chip | Fixed-px; numeric — add `.tabular-nums` | P2 |
| 7409-7416 | `.chalkboard-active .practice-pair-col-title` | Inter 0.7rem w600 upper | `--type-caption` 0.75rem | Below caption token; fix to 0.75 | P2 |
| 7546-7558 | `.chalkboard-active .practice-swipe-btn` | Inter 0.92rem w700 | `--type-body` 1rem | UI button under-size | P2 |
| 7562-7568 | `.chalkboard-active .practice-swipe-status` | Inter 0.78rem | `--type-caption` 0.75rem | Off-grid size; use caption token | P3 |

**Fix approach:** Per-rule pass on `App.css:7400-7660`. Group by role (options vs labels vs chrome). Swap fonts, bump sizes, set line-heights, replace fixed-px with tokens. Simultaneously update any React components that reference these classes if they need additional tokens.

**Note:** The chalkboard **question stem** rule (covered by P0.2 above, around `App.css:7268`) is the most visible piece of the same surface. Fixing it in isolation without the rest of this table ships a visually-inconsistent chalkboard — pair P0.2 with P0.6.

### P0.4 — `--color-text-muted: #999` used anywhere carrying content meaning

- **Where:** `App.css:10`, applied as `color: var(--color-text-muted)` or equivalently `color: #999` throughout.
- **Contrast:** ~2.85:1 on white. **Fails WCAG AA (4.5:1).**
- **Strategy says:** Banned for student content. Allowed only for pure visual separators that carry no meaning.
- **Fix:** Replace with `--color-text-secondary` (currently `#666`, ~5.7:1). If `#666` looks too dark in a design, promote to `#5A5A5A` (≈7:1) — subjectively similar weight but passes AAA for large text. Grep for `#999` in `App.css` — expect 10-30 call sites — review each.

### P0.5 — Lexend Deca not loaded

- **Where:** `index.html:13-15` loads Inter + Caveat + JetBrains Mono. No Lexend.
- **Fix:** Add `&family=Lexend+Deca:wght@400;600;700` to the Google Fonts URL (weights 400/600/700 only — 500 is banned by typography D3). Add `--font-reading: 'Lexend Deca', 'Lexend', -apple-system, ...` variable. Add `<link rel="preload" as="font" type="font/woff2" href="…" crossorigin>` for the primary reading weight since it's on the critical path. No font sprawl — Lexend Deca replaces nothing; it's the fourth font, each with a narrow role. Confirm total font payload stays under the 150KB budget (see typography.md §7.4).

---

## 4. P1 violations

### P1.1 — Line-height on long-form prose just barely meets floor

- **Where:** `App.css:2649` `.explanation-card-content { line-height: 1.6 }`.
- **Strategy:** 1.65 for long-form reading.
- **Fix:** Single-value change. Cheap.

### P1.2 — Typewriter spotlight line-height (1.5) too loose for short centred text

- **Where:** `App.css:2734`.
- **Strategy:** `--type-spotlight` line-height 1.45 (display-ish behaviour).
- **Fix:** Tighten to 1.45 when content shifts to Lexend (size going up — leading can come down proportionally).

### P1.3 — Feedback / hint text below floor on activity surfaces

- **Where:** Activity hint/success messages around `App.css:1813`, `App.css:2020`, `App.css:2043` at 0.85-0.9rem.
- **Strategy:** `--type-body` (16px) for all student-visible feedback.
- **Fix:** Promote any `font-size: 0.85rem` or `0.9rem` that is student feedback text to `var(--fs-md)`.

### P1.4 — `--color-error: #e53e3e` borderline contrast on white

- **Contrast:** ~4.6:1 (passes AA normal, fails AAA).
- **Strategy:** Error text must pass 4.5:1. Marginal pass = risk on phones in sun.
- **Fix:** Darken to `#C4302B` (≈6:1) — still reads as "error red" but safer.

### P1.5 — Option-button selected state relies on colour alone in several captures

- **Where:** Multiple `.checkin-option-btn.selected` rules — change background + border colour but no weight shift.
- **Strategy:** Colour alone never carries meaning. Add `font-weight: 600` on `.selected` to reinforce.
- **Fix:** Add weight change in each selected-state rule. Small diffs.

---

## 5. P2 violations (scale & consistency)

### P2.1 — 31 distinct font-size values

Found by audit. Distribution:

| Size | Count | Action |
|---|---|---|
| 0.65, 0.7, 0.72, 0.75, 0.78, 0.8, 0.82 | ~78 total | Promote to `--fs-xs` (0.75) or `--fs-sm` (0.875) — pick per role |
| 0.85, 0.875, 0.88, 0.9, 0.92 | ~104 total | Most promote to `--fs-sm` (0.875); feedback text promotes to `--fs-md` (1) |
| 0.95, 1, 1.02, 1.05 | ~70 total | Promote to `--fs-md` (1); content prose promotes to `--fs-lg` (1.125) |
| 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45 | ~35 total | Stem / card-title / section heading — promote to `--fs-lg` / `--fs-xl` |
| 1.5, 1.55, 1.6 | ~15 total | Page titles — promote to `--fs-xl` (1.375) or `--fs-2xl` (1.75) |
| 1.75, 1.8, 1.85, 1.9, 2, 2.4, 2.5 | ~15 total | Display — promote to `--fs-2xl`, `--fs-3xl`, `--fs-4xl` |

**Fix approach:** Don't touch all 31 values in one PR. Migrate *by role*: one PR per content type (explanation, options, titles, meta). Keep primitives in tokens.css; introduce semantic `--type-*` aliases as planned; change `.class { font-size: 0.95rem }` → `font-size: var(--type-option);`

### P2.2 — Weight 500 scattered

Weight 500 appears ~40 times across `App.css` but provides no perceivable hierarchy vs 400 or 600.

**Fix:** Audit each `font-weight: 500` — if it's for emphasis, promote to 600; if it's decorative, demote to 400.

### P2.3 — ChatSession uses 8 competing sizes

Per audit: 0.8, 0.85, 0.9, 0.95, 1, 1.05, 1.3, 1.6 rem all appear on one screen family. Creates a "wall of sizes" feel.

**Fix:** Collapse to the five roles actually present on the screen:
- Card-type badge → `--type-caption` (0.75)
- Card title → `--type-card-title` (1.375)
- Body prose → `--type-body-reading` (1.125)
- Spotlight → `--type-spotlight` (1.75)
- Buttons → `--type-body` (1)

Five sizes, not eight. Remove intermediates.

### P2.4 — Line-height absent on many rules

Many rules set `font-size` without setting `line-height`, falling back to root `1.5`. That's OK for body prose but wrong for option buttons (want 1.45) and card titles (want 1.3).

**Fix:** Require line-height whenever `font-size` is set in a text rule.

### P2.5 — Monospace surfaces use `Courier New` instead of the loaded `--font-mono`

- **Where:** `App.css:2664` — `.explanation-card-visual { font-family: 'Courier New', monospace; font-size: 0.85rem; ... }`.
- **Strategy says:** All monospace surfaces (formula insets, code blocks, worked examples) must reference `var(--font-mono)` which resolves to JetBrains Mono (already loaded).
- **Why it matters:** `Courier New` is system-dependent. On Android/Linux it renders as a bitmap-y fallback that looks visually out of place next to Inter/Lexend prose. JetBrains Mono is already paid for in the font load — using it costs zero bytes.
- **Fix:** Replace `'Courier New', monospace` → `var(--font-mono)`. Promote `0.85rem` to a token — for formula/code inside prose, spec says `0.95em` of surrounding prose size, so consider removing the fixed size and inheriting.

### P2.6 — Typewriter spotlight `<pre>` blocks inherit body font

- **Where:** `App.css:2759-2762` — `.tw-spotlight-content pre { text-align: left; font-size: 1rem; }` — no `font-family` set.
- **Strategy says:** `<pre>` inside prose is a formula/code surface; must use `var(--font-mono)` per D1 and §5.6.
- **Why it matters:** Formulas rendered inside spotlight reveal currently render in the sans reading font, losing the "this is a formula" visual cue. Defeats the purpose of inset.
- **Fix:** Add `font-family: var(--font-mono);` to the `.tw-spotlight-content pre` rule. Also set explicit `line-height: 1.5` since spotlight default is 1.5 but when family switches to mono it should be re-asserted.

---

## 6. P3 violations (chrome polish)

- Mode badge at `0.7rem` (`App.css:1216`) — okay-ish as uppercase chip but should snap to `--fs-xs` (0.75).
- Breadcrumb sizes vary (`0.8, 0.85`) — unify to `--type-label` (0.875).
- Session-history timestamps at `0.8rem` — OK, promote to `--type-caption` token.

Low urgency — bundle with the P2 size-consolidation PR rather than separate work.

---

## 7. New infrastructure required

These do not exist today; must be added before P0 fixes can be expressed cleanly.

### 7.1 Load Lexend Deca

`index.html:13-15` — add Lexend Deca to the Google Fonts URL. Preconnect already present. Load only weights `400;600;700` (weight 500 is banned by typography D3). Variable-font syntax is preferred where available — one request replaces three static weights.

Also add `<link rel="preload" as="font" type="font/woff2" href="…lexend-deca-variable.woff2" crossorigin>` for the reading-font primary weight — explanation prose is on the critical path every session and this reduces font-swap CLS.

### 7.2 Add primitive AND semantic role tokens to App.css

The `--fs-*` scale exists **only in `llm-frontend/mockups/chalkboard/tokens.css:59-66`**, not in the live runtime. `App.css:1-113` has no size-scale tokens today. Phase 1 must add the primitives first, then layer semantics.

Add to `llm-frontend/src/App.css` `:root` block (after the spacing scale at line 87):

```css
/* Typography — primitives (mirrored from mockups/chalkboard/tokens.css) */
--fs-xs:   0.75rem;   /* 12px */
--fs-sm:   0.875rem;  /* 14px */
--fs-md:   1rem;      /* 16px */
--fs-lg:   1.125rem;  /* 18px */
--fs-xl:   1.375rem;  /* 22px */
--fs-2xl:  1.75rem;   /* 28px */
--fs-3xl:  2.25rem;   /* 36px */
--fs-4xl:  3rem;      /* 48px */

/* Reading font (evidence-backed for Grade 3-8 fluency) */
--font-reading: 'Lexend Deca', 'Lexend', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;

/* Semantic role tokens — always reference these in components, not raw --fs-* */
--type-caption:      var(--fs-xs);    /* 12px — chrome meta only */
--type-label:        var(--fs-sm);    /* 14px — UI labels, breadcrumbs */
--type-body:         var(--fs-md);    /* 16px — secondary UI, options */
--type-option:       var(--fs-md);    /* 16px — answer choices */
--type-body-reading: var(--fs-lg);    /* 18px — long-form prose */
--type-stem:         var(--fs-lg);    /* 18px — question stems */
--type-card-title:   var(--fs-xl);    /* 22px — card headings */
--type-page-title:   var(--fs-2xl);   /* 28px — screen titles */
--type-spotlight:    var(--fs-2xl);   /* 28px — typewriter reveal */
--type-display:      var(--fs-3xl);   /* 36px — celebration / score display */
```

### 7.3 Tabular numerals utility

`App.css` body rule gets an opt-in:

```css
.tabular-nums {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum";
}
```

Apply to: timer displays, streak counts, score counters, report-card numerics.

### 7.4 Update `--color-text-muted` or purge its student-content usage

Current: `--color-text-muted: #999;` fails AA.

Option A (preferred): redefine to `#5A5A5A` (≈7:1) — acceptable on white.
Option B: leave variable, but grep and remove every application in student-facing components; allow only on admin.

### 7.5 Accessibility smoke: add an eslint or CI lint for `px` on font-size

Catch regressions where someone types `font-size: 14px;` instead of using tokens.

---

## 8. Suggested rollout plan (measured, not big-bang)

**Phase 1 — foundations (½–1 day, no visible change if deferred):**
- Load Lexend Deca (weights 400/600/700 only; preload primary weight)
- **Add primitive `--fs-*` scale to `App.css:1-113` `:root`** (does not exist in live CSS today — mockup-only)
- Add `--font-reading` variable
- Add semantic `--type-*` tokens on top of the primitives
- Add `.tabular-nums` utility
- Darken `--color-error`; redefine or purge `--color-text-muted`
- Update `index.html` font loads and preload hint

**Phase 2 — primary reading surface (1 day, visible impact):**
- Explanation card body (`App.css:2648`) → `--type-body-reading` Lexend 1.65
- Typewriter spotlight (`App.css:2733`) → `--type-spotlight` Lexend 1.45
- Spotlight `<pre>` (`App.css:2759`) → add `var(--font-mono)`
- Explanation visual formula inset (`App.css:2664`) → replace `'Courier New'` with `var(--font-mono)`
- Chapter / topic description prose → Lexend Deca

**Phase 3 — shared check-in / practice base rules (2 days):**

Covers P0.3 (in-session check-in family) and the legacy non-chalkboard option rules in one pass, because they share the same base classes.

- `.checkin-*` base at `App.css:3269-3453` — swap to `--type-*` tokens, set Lexend on stem/instruction/feedback surfaces, drop weight 500, set line-heights per role
- Per-activity base: `.tf-*`, `.fill-*`, `.sort-*`, `.seq-*`, `.error-*`, `.odd-*`, `.predict-*`, `.eliminate-*`, `.match-*`, `.swipe-*` — each statement/instruction/item text bumped to correct token + font
- Legacy match-pairs / check-in option rules → `--type-option` 1rem 1.45 Lexend
- Feedback / hint text → `--type-body` 1rem 1.5
- Option-selected state adds weight shift (P1.5)

Browser-verify each of the 11 check-in types in a Teach-Me session before moving on.

**Phase 4 — chalkboard overrides + practice surface (2-3 days, biggest surface):**

Covers the two distinct chalkboard-scoped rule blocks:

**(a) In-session chalkboard overrides — `App.css:4310-4505`:** These rules currently touch colour/border/font-family only. Add `font-family: var(--font-reading);` on the reading-prose surfaces (`.chalkboard-active .tf-statement`, `.chalkboard-active .fill-sentence`, `.chalkboard-active .checkin-instruction`). If Phase 3 already got sizes/line-heights right on the base rules, overrides should NOT need to restate them — audit to confirm, simplify any restatement.

**(b) Practice chalkboard surface — `App.css:7400-7660`:** The P0.6 audit shows ~16 independent rules, of which ~7 are direct P0 violations (handwritten bucket labels, sub-floor student-content sizes, wrong font on swipe cards, undersize free-form textarea, etc.). Realistic estimate:

- Per-rule pass on lines 7400-7660 (enumerate the 16 rules, apply correct token per role map)
- Practice question stem (`App.css:7268`) — Caveat → Lexend, size-token
- Bucket label (`App.css:7477`) — Caveat → Inter uppercase
- Verify in browser on each of the 11 practice capture formats under `/practice/*`

**Acceptance for Phase 4:** no `.chalkboard-active` rule sets a fixed-px size or weight 500; no non-decorative text uses `var(--font-hand)`; reading-prose surfaces explicitly declare `--font-reading` when the base rule doesn't.

**Phase 5 — consolidation of legacy 31-size chaos (2-3 days, largely mechanical):**
- Grep each legacy `font-size: X.XXrem` / `font-size: Xpx` in `App.css`, classify by role, swap to `var(--type-*)`
- Drop weight 500 everywhere
- Unify breadcrumb / meta / caption sizes
- ChatSession 8-size collapse to 5 roles (P2.3)

**Phase 6 — accessibility pass (½ day):**
- Contrast audit on every colour pair (automated via a `contrast-check` script over `--color-*` tokens)
- Dynamic Type smoke test (iOS settings → Larger Text → every student screen still usable; specifically check fixed-px sites called out in P1/P2)
- Verify tap targets ≥ 44×44 everywhere
- Performance acceptance (typography.md §7.4): LCP ≤ 2.5s on Fast-3G simulation; CLS ≤ 0.05 attributable to font swap

**Total: ~9-11 engineering days** for complete typographic alignment across the student surface. Phase 2 delivers the single largest learning-quality gain on the primary reading surface (~40-50% of the benefit). Phase 3 delivers the biggest reach win (in-session check-ins happen in every Teach-Me session). Phase 4 completes the chalkboard story end-to-end.

---

## 9. Measurement (post-rollout)

All targets are falsifiable — if they don't move, we rolled back or re-designed. "Should rise slightly" is banned as a measure; every entry below has a direction, magnitude, and window.

### Primary learning-quality metrics

| Metric | Baseline | Target | Window | How measured |
|---|---|---|---|---|
| **Re-read rate on explanation cards** (scroll-back or "I didn't understand" tap rate per student-session) | Capture 7 days before Phase 2 ships | −20% relative | 7-day rolling, post-Phase-2 | Event stream; exclude first-time visitors for 3 days (cold-start noise) |
| **Practice first-try correctness on multi-line options** (questions with option text > 1 line) | Same 7-day baseline | +3–5 percentage points | 14-day rolling, post-Phase-3 and Phase-4 | Group by student to control for cohort mix; pair test pre/post |
| **Explanation-card abandonment** (closed / navigated away before reaching the last block) | Baseline capture | −15% relative | 7-day rolling, post-Phase-2 | Event stream |
| **Practice-quiz accuracy delta after explanation** | Baseline capture | Positive-direction only (no target magnitude) | 14-day rolling, post-Phase-2 | Compare student's next practice session to their historical average on same topic |

### Accessibility / infrastructure metrics (pass/fail, not directional)

| Metric | Target |
|---|---|
| Automated contrast check (CI) on every `--color-*` token vs every surface it renders on | **100% pass** at 4.5:1 normal / 3:1 large |
| **New** `font-size: Xpx` introduced after Phase 1 (enforced via lint / CI grep) | **Zero** — no regressions |
| Remaining `font-size: Xpx` in student-facing CSS | **Zero** by Phase 5 completion (progressively eliminated in Phases 2-5 as each surface migrates) |
| `font-weight: 500` occurrences in student-facing CSS | **Zero** post-Phase 5 |
| `Courier New` / system monospace fallback in student-facing CSS | **Zero** post-Phase 2 |
| `var(--font-hand)` applications outside decorative whitelist (card type labels, celebration, page-title flourish) | **Zero** post-Phase 4 |
| LCP on `ChatSession` explanation-card-mount, Fast-3G simulated | **≤ 2.5 s** |
| CLS attributable to font swap per screen | **≤ 0.05** |
| Total font payload for student surface, cold load | **≤ 150 KB compressed** |

### Qualitative / sentinel signals

- **Report-issue entries** tagged "can't read" / "too small" / "font" in the 30 days post-rollout: target **zero**. A single recurrence should trigger investigation of the specific surface named.
- **Support / WhatsApp parent feedback** mentioning font/readability: watch for absence of complaints (we don't get compliments on typography, only complaints).

### Anti-measure

**Do not** use "time spent on explanation cards" as a measure. It's ambiguous: rising time could mean "reading more carefully" (good) or "struggling to decode" (bad). The re-read rate and abandonment rate disambiguate.

---

## 10. Out of scope

- Admin dashboards (`features/admin/*`) — not student-facing.
- Devtools drawer (`features/devtools/*`) — not student-facing.
- Copy content itself — belongs to `docs/principles/easy-english.md` and `docs/principles/how-to-explain.md`, not typography.
- Localisation into Hindi / Tamil / Telugu — future; separate effort (different font stacks required).
- Email notification typography — separate channel, not app.
