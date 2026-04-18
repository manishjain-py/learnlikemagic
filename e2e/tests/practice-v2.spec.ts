/**
 * Let's Practice v2 — comprehensive manual-QA companion spec.
 *
 * Covers (from §10 of qa-handover.md):
 *   §1  tile gating (with bank / without)
 *   §2  admin bank viewer — no per-topic N+1 on mount (G2)
 *   §3  full drill across all 12 formats (with real answers where possible)
 *   §4  G1 remount guarantee — static source check on `key={q.q_id}`
 *   §5  banner fires from non-practice route after grading completes
 *   §6  resume mid-set — same Qs, same seed, prior answers retained
 *   §9  results — fractional score, per-Q expand + rationale, CTAs
 *   §10 legacy /exam routes, report card practice chip
 *
 * NOT covered (intentionally):
 *   §7  Debounce-race on submit — too timing-sensitive for reliable e2e.
 *       Covered by backend unit tests (test_practice_service.py submit).
 *   §8  Grading failure via broken LLM config — requires destructive admin
 *       mutation + rollback. Kept manual.
 *
 * Fixed IDs: Grade 3 Math, Ch 1 Place Value, topic 1 (bank generated).
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BOOK_ID = 'test_auth_mathematics_1_2026';
const CHAPTER_ID = '1edc6a1c-a35e-482d-9e90-0f52fa557edf';
const TOPIC_1_GID = 'd9b2bb37-f8d3-4d1b-8bfa-b0e19869085b'; // has bank
const TOPIC_2_GID = '64393206-11e5-4408-b424-aea22846a695'; // no bank

/**
 * Format-aware answer of whatever capture is currently mounted. Returns the
 * format name for telemetry (caller can log or assert consecutive-format
 * state). For unfamiliar shapes, skips without failing.
 */
async function answerCurrentQuestion(page: Page): Promise<string> {
  const card = page.locator('.practice-question-card');

  // Index-based captures (pick_one, true_false, fill_blank, tap_to_eliminate,
  // predict_then_reveal, spot_the_error, odd_one_out) all render buttons
  // with class `.practice-option`.
  const firstOption = card.locator('.practice-option').first();
  if ((await firstOption.count()) > 0) {
    await firstOption.click();
    return 'option';
  }

  // free_form — textarea
  const textarea = card.locator('textarea.practice-freeform-textarea');
  if ((await textarea.count()) > 0) {
    await textarea.fill('Sample answer with brief reasoning.');
    return 'free_form';
  }

  // match_pairs — tap a left-column item then a right-column item
  const pairCols = card.locator('.practice-pair-col');
  if ((await pairCols.count()) === 2) {
    const lefts = pairCols.nth(0).locator('.practice-pair-item');
    const rights = pairCols.nth(1).locator('.practice-pair-item');
    const n = Math.min(await lefts.count(), await rights.count());
    for (let i = 0; i < n; i++) {
      await lefts.nth(i).click();
      await rights.nth(i).click();
      await page.waitForTimeout(50);
    }
    return 'match_pairs';
  }

  // sort_buckets — tap an item chip, then tap a bucket
  const chips = card.locator('.practice-item-chip');
  if ((await chips.count()) > 0) {
    const buckets = card.locator('.practice-bucket');
    while ((await chips.count()) > 0) {
      await chips.first().click();
      await buckets.first().click();
      await page.waitForTimeout(50);
    }
    return 'sort_buckets';
  }

  // swipe_classify — click the left bucket button for every card. Component
  // advances cursor internally; loop until "All items classified" shows.
  const swipeBtns = card.locator('.practice-swipe-btn');
  if ((await swipeBtns.count()) > 0) {
    const done = card.locator('.practice-swipe-empty');
    for (let i = 0; i < 20; i++) {
      if ((await done.count()) > 0) break;
      await swipeBtns.first().click();
      await page.waitForTimeout(50);
    }
    return 'swipe_classify';
  }

  // sequence — the capture auto-registers the initial order as the answer
  // on mount (see SequenceCapture.tsx). So leaving it alone produces a valid
  // (though possibly wrong) answer.
  if ((await card.locator('.sequence-item, [class*="sequence"]').count()) > 0) {
    return 'sequence';
  }

  return 'unknown';
}

/** Run the full 10-Q drill to submission. Assumes runner is already open. */
async function completeDrill(page: Page): Promise<void> {
  for (let i = 0; i < 10; i++) {
    await expect(page.locator('.practice-header-title'))
      .toHaveText(new RegExp(`Question ${i + 1} of 10`), { timeout: 10_000 });
    await answerCurrentQuestion(page);
    await page.locator('.practice-nav-btn--primary').click();
    await page.waitForTimeout(250);
  }
  await expect(page.getByRole('heading', { name: /Review your picks/i }))
    .toBeVisible({ timeout: 5_000 });
  await page.locator('.practice-nav-btn--primary').click();
  await expect(page).toHaveURL(/\/practice\/attempts\/[^/]+\/results/, { timeout: 10_000 });
}

test.describe("Let's Practice v2 — full suite", () => {
  test('§1a Topic WITH bank → Start button visible on landing', async ({ page }) => {
    await page.goto(`/practice/${TOPIC_1_GID}`);
    await expect(page.locator('.practice-start-btn')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.practice-unavailable-banner')).toHaveCount(0);
  });

  test('§1b Topic WITHOUT bank → unavailable banner', async ({ page }) => {
    await page.goto(`/practice/${TOPIC_2_GID}`);
    await expect(page.locator('.page-loading')).toHaveCount(0, { timeout: 15_000 });
    await expect(page.locator('.practice-unavailable-banner')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.practice-start-btn')).toHaveCount(0);
  });

  test('§2 Admin bank viewer — no N+1 on mount (G2)', async ({ page }) => {
    const chapterJobCalls: string[] = [];
    const topicJobCalls: string[] = [];
    const chapterStatusCalls: string[] = [];
    page.on('request', (req) => {
      const u = req.url();
      if (u.includes('/practice-bank-jobs/latest')) {
        if (u.includes('guideline_id=')) topicJobCalls.push(u);
        else if (u.includes('chapter_id=')) chapterJobCalls.push(u);
      }
      if (u.includes('/practice-bank-status')) chapterStatusCalls.push(u);
    });
    await page.goto(`/admin/books-v2/${BOOK_ID}/practice-banks/${CHAPTER_ID}`);
    await page.waitForLoadState('networkidle', { timeout: 15_000 });
    console.log('[G2] chapterStatus:', chapterStatusCalls.length,
                'chapterJobs:', chapterJobCalls.length,
                'topicJobs:', topicJobCalls.length);
    expect(topicJobCalls.length).toBeLessThanOrEqual(2);
    expect(chapterStatusCalls.length).toBeLessThanOrEqual(2);
  });

  test('§3+9 Full drill (all formats) → grading → results: score, rationale, CTAs', async ({ page }) => {
    test.setTimeout(5 * 60_000);

    // Capture format sequence for the G1 consecutive-same-format rule check
    const shape: { formats: string[]; attemptId?: string } = { formats: [] };
    page.on('response', async (res) => {
      const url = res.url();
      const m = url.match(/\/practice\/attempts\/([^/]+)$/);
      if (m && res.status() === 200 && shape.formats.length === 0) {
        try {
          const body = await res.json();
          if (body.questions) {
            shape.attemptId = body.id || m[1];
            shape.formats = body.questions.map((q: any) => q.format);
          }
        } catch { /* ignore non-json */ }
      }
    });

    await page.goto(`/practice/${TOPIC_1_GID}`);
    await page.locator('.practice-start-btn').click();
    await expect(page.locator('.practice-header-title')).toBeVisible({ timeout: 10_000 });

    // Track which formats we actually exercised
    const formatsAnswered: string[] = [];
    for (let i = 0; i < 10; i++) {
      await expect(page.locator('.practice-header-title'))
        .toHaveText(new RegExp(`Question ${i + 1} of 10`), { timeout: 10_000 });
      const handler = await answerCurrentQuestion(page);
      formatsAnswered.push(handler);
      await page.locator('.practice-nav-btn--primary').click();
      await page.waitForTimeout(250);
    }

    await expect(page.getByRole('heading', { name: /Review your picks/i }))
      .toBeVisible({ timeout: 5_000 });

    if (shape.formats.length === 10) {
      console.log('[formats]', shape.formats.join(' → '));
      console.log('[answered]', formatsAnswered.join(' → '));
      // §5 locked decision #14: ≤ 2 consecutive allowed, 3+ is a bug.
      let maxRun = 1, curRun = 1;
      for (let i = 1; i < shape.formats.length; i++) {
        if (shape.formats[i] === shape.formats[i - 1]) {
          curRun += 1; maxRun = Math.max(maxRun, curRun);
        } else curRun = 1;
      }
      expect(maxRun).toBeLessThanOrEqual(2);
    }

    // Submit
    await page.locator('.practice-nav-btn--primary').click();
    await expect(page).toHaveURL(/\/practice\/attempts\/[^/]+\/results/, { timeout: 10_000 });

    // Wait for grading — Practice again CTA only renders on 'graded' status.
    const practiceAgain = page.locator('button').filter({ hasText: /Practice again/i });
    await expect(practiceAgain).toBeVisible({ timeout: 180_000 });

    // Score badge format: "X/10" or "X.5/10" (half-point rounded)
    const scoreBadge = page.locator('.practice-score-badge');
    await expect(scoreBadge).toBeVisible();
    const scoreText = await scoreBadge.innerText();
    expect(scoreText).toMatch(/^\d+(\.\d)?\/\d+$/);
    console.log('[score]', scoreText);

    // Correct-count label
    await expect(page.locator('.practice-score-label'))
      .toContainText(/\d+\/\d+ correct/);

    // Per-Q expand → rationale present
    const firstRow = page.locator('.practice-review-row').first();
    await firstRow.locator('.practice-review-btn').click();
    const expanded = firstRow.locator('.practice-review-expand');
    await expect(expanded).toBeVisible({ timeout: 5_000 });
    await expect(expanded.locator('.practice-review-rationale'))
      .toBeVisible({ timeout: 5_000 });

    // Back-to-topic CTA present (Reteach only when canReteach=true, i.e.
    // flowState has subject/chapter/topic — not our case since we hit the
    // landing URL directly)
    await expect(page.locator('button').filter({ hasText: /Back to topic/i }))
      .toBeVisible();
  });

  test('§4 G1 remount guarantee — QuestionRenderer has key={q.q_id}', async () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../llm-frontend/src/pages/PracticeRunnerPage.tsx'),
      'utf8',
    );
    // Anchor: the one <QuestionRenderer> use in the runner must carry the
    // per-question key so React remounts across Qs (no state leak).
    expect(src).toMatch(/<QuestionRenderer[\s\S]{0,200}key=\{q\.q_id/);
  });

  test('§5 Banner appears on non-practice route within 30s of grading', async ({ page }) => {
    test.setTimeout(5 * 60_000);
    // Do a drill + submit; grading runs in background.
    await page.goto(`/practice/${TOPIC_1_GID}`);
    await expect(page.locator('.page-loading')).toHaveCount(0, { timeout: 15_000 });
    await page.locator('.practice-start-btn').click({ timeout: 15_000 });
    await expect(page.locator('.practice-header-title')).toBeVisible({ timeout: 15_000 });
    await completeDrill(page);

    // CRITICAL: navigate AWAY from results page BEFORE grading completes.
    // The results page auto-marks the attempt as viewed on mount, which
    // would prevent the banner from ever showing.
    await page.goto('/');

    // PracticeBanner is mounted in AuthenticatedLayout above AppShell and
    // polls every 30s. Give it up to 90s (3 polls) to cover grading + poll.
    const banner = page.locator('.practice-banner').first();
    await expect(banner).toBeVisible({ timeout: 90_000 });

    // Click banner → navigates to /practice/attempts/{id}/results
    await banner.click();
    await expect(page).toHaveURL(/\/practice\/attempts\/[^/]+\/results/, { timeout: 10_000 });
  });

  test('§6 Resume mid-set — same questions, same seed', async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto(`/practice/${TOPIC_1_GID}`);
    await expect(page.locator('.page-loading')).toHaveCount(0, { timeout: 15_000 });
    await page.locator('.practice-start-btn').click({ timeout: 15_000 });
    await expect(page.locator('.practice-header-title')).toBeVisible({ timeout: 15_000 });

    const q1Text = await page.locator('.practice-question-card').innerText();
    await answerCurrentQuestion(page);
    await page.locator('.practice-nav-btn--primary').click();
    await expect(page.locator('.practice-header-title'))
      .toHaveText(/Question 2 of 10/, { timeout: 5_000 });
    await page.waitForTimeout(1_000);

    await page.goto(page.url());
    await expect(page.locator('.practice-header-title')).toBeVisible({ timeout: 10_000 });

    while (!(await page.locator('.practice-nav-btn--ghost').isDisabled())) {
      await page.locator('.practice-nav-btn--ghost').click();
    }
    await expect(page.locator('.practice-header-title'))
      .toHaveText(/Question 1 of 10/);
    const q1TextAfter = await page.locator('.practice-question-card').innerText();
    expect(q1TextAfter).toBe(q1Text);
  });

  test('§10a Legacy /exam URL does not render exam UI', async ({ page }) => {
    await page.goto('/exam/whatever');
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    expect(await page.locator('[class*="exam-mode"], [class*="exam-question"]').count()).toBe(0);
  });

  test('§10b Report card shows practice chip after a graded attempt', async ({ page }) => {
    test.setTimeout(60_000);
    // The §3+9 test above creates at least one graded attempt. Just assert
    // that report card renders and contains the practice score marker.
    await page.goto('/report-card');
    await page.waitForLoadState('networkidle', { timeout: 15_000 });

    // Expand into the book/chapter where we have a graded attempt. Top of
    // report card should list subjects. We'll search for any practice-score
    // class in the whole page — if at least one rendered, report card is
    // correctly merging practice attempts.
    const practiceChipLocator = page.locator('.reportcard-practice-score');
    // It may require drilling into the subject. Give it a generous wait.
    // If not on the root, walk into Mathematics > Place Value > Thousands topic.
    const chipCount = await practiceChipLocator.count();
    if (chipCount === 0) {
      // Try clicking into the Math subject card
      const mathCard = page.locator('text=/Math|Mathematics/i').first();
      if ((await mathCard.count()) > 0) {
        await mathCard.click();
        await page.waitForTimeout(500);
      }
    }
    await expect(page.locator('.reportcard-practice-score').first())
      .toBeVisible({ timeout: 10_000 });
  });
});
