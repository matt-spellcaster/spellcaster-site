# Design

Approved by Matthew at the M2 design gate on 2026-09-23 (Inter, cool dark, cards), then
revised on 2026-09-24 to the "Editorial, with sky" direction from the session 4 design canvas:
a serif reading page on a warm black, with a thin-line planetary horizon under the pitch. The
mockup pages from the M2 gate were removed afterwards; `git log -- src/pages/mockup` has them.

## Decisions

| Decision | Choice |
|---|---|
| Theme | Dark only, on a warm black |
| Reading face | **Newsreader** (variable: weight and optical size, Latin subset), self-hosted through Astro's Fonts API from `@fontsource-variable/newsreader`. Headings, body text, the project names. |
| UI face | **Inter** (variable, Latin subset), from `@fontsource-variable/inter`. The header, nav, menu, labels, small links, captions, facts' labels, tables, the footer. |
| Accent | **Blue `#8ab4f8`**: links in running text, the ledger's GitHub links, primary buttons |
| Layout | One reading column, `--container-page` (52rem, 48rem of text). The home page reads top to bottom: pitch, the featured project as an article, the other projects as a ledger, About, Contact. |
| Header glass | Tint **0.80** of the canvas, `saturate(160%) blur(16px)` |
| Menu glass | Tint **0.92**, same filter (see below) |
| Sky | The wash, the stars and the horizon, at `--sky-intensity` 0.6 |

## Tokens

Defined once in `src/styles/global.css` (`@theme`), and checked by `tests/unit/contrast.test.ts`.

| Token | Value | Use |
|---|---|---|
| `canvas` | `#111010` | Page background; text on accent buttons |
| `surface` | `#181616` | The screenshot frame, code blocks; the opaque glass fallback |
| `surface-2` | `#221f1f` | Hover states, inline code |
| `planet` | `#0b0c10` | The horizon's disc. Nothing is drawn on it. |
| `line` | `#2b2828` | Borders and dividers |
| `ink` | `#ecebe6` | Headings, names, links. Body text is `ink` at 85%, the ledger's one-liners at 70%. |
| `muted` | `#b0ada5` | Labels, captions, the nav, the footer |
| `accent` | `#8ab4f8` | Links and primary buttons |
| `keep` / `revoke` / `decide` | `#5cc98a` / `#f07178` / `#e6b450` | The demo's decision colours (M6); code highlighting |

Every text colour meets WCAG AA (4.5:1) on every surface, on the header glass with a white
image directly behind it (the worst case: blur leaves a white area white), and on the sky's
wash at its strongest. `muted` is as dark as the glass check allows. The contrast test fails
on any colour in `@theme` it doesn't know, so a new one has to be added there.

The sky's own blues (`#4f7fd9` haze, `#6f9fe6` limb light, `#dbe7ff` the line and the stars)
are gradient stops in `Sky.astro` and `Horizon.astro`, never text and never a surface; the
wash is the only one behind text, and the test checks it.

## Type

- The pitch is a 34px statement (28px on phones), the featured title 40px, the project names
  20px, body text 19px to 20px; all Newsreader at weight 400 or 500, never bolder. Newsreader's
  optical-size axis gives the big sizes their finer cut on its own.
- Section labels ("Featured", "More projects", "Case study") are the `eyebrow` utility: Inter
  12px, tracked, uppercase, `muted`.
- Text links (`TextLink.astro`) are underlined, in `ink` with the underline at 40%, and turn
  `accent` on hover. Links in running text are `accent` and underlined. Buttons
  (`LinkButton.astro`) stay for the case study and the 404 page.

## Sky

`Sky.astro` (in the layout) draws a cool radial wash from the top edge and 88 seeded stars over
the hero. `Horizon.astro` (in the hero, under the links) draws the limb of a warm-black planet:
a wide haze, a tighter limb light, the disc, and a 1.5px line, fading out before the featured
project. Both are `aria-hidden`, take no space in the flow, and scale with `--sky-intensity`.

- **Gradients only.** No `filter: blur()` and no SVG `feGaussianBlur`: a 64px CSS blur behind
  the screenshot crashed WebKit's renderer in the phone tests, so the glow is radial gradients
  with their stops at the limb.
- The drawings are a fixed 2560px wide and centred, so the curve and the glow are the same size
  on every screen; narrower screens see the middle. The horizon's box is absolutely positioned
  with `top: auto`, so it follows the hero's real height on every screen but spans the viewport.
- The screenshot frame is opaque `surface` with an inner edge light and a soft shadow. It is not
  glass (see below), and nothing bright is ever behind it.

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
