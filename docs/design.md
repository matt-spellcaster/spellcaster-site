# Design

Approved by Matthew at the M2 design gate on 2026-09-23, after comparing Inter and Geist at 375,
768 and 1280 px, with a white image scrolled under the header. The mockup pages were removed
afterwards; `git log -- src/pages/mockup` has them.

## Decisions

| Decision | Choice |
|---|---|
| Theme | Dark only |
| Font | **Inter** (variable, Latin subset), self-hosted through Astro's Fonts API from `@fontsource-variable/inter` |
| Accent | **Blue `#8ab4f8`**: links, primary buttons, section labels |
| Header glass | Tint **0.80** of the canvas, `saturate(160%) blur(16px)` |
| Menu glass | Tint **0.92**, same filter (see below) |

## Tokens

Defined once in `src/styles/global.css` (`@theme`), and checked by `tests/unit/contrast.test.ts`.

| Token | Value | Use |
|---|---|---|
| `canvas` | `#0b0d10` | Page background; text on accent buttons |
| `surface` | `#12151a` | Cards and frames; the opaque glass fallback |
| `surface-2` | `#1a1e24` | Hover states |
| `line` | `#262b33` | Borders and dividers |
| `line-strong` | `#636c7a` | Outlines that carry meaning: the boxes in the card diagrams |
| `ink` | `#e8eaed` | Body text and headings |
| `muted` | `#a3aab5` | Secondary text |
| `accent` | `#8ab4f8` | Links and primary buttons |
| `keep` / `revoke` / `decide` | `#5cc98a` / `#f07178` / `#e6b450` | The demo's decision colours (M6); code highlighting |

Every text colour meets WCAG AA (4.5:1) on every surface. The header's colours (`ink`, `muted`,
`accent`) also do on the header glass with a white image directly behind it (the worst case:
blur leaves a white area white). `line-strong` meets 3:1 on every surface. The contrast test
fails on any colour in `@theme` it doesn't know, so a new one has to be added there.

## Glass

Frosted glass is used on the header and the mobile menu only, never on content. This follows
Apple's "content first" guidance, and it's where a translucent layer earns its keep: the page
scrolls under it.

- `src/styles/glass.css` writes the filter out literally, `-webkit-` first. Safari before 18
  needs the prefix and ignores custom properties inside it.
- Astro builds with target `esnext`, so the CSS minifier would drop the prefix. `astro.config.ts`
  sets `build.cssTarget` to the supported browsers, and a dist test checks the prefix survives.
- Every fallback is opaque (`surface`): no `backdrop-filter` support, `prefers-reduced-transparency`,
  `prefers-contrast: more` and forced colors (system colours). An E2E test checks the last two.
- Nothing above the header may set `transform`, `filter`, `contain`, `perspective` or
  `will-change`: each one breaks `position: fixed` or the backdrop. An E2E test checks.
- **The menu sheet uses a heavier tint (0.92).** It's a popover, so it lives in the top layer,
  and WebKit draws no blur there. At 0.80 the page's heading showed through the menu links.
  To recheck on real devices in M4c: if iOS Safari does blur the sheet, 0.92 still looks right.

## Mobile menu

A Popover API sheet (`src/components/MobileMenu.astro`). Opening, closing, Esc, outside clicks
and returning focus to the Menu button all work without JavaScript. The sheet repeats the header
row (name on the left, Close where Menu was), so opening it reads as the header growing
downwards. A small script closes the sheet after an in-page link, since an in-page link doesn't
change the document.
