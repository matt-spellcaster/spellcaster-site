// Makes the committed social and icon images. Run it again after changing the design:
//   scripts/dev.sh node scripts/og-images.ts
// Writes public/og/{home,okta-access-review-aws}.png (1200x630), public/apple-touch-icon.png
// (180x180) and public/favicon.ico (32x32, a PNG inside an ICO container).
import { chromium } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const inter = readFileSync(
  'node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2',
);
const shot = readFileSync('src/assets/okta/slack-review-finished.png');
const favicon = readFileSync('public/favicon.svg', 'utf8');

const base = `
  @font-face { font-family: Inter; font-weight: 100 900; src: url(data:font/woff2;base64,${inter.toString('base64')}) format('woff2'); }
  * { margin: 0; box-sizing: border-box; }
  body { width: 1200px; height: 630px; overflow: hidden; background: #0b0d10; color: #e8eaed;
         font-family: Inter, sans-serif; -webkit-font-smoothing: antialiased; }
  .glow { position: absolute; inset: 0; background:
          radial-gradient(700px 380px at 12% -10%, rgb(138 180 248 / 0.22), transparent 70%),
          radial-gradient(520px 320px at 95% 110%, rgb(92 201 138 / 0.08), transparent 70%); }
  .url { position: absolute; left: 80px; bottom: 64px; font-size: 26px; color: #a3aab5; }
  .mark { position: absolute; right: 80px; bottom: 56px; width: 44px; height: 44px; }`;

const mark = favicon.replace('<svg ', '<svg class="mark" ');

const pages: Record<string, string> = {
  home: `<style>${base}
      h1 { position: absolute; left: 80px; top: 200px; font-size: 104px; font-weight: 600; letter-spacing: -0.035em; }
      p { position: absolute; left: 84px; top: 350px; font-size: 38px; color: #a3aab5; }
    </style>
    <div class="glow"></div>
    <h1>Matthew Spell</h1>
    <p>IAM and IT systems engineering</p>
    <div class="url">spellcaster.foo</div>${mark}`,

  'okta-access-review-aws': `<style>${base}
      .label { position: absolute; left: 80px; top: 120px; font-size: 26px; font-weight: 500; color: #8ab4f8; }
      h1 { position: absolute; left: 80px; top: 164px; width: 560px; font-size: 68px; line-height: 1.08;
           font-weight: 600; letter-spacing: -0.03em; }
      p { position: absolute; left: 82px; top: 336px; width: 540px; font-size: 28px; line-height: 1.45; color: #a3aab5; }
      .frame { position: absolute; left: 700px; top: 70px; width: 440px; height: 620px; padding: 10px;
               border: 1px solid #262b33; border-radius: 22px; background: #12151a; overflow: hidden; }
      .frame img { width: 100%; border-radius: 14px; display: block; }
      .mark { display: none; }
    </style>
    <div class="glow"></div>
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
