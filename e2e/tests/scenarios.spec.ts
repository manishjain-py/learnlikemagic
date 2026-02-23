/**
 * Dynamic Playwright test runner for e2e/scenarios.json
 *
 * Reads scenario definitions and creates test.describe()/test() blocks dynamically.
 * Results are tracked by Playwright's native JSON reporter (see playwright.config.ts).
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Paths
const ROOT = path.resolve(__dirname, '../..');
const SCENARIOS_PATH = path.join(ROOT, 'e2e', 'scenarios.json');
const REPORT_DIR = path.join(ROOT, 'reports', 'e2e-runner');
const SCREENSHOT_DIR = path.join(REPORT_DIR, 'screenshots');

// Ensure output directories exist
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// Load scenarios
if (!fs.existsSync(SCENARIOS_PATH)) {
  throw new Error(`scenarios.json not found at ${SCENARIOS_PATH}. Run e2e-updater first.`);
}
const scenariosData = JSON.parse(fs.readFileSync(SCENARIOS_PATH, 'utf-8'));
const suites = scenariosData.suites || [];

/**
 * Execute a single scenario step against a Playwright page.
 */
async function executeStep(
  page: Page,
  step: any,
  scenarioId: string,
  screenshots: string[]
): Promise<void> {
  const timeout = step.timeout || 15000;

  switch (step.action) {
    case 'navigate':
      await page.goto(step.url, { waitUntil: 'domcontentloaded', timeout });
      break;

    case 'click':
      await page.locator(step.selector).first().click({ timeout });
      break;

    case 'waitForSelector':
      await page.locator(step.selector).first().waitFor({ state: 'visible', timeout });
      break;

    case 'type':
      await page.locator(step.selector).first().fill(step.value, { timeout });
      break;

    case 'screenshot': {
      const filename = `${scenarioId}-${step.label}.png`;
      const filepath = path.join(SCREENSHOT_DIR, filename);
      await page.screenshot({ path: filepath, fullPage: false });
      screenshots.push(filename);
      break;
    }

    case 'waitForResponse':
      // Wait for any XHR/fetch response (used after sending a message)
      await page.waitForResponse(
        (resp) => resp.status() >= 200 && resp.status() < 500,
        { timeout }
      );
      break;

    default:
      throw new Error(`Unknown step action: ${step.action}`);
  }
}

/**
 * Evaluate assertions against the page.
 */
async function evaluateAssertions(page: Page, assertions: any[]): Promise<void> {
  for (const assertion of assertions) {
    switch (assertion.type) {
      case 'visible':
        await expect(page.locator(assertion.selector).first()).toBeVisible({ timeout: 10000 });
        break;

      case 'countAtLeast': {
        const count = await page.locator(assertion.selector).count();
        expect(count).toBeGreaterThanOrEqual(assertion.count);
        break;
      }

      default:
        throw new Error(`Unknown assertion type: ${assertion.type}`);
    }
  }
}

// Dynamically create test suites
for (const suite of suites) {
  test.describe(suite.name, () => {
    for (const scenario of suite.scenarios || []) {
      test(scenario.name, async ({ page }) => {
        const screenshots: string[] = [];

        try {
          // Execute steps
          for (const step of scenario.steps || []) {
            await executeStep(page, step, scenario.id, screenshots);
          }

          // Evaluate assertions
          if (scenario.assertions && scenario.assertions.length > 0) {
            await evaluateAssertions(page, scenario.assertions);
          }
        } catch (err: any) {
          // Take a failure screenshot
          try {
            const failFilename = `${scenario.id}-FAILURE.png`;
            await page.screenshot({
              path: path.join(SCREENSHOT_DIR, failFilename),
              fullPage: true,
            });
            screenshots.push(failFilename);
          } catch {
            // Ignore screenshot failures
          }

          throw err; // Re-throw so Playwright marks the test as failed
        }
      });
    }
  });
}
