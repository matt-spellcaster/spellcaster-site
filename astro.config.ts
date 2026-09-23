import mdx from '@astrojs/mdx';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, fontProviders } from 'astro/config';

// Static site served from S3 + CloudFront. Every page is /path/index.html, and every
// internal link ends in "/" (the CloudFront function redirects slashless paths).
export default defineConfig({
  site: 'https://spellcaster.foo',
  output: 'static',
  trailingSlash: 'always',
  // Here rather than as CLI flags: a dev-server restart re-reads this file but drops the flags,
  // and fell back to Vite's port 5173, which scripts/dev.sh doesn't publish. host: true
  // listens on every interface inside the container; dev.sh publishes only 127.0.0.1 unless
  // DEV_LAN=1.
  server: { host: true, port: 4321 },
  build: { format: 'directory' },
  integrations: [mdx(), react(), sitemap()],
  // Self-hosted from pinned npm packages (no font CDN, so no CSP exception). Latin only.
  fonts: [
    {
      provider: fontProviders.local(),
      name: 'Inter',
      cssVariable: '--font-inter',
      fallbacks: ['system-ui', 'sans-serif'],
      options: {
        variants: [
          {
            src: ['@fontsource-variable/inter/files/inter-latin-wght-normal.woff2'],
            weight: '100 900',
            style: 'normal',
          },
        ],
      },
    },
  ],
  // Shiki writes inline style attributes per token; Prism uses classes, which the CSP allows.
  markdown: { syntaxHighlight: 'prism' },
  vite: {
    plugins: [tailwindcss()],
    // Astro builds with target "esnext", so the CSS minifier would assume the newest
    // browsers and drop -webkit-backdrop-filter, which Safari before 18 needs for the glass.
    // These are the browsers the site supports (Tailwind 4's own floor).
    build: { cssTarget: ['chrome111', 'edge111', 'firefox114', 'safari16.4', 'ios16.4'] },
  },
  security: {
    // Astro writes a <meta http-equiv="content-security-policy"> into every page and adds a
    // hash for each script and style it processes. See CLAUDE.md for what this rules out.
    csp: {
      directives: [
        "default-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
      ],
      // Stylesheets and <style> go on style-src-elem ('self' plus Astro's hashes). The only
      // relaxation is inline style="" attributes (the demo's animations set them) on
      // style-src-attr. 'unsafe-inline' on style-src would make browsers ignore every hash.
      styleDirective: {
        resources: [
          { resource: "'self'", kind: 'element' },
          { resource: "'unsafe-inline'", kind: 'attribute' },
        ],
      },
    },
  },
});
