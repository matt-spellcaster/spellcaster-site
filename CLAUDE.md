# spellcaster-site

Matthew Spell's portfolio site, served at https://spellcaster.foo/. It's an Astro static
site deployed to S3 + CloudFront with Terraform, through GitHub OIDC. The repository is
**public** and is part of the portfolio, so it has to read well.

## Hard rules

1. **npm runs only in the dev container.** Use `scripts/dev.sh npm …`, never npm or npx on
   the host. The container mounts only this repository and a `node_modules` volume.
2. **Supply chain.** Don't loosen `.npmrc` (`ignore-scripts`, `min-release-age=7`,
   `allow-git=none`, `save-exact`, `engine-strict`). Pin every dependency exactly, to the
   newest release that is at least 7 days old. Pin every GitHub Action by full commit SHA,
   and give every job its own minimal `permissions`.
3. **CSP.** Astro writes the CSP `<meta>` tag and hashes every script and style it
   processes. Never use `is:inline`, `define:vars`, `<ClientRouter/>`, Shiki or prefetch;
   each one either bypasses hashing or needs a CSP exception. Code blocks use Prism. The
   only relaxation is `style-src-attr 'unsafe-inline'`. `tests/unit/repo-rules.test.ts`
   and `tests/dist/` enforce this.
4. **Design.** Dark only. Frosted glass only on the header and the mobile menu, never on
   content, with opaque fallbacks for reduced transparency, more contrast and forced colors.
5. **Links.** Every internal `href` ends in `/` (for example `/projects/okta-access-review-aws/`).
6. **Draft copy.** Every piece of text that Matthew hasn't approved yet starts with
   `DRAFT:`. The launch check fails while any are left.
7. **Nothing private in git.** No AWS account IDs, `backend.hcl`, `*.tfvars`, Terraform
   state, phone number or home address. CI logs are public too: Terraform prints only its
   plan summary, and role ARNs and the state bucket live in GitHub secrets. The
   pre-commit hook (`git config core.hooksPath .githooks`) refuses the obvious cases.

## Commands (all through `scripts/dev.sh`)

| Command | What it does |
|---|---|
| `npm ci` | Install from the lockfile (first run, and after the lockfile changes) |
| `npm run dev` | Dev server at http://localhost:4321/ (`DEV_LAN=1` for a phone on the same Wi-Fi) |
| `npm run verify` | Everything CI's Build and E2E jobs run: lint, `astro check`, unit tests, build, dist tests, Playwright |
| `npm run format` | Prettier |

## Layout

- `src/pages/`, `src/layouts/`, `src/styles/`: the site.
- `tests/unit/` (source and repository rules), `tests/dist/` (the built `dist/`),
  `tests/e2e/` (Playwright + axe on Desktop Chrome, iPhone WebKit and Pixel).
- `.devcontainer/Dockerfile`: Node and Playwright versions must match `.node-version` and
  `package.json` (a unit test checks).
- `.github/workflows/compliance.yml`: Build → E2E, Security, Evidence (a signed SHA-256
  evidence bundle on main), then Deploy production (gated on `vars.DEPLOY_ENABLED`).
- `.github/rulesets/main.json`: the ruleset on `main`. When a new required check is added,
  PUT the ruleset again before opening that PR, and update `REQUIRED_CHECKS` in
  `scripts/ci/check_branch_rules.py`.
- `scripts/ci/`: standard-library Python helpers the workflow calls.
