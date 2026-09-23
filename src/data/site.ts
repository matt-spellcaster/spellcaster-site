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
  pitch:
    'DRAFT: I’m an IAM and IT systems engineer, and I build tooling around Okta and AWS: access reviews, offboarding checks, and governed access for AI assistants. Every project here links to its code and the CI checks it passes.',
  email: 'hello@spellcaster.foo',
  github: 'https://github.com/matt-spellcaster',
  // null until the URL is confirmed; the launch check requires it.
  linkedin: null as string | null,
  // Linked only once the PDF is in public/; the launch check requires it.
  resume: existsSync(`public${RESUME}`) ? RESUME : null,
  repo: 'https://github.com/matt-spellcaster/spellcaster-site',
} as const;

export const nav: SiteLink[] = [
  { label: 'Work', href: '/#work' },
  { label: 'About', href: '/#about' },
  { label: 'Contact', href: '/#contact' },
];
