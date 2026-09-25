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

describe('the demo', () => {
  // The demo's own code, not the tool's export (src/data/demo/), whose text it only draws.
  const demo = [...filesUnder('src/components/demo'), ...filesUnder('src/lib/demo')];

  it('draws every piece of text as a text node, never as HTML', () => {
    const html =
      /dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|set:html|createContextualFragment/;
    expect(demo.filter((f) => html.test(read(f)))).toEqual([]);
  });

  it('makes no network request and loads no code later', () => {
    const network = /\bfetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|\bimport\(/;
    expect(demo.filter((f) => network.test(read(f)))).toEqual([]);
  });

  it('writes its own copy with no em or en dashes (CLAUDE.md rule 6)', () => {
    // src/lib/demo/ writes the tool's text, dashes and all; the components hold the demo's own.
    const own = filesUnder('src/components/demo');
    expect(own.filter((f) => /[\u2013\u2014]/.test(read(f)))).toEqual([]);
  });
});

describe('design', () => {
  it('colours come from @theme, not one-off values in class names', () => {
    // A class like stroke-[#394150] would skip the contrast test; add a token instead.
    const markup = filesUnder('src').filter((f) => /\.(astro|tsx|mdx)$/.test(f));
    const oneOff = /\b[a-z-]+-\[(?:#|rgba?\(|hsla?\(|oklch\(|oklab\(|color:)/;
    expect(markup.filter((f) => oneOff.test(read(f)))).toEqual([]);
  });

  it('draws with gradients, never a blur filter (one crashed WebKit); the glass is the exception', () => {
    // CLAUDE.md rule 4. glass.css holds the header's backdrop-filter, and the assets' own SVGs
    // are images, not the page.
    const sources = filesUnder('src').filter(
      (f) => /\.(astro|tsx|mdx|css)$/.test(f) && !f.endsWith('glass.css'),
    );
    const blur = /<filter\b|feGaussianBlur|\bfilter[:=]\s*(?!none)|\b(?:backdrop-)?blur-(?:\[|\w)/;
    expect(sources.filter((f) => blur.test(read(f)))).toEqual([]);
  });
});

describe('toolchain versions agree', () => {
  const pkg = JSON.parse(read('package.json')) as { devDependencies: Record<string, string> };
  const dockerfile = read('.devcontainer/Dockerfile');

  it('the dev container installs the same Playwright as package.json', () => {
    const arg = /ARG PLAYWRIGHT_VERSION=(\S+)/.exec(dockerfile)?.[1];
    expect(arg).toBe(pkg.devDependencies['@playwright/test']);
  });

  it("the dev container's Node image is .node-version, pinned by digest", () => {
    const from = /^FROM node:(\d+\.\d+\.\d+)-bookworm-slim@sha256:[0-9a-f]{64}$/m.exec(dockerfile);
    expect(from?.[1]).toBe(read('.node-version').trim());
  });

  it('the Node running this test matches .node-version (the dev container, or setup-node in CI)', () => {
    expect(process.version).toBe(`v${read('.node-version').trim()}`);
  });

  it('every workflow pins the same tools as compliance.yml', () => {
    const pins = (file: string) =>
      Object.fromEntries(
        [...read(file).matchAll(/^ {2}([A-Z_]+_(?:VERSION|SHA256)): '([^']+)'/gm)].map((m) => [
          m[1],
          m[2],
        ]),
      );
    const compliance = pins('.github/workflows/compliance.yml');
    for (const file of ['.github/workflows/qa-up.yml', '.github/workflows/qa-down.yml']) {
      const own = pins(file);
      expect(Object.keys(own).length, file).toBeGreaterThan(0);
      for (const [name, value] of Object.entries(own))
        expect(value, `${file} ${name}`).toBe(compliance[name]);
    }
  });

  it('every dependency is pinned exactly', () => {
    const all = JSON.parse(read('package.json')) as Record<string, Record<string, string>>;
    const loose = Object.entries({ ...all['dependencies'], ...all['devDependencies'] }).filter(
      ([, version]) => !/^\d+\.\d+\.\d+$/.test(version),
    );
    expect(loose).toEqual([]);
  });
});

describe('supply chain', () => {
  it('.npmrc keeps every install setting CLAUDE.md requires', () => {
    const npmrc = Object.fromEntries(
      read('.npmrc')
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith('#'))
        .map((line) => line.split('=').map((part) => part.trim())),
    ) as Record<string, string>;
    expect(npmrc).toMatchObject({
      'ignore-scripts': 'true',
      'allow-git': 'none',
      'save-exact': 'true',
      'engine-strict': 'true',
    });
    expect(Number(npmrc['min-release-age'])).toBeGreaterThanOrEqual(7);
  });

  describe('the dev container', () => {
    const devsh = read('scripts/dev.sh');

    it('mounts the repository read-only, apart from what the tools write', () => {
      expect(devsh).toContain('args+=(--volume "$root:/work:ro")');
      const writable = /^writable=\(([^)]*)\)/m.exec(devsh)?.[1]?.trim().split(/\s+/);
      // Nothing here runs on the host or tells Claude Code what to do. Think before adding.
      expect(writable).toEqual([
        'src',
        'public',
        'tests',
        'dist',
        '.astro',
        'test-results',
        'playwright-report',
        'package.json',
        'astro.config.ts',
        'eslint.config.ts',
        'playwright.config.ts',
        'vitest.config.ts',
        'tsconfig.json',
        'scripts/og-images.ts',
      ]);
      expect(devsh).toContain('args+=(--volume "$root/tests/ci:/work/tests/ci:ro")');
    });

    it('never shows it infra/ or .notes/, and stops if a file that acts on the host appears', () => {
      expect(devsh).toMatch(
        /for path in infra \.notes; do\s+if .*type=tmpfs,destination=\/work\/\$path/,
      );
      for (const name of ['.git', 'CLAUDE.md', 'CLAUDE.local.md', '.mcp.json', '.claude']) {
        expect(devsh).toContain(`-name ${name} `);
      }
    });
  });
});

describe('required checks', () => {
  // The ruleset on main, the branch-rules evidence and the workflow's job names must agree:
  // a renamed job would leave every pull request waiting for a check that never reports.
  const ruleset = JSON.parse(read('.github/rulesets/main.json')) as {
    rules: { type: string; parameters?: { required_status_checks?: { context: string }[] } }[];
  };
  const required = ruleset.rules
    .find((rule) => rule.type === 'required_status_checks')
    ?.parameters?.required_status_checks?.map((check) => check.context);

  it('check_branch_rules.py expects the ruleset required checks', () => {
    const list = /^REQUIRED_CHECKS = \[([^\]]*)\]/m.exec(
      read('scripts/ci/check_branch_rules.py'),
    )?.[1];
    const expected = [...(list ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(expected).toEqual(required);
  });

  it('each required check is a job in compliance.yml', () => {
    const jobs = [...read('.github/workflows/compliance.yml').matchAll(/^ {4}name: (.+)$/gm)].map(
      (m) => m[1],
    );
    expect(required?.length).toBeGreaterThan(0);
    for (const name of required ?? []) expect(jobs).toContain(name);
  });
});
