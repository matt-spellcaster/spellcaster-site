import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

// Every built page, with its h1. A path that doesn't exist gets the 404 page.
const PAGES: [string, string][] = [
  ['/', 'Matthew Spell'],
  ['/projects/okta-access-review-aws/', 'Okta access review in AWS'],
  ['/no-such-page/', 'Page not found'],
];
const WITH_HEADER = '/';
const CASE_STUDY = '/projects/okta-access-review-aws/';

async function collectProblems(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('console', (msg) => {
    // Failed loads are checked from the responses below, so the 404 page's own status
    // (which browsers also log here) doesn't count.
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
      problems.push(msg.text());
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400 && response.request().resourceType() !== 'document') {
      problems.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on('requestfailed', (request) => problems.push(`failed ${request.url()}`));
  page.on('pageerror', (err) => problems.push(err.message));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) =>
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  return problems;
}

for (const [path, h1] of PAGES) {
  test.describe(path, () => {
    test('loads with no console errors or CSP violations', async ({ page }) => {
      const problems = await collectProblems(page);
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(h1);
      await expect(page.locator('meta[http-equiv="content-security-policy"]')).toHaveCount(1);
      // Bring each image into view and wait for it, so lazy ones load under the CSP too.
      // (A second waitForLoadState('networkidle') would return at once, without waiting.)
      for (const img of await page.locator('img').all()) {
        await img.scrollIntoViewIfNeeded();
        await expect
          .poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
          .toBe(true);
      }
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
    expect(await style()).toEqual({ filter: 'none', bg: 'rgb(24, 22, 22)' });

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

test.describe('case study', () => {
  test('the summary, the three bullets and both links fit the first mobile screen', async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.use.isMobile, 'a phone-sized check');
    await page.goto(CASE_STUDY);
    const viewport = page.viewportSize()?.height ?? 0;
    const links = page.locator('#summary').getByRole('link');
    await expect(links).toHaveCount(2);
    for (const link of await links.all()) {
      const box = await link.boundingBox();
      expect(box && box.y + box.height).toBeLessThanOrEqual(viewport);
    }
  });

  test('a missing page returns 404', async ({ page }) => {
    const response = await page.goto('/no-such-page/');
    expect(response?.status()).toBe(404);
  });
});
