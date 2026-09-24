// WCAG contrast for every text colour on every surface, including the worst case for the
// header glass (a white image directly behind it: blur and saturation leave a white area
// white, so the worst case is the tint composited over pure white) and the sky's wash
// behind the hero at its strongest.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

type RGB = [number, number, number];

const theme = readFileSync('src/styles/global.css', 'utf8');
const glass = readFileSync('src/styles/glass.css', 'utf8');
const sky = readFileSync('src/components/Sky.astro', 'utf8');

function token(name: string): RGB {
  const hex = new RegExp(`--color-${name}:\\s*#([0-9a-f]{6})`, 'i').exec(theme)?.[1];
  if (!hex) throw new Error(`--color-${name} not found in global.css`);
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as RGB;
}

function luminance(rgb: RGB): number {
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as RGB;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// The first rule in glass.css: `.glass { background-color: rgb(R G B / A); ... }`
const tint = /\.glass\s*\{[^}]*background-color:\s*rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)/.exec(
  glass,
);
const [tintRGB, tintAlpha] = tint
  ? [[Number(tint[1]), Number(tint[2]), Number(tint[3])] as RGB, Number(tint[4])]
  : [undefined, undefined];

// The wash in Sky.astro: `rgb(R G B / A)` at the centre of its gradient, drawn at
// --sky-intensity (global.css) over the canvas.
const wash = /rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)/.exec(sky);
const [washRGB, washAlpha] = wash
  ? [[Number(wash[1]), Number(wash[2]), Number(wash[3])] as RGB, Number(wash[4])]
  : [undefined, undefined];
const intensity = Number(/--sky-intensity:\s*([\d.]+)/.exec(theme)?.[1]);

const white: RGB = [255, 255, 255];
const over = (fg: RGB, alpha: number, bg: RGB): RGB =>
  fg.map((c, i) => c * alpha + (bg[i] ?? 0) * (1 - alpha)) as RGB;

// Every colour in @theme is one of these, so a new one can't skip the checks below.
const headerTexts = ['ink', 'muted', 'accent'] as const; // also on the header glass
const texts = [...headerTexts, 'keep', 'revoke', 'decide'] as const; // + code highlighting, the demo
const surfaces = ['canvas', 'surface', 'surface-2', 'planet'] as const; // planet: the horizon's disc
const lines = ['line'] as const; // borders and dividers

it('every @theme colour is a text, surface or line colour', () => {
  const all = [...theme.matchAll(/--color-([\w-]+):/g)].map((m) => m[1]);
  expect(all.sort()).toEqual([...texts, ...surfaces, ...lines].sort());
});

describe('text contrast (WCAG AA, 4.5:1)', () => {
  it.each(texts.flatMap((t) => surfaces.map((s) => [t, s] as const)))(
    '%s on %s',
    (text, surface) => {
      expect(contrast(token(text), token(surface))).toBeGreaterThanOrEqual(4.5);
    },
  );

  it('button text (canvas) on the accent', () => {
    expect(contrast(token('canvas'), token('accent'))).toBeGreaterThanOrEqual(4.5);
  });
});

describe('header glass', () => {
  it('has a parseable tint of at least 0.80', () => {
    expect(tintRGB).toBeDefined();
    expect(tintAlpha).toBeGreaterThanOrEqual(0.8);
  });

  it.each(headerTexts)('%s stays readable over a white image', (text) => {
    const worst = over(tintRGB ?? white, tintAlpha ?? 0, white);
    expect(contrast(token(text), worst)).toBeGreaterThanOrEqual(4.5);
  });
});

describe('the sky', () => {
  it('has a parseable wash and an intensity between 0 and 1', () => {
    expect(washRGB).toBeDefined();
    expect(intensity).toBeGreaterThan(0);
    expect(intensity).toBeLessThanOrEqual(1);
  });

  it.each(texts)('%s stays readable over the wash at its strongest', (text) => {
    const strongest = over(washRGB ?? white, (washAlpha ?? 1) * intensity, token('canvas'));
    expect(contrast(token(text), strongest)).toBeGreaterThanOrEqual(4.5);
  });
});
