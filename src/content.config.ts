import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// One entry per project card. The featured entry also has a body: its case study page.
const projects = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/projects' }),
  schema: ({ image }) =>
    z
      .object({
        title: z.string(),
        // The card's one-liner and the page description: 160 characters, not counting "DRAFT: ".
        summary: z
          .string()
          .refine((s) => s.replace(/^DRAFT: /, '').length <= 160, 'summary is over 160 characters'),
        repo: z.url(),
        order: z.number().int(),
        featured: z.boolean().default(false),
        cover: image().optional(),
        coverAlt: z.string().optional(),
        // Repos with no images get a small diagram drawn from their README instead.
        diagram: z.enum(['okta-mcp-local', 'okta-mcp-gateway']).optional(),
        // Featured only: the three "What this shows" bullets at the top of the case study.
        shows: z.array(z.string()).length(3).optional(),
        sampleReport: z.url().optional(),
      })
      .refine((p) => !p.cover || p.coverAlt, 'a cover needs coverAlt')
      .refine((p) => p.cover || p.diagram, 'a card needs a cover or a diagram')
      .refine(
        (p) => !p.featured || (p.cover && p.shows),
        'the featured project needs a cover and shows',
      ),
});

export const collections = { projects };
