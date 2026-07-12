import { defineConfig, devices } from '@playwright/test';
import { STORAGE_STATE } from './tests/helpers';

/**
 * Playwright configuration for the foragerr end-to-end harness (FRG-PROC-010).
 *
 * The application under test is the REAL container image, brought up by
 * `run.sh` via docker compose; Playwright only drives it over the network at
 * the compose-assigned ephemeral port passed in `FORAGERR_BASE_URL`. There is
 * therefore no `webServer` here — lifecycle is owned by run.sh.
 *
 * Chromium only, headless. Traces and screenshots are captured on failure so a
 * red run is diagnosable; the JSON reporter feeds the generated acceptance
 * report (scripts/acceptance-report.mjs).
 */
const baseURL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';

export default defineConfig({
  testDir: './tests',
  // Scenarios share state (a seeded library grows across S2->S6), so the spine
  // runs serially in file order, one worker, no parallelism.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 1,
  // Generous: a real container doing add->refresh->grab->download->import.
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [
    ['list'],
    ['json', { outputFile: 'results/results.json' }],
    ['html', { outputFolder: 'results/html', open: 'never' }],
  ],
  use: {
    baseURL,
    headless: true,
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [
    // Mandatory-auth setup (FRG-AUTH-010): logs in once via the real UI and
    // saves the session to STORAGE_STATE. Every browser-driven scenario depends
    // on it and loads that state, so the whole suite runs authenticated.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: STORAGE_STATE },
      dependencies: ['setup'],
    },
  ],
});
