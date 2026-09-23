import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('home page loads with no console errors or CSP violations', async ({ page }) => {
  const problems: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(msg.text());
  });
  page.on('pageerror', (err) => problems.push(err.message));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) =>
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`),
    );
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Matthew Spell');
  await expect(page.locator('meta[http-equiv="content-security-policy"]')).toHaveCount(1);
  await page.waitForLoadState('networkidle');
  expect(problems).toEqual([]);
});

test('home page passes axe (WCAG 2.2 AA)', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});
