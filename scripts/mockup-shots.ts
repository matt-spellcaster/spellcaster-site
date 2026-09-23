// Screenshots for the M2 design gate: Inter vs Geist at 1280, 768 and 375 px, the glass
// over a white image, the open mobile menu, and the accent options.
//   scripts/dev.sh sh -c 'npm run build && node scripts/mockup-shots.ts'
// Writes tmp/mockup/*.png (git-ignored). Deleted with the mockup pages after the gate.
import { chromium, webkit, type Browser, type Page } from '@playwright/test';
import { preview } from 'astro';
import { mkdirSync, writeFileSync } from 'node:fs';

const OUT = 'tmp/mockup';
const FONTS = ['inter', 'geist'] as const;
type Shot = { name: string; png: Buffer };

mkdirSync(OUT, { recursive: true });
const server = await preview({ server: { host: '127.0.0.1', port: 4321 }, logLevel: 'error' });
const base = 'http://127.0.0.1:4321';

async function open(
  browser: Browser,
  width: number,
  height: number,
  mobile: boolean,
  font: string,
) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 2,
    isMobile: mobile,
    hasTouch: mobile,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  await page.goto(`${base}/mockup/${font}/`, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

async function lazyLoadAll(page: Page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 400) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 30));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForLoadState('networkidle');
}

// The page from the top down to the end of the featured section.
async function pageShot(page: Page): Promise<Buffer> {
  const end = await page
    .locator('#glass-test')
    .evaluate((el) => el.getBoundingClientRect().top + scrollY);
  const width = page.viewportSize()?.width ?? 0;
  return page.screenshot({ fullPage: true, clip: { x: 0, y: 0, width, height: end } });
}

// The white middle of the report image scrolled right under the header.
async function glassShot(page: Page): Promise<Buffer> {
  await page.locator('#glass-test .bg-white').evaluate((el) => {
    window.scrollTo(0, el.getBoundingClientRect().top + scrollY + el.clientHeight * 0.45);
  });
  await page.waitForTimeout(150);
  const width = page.viewportSize()?.width ?? 0;
  return page.screenshot({ clip: { x: 0, y: 0, width, height: 180 } });
}

const shots: Record<string, Shot[]> = { desktop: [], tablet: [], phone: [], glass: [] };
const [chrome, safari] = await Promise.all([chromium.launch(), webkit.launch()]);

for (const font of FONTS) {
  for (const [key, browser, width, height, mobile] of [
    ['desktop', chrome, 1280, 800, false],
    ['tablet', chrome, 768, 1024, false],
    ['phone', safari, 375, 812, true],
  ] as const) {
    const page = await open(browser, width, height, mobile, font);
    await lazyLoadAll(page);
    shots[key]?.push({ name: `${font} ${width}px`, png: await pageShot(page) });
    shots['glass']?.push({
      name: `${font} ${width}px, white image under the header`,
      png: await glassShot(page),
    });
    if (key === 'phone') {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.getByRole('button', { name: 'Menu' }).click();
      await page.waitForTimeout(150);
      shots['phone']?.push({ name: `${font} 375px, menu open`, png: await page.screenshot() });
      await page.getByRole('button', { name: 'Close' }).click();
      shots['phone']?.push({
        name: `${font} 375px, menu over the white image`,
        png: await menuOverWhite(page),
      });
    }
    if (key === 'desktop' && font === 'inter') {
      const png = await page.locator('#accents').screenshot();
      writeFileSync(`${OUT}/accents.png`, png);
    }
    await page.context().close();
  }
}

async function menuOverWhite(page: Page): Promise<Buffer> {
  await page.locator('#glass-test .bg-white').evaluate((el) => {
    window.scrollTo(0, el.getBoundingClientRect().top + scrollY + el.clientHeight * 0.45);
  });
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.waitForTimeout(150);
  return page.screenshot();
}

// One comparison sheet per group: the shots side by side with their labels.
const sheet = await (await chrome.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
for (const [group, list] of Object.entries(shots)) {
  const columns = group === 'phone' ? 4 : group === 'glass' ? 1 : 2;
  const html = `<!doctype html><body style="margin:0;padding:24px;background:#2a2e35;font:14px system-ui;color:#fff">
    <div style="display:grid;grid-template-columns:repeat(${columns},1fr);gap:24px;align-items:start">
    ${list
      .map(
        (
          s,
        ) => `<figure style="margin:0"><figcaption style="margin-bottom:8px">${s.name}</figcaption>
        <img style="width:100%;display:block;outline:1px solid #555" src="data:image/png;base64,${s.png.toString('base64')}"></figure>`,
      )
      .join('')}</div></body>`;
  await sheet.setContent(html, { waitUntil: 'load' });
  writeFileSync(`${OUT}/sheet-${group}.png`, await sheet.screenshot({ fullPage: true }));
}

await Promise.all([chrome.close(), safari.close()]);
await server.stop();
console.log(`Wrote ${OUT}/sheet-{desktop,tablet,phone,glass}.png and ${OUT}/accents.png`);
