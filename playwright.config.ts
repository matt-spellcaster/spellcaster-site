import { defineConfig, devices } from '@playwright/test';

// Runs against `astro preview` of dist/, so build first (CI tests the downloaded artifact).
export default defineConfig({
  testDir: 'tests/e2e',
  forbidOnly: !!process.env['CI'],
  retries: 0,
  // One browser at a time: WebKit and Chromium running side by side in the container starve
  // each other (a 1.6 s axe run took over 30 s). The whole suite takes about 25 s serially.
  workers: 1,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
  // A folder inside test-results/: Playwright deletes its output folder before a run, and in
  // the dev container test-results/ itself is a mount, which can't be deleted.
  outputDir: 'test-results/e2e',
  use: { baseURL: 'http://127.0.0.1:4321' },
  projects: [
    { name: 'desktop-chrome', use: { ...devices['Desktop Chrome'] } },
    { name: 'iphone', use: { ...devices['iPhone 15'] } },
    { name: 'pixel', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: 'npx astro preview --host 127.0.0.1 --port 4321',
    url: 'http://127.0.0.1:4321/',
    reuseExistingServer: false,
  },
});
