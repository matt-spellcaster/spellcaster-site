// Lighthouse on the built site, as a phone sees it (Lighthouse's default mobile emulation):
//   scripts/dev.sh npm run build
//   scripts/dev.sh node scripts/lighthouse.ts
// The QA up workflow runs it on the tested build, in a job with no AWS access and no QA
// password (docs/qa.md). It serves dist/ with astro preview, runs Lighthouse on every page in
// Playwright's Chromium, and writes each report and a summary.json to test-results/lighthouse/.
// It fails if any page scores under 0.95 for accessibility or best practices. Performance
// only warns: served from here, the site has none of CloudFront's compression or caching.
import { chromium } from '@playwright/test';
import { preview } from 'astro';
import lighthouse from 'lighthouse';
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const OUT = 'test-results/lighthouse';
const PORT = 4322; // not the dev server's 4321, so both can run
const DEBUG_PORT = 9223;
const REQUIRED = { accessibility: 0.95, 'best-practices': 0.95 } as const;
const WARN = { performance: 0.9 } as const;
const CATEGORIES = [...Object.keys(REQUIRED), ...Object.keys(WARN)];

// Every page is a folder's index.html (build.format: 'directory'). The 404 page is left out:
// Lighthouse refuses to test a page served with an error status.
function pages(dir = 'dist'): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((f) => f.isFile() && f.name === 'index.html')
    .map((f) => `/${relative('dist', f.parentPath).split(sep).join('/')}/`.replace('//', '/'))
    .sort();
}

type Row = {
  page: string;
  scores: Record<string, number | null>;
  problems: string[];
  warnings: string[];
};

function judge(page: string, scores: Record<string, number | null>, error?: string): Row {
  const problems = error ? [error] : [];
  const warnings: string[] = [];
  for (const [category, min] of Object.entries(REQUIRED)) {
    const score = scores[category];
    if (score == null || score < min)
      problems.push(`${category} ${score ?? 'missing'}, needs ${min}`);
  }
  for (const [category, min] of Object.entries(WARN)) {
    const score = scores[category];
    if (score == null || score < min)
      warnings.push(`${category} ${score ?? 'missing'}, hoped for ${min}`);
  }
  return { page, scores, problems, warnings };
}

const list = pages();
if (list.length === 0) throw new Error('dist/ has no pages: run npm run build first');
mkdirSync(OUT, { recursive: true });

const server = await preview({ logLevel: 'warn', server: { host: '127.0.0.1', port: PORT } });
// The full Chromium in its new headless mode, which is what Lighthouse expects.
const browser = await chromium.launch({
  channel: 'chromium',
  args: [`--remote-debugging-port=${DEBUG_PORT}`],
});
const rows: Row[] = [];
try {
  for (const page of list) {
    const result = await lighthouse(`http://127.0.0.1:${PORT}${page}`, {
      port: DEBUG_PORT,
      output: ['html', 'json'],
      logLevel: 'error',
      onlyCategories: CATEGORIES,
    });
    if (!result) throw new Error(`Lighthouse returned nothing for ${page}`);
    const name = page === '/' ? 'home' : page.slice(1, -1).replaceAll('/', '-');
    const [html, json] = result.report as string[];
    writeFileSync(join(OUT, `${name}.html`), html ?? '');
    writeFileSync(join(OUT, `${name}.json`), json ?? '');
    const scores = Object.fromEntries(
      CATEGORIES.map((c) => [c, result.lhr.categories[c]?.score ?? null]),
    );
    rows.push(judge(page, scores, result.lhr.runtimeError?.message));
  }
} finally {
  await browser.close();
  await server.stop();
}

writeFileSync(join(OUT, 'summary.json'), `${JSON.stringify(rows, null, 2)}\n`);
for (const row of rows) {
  const scores = CATEGORIES.map((c) => `${c} ${row.scores[c] ?? '-'}`).join(', ');
  console.log(`${row.problems.length ? 'FAIL' : 'ok  '}  ${row.page}  ${scores}`);
  for (const problem of row.problems) console.error(`      ${problem}`);
  for (const warning of row.warnings) console.log(`      warning: ${warning}`);
}
const failed = rows.filter((r) => r.problems.length).length;
console.log(`${rows.length} pages, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
