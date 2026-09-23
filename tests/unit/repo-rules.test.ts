// Enforces the hard rules in CLAUDE.md that a linter can't express.
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(path, 'utf8');

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => join(entry.parentPath, entry.name));
}

describe('CSP bans', () => {
  // Each of these either bypasses Astro's CSP hashing or needs a CSP exception.
  const banned: [RegExp, string][] = [
    [/\bis:inline\b/, 'is:inline (unhashed inline script or style)'],
    [/\bdefine:vars\b/, 'define:vars (inline style attributes and unhashed scripts)'],
    [/\bClientRouter\b/, '<ClientRouter/> (view transitions inject unhashed scripts)'],
    [/\bdata-astro-prefetch\b|\bprefetch\s*:/, 'prefetch'],
  ];
  const sources = filesUnder('src').filter((f) => /\.(astro|tsx?|mdx?|css)$/.test(f));

  it.each(banned)('src/ never uses %s', (pattern, what) => {
    const offenders = sources.filter((f) => pattern.test(read(f)));
    expect(offenders, `${what} found`).toEqual([]);
  });

  it('astro.config.ts keeps Prism and never enables prefetch', () => {
    const config = read('astro.config.ts');
    expect(config).toMatch(/syntaxHighlight:\s*'prism'/);
    expect(config).not.toMatch(/prefetch/);
  });
});

describe('toolchain versions agree', () => {
  const pkg = JSON.parse(read('package.json')) as { devDependencies: Record<string, string> };
  const dockerfile = read('.devcontainer/Dockerfile');

  it('the dev container installs the same Playwright as package.json', () => {
    const arg = /ARG PLAYWRIGHT_VERSION=(\S+)/.exec(dockerfile)?.[1];
    expect(arg).toBe(pkg.devDependencies['@playwright/test']);
  });

  it('Node matches .node-version (the dev container locally, setup-node in CI)', () => {
    expect(process.version).toBe(`v${read('.node-version').trim()}`);
  });

  it('every dependency is pinned exactly', () => {
    const all = JSON.parse(read('package.json')) as Record<string, Record<string, string>>;
    const loose = Object.entries({ ...all['dependencies'], ...all['devDependencies'] }).filter(
      ([, version]) => !/^\d+\.\d+\.\d+$/.test(version),
    );
    expect(loose).toEqual([]);
  });
});
