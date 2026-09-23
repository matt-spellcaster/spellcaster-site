import mdx from '@astrojs/mdx';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'astro/config';

// Static site served from S3 + CloudFront. Every page is /path/index.html, and every
// internal link ends in "/" (the CloudFront function redirects slashless paths).
export default defineConfig({
  site: 'https://spellcaster.foo',
  output: 'static',
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [mdx(), react(), sitemap()],
  // Shiki writes inline style attributes per token; Prism uses classes, which the CSP allows.
  markdown: { syntaxHighlight: 'prism' },
  vite: { plugins: [tailwindcss()] },
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
