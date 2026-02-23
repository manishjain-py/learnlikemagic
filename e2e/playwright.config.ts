import { defineConfig } from '@playwright/test';
import { execSync } from 'child_process';

function getGitMeta() {
  try {
    return {
      branch: execSync('git branch --show-current').toString().trim(),
      commit: execSync('git rev-parse --short HEAD').toString().trim(),
    };
  } catch {
    return { branch: 'unknown', commit: 'unknown' };
  }
}

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  metadata: getGitMeta(),
  retries: 1,
  workers: 1, // Sequential — scenarios may depend on app state
  outputDir: '../reports/e2e-runner/test-output',
  use: {
    baseURL: 'http://localhost:3000',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
    viewport: { width: 1280, height: 720 },
    actionTimeout: 10_000,
  },
  reporter: [
    ['html', { outputFolder: '../reports/e2e-runner/playwright-report', open: 'never' }],
    ['json', { outputFile: '../reports/e2e-runner/test-results.json' }],
    ['list'],
  ],
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
