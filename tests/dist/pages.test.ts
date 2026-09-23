// Checks the built site in dist/. Run `npm run build` first.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const DIST = 'dist';
const files = existsSync(DIST) ? readdirSync(DIST, { recursive: true, encoding: 'utf8' }) : [];
const pages = files.filter((f) => f.endsWith('.html'));
const stylesheets = files.filter((f) => f.endsWith('.css'));

function cspOf(html: string): Map<string, string[]> {
  const content = /<meta http-equiv="content-security-policy" content="([^"]*)"/i.exec(html)?.[1];
  return new Map(
    (content ?? '')
      .split(';')
      .map((d) => d.trim().split(/\s+/))
      .filter(([name]) => name)
      .map(([name, ...sources]) => [name ?? '', sources]),
  );
}

const sha256 = (text: string) => `'sha256-${createHash('sha256').update(text).digest('base64')}'`;

describe('built pages', () => {
  it('dist/ has pages (run `npm run build` first)', () => {
    expect(pages).toContain('index.html');
  });

  describe.each(pages)('%s', (page) => {
    const html = readFileSync(join(DIST, page), 'utf8');

    it('has exactly one CSP meta tag, with our directives', () => {
      expect(html.match(/<meta http-equiv="content-security-policy"/gi) ?? []).toHaveLength(1);
      const policy = cspOf(html);
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

    it('hashes every inline script and style in the CSP', () => {
      const policy = cspOf(html);
      const allowed = {
        script: policy.get('script-src') ?? [],
        style: policy.get('style-src-elem') ?? policy.get('style-src') ?? [],
      };
      for (const tag of ['script', 'style'] as const) {
        for (const [, attrs = '', body = ''] of html.matchAll(
          new RegExp(`<${tag}\\b([^>]*)>([\\s\\S]*?)</${tag}>`, 'g'),
        )) {
          if (/\bsrc=/.test(attrs) || /type="application\/ld\+json"/.test(attrs)) continue;
          expect(allowed[tag], `inline <${tag}> is not hashed`).toContain(sha256(body));
        }
      }
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

describe('header glass CSS', () => {
  const css = stylesheets.map((f) => readFileSync(join(DIST, f), 'utf8')).join('\n');
  const rule = /\.glass\{[^}]*saturate\(160%\)[^}]*\}/.exec(css)?.[0] ?? '';

  it('keeps -webkit-backdrop-filter first, for Safari before 18', () => {
    expect(rule).toMatch(
      /-webkit-backdrop-filter:saturate\(160%\) ?blur\(16px\);backdrop-filter:saturate\(160%\) ?blur\(16px\)/,
    );
  });
});
