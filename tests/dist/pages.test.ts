// Checks the built site in dist/. Run `npm run build` first.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';
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

function internalLinks(html: string): string[] {
  return [...html.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)]
    .map((m) => m[1] ?? '')
    .filter((h) => h.startsWith('/') && !h.startsWith('//'));
}

function pngSize(path: string): [number, number] | undefined {
  if (!existsSync(path)) return undefined;
  const png = readFileSync(path);
  return [png.readUInt32BE(16), png.readUInt32BE(20)];
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
      // Every directive, exactly: a new host, data: or 'unsafe-eval' anywhere fails here.
      const hashes = (name: string) =>
        (policy.get(name) ?? []).map((s) => (/^'sha256-[A-Za-z0-9+/]+=*'$/.test(s) ? 'hash' : s));
      expect([...policy.keys()].sort()).toEqual(
        [
          'base-uri',
          'connect-src',
          'default-src',
          'font-src',
          'form-action',
          'img-src',
          'object-src',
          'script-src',
          'style-src',
          'style-src-attr',
          'style-src-elem',
        ].sort(),
      );
      expect(policy.get('default-src')).toEqual(["'self'"]);
      expect(policy.get('img-src')).toEqual(["'self'", 'data:']);
      expect(policy.get('font-src')).toEqual(["'self'"]);
      expect(policy.get('connect-src')).toEqual(["'self'"]);
      expect(policy.get('object-src')).toEqual(["'none'"]);
      expect(policy.get('base-uri')).toEqual(["'none'"]);
      expect(policy.get('form-action')).toEqual(["'none'"]);
      expect(policy.get('style-src')).toEqual(["'self'"]);
      // Scripts and stylesheets: this site's files plus Astro's hashes, nothing else.
      for (const name of ['script-src', 'style-src-elem']) {
        expect(new Set(hashes(name)), name).toEqual(new Set(["'self'", 'hash']));
      }
      // The one relaxation is inline style="" attributes. Anywhere else, 'unsafe-inline'
      // would switch off hashing for scripts or stylesheets.
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
      const bad = internalLinks(html).filter((h) => !/\/(#.*)?$/.test(h) && !/\.[a-z0-9]+$/i.test(h));
      expect(bad).toEqual([]);
    });

    it('internal links and #fragments resolve', () => {
      const broken = internalLinks(html).filter((href) => {
        const [path = '/', fragment] = href.split('#');
        const file = path.endsWith('/') ? join(DIST, path, 'index.html') : join(DIST, path);
        if (!existsSync(file)) return true;
        return !!fragment && !readFileSync(file, 'utf8').includes(`id="${fragment}"`);
      });
      expect(broken).toEqual([]);
    });

    it('same-page #fragments resolve (the skip link, for one)', () => {
      const fragments = [...html.matchAll(/<a\b[^>]*\bhref="#([^"]+)"/g)].map((m) => m[1]);
      expect(fragments.filter((f) => !html.includes(`id="${f}"`))).toEqual([]);
    });

    it('every image src and srcset URL is in dist/', () => {
      const urls = [...html.matchAll(/<(?:img|source)\b[^>]*>/g)]
        .flatMap(([tag]) => [
          /\bsrc="([^"]+)"/.exec(tag)?.[1],
          ...(/\bsrcset="([^"]+)"/.exec(tag)?.[1] ?? '').split(',').map((c) => c.trim().split(/\s+/)[0]),
        ])
        .filter((url): url is string => !!url && url.startsWith('/'));
      expect(urls.length).toBeGreaterThanOrEqual(page === '404.html' ? 0 : 1);
      expect(urls.filter((url) => !existsSync(join(DIST, decodeURI(url.split('?')[0] ?? ''))))).toEqual([]);
    });

    it.runIf(page !== '404.html')('has a title, description, canonical and Open Graph image', () => {
      expect(html).toMatch(/<title>[^<]+<\/title>/);
      expect(html).toMatch(/<meta name="description" content="[^"]{50,}"/);
      const canonical = /<link rel="canonical" href="([^"]+)"/.exec(html)?.[1];
      expect(canonical).toBe(`https://spellcaster.foo/${page.replace(/index\.html$/, '')}`);
      const og = /<meta property="og:image" content="https:\/\/spellcaster\.foo(\/og\/[^"]+\.png)"/.exec(html)?.[1];
      expect(og, 'og:image').toBeDefined();
      expect(pngSize(join(DIST, og ?? ''))).toEqual([1200, 630]);
    });
  });
});

describe('site files', () => {
  it.each(['robots.txt', 'sitemap-index.xml', 'favicon.ico', 'favicon.svg', 'apple-touch-icon.png', '404.html'])(
    '%s exists',
    (file) => expect(existsSync(join(DIST, file))).toBe(true),
  );

  it('the sitemap lists the pages and not the 404', () => {
    const urls = files
      .filter((f) => /^sitemap-\d+\.xml$/.test(f))
      .flatMap((f) => [...readFileSync(join(DIST, f), 'utf8').matchAll(/<loc>([^<]+)<\/loc>/g)])
      .map((m) => m[1]);
    expect(urls).toContain('https://spellcaster.foo/');
    expect(urls).toContain('https://spellcaster.foo/projects/okta-access-review-aws/');
    expect(urls.filter((u) => u?.includes('404'))).toEqual([]);
  });

  it('publishes no PDF (the resume stays off the site)', () => {
    expect(files.filter((f) => f.toLowerCase().endsWith('.pdf'))).toEqual([]);
  });
});

// The home page and the case study load no framework: no island, and at most 2 KB of
// gzipped JavaScript (today, only the menu's few lines).
describe.each(['index.html', 'projects/okta-access-review-aws/index.html'])('JS budget: %s', (page) => {
  const html = existsSync(join(DIST, page)) ? readFileSync(join(DIST, page), 'utf8') : '';

  it('has no hydrated island', () => {
    expect(html).not.toContain('<astro-island');
  });

  it('ships at most 2 KB of gzipped JavaScript', () => {
    let bytes = 0;
    for (const [, attrs = '', body = ''] of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      if (attrs.includes('application/ld+json')) continue;
      const src = /\bsrc="([^"]+)"/.exec(attrs)?.[1];
      bytes += gzipSync(src ? readFileSync(join(DIST, src)) : Buffer.from(body)).length;
    }
    expect(bytes).toBeLessThanOrEqual(2048);
  });
});

// `npm run launch-check`: the gate before M5's launch PR. The job-title line is optional and
// never blocks a launch.
describe.runIf(process.env['LAUNCH_CHECK'] === '1')('launch check', () => {
  it('no DRAFT: markers are left', () => {
    const drafts = pages.filter((p) => readFileSync(join(DIST, p), 'utf8').includes('DRAFT:'));
    expect(drafts).toEqual([]);
  });

  it('no [placeholders] are left in the copy', () => {
    // Any bracketed text a person or a crawler reads: the page text, alt and title text,
    // meta content (descriptions, OG alt text) and the JSON-LD's strings. Code blocks, styles
    // and class names are left out, since brackets are normal there.
    const strings = (value: unknown): string[] =>
      typeof value === 'string' ? [value] : Object.values(value ?? {}).flatMap(strings);
    const copy = (html: string) => [
      html.replace(/<(script|style|pre)\b[\s\S]*?<\/\1>/g, ' ').replace(/<[^>]+>/g, ' '),
      ...[...html.matchAll(/\s(?:alt|title|aria-label|content)="([^"]*)"/g)].map((m) => m[1] ?? ''),
      ...[...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].flatMap(
        (m) => strings(JSON.parse(m[1] ?? 'null')),
      ),
    ];
    const left = pages.flatMap((p) =>
      copy(readFileSync(join(DIST, p), 'utf8')).flatMap((text) =>
        [...text.matchAll(/\[[^\]\n]{1,80}\]/g)].map((m) => `${p}: ${m[0]}`),
      ),
    );
    expect(left).toEqual([]);
  });

  it('the home page links to LinkedIn', () => {
    expect(readFileSync(join(DIST, 'index.html'), 'utf8')).toMatch(/href="https:\/\/(www\.)?linkedin\.com\//);
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
