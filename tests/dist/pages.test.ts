// Checks the built site in dist/. Run `npm run build` first.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
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
    const left = pages.filter((p) => /\[(N|role|company|what else)\]/.test(readFileSync(join(DIST, p), 'utf8')));
    expect(left).toEqual([]);
  });

  it('the home page links to LinkedIn', () => {
    expect(readFileSync(join(DIST, 'index.html'), 'utf8')).toMatch(/href="https:\/\/(www\.)?linkedin\.com\//);
  });

  it('the resume is there, under 1 MB, and linked', () => {
    const resume = join(DIST, 'matthew-spell-resume.pdf');
    expect(existsSync(resume)).toBe(true);
    expect(statSync(resume).size).toBeLessThanOrEqual(1024 * 1024);
    expect(readFileSync(join(DIST, 'index.html'), 'utf8')).toContain('href="/matthew-spell-resume.pdf"');
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
