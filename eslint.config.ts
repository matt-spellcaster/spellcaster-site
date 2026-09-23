import js from '@eslint/js';
import astro from 'eslint-plugin-astro';
import jsxA11y from 'eslint-plugin-jsx-a11y-x';
import { defineConfig, globalIgnores } from 'eslint/config';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  globalIgnores([
    'dist/',
    '.astro/',
    'node_modules/',
    'playwright-report/',
    'test-results/',
    'results/',
    'evidence/',
  ]),
  js.configs.recommended,
  tseslint.configs.strict,
  astro.configs.recommended,
  {
    // The original eslint-plugin-jsx-a11y doesn't support ESLint 10; this is its maintained fork.
    files: ['**/*.{astro,tsx}'],
    ...jsxA11y.configs.strict,
  },
  { languageOptions: { globals: { ...globals.node, ...globals.browser } } },
);
