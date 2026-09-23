import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

// Every built page. The mockup pages go away after the design gate.
const PAGES = ['/', '/mockup/inter/', '/mockup/geist/'];
const WITH_HEADER = '/mockup/inter/';

async function collectProblems(page: Page): Promise<string[]> {
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
  return problems;
}

for (const path of PAGES) {
  test.describe(path, () => {
    test('loads with no console errors or CSP violations', async ({ page }) => {
      const problems = await collectProblems(page);
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Matthew Spell');
      await expect(page.locator('meta[http-equiv="content-security-policy"]')).toHaveCount(1);
      await page.waitForLoadState('networkidle');
      // Scroll to the bottom so lazy images load under the CSP too.
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForLoadState('networkidle');
      expect(problems).toEqual([]);
    });

    test('passes axe (WCAG 2.2 AA)', async ({ page }) => {
      await page.goto(path);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(results.violations).toEqual([]);
    });

    test('reflows at 320 px with no horizontal scrolling', async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 640 });
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}

test.describe('header', () => {
  test('no ancestor breaks position: fixed or the glass', async ({ page }) => {
    await page.goto(WITH_HEADER);
    const offenders = await page.locator('header.glass').evaluate((header) => {
      const found: string[] = [];
      for (let el = header.parentElement; el; el = el.parentElement) {
        const s = getComputedStyle(el);
        const bad = {
          transform: s.transform !== 'none',
          filter: s.filter !== 'none',
          'backdrop-filter': s.backdropFilter !== 'none',
          perspective: s.perspective !== 'none',
          contain: !['none', ''].includes(s.contain),
          'will-change': !['auto', ''].includes(s.willChange),
        };
        for (const [prop, isBad] of Object.entries(bad))
          if (isBad) found.push(`${el.tagName} ${prop}`);
      }
      return found;
    });
    expect(offenders).toEqual([]);
  });

  test('uses the glass by default and opaque fallbacks when asked', async ({ page }) => {
    await page.goto(WITH_HEADER);
    const header = page.locator('header.glass');
    const style = () =>
      header.evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          filter: s.backdropFilter || s.getPropertyValue('-webkit-backdrop-filter'),
          bg: s.backgroundColor,
        };
      });

    expect((await style()).filter).toContain('blur(16px)');

    await page.emulateMedia({ contrast: 'more' });
    expect(await style()).toEqual({ filter: 'none', bg: 'rgb(18, 21, 26)' });

    await page.emulateMedia({ contrast: 'no-preference', forcedColors: 'active' });
    expect((await style()).filter).toBe('none');
  });
});

test.describe('mobile menu', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(!testInfo.project.use.isMobile, 'the menu button shows only on small screens');
    await page.goto(WITH_HEADER);
  });

  test('opens with Enter, closes with Esc and returns focus', async ({ page }) => {
    const button = page.getByRole('button', { name: 'Menu' });
    const sheet = page.locator('#site-menu');
    await button.focus();
    await page.keyboard.press('Enter');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole('link', { name: 'Work' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    await expect(button).toBeFocused();
  });

  test('the Close button and in-page links close it', async ({ page }) => {
    const sheet = page.locator('#site-menu');
    await page.getByRole('button', { name: 'Menu' }).click();
    await sheet.getByRole('button', { name: 'Close' }).click();
    await expect(sheet).toBeHidden();

    await page.getByRole('button', { name: 'Menu' }).click();
    await sheet.getByRole('link', { name: 'Work' }).click();
    await expect(sheet).toBeHidden();
  });
});
