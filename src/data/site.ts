// The single source for who the site is about and where it links. Copy that starts with
// "DRAFT:" hasn't been approved yet; the launch check fails while any is left.

export interface SiteLink {
  label: string;
  href: string;
}

export const site = {
  name: 'Matthew Spell',
  // The optional line under the name. null hides it; it never blocks a launch.
  jobTitle: null as string | null,
  // Also the home page's meta description (search results, link previews).
  pitch: 'Full stack IT. Here are some things I built.',
  email: 'hello@spellcaster.foo',
  github: 'https://github.com/matt-spellcaster',
  linkedin: 'https://www.linkedin.com/in/matthew-spell-065b9483/' as string | null,
  // Private for now, so nothing on the site links to it (the footer did).
  repo: 'https://github.com/matt-spellcaster/spellcaster-site-WIP',
} as const;

export const nav: SiteLink[] = [
  { label: 'Work', href: '/#work' },
  { label: 'About', href: '/#about' },
  { label: 'Contact', href: '/#contact' },
];
