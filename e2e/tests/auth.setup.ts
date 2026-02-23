/**
 * Playwright auth setup — logs in once via email and saves storageState
 * so all subsequent tests run as an authenticated user.
 */

import { test as setup, expect } from '@playwright/test';
import * as path from 'path';

const AUTH_FILE = path.join(__dirname, '..', '.auth', 'user.json');

setup('authenticate via email login', async ({ page }) => {
  const email = process.env.E2E_TEST_EMAIL;
  const password = process.env.E2E_TEST_PASSWORD;

  if (!email || !password) {
    throw new Error(
      'E2E_TEST_EMAIL and E2E_TEST_PASSWORD must be set. Create e2e/.env with these values.'
    );
  }

  // Navigate to login page
  await page.goto('/login');

  // Click "Continue with Email"
  await page.click('.auth-btn-email');

  // Fill in credentials
  await page.fill('#email', email);
  await page.fill('#password', password);

  // Submit
  await page.click('button[type="submit"]');

  // Wait for navigation away from login — could land on / or /onboarding
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15000 });

  // Save signed-in state
  await page.context().storageState({ path: AUTH_FILE });
});
