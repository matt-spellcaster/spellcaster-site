// The single source for who the site is about and where it links. Copy that starts with
// "DRAFT:" hasn't been approved yet; the launch check fails while any is left.
import { existsSync } from 'node:fs';

const RESUME = '/matthew-spell-resume.pdf';

export interface SiteLink {
  label: string;
  href: string;
}

export const site = {
  name: 'Matthew Spell',
  // The optional line under the name. null hides it; it never blocks a launch.
  jobTitle: null as string | null,
  pitch: "I work in identity and IT. These are a few things I've built.",
  email: 'hello@spellcaster.foo',
  github: 'https://github.com/matt-spellcaster',
  linkedin: 'https://www.linkedin.com/in/matthew-spell-065b9483/' as string | null,
  // Linked only once the PDF is in public/; the launch check requires it.
  resume: existsSync(`public${RESUME}`) ? RESUME : null,
  repo: 'https://github.com/matt-spellcaster/spellcaster-site',
} as const;

export const nav: SiteLink[] = [
  { label: 'Work', href: '/#work' },
  { label: 'About', href: '/#about' },
  { label: 'Contact', href: '/#contact' },
];
