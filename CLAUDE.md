# spellcaster-site-WIP

Matthew Spell's portfolio site, served at https://spellcaster.foo/. It's an Astro static
site deployed to S3 + CloudFront with Terraform, through GitHub OIDC. The repository is
**private for now and may be made public later** (Matthew's call, 2026-09-24), so treat it as
public: it has to read well, and nothing private goes in (rule 7), whatever the setting says.

## Hard rules

1. **npm runs only in the dev container.** Use `scripts/dev.sh npm …`, never npm or npx on
   the host. The container mounts only this repository and a `node_modules` volume, and the
   repository is read-only in it apart from the `writable` list in `dev.sh` (what the tools
   write), so a bad package can't touch what acts on the host. `infra/` and `.notes/` are
   hidden from it. After each run, `dev.sh` stops loudly if a `CLAUDE.md`, `.mcp.json`,
   `.claude/` or nested `.git` appeared. `npm run format` can't rewrite files outside that
   list (`.github/`, for one): format those by hand. The dev server serves only `src`,
   `public`, `node_modules` and `.astro`.
2. **Supply chain.** Don't loosen `.npmrc` (`ignore-scripts`, `min-release-age=7`,
   `allow-git=none`, `save-exact`, `engine-strict`). Pin every dependency exactly, to the
   newest release that is at least 7 days old. Pin every GitHub Action by full commit SHA,
   and give every job its own minimal `permissions`.
3. **CSP.** Astro writes the CSP `<meta>` tag and hashes every script and style it
   processes. Never use `is:inline`, `define:vars`, `<ClientRouter/>`, Shiki or prefetch;
   each one either bypasses hashing or needs a CSP exception. Code blocks use Prism. The
   only relaxation is `style-src-attr 'unsafe-inline'`. `tests/unit/repo-rules.test.ts`
   and `tests/dist/` enforce this.
4. **Design.** Follow `docs/design.md` (the M2 gate, revised for "Editorial, with sky"):
   dark only on a warm black, Newsreader for what's read and Inter for the UI, accent
   `#8ab4f8`. Frosted glass only on the header and the mobile menu, never on content, with
   opaque fallbacks. The sky is drawn with gradients only, never a large blur (one crashed
   WebKit). New colours go in `@theme` in `src/styles/global.css`, where the contrast test
   sees them.
5. **Links.** Every internal `href` ends in `/` (for example `/projects/okta-access-review-aws/`).
6. **Draft copy.** Text Matthew hasn't approved yet starts with `DRAFT:` (on the case study,
   at the start of each section), and facts only he can supply are `[placeholders]`.
   The dist tests fail while any are left, or while the LinkedIn link is missing, since every
   merge to `main` goes live: draft copy stays on its branch, and can't go to QA (read it on
   the dev server).
   Copy is written in Matthew's voice: plain, short sentences, no dashes (a dist test fails on
   an em or en dash), and no claim the linked repositories don't back up.
7. **Nothing private in git.** No AWS account IDs, `backend.hcl`, `*.tfvars`, Terraform
   state, phone number or home address. CI logs would be public too: Terraform prints only its
   plan summary, and role ARNs and the state bucket live in GitHub secrets. The
   pre-commit hook (`git config core.hooksPath .githooks`) refuses the obvious cases,
   including any PDF, found by name or content (`scripts/ci/check_pdfs.py`): a PDF's text is
   compressed, so no line scan can read it, and none belongs here. Matthew's resume is not
   on the site, by his choice, and a dist test fails on any PDF in `dist/`. CI's Security
   job runs the same PDF check over every branch and tag, but by then the file is in the history:
   the hook is the only check that stops a leak.

## Commands (all through `scripts/dev.sh`)

| Command | What it does |
|---|---|
| `npm ci` | Install from the lockfile (first run, and after the lockfile changes) |
| `npm run dev` | Dev server at http://localhost:4321/ (`DEV_LAN=1` for a phone on the same Wi-Fi) |
| `npm run verify` | Everything CI's Build and E2E jobs run: lint, `astro check`, unit tests, build, dist tests, Playwright |
| `npm run format` | Prettier |
| `npm run lighthouse` | Lighthouse (mobile) on every built page; reports in `test-results/lighthouse/` |
| `node scripts/og-images.ts` | Remakes the committed social images and favicons after a design change |

To pin the demo to another commit of the tool, run on the host (it needs git and Docker; the
tool's code runs in a throwaway container): `python3 -I scripts/ci/demo_data.py sync --commit <sha>`.

The Python CI helpers' tests use only the standard library, so they run on the host (CI's
Build job runs them too): `python3 -I -m unittest discover -s tests/ci`. Keep the `-I`: it
keeps the writable repository root off Python's import path, so a file the container wrote
there can't shadow a standard module.

Terraform also runs on the host, because the container can't see `infra/`. After changing
`infra/`, run `terraform fmt -recursive infra` and, in each root, `terraform validate`. Only
Matthew applies `infra/bootstrap` (`docs/aws.md`); after any change to its CI roles, he runs
`python3 -I scripts/ci/iam_policy_tests.py` against the account.

## Layout

- `src/pages/`, `src/layouts/`, `src/components/`, `src/styles/`: the site.
- `src/data/site.ts`: name, pitch and links, in one place.
- The case study's "Be the CISO" demo: `src/components/demo/` (the React island, the only one;
  its own words are in `copy.ts`), `src/lib/demo/` (the tool's review ported to TypeScript),
  `src/data/demo/` and `tests/fixtures/demo/` (the tool's export and its golden replays, never
  edited by hand: `scripts/ci/demo_data.py sync` moves the pin, CI's Demo data job checks it).
  A change to the engine has to keep `tests/unit/demo-golden.test.ts` byte for byte.
- `src/content/projects/`: one entry per project on the home page; the featured one (`.mdx`)
  is also the case study at `/projects/<id>/`. The schema is in `src/content.config.ts`.
- `tests/unit/` (source and repository rules), `tests/dist/` (the built `dist/`),
  `tests/e2e/` (Playwright + axe on Desktop Chrome, iPhone WebKit and Pixel), `tests/ci/`
  (the Python CI helpers).
- `.devcontainer/Dockerfile`: Node and Playwright versions must match `.node-version` and
  `package.json` (a unit test checks).
- `infra/bootstrap/`: the Terraform Matthew applies by hand (state, OIDC, the CI roles, the
  qa zone, both certificates, CloudFront policies, alerts). `infra/envs/prod` is applied by
  CI's Deploy production job; `infra/envs/qa` by the QA up and QA down workflows. Both use `infra/modules/site`
  (bucket, viewer-request function, distribution). The function's tests sit beside it and run
  in CI's Terraform job with plain Node, since the container can't see `infra/`. Every root commits a `.terraform.lock.hcl`
  for linux_amd64 and darwin_arm64.
  Accepted Checkov findings, each with a reason, are in `infra/.checkov.yaml`.
- `docs/aws.md` (accounts, roles, bring-up), `docs/dns.md` (the Cloudflare records),
  `docs/qa.md` (QA: turning it on, using it, the password) and `docs/teardown.md`.
- `.github/workflows/compliance.yml`: Build → E2E, Security, Terraform, Demo data, Evidence (a SHA-256 evidence
  bundle), then on main Sign evidence (the only job that can mint an OIDC token today) and
  Deploy production (gated on `vars.DEPLOY_ENABLED`: plan, apply, publish the tested build,
  smoke test; `docs/aws.md` has the steps).
- `.github/workflows/qa-up.yml` and `qa-down.yml`: QA on demand, from a branch's tested
  build, behind the password in SSM (`scripts/ci/qa_auth.sh`, sourced per step, never in
  `GITHUB_ENV`); QA down also runs nightly. Lighthouse runs there with no AWS access.
- `.github/rulesets/main.json`: the ruleset on `main`. When a new required check is added,
  PUT the ruleset again before opening that PR, and update `REQUIRED_CHECKS` in
  `scripts/ci/check_branch_rules.py`.
- `scripts/ci/`: standard-library Python helpers the workflow calls.
