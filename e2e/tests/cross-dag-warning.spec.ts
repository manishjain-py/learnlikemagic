/**
 * Cross-DAG warning banner — Phase 6b.
 *
 * Verifies the polling → render → action loop on TopicDAGView without
 * driving a real `topic_sync` (which is destructive and is already
 * integration-tested in
 *   tests/integration/test_topic_pipeline_dag.py
 *     ::test_full_lifecycle_with_topic_sync_delete_recreate
 * ). The trade is intentional: this spec covers the frontend wiring;
 * the backend test covers the actual delete-recreate semantics.
 *
 * Flow:
 *   1. Navigate to the topic DAG dashboard.
 *   2. Assert no banner.
 *   3. POST `_test/diverge` — flips the stored hash so the next poll
 *      returns `chapter_resynced`.
 *   4. Trigger a poll tick (visibilitychange) so we don't wait the full
 *      30s slow-poll interval.
 *   5. Banner appears.
 *   6. Click "Rerun explanations" (intercepted via page.route so the
 *      real cascade doesn't kick off and re-generate explanations).
 *   7. Assert the rerun POST was dispatched.
 *
 * Cleanup: POST `_test/restore` to put the live hash back so subsequent
 * runs (and any human watching the fixture) don't see a stale banner.
 *
 * Fixture (matches practice-v2.spec.ts): Grade 3 Math, Ch 1, topic 1.
 * That topic must already have explanations done — the banner depends
 * on a captured hash row in `topic_content_hashes`.
 */

import { test, expect } from '@playwright/test';

const BOOK_ID = 'test_auth_mathematics_1_2026';
const CHAPTER_ID = '1edc6a1c-a35e-482d-9e90-0f52fa557edf';
const TOPIC_KEY = 'thousands-and-4-digit-numbers';
const GUIDELINE_ID = 'd9b2bb37-f8d3-4d1b-8bfa-b0e19869085b';

const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://localhost:8000';
const DASHBOARD_URL = `/admin/books-v2/${BOOK_ID}/pipeline/${CHAPTER_ID}/${TOPIC_KEY}`;

test.describe('Cross-DAG warning banner', () => {
  test.afterEach(async ({ request }) => {
    // Always restore — even on failure — so a flaky run doesn't leave the
    // fixture topic permanently flagged. 404 is fine if the fixture was
    // already missing before the test ran.
    await request
      .post(
        `${BACKEND_URL}/admin/v2/topics/${GUIDELINE_ID}/cross-dag-warnings/_test/restore`,
      )
      .catch(() => undefined);
  });

  test('inject hash divergence → banner appears → Rerun button fires cascade', async ({
    page,
    request,
  }) => {
    // Intercept the rerun POST so we don't actually re-run explanations
    // (which costs ~minutes of LLM calls). The unit + integration tests
    // already cover the cascade orchestrator; this spec just verifies the
    // banner button is wired to the right HTTP call.
    let rerunHit = false;
    await page.route(
      `**/admin/v2/topics/${GUIDELINE_ID}/stages/explanations/rerun`,
      async (route) => {
        rerunHit = true;
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            cascade_id: 'e2e-mock-cascade',
            pending: ['explanations'],
            running: 'explanations',
            message: 'Mocked cascade',
          }),
        });
      },
    );

    await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });
    // The DAG endpoint runs lazy backfill on first read and takes ~7s on the
    // fixture topic; allow 30s slack so the canvas has time to render.
    await page.waitForSelector('.react-flow', { timeout: 30_000 });

    // Baseline: no warning yet.
    await expect(page.locator('[data-testid="cross-dag-warning"]')).toHaveCount(0);

    // Flip the hash via the test-only inject endpoint. Returns the warning
    // it just created so we can sanity-check the response.
    const injectResp = await request.post(
      `${BACKEND_URL}/admin/v2/topics/${GUIDELINE_ID}/cross-dag-warnings/_test/diverge`,
    );
    expect(
      injectResp.ok(),
      `inject endpoint failed (${injectResp.status()}). The fixture topic must ` +
        'have explanations done at least once — check that the GUIDELINE_ID ' +
        'matches a topic with a captured hash row.',
    ).toBeTruthy();
    const injectBody = await injectResp.json();
    expect(injectBody.warnings).toHaveLength(1);
    expect(injectBody.warnings[0].kind).toBe('chapter_resynced');

    // Force the next polling tick so we don't wait 30s. TopicDAGView
    // listens for `visibilitychange` and re-ticks when the page is visible
    // — we just dispatch the event without changing visibility, so the
    // handler runs the "visible" branch which clears the timer + ticks.
    await page.evaluate(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Banner appears.
    const banner = page.locator('[data-testid="cross-dag-warning"]');
    await expect(banner).toBeVisible({ timeout: 10_000 });
    await expect(banner).toContainText('Chapter content changed');

    // Rerun button is present and enabled.
    const rerunBtn = banner.locator('button', { hasText: /Rerun explanations/ });
    await expect(rerunBtn).toBeEnabled();

    await rerunBtn.click();

    // The intercepted route should have been hit. Poll because the click
    // handler fires the request asynchronously.
    await expect.poll(() => rerunHit, { timeout: 5_000 }).toBe(true);

    // The success toast confirms the click handler ran end-to-end.
    await expect(page.getByText('Cascade started').first()).toBeVisible({
      timeout: 5_000,
    });
  });
});
