// The "Be the CISO" demo in a real browser. The unit tests prove the engine replays the
// tool byte for byte; these prove the page drives it: by keyboard alone, through the reason
// dialog, and through the evidence check, with no network request and no CSP violation.

import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type { DemoData, Golden } from '../../src/lib/demo/types';

const CASE_STUDY = '/projects/okta-access-review-aws/';
const golden = JSON.parse(readFileSync('tests/fixtures/demo/web.golden.json', 'utf8')) as Golden;
const A = golden.scenarios['A'];
const data = JSON.parse(readFileSync('src/data/demo/web.json', 'utf8')) as DemoData;
// What the review holds, from its data: how many items, and how many Confirm accepts.
const TOTAL = data.items.length;
const PROPOSED = data.items.filter((i) => i.proposed === 'keep' || i.proposed === 'revoke').length;
const CONFIRM = `Confirm ${PROPOSED} proposed`;
const decided = (n: number) => `${n} of ${TOTAL} decided`;
// A proposed revoke, to keep (which asks for a reason), and the one after it.
const [KEPT = '', OTHER = ''] = data.items
  .filter((i) => i.proposed === 'revoke')
  .map((i) => `${i.name || i.user}: ${i.target}`);
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

interface Watch {
  problems: string[];
  /** Requests made after the demo loaded. */
  requests: string[];
}

/** The case study, with the demo scrolled into view and running. */
async function openDemo(page: Page): Promise<{ demo: Locator; watch: Watch }> {
  const watch: Watch = { problems: [], requests: [] };
  page.on('console', (msg) => {
    if (msg.type() === 'error') watch.problems.push(msg.text());
  });
  page.on('pageerror', (err) => watch.problems.push(err.message));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) =>
      console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  await page.goto(CASE_STUDY);
  const demo = page.locator('astro-island');
  await demo.scrollIntoViewIfNeeded();
  // Astro drops the ssr attribute once the island has hydrated.
  await expect(demo).not.toHaveAttribute('ssr');
  await page.waitForLoadState('networkidle');
  page.on('request', (request) => watch.requests.push(request.url()));
  return { demo, watch };
}

/** Focus a control and press Enter: the keyboard, not the mouse. */
async function press(page: Page, control: Locator): Promise<void> {
  await control.focus();
  await page.keyboard.press('Enter');
}

async function expectStep(demo: Locator, title: string): Promise<void> {
  await expect(demo.getByRole('heading', { level: 3, name: title })).toBeFocused();
}

/** Scenario A, as the tool's export plays it: confirm, then keep what needs a call. */
async function scenarioA(page: Page, demo: Locator): Promise<void> {
  await scenarioAToSignOff(page, demo);
  await press(page, demo.getByRole('button', { name: 'Approve review' }));
  const signOff = page.getByRole('dialog', { name: 'Sign off this review?' });
  await page.keyboard.press('Tab');
  await expect(signOff.getByRole('button', { name: 'Sign off' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expectStep(demo, 'The tickets');
}

/** Scenario A up to the sign-off step. */
async function scenarioAToSignOff(page: Page, demo: Locator): Promise<void> {
  await press(page, demo.getByRole('button', { name: 'Start the review' }));
  await expectStep(demo, 'The review opens');
  await press(page, demo.getByRole('button', { name: 'Open your DM' }));
  await expectStep(demo, 'Decide every item');

  await press(page, demo.getByRole('button', { name: CONFIRM }).last());
  const confirm = page.getByRole('dialog', { name: 'Confirm proposals?' });
  await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(confirm.getByRole('button', { name: 'Confirm' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(confirm).toBeHidden();
  await expect(demo.getByText(decided(PROPOSED), { exact: true })).toBeVisible();

  // What's left needs a call. After each decision, focus goes on to the next undecided
  // item's first button by itself (decided cards keep theirs, for a change of mind).
  const next = demo
    .locator('[role="group"][data-item]:not([data-decided])')
    .getByRole('button', { name: /^(Keep|Acknowledge)$/ });
  for (let n = PROPOSED + 1; n <= TOTAL; n++) {
    await expect(next.first()).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(demo.getByText(decided(n), { exact: true })).toBeVisible();
  }
  const signOffNext = demo.getByRole('button', { name: 'Review the list and sign off' });
  await expect(signOffNext).toBeFocused();
  await page.keyboard.press('Enter');
  await expectStep(demo, 'Sign off');
}

test.describe('Be the CISO', () => {
  test('keyboard only: scenario A signs the same decisions.json as the tool', async ({ page }) => {
    if (!A) throw new Error('no scenario A in the golden file');
    const { demo, watch } = await openDemo(page);
    await scenarioA(page, demo);
    const last = A.jira.filter((c) => c.call === 'create').at(-1)?.key ?? 'none';
    await expect(demo.getByText(last).first()).toBeVisible();

    await press(page, demo.getByRole('button', { name: 'Check the evidence' }));
    await expectStep(demo, 'Check the evidence');
    await press(page, demo.getByRole('button', { name: 'Run the check' }));
    const terminal = demo.locator('pre');
    await expect(terminal).toHaveText(A.attest['intact'] ?? '', { useInnerText: true });
    // Green for a pass: the case study's own code block style stops at the demo.
    await expect(terminal).toHaveCSS('border-top-color', 'rgb(92, 201, 138)');
    // The browser hashed what it signed, and it's the tool's own decisions.json.
    await expect(demo.getByText(A.decisions_sha256)).toBeVisible();
    expect(watch.requests).toEqual([]);
    expect(watch.problems).toEqual([]);
  });

  test("each one-byte change gets the tool's own verdict", async ({ page }) => {
    if (!A) throw new Error('no scenario A in the golden file');
    const { demo, watch } = await openDemo(page);
    await scenarioA(page, demo);
    await demo.getByRole('button', { name: 'Check the evidence' }).click();
    for (const change of A.tampers) {
      const button = demo.getByRole('button', { name: new RegExp(`^${change.why}`) });
      await button.click();
      await expect(button).toHaveAttribute('aria-pressed', 'true');
      await expect(demo.locator('pre')).toHaveText(A.attest[change.file] ?? '', {
        useInnerText: true,
      });
      await expect(demo.locator('pre')).toHaveCSS('border-top-color', 'rgb(240, 113, 120)');
    }
    await demo.getByRole('button', { name: 'Put it back' }).click();
    await expect(demo.locator('pre')).toHaveText(A.attest['intact'] ?? '', { useInnerText: true });
    expect(watch.requests).toEqual([]);
    expect(watch.problems).toEqual([]);
  });

  test('keeping a proposed revoke asks for a reason, in the tool’s words', async ({ page }) => {
    const { demo, watch } = await openDemo(page);
    await demo.getByRole('button', { name: 'Start the review' }).click();
    await demo.getByRole('button', { name: 'Open your DM' }).click();
    const card = demo.getByRole('group', { name: KEPT });
    await card.getByRole('button', { name: 'Keep' }).click();

    const dialog = page.getByRole('dialog', { name: 'Reason needed' });
    const why = dialog.getByRole('textbox', { name: 'Why?' });
    await expect(why).toBeFocused();
    const axe = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    expect(axe.violations).toEqual([]);

    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('alert')).toHaveText(
      'a reason is needed to keep access that was proposed for revocation, or to override a proposal',
    );
    await why.fill('x'.repeat(161));
    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('alert')).toHaveText('Keep it to 160 characters here.');

    const reason = 'R&D <needs> it & so does Ops 🔐';
    await why.fill(reason);
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expect(card).toContainText(`Keep by You (CISO) · ${reason}`);
    // It keeps its buttons, for a change of mind.
    await expect(card.getByRole('button')).toHaveCount(2);
    await expect(demo.getByText(decided(1), { exact: true })).toBeVisible();
    // Focus went on to the first button of the next item below, not back to the page.
    const order = await page.evaluate((kept) => {
      const groups = [...document.querySelectorAll('[role="group"][data-item]')];
      const focused = document.activeElement?.closest('[role="group"]');
      return {
        decided: groups.findIndex((g) => g.getAttribute('aria-label') === kept),
        focused: focused ? groups.indexOf(focused) : -1,
        first: focused?.querySelector('button') === document.activeElement,
      };
    }, KEPT);
    expect(order.focused).toBe(order.decided + 1);
    expect(order.first).toBe(true);

    // Cancel leaves the item open.
    const other = demo.getByRole('group', { name: OTHER }).last();
    await other.getByRole('button', { name: 'Keep' }).click();
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
    await expect(other.getByRole('button', { name: 'Keep' })).toBeVisible();
    expect(watch.requests).toEqual([]);
    expect(watch.problems).toEqual([]);
  });

  test('a decision can be changed from the sign-off step, as its dialog says', async ({ page }) => {
    const { demo, watch } = await openDemo(page);
    await scenarioAToSignOff(page, demo);
    const approve = demo.getByRole('button', { name: 'Approve review' });
    await expect(approve).toBeVisible();
    await demo.getByRole('button', { name: /Change a decision$/ }).click();
    await expectStep(demo, 'Decide every item');

    // A proposed revoke, confirmed with the rest, is kept instead; that asks why.
    const card = demo.getByRole('group', { name: OTHER }).last();
    const keep = card.getByRole('button', { name: 'Keep' });
    const revoke = card.getByRole('button', { name: 'Revoke' });
    await expect(card).toContainText('Revoke by You (CISO)');
    await expect(revoke).toHaveAttribute('aria-pressed', 'true');
    await expect(keep).toHaveAttribute('aria-pressed', 'false');
    // Clicking the decision it already has changes nothing, and focus stays on it.
    await revoke.click();
    await expect(revoke).toBeFocused();
    await keep.click();
    const dialog = page.getByRole('dialog', { name: 'Reason needed' });
    await dialog.getByRole('textbox', { name: 'Why?' }).fill('Moved teams');
    await page.keyboard.press('Enter');
    await expect(card).toContainText('Keep by You (CISO) · Moved teams');
    await expect(keep).toHaveAttribute('aria-pressed', 'true');
    await expect(revoke).toHaveAttribute('aria-pressed', 'false');
    await expect(keep).toBeFocused(); // a change of mind doesn't send focus down the page
    await expect(demo.getByText(decided(TOTAL), { exact: true })).toBeVisible();

    await demo.getByRole('button', { name: 'Review the list and sign off' }).click();
    await expectStep(demo, 'Sign off');
    await expect(demo.getByText(/Moved teams/)).toBeVisible(); // the list was redrawn
    expect(watch.requests).toEqual([]);
    expect(watch.problems).toEqual([]);
  });

  test('each step passes axe (WCAG 2.2 AA)', async ({ page }) => {
    const { demo } = await openDemo(page);
    const check = async () => {
      const results = await new AxeBuilder({ page })
        .include('astro-island')
        .withTags(AXE_TAGS)
        .analyze();
      expect(results.violations).toEqual([]);
    };
    await check();
    await scenarioA(page, demo);
    await check();
    await demo.getByRole('button', { name: 'Check the evidence' }).click();
    await demo.getByRole('button', { name: 'Run the check' }).click();
    await check();
  });

  test('fits a 375 × 812 phone at every step, with no sideways scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const { demo } = await openDemo(page);
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
    expect(await overflow()).toBeLessThanOrEqual(0);
    await demo.getByRole('button', { name: 'Start the review' }).click();
    await demo.getByRole('button', { name: 'Open your DM' }).click();
    // The next item's button, focused after a decision, sits clear of the sticky progress bar.
    // After Confirm, what's left is the tool's "your call" items, which need no reason; the
    // one after the first is further down the page, so focusing it has to scroll.
    const bar = demo.locator('.sticky');
    await demo.getByRole('button', { name: CONFIRM }).last().click();
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click();
    const open = demo.locator('[role="group"][data-item]:not([data-decided])');
    const first = open.first();
    const second = await open.nth(1).getAttribute('data-item');
    await press(page, first.getByRole('button', { name: /^(Keep|Acknowledge)$/ }));
    const focused = page.locator(`[role="group"][data-item="${second}"] button`).first();
    await expect(focused).toBeFocused();
    const bottom = (await focused.boundingBox()) ?? { y: Infinity, height: 0 };
    expect(bottom.y + bottom.height).toBeLessThanOrEqual((await bar.boundingBox())?.y ?? 0);
    await demo.getByRole('button', { name: 'Start over' }).click();
    await scenarioA(page, demo);
    expect(await overflow()).toBeLessThanOrEqual(0);
    await demo.getByRole('button', { name: 'Check the evidence' }).click();
    await demo.getByRole('button', { name: /^backdate a decision/ }).click();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });

  test("says so, and points at the screenshots, when the browser can't hash", async ({ page }) => {
    // crypto.subtle exists only in a secure context: plain http on a LAN address has none.
    await page.addInitScript(() => {
      Object.defineProperty(Crypto.prototype, 'subtle', { get: () => undefined });
    });
    const { demo } = await openDemo(page);
    await expect(demo.getByText(/Without JavaScript/)).toHaveCount(0);
    await demo.getByRole('button', { name: 'Start the review' }).click();
    await demo.getByRole('button', { name: 'Open your DM' }).click();
    await demo.getByRole('button', { name: CONFIRM }).last().click();
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click();
    const next = demo
      .locator('[role="group"][data-item]:not([data-decided])')
      .getByRole('button', { name: /^(Keep|Acknowledge)$/ });
    while ((await next.count()) > 0) await next.first().click();
    await demo.getByRole('button', { name: 'Review the list and sign off' }).click();
    await demo.getByRole('button', { name: 'Approve review' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Sign off' }).click();
    await expect(demo.getByRole('alert')).toContainText(
      'The screenshots below show a full-size review.',
    );
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('Start over goes back to the beginning with nothing decided', async ({ page }) => {
    const { demo } = await openDemo(page);
    await scenarioA(page, demo);
    await demo.getByRole('button', { name: 'Start over' }).click();
    await demo.getByRole('button', { name: 'Start the review' }).click();
    await demo.getByRole('button', { name: 'Open your DM' }).click();
    await expect(demo.getByText(decided(0), { exact: true })).toBeVisible();
  });
});

test.describe('Be the CISO, with JavaScript off', () => {
  test.use({ javaScriptEnabled: false });

  test('the page still reads, and the screenshots open', async ({ page }) => {
    await page.goto(CASE_STUDY);
    await expect(page.getByRole('heading', { level: 2, name: 'Be the CISO' })).toBeVisible();
    await expect(page.getByText("You're the CISO at Acme")).toBeVisible();
    // Start can't work without JavaScript, so it says where to look instead.
    await expect(page.getByRole('button', { name: 'Start the review' })).toBeDisabled();
    await expect(page.getByText(/Without JavaScript, the screenshots below/)).toBeVisible();
    await page.getByText(/A full-size review, as screenshots/).click();
    await expect(page.getByRole('img', { name: /Confirm 13 proposed/ })).toBeVisible();
  });
});
