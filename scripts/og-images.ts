// Makes the committed social and icon images. Run it again after changing the design:
//   scripts/dev.sh node scripts/og-images.ts
// Writes public/og/{home,okta-access-review-aws}.png (1200x630), public/apple-touch-icon.png
// (180x180) and public/favicon.ico (32x32, a PNG inside an ICO container).
import { chromium } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const font = (path: string) =>
  `url(data:font/woff2;base64,${readFileSync(`node_modules/${path}`).toString('base64')}) format('woff2')`;
const inter = font('@fontsource-variable/inter/files/inter-latin-wght-normal.woff2');
const newsreader = font(
  '@fontsource-variable/newsreader/files/newsreader-latin-standard-normal.woff2',
);
const shot = readFileSync('src/assets/okta/slack-review-finished.png');
const favicon = readFileSync('public/favicon.svg', 'utf8');

// The same look as the site (docs/design.md): warm black, Newsreader, the sky's wash and the
// thin-line horizon along the bottom.
const base = `
  @font-face { font-family: Newsreader; font-weight: 200 800; src: ${newsreader}; }
  @font-face { font-family: Inter; font-weight: 100 900; src: ${inter}; }
  * { margin: 0; box-sizing: border-box; }
  body { width: 1200px; height: 630px; overflow: hidden; background: #111010; color: #ecebe6;
         font-family: Newsreader, Georgia, serif; -webkit-font-smoothing: antialiased; }
  .sky { position: absolute; inset: 0; opacity: 0.6;
         background: radial-gradient(760px 420px at 50% 0, rgb(79 127 217 / 0.16), transparent 100%); }
  .horizon { position: absolute; left: 0; bottom: 0; width: 1200px; height: 300px; opacity: 0.6; }
  .url { position: absolute; left: 80px; bottom: 64px; font-family: Inter, sans-serif; font-size: 24px; color: #b0ada5; }
  .mark { position: absolute; right: 80px; bottom: 56px; width: 44px; height: 44px; }`;

// The limb of the planet, as in src/components/Horizon.astro: gradients, no filters.
const horizon = (() => {
  const cx = 600;
  const r = 1720;
  const cy = 90 + r;
  return `<svg class="horizon" viewBox="0 0 1200 300" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="fade" gradientUnits="userSpaceOnUse" x1="0" y1="90" x2="0" y2="300">
        <stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/>
      </linearGradient>
      <mask id="mask"><rect width="1200" height="300" fill="url(#fade)"/></mask>
      <radialGradient id="haze" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${r + 220}">
        <stop offset="${r / (r + 220)}" stop-color="#4f7fd9" stop-opacity="0.18"/>
        <stop offset="1" stop-color="#4f7fd9" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="limb" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${r + 70}">
        <stop offset="${r / (r + 70)}" stop-color="#6f9fe6" stop-opacity="0.32"/>
        <stop offset="1" stop-color="#6f9fe6" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <g mask="url(#mask)">
      <rect width="1200" height="300" fill="url(#haze)"/>
      <rect width="1200" height="300" fill="url(#limb)"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="#0b0c10"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#dbe7ff" stroke-width="1.5" opacity="0.9"/>
    </g>
  </svg>`;
})();

const mark = favicon.replace('<svg ', '<svg class="mark" ');

const pages: Record<string, string> = {
  home: `<style>${base}
      h1 { position: absolute; left: 80px; top: 176px; font-size: 96px; font-weight: 500; letter-spacing: -0.02em; }
      p { position: absolute; left: 82px; top: 330px; width: 760px; font-size: 40px; line-height: 1.3; color: #b0ada5; }
    </style>
    <div class="sky"></div>${horizon}
    <h1>Matthew Spell</h1>
    <p>Full stack IT. Here are some things I built.</p>
    <div class="url">spellcaster.foo</div>${mark}`,

  'okta-access-review-aws': `<style>${base}
      .label { position: absolute; left: 80px; top: 120px; font-family: Inter, sans-serif; font-size: 20px;
               font-weight: 500; letter-spacing: 0.12em; text-transform: uppercase; color: #b0ada5; }
      h1 { position: absolute; left: 80px; top: 160px; width: 560px; font-size: 64px; line-height: 1.12;
           font-weight: 500; letter-spacing: -0.015em; }
      p { position: absolute; left: 82px; top: 330px; width: 540px; font-size: 28px; line-height: 1.45; color: #b0ada5; }
      .frame { position: absolute; left: 700px; top: 70px; width: 440px; height: 620px; padding: 10px;
               border: 1px solid #2b2828; border-radius: 22px; background: #181616; overflow: hidden;
               box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.05), 0 24px 48px -24px rgb(0 0 0 / 0.7); }
      .frame img { width: 100%; border-radius: 14px; display: block; }
      .mark { display: none; }
    </style>
    <div class="sky"></div>${horizon}
    <div class="label">Case study</div>
    <h1>Okta access review in AWS</h1>
    <p>18 checks, sign-off in Slack, fixes in Jira, evidence in S3</p>
    <div class="frame"><img src="data:image/png;base64,${shot.toString('base64')}"></div>
    <div class="url">spellcaster.foo</div>${mark}`,
};

// A PNG is a valid ICO image (Windows Vista and later, every current browser).
function ico(png: Buffer): Buffer {
  const header = Buffer.alloc(22);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(1, 4); // one image
  header.writeUInt8(32, 6); // width
  header.writeUInt8(32, 7); // height
  header.writeUInt16LE(1, 10); // colour planes
  header.writeUInt16LE(32, 12); // bits per pixel
  header.writeUInt32LE(png.length, 14);
  header.writeUInt32LE(22, 18); // offset of the image data
  return Buffer.concat([header, png]);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
mkdirSync('public/og', { recursive: true });
for (const [name, html] of Object.entries(pages)) {
  await page.setContent(`<!doctype html><html><body>${html}</body></html>`, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  writeFileSync(`public/og/${name}.png`, await page.screenshot({ type: 'png' }));
}

// Apple touch icons are full-bleed squares; iOS rounds the corners itself.
const square = favicon.replace('rx="7"', 'rx="0"');
for (const [size, out] of [
  [180, 'public/apple-touch-icon.png'],
  [32, 'public/favicon.ico'],
] as const) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<!doctype html><style>*{margin:0}svg{display:block;width:${size}px;height:${size}px}</style>${size === 32 ? favicon : square}`,
  );
  const png = await page.screenshot({ type: 'png', omitBackground: true });
  writeFileSync(out, size === 32 ? ico(png) : png);
}

await browser.close();
console.log('Wrote public/og/*.png, public/apple-touch-icon.png and public/favicon.ico');
