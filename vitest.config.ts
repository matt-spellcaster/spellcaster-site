import { defineConfig } from 'vitest/config';

// unit: source and repository rules; runs before the build.
// dist: checks the built site in dist/; runs after `npm run build`.
export default defineConfig({
  test: {
    projects: [
      { test: { name: 'unit', include: ['tests/unit/**/*.test.ts'] } },
      { test: { name: 'dist', include: ['tests/dist/**/*.test.ts'] } },
    ],
  },
});
