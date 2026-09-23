import { defineConfig, devices } from '@playwright/test';

// Runs against `astro preview` of dist/, so build first (CI tests the downloaded artifact).
export default defineConfig({
  testDir: 'tests/e2e',
  forbidOnly: !!process.env['CI'],
  retries: 0,
  // More parallel browsers than this starve each other in the dev container (and on
  // GitHub's 4-vCPU runners): tests that take 1 s at two workers take 15-25 s at five.
  workers: 2,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
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
