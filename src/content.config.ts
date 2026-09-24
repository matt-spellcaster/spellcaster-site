import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// One entry per project on the home page. The featured entry has a cover (its screenshot)
// and a body: its case study page. The others are a name, a line and a link.
const projects = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/projects' }),
  schema: ({ image }) =>
    z
      .object({
        title: z.string(),
        // The one-liner on the home page and the page description: 160 characters, not counting "DRAFT: ".
        summary: z
          .string()
          .refine((s) => s.replace(/^DRAFT: /, '').length <= 160, 'summary is over 160 characters'),
        repo: z.url(),
        order: z.number().int(),
        featured: z.boolean().default(false),
        cover: image().optional(),
        coverAlt: z.string().optional(),
        // Featured only: the three "What this shows" bullets at the top of the case study.
        shows: z.array(z.string()).length(3).optional(),
        sampleReport: z.url().optional(),
      })
      .refine((p) => !p.cover || p.coverAlt, 'a cover needs coverAlt')
      .refine(
        (p) => !p.featured || (p.cover && p.shows),
        'the featured project needs a cover and shows',
      ),
});

export const collections = { projects };
