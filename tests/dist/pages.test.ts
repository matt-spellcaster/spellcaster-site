// Checks the built site in dist/. Run `npm run build` first.
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const DIST = 'dist';
const pages = existsSync(DIST)
  ? readdirSync(DIST, { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.html'))
  : [];

describe('built pages', () => {
  it('dist/ has pages (run `npm run build` first)', () => {
    expect(pages).toContain('index.html');
  });

  describe.each(pages)('%s', (page) => {
    const html = readFileSync(join(DIST, page), 'utf8');

    it('has exactly one CSP meta tag, with our directives', () => {
      const tags = [...html.matchAll(/<meta http-equiv="content-security-policy" content="([^"]*)"/gi)];
      expect(tags).toHaveLength(1);
      const policy = new Map(
        (tags[0]?.[1] ?? '')
          .split(';')
          .map((d) => d.trim().split(/\s+/))
          .filter(([name]) => name)
          .map(([name, ...sources]) => [name, sources]),
      );
      expect(policy.get('default-src')).toEqual(["'self'"]);
      expect(policy.get('object-src')).toEqual(["'none'"]);
      expect(policy.get('base-uri')).toEqual(["'none'"]);
      expect(policy.get('form-action')).toEqual(["'none'"]);
      // The one relaxation is inline style="" attributes. Anywhere else, 'unsafe-inline'
      // would switch off hashing for scripts or stylesheets.
      for (const [name, sources] of policy) {
        if (name !== 'style-src-attr') expect(sources, name).not.toContain("'unsafe-inline'");
      }
      expect(policy.get('style-src-attr')).toEqual(["'unsafe-inline'"]);
    });

    it('has exactly one h1', () => {
      expect(html.match(/<h1[\s>]/g) ?? []).toHaveLength(1);
    });

    it('internal links end in /', () => {
      const hrefs = [...html.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)].map((m) => m[1] ?? '');
      const internal = hrefs.filter((h) => h.startsWith('/') && !h.startsWith('//'));
      const bad = internal.filter((h) => !/\/(#.*)?$/.test(h) && !/\.[a-z0-9]+$/i.test(h));
      expect(bad).toEqual([]);
    });
  });
});
