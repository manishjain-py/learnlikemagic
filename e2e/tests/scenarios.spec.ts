/**
 * Dynamic Playwright test runner for e2e/scenarios.json
 *
 * Reads scenario definitions and creates test.describe()/test() blocks dynamically.
 * Outputs structured results to reports/e2e-runner/scenario-results.json.
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

// Paths
const ROOT = path.resolve(__dirname, '../..');
const SCENARIOS_PATH = path.join(ROOT, 'e2e', 'scenarios.json');
const REPORT_DIR = path.join(ROOT, 'reports', 'e2e-runner');
const SCREENSHOT_DIR = path.join(REPORT_DIR, 'screenshots');
const RESULTS_PATH = path.join(REPORT_DIR, 'scenario-results.json');

// Ensure output directories exist
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// Load scenarios
if (!fs.existsSync(SCENARIOS_PATH)) {
  throw new Error(`scenarios.json not found at ${SCENARIOS_PATH}. Run e2e-updater first.`);
}
const scenariosData = JSON.parse(fs.readFileSync(SCENARIOS_PATH, 'utf-8'));
const suites = scenariosData.suites || [];

// Results accumulator
interface ScenarioResult {
  id: string;
  name: string;
  status: 'passed' | 'failed';
  duration_ms: number;
  screenshots: string[];
  error?: string;
}

interface SuiteResult {
  name: string;
  status: 'passed' | 'failed';
  scenarios: ScenarioResult[];
}

const allResults: SuiteResult[] = [];

// Git metadata
function getGitInfo(): { branch: string; commit: string } {
  try {
    const branch = execSync('git branch --show-current', { cwd: ROOT }).toString().trim();
    const commit = execSync('git rev-parse --short HEAD', { cwd: ROOT }).toString().trim();
    return { branch, commit };
  } catch {
    return { branch: 'unknown', commit: 'unknown' };
  }
}

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
  const suiteResult: SuiteResult = {
    name: suite.name,
    status: 'passed',
    scenarios: [],
  };
  allResults.push(suiteResult);

  test.describe(suite.name, () => {
    for (const scenario of suite.scenarios || []) {
      test(scenario.name, async ({ page }) => {
        const startTime = Date.now();
        const screenshots: string[] = [];
        const result: ScenarioResult = {
          id: scenario.id,
          name: scenario.name,
          status: 'passed',
          duration_ms: 0,
          screenshots: [],
        };
        suiteResult.scenarios.push(result);

        try {
          // Execute steps
          for (const step of scenario.steps || []) {
            await executeStep(page, step, scenario.id, screenshots);
          }

          // Evaluate assertions
          if (scenario.assertions && scenario.assertions.length > 0) {
            await evaluateAssertions(page, scenario.assertions);
          }

          result.status = 'passed';
          result.screenshots = screenshots;
        } catch (err: any) {
          result.status = 'failed';
          result.error = err.message || String(err);
          result.screenshots = screenshots;
          suiteResult.status = 'failed';

          // Take a failure screenshot
          try {
            const failFilename = `${scenario.id}-FAILURE.png`;
            await page.screenshot({
              path: path.join(SCREENSHOT_DIR, failFilename),
              fullPage: true,
            });
            result.screenshots.push(failFilename);
          } catch {
            // Ignore screenshot failures
          }

          throw err; // Re-throw so Playwright marks the test as failed
        } finally {
          result.duration_ms = Date.now() - startTime;
        }
      });
    }
  });
}

// Write results after all tests complete
test.afterAll(async () => {
  const git = getGitInfo();
  const now = new Date();
  const slug = `e2e-runner-${now.toISOString().replace(/[-:T]/g, '').slice(0, 15)}`;

  const resultsJson = {
    runSlug: slug,
    timestamp: now.toISOString(),
    branch: git.branch,
    commit: git.commit,
    suites: allResults,
  };

  fs.writeFileSync(RESULTS_PATH, JSON.stringify(resultsJson, null, 2));
});
