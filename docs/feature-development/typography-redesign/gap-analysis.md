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
| Semantic role tokens | Exist in CSS | Only primitive `--fs-*` | Add `--type-*` semantic layer |
| Tabular numerals on scores/timers | Required | None | Add `font-variant-numeric: tabular-nums` |

---

## 2. Priority matrix

Fixes are ranked by **learning impact × reach**. A bug on the primary reading surface that every student hits every session = P0. A 0.7rem badge on one legacy screen = P3.

| P | Definition | Examples |
|---|---|---|
| P0 | Directly degrades reading fluency on primary content surface. Every student, every session. | Body prose undersize + wrong font; option sizes; Caveat on stems |
| P1 | Degrades comprehension on secondary content surface. Most students, most sessions. | Practice feedback undersize; line-height on options; muted-colour contrast fails |
| P2 | Visual chaos / inconsistency. Doesn't fail comprehension but undermines design trust and future maintenance. | 31-size scale; weight 500 sprinkled; ChatSession 8-size overload |
| P3 | Chrome polish. Low single-student impact. | Badge micro-sizes; breadcrumb size variance |

---

## 3. P0 violations (fix before anything else)

### P0.1 — Explanation prose is too small and in the wrong font

- **Where:** `llm-frontend/src/App.css` ~line 2648 — `.explanation-card-content` at `1.05rem / Inter / line-height 1.6`.
- **Also:** `TypewriterMarkdown.tsx` spotlight at `1.6rem Inter / 1.5`.
- **Strategy says:** `--type-body-reading` = `1.125rem / Lexend Deca / 1.65`; spotlight = `--type-spotlight` = `1.75rem Lexend / 1.45`.
- **Why it matters:** This is the single most-read surface in the app. Every minute of the tutor talking lands here. Research (MDPI 2024 children's reading speed; Lexend WCPM study) shows 18px Lexend beats 16.8px Inter for Grade 3-8 readers — and ESL students benefit most.
- **Fix:** Add Lexend Deca to font loads in `index.html`; add `--font-reading: 'Lexend Deca', 'Lexend', ...` in `App.css:73-77`; apply `font-family: var(--font-reading); font-size: var(--fs-lg); line-height: 1.65;` to `.explanation-card-content` and `.tw-spotlight-content`.

### P0.2 — Caveat planned for practice question stems

- **Where:** `App.css` ~line 7268 — `.chalkboard-active .practice-question-text { font-family: var(--font-hand); font-size: 1.45rem; }`.
- **Strategy says:** Question stems must be Lexend Deca (never Caveat/handwritten). Caveat reserved for decorative labels and celebration only.
- **Why it matters:** Cursive/handwritten fonts measurably slow elementary reading. On a question stem the student has to parse *fast* to answer, every decoding millisecond compounds across a 20-question practice set.
- **Fix:** Keep chalkboard aesthetic by applying Caveat to the card's *type label* and *card corners* only. Stem goes to `--type-stem` Lexend Deca on the chalkboard surface (white on green passes 9:1 contrast).
- **Urgency:** This lands with the chalkboard rollout. Catch it **before** chalkboard migrates any student screen.

### P0.3 — Practice / check-in options too small with tight leading

- **Where:** 
  - `App.css:3166-3168` — match-pairs items `0.95rem / 1.3`
  - `App.css:3299-3301` — check-in option `0.95rem / 1.3`
  - Practice capture components inherit similar pattern
- **Strategy says:** `--type-option` = `1rem / Lexend Deca / line-height 1.45`.
- **Why it matters:** Options are read under task pressure and are often 2-3 lines. `0.95rem` (15.2px) + `1.3` leading is cramped; slows decoding, increases rage-tap misreads.
- **Fix:** Bump size to `1rem`, line-height to `1.45`, switch font-family on the captures that carry student content to Lexend Deca. Shared `.practice-option`, `.checkin-option-btn` classes — two CSS edits cover most surfaces.

### P0.4 — `--color-text-muted: #999` used anywhere carrying content meaning

- **Where:** `App.css:10`, applied as `color: var(--color-text-muted)` or equivalently `color: #999` throughout.
- **Contrast:** ~2.85:1 on white. **Fails WCAG AA (4.5:1).**
- **Strategy says:** Banned for student content. Allowed only for pure visual separators that carry no meaning.
- **Fix:** Replace with `--color-text-secondary` (currently `#666`, ~5.7:1). If `#666` looks too dark in a design, promote to `#5A5A5A` (≈7:1) — subjectively similar weight but passes AAA for large text. Grep for `#999` in `App.css` — expect 10-30 call sites — review each.

### P0.5 — Lexend Deca not loaded

- **Where:** `index.html:13-15` loads Inter + Caveat + JetBrains Mono. No Lexend.
- **Fix:** Add `&family=Lexend+Deca:wght@400;500;600;700` to the Google Fonts URL. Add `--font-reading: 'Lexend Deca', 'Lexend', -apple-system, ...` variable. No font sprawl — Lexend Deca replaces nothing; it's the *fourth* font, each with a narrow role.

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

`index.html:13-15` — add to the Google Fonts URL. Preconnect already present.

### 7.2 Add semantic role tokens

`App.css` top `:root` block (after `--fs-4xl` at line 66):

```css
/* Reading font (evidence-backed for Grade 3-8 fluency) */
--font-reading: 'Lexend Deca', 'Lexend', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

/* Semantic role tokens — always reference these in components, not raw --fs-* */
--type-caption:      var(--fs-xs);     /* 12px — chrome meta only */
--type-label:        var(--fs-sm);     /* 14px — UI labels, breadcrumbs */
--type-body:         var(--fs-md);     /* 16px — secondary UI, options */
--type-option:       var(--fs-md);     /* 16px — answer choices */
--type-body-reading: var(--fs-lg);     /* 18px — long-form prose */
--type-stem:         var(--fs-lg);     /* 18px — question stems */
--type-card-title:   var(--fs-xl);     /* 22px — card headings */
--type-page-title:   var(--fs-2xl);    /* 28px — screen titles */
--type-spotlight:    var(--fs-2xl);    /* 28px — typewriter reveal */
--type-display:      var(--fs-3xl);    /* 36px — celebration */
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

**Phase 1 — foundations (½ day, no visible change if deferred):**
- Load Lexend Deca
- Add semantic `--type-*` tokens (map to existing `--fs-*`)
- Add `.tabular-nums` utility
- Darken `--color-error`; redefine `--color-text-muted`

**Phase 2 — primary reading surface (1 day, visible impact):**
- Explanation card body → `--type-body-reading` Lexend 1.65
- Typewriter spotlight → `--type-spotlight` Lexend 1.45
- Chapter / topic description prose → Lexend Deca

**Phase 3 — practice + check-in (1-2 days):**
- Question stems → `--type-stem` Lexend 1.55
- Options / answer choices → `--type-option` 1rem 1.45 Lexend
- Feedback / hint text → `--type-body` 1rem 1.5

**Phase 4 — chalkboard-migration gate (1-day sweep during chalkboard work):**
- Ensure chalkboard migration uses Lexend for stems / options / prose
- Caveat only on: card type labels, celebration headlines, page-title flourish
- Every new chalkboard component must pick a row from the role map

**Phase 5 — consolidation (2-3 days, largely mechanical):**
- Collapse 31 sizes → 8 primitives + 10 semantic tokens
- Drop weight 500 everywhere
- Unify breadcrumb / meta / caption sizes

**Phase 6 — accessibility pass (½ day):**
- Contrast audit on every colour pair (automated with contrast checker script)
- Dynamic Type smoke test (iOS settings → Larger Text → every screen still usable)
- Verify tap targets ≥ 44×44 everywhere

**Total: ~6-8 engineering days** for complete typographic alignment across student surface. Phase 2 alone delivers ~70% of the learning-quality gain.

---

## 9. Measurement (post-rollout)

How we'll know it worked:

- **Reading speed proxy:** Time spent on explanation cards before clicking Next — should rise slightly (students are reading more) without sessions getting longer (they're also comprehending more).
- **Re-read rate:** Proportion of students who scroll back or tap "I didn't understand" on an explanation. Target: -20% on migrated surfaces.
- **Practice accuracy on first attempt:** If option-label legibility improves, first-try correctness on multi-line options ticks up.
- **Complaint patterns:** Report-issue entries tagged "can't read" / "too small" go to zero.
- **Dynamic Type usage:** Some students have OS font-size cranked up — post-fix their experience should no longer break layouts.
- **Automated contrast check (CI):** 100% pass on every production CSS colour pair.

---

## 10. Out of scope

- Admin dashboards (`features/admin/*`) — not student-facing.
- Devtools drawer (`features/devtools/*`) — not student-facing.
- Copy content itself — belongs to `docs/principles/easy-english.md` and `docs/principles/how-to-explain.md`, not typography.
- Localisation into Hindi / Tamil / Telugu — future; separate effort (different font stacks required).
- Email notification typography — separate channel, not app.
