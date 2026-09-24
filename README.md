# spellcaster-site-WIP

The source of [spellcaster.foo](https://spellcaster.foo/), Matthew Spell's portfolio.
It's a static [Astro](https://astro.build/) site on S3 and CloudFront, managed with
Terraform and deployed by GitHub Actions through OIDC. Every change goes through a pull
request with required checks, and every run on `main` produces a signed evidence bundle.

## Quickstart

You need Docker, git and Python 3 (for the pre-commit hook). Every npm command runs inside
a dev container that can see this repository and nothing else from your machine (no cloud
credentials, SSH keys or tokens).

```bash
git clone https://github.com/matt-spellcaster/spellcaster-site-WIP.git
cd spellcaster-site-WIP
git config core.hooksPath .githooks   # refuse keys, state, account IDs and PDFs
scripts/dev.sh npm ci                 # the first run also builds the container image
scripts/dev.sh npm run verify         # lint, type check, tests, build, browser tests
scripts/dev.sh npm run dev            # http://localhost:4321/
```

To check the site on a phone on the same Wi-Fi, run `DEV_LAN=1 scripts/dev.sh npm run dev`
and open the address it prints.

## How changes ship

| Stage | What happens |
|---|---|
| Pull request | **Build** (dependency audit and signatures, lint, type check, unit and dist tests, build), **E2E** (Playwright + axe on Chrome, iPhone WebKit and Pixel, against the exact built artifact), **Security** (gitleaks and a no-PDFs check over the full history, zizmor, actionlint, branch-rule checks) and **Evidence** are all required |
| Merge to `main` | The same checks, then the evidence bundle is signed with a GitHub artifact attestation |

`CLAUDE.md` lists the rules this repository follows (supply chain, CSP, design, and what
never gets committed).
