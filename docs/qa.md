# QA

QA is a copy of the site at `https://qa.spellcaster.foo/`, for trying a branch on real
phones and browsers before it merges. It exists only while you need it: **QA up** builds it,
**QA down** takes it away, and QA down also runs every night at 07:17 UTC, so a forgotten QA
is gone by morning.

It's production's twin (the same module, headers, redirects and TLS), with three
differences:

- **A password.** Every request needs it, redirects included. The user name is `qa`, and the
  password is in SSM, `/portfolio/qa/basic-auth-password`. The CloudFront function holds only
  a SHA-256 hash of the whole header, never the password.
- **`X-Robots-Tag: noindex, nofollow`** on every response, the password prompt included.
- **Nothing is kept.** The bucket has no old versions, and a destroy empties it first.

The password keeps casual visitors and crawlers out. It isn't a security boundary: the name
`qa.spellcaster.foo` is public in Certificate Transparency logs, and the hash sits in QA's
Terraform state and in the function's code, which the production role can read. That's why
the password is long and random.

## Turning QA on (once)

Until now the `qa` environment in GitHub has been locked: no branch may use it, so nothing can
assume `portfolio-qa`. Production's distribution now holds `spellcaster.foo` and `www`, which
was the condition for unlocking it ([aws.md](aws.md), "Two things IAM can't fence").

**1. Store the password** (skip this if it's already there). It's long and random, and on
one line:

```bash
aws sso login --profile portfolio-admin
aws ssm put-parameter --profile portfolio-admin --region us-east-1 --name /portfolio/qa/basic-auth-password --type SecureString --value "$(openssl rand -base64 30)"
```

**2. Give the `qa` environment its role.** From `infra/bootstrap`:

```bash
aws sso login --profile portfolio-admin
AWS_PROFILE=portfolio-admin terraform init -backend-config=backend.hcl
AWS_PROFILE=portfolio-admin terraform output -raw qa_role_arn | gh secret set AWS_ROLE_ARN --env qa --repo matt-spellcaster/spellcaster-site-WIP
```

**3. Let branches deploy to it.** QA up runs on whichever branch you pick, and QA down's
nightly run is on `main`. GitHub matches branch names with `*` stopping at a `/`, so both
patterns are needed:

```bash
for pattern in '*' '*/*'; do
  gh api -X POST repos/matt-spellcaster/spellcaster-site-WIP/environments/qa/deployment-branch-policies \
    -f name="$pattern" -f type=branch --silent
done
gh api repos/matt-spellcaster/spellcaster-site-WIP/environments/qa/deployment-branch-policies --jq '[.branch_policies[].name]'
```

The last command should print `["*","*/*"]`. That covers `main` and names like
`infra/m4c-qa`. Dependabot's branches (`dependabot/npm_and_yarn/…`) have two slashes, so
they don't match, though only someone with write access can start QA up anyway.

## Using it

**Put a branch on QA.** Push the branch and open a pull request, then wait for the
Compliance checks' **Build** and **E2E** jobs to pass. QA up publishes the site those jobs
built and tested for that commit, so it never builds anything itself. Then:

**github.com** → the repository → **Actions** → **QA up** → **Run workflow** → pick the
branch → **Run workflow**.

It has three jobs:

1. **Find the tested build**: the newest Compliance run of the branch's latest commit whose
   Build and E2E passed. A pull request's run builds the branch merged with `main`, so QA
   shows what `main` would look like after the merge. If there isn't one, it stops and says so.
2. **Deploy QA** (as `portfolio-qa`): checks nothing of QA's exists that its Terraform state
   doesn't know about (a distribution holding `qa.spellcaster.foo`, the bucket, the function
   or the records), plans and applies `infra/envs/qa`, publishes the build, and runs the smoke test with the
   password. The smoke test also checks that a request without the password, or with a wrong
   one, gets 401 and noindex. The first run takes 5 to 15 minutes while CloudFront creates
   the distribution; later runs take a minute or two.
3. **Lighthouse**: scores every page as a phone would see it. It fails under 0.95 for
   accessibility or best practices, and warns under 0.9 for performance. It runs in a job
   with no AWS access and no password (Lighthouse is a large dependency), on the same build
   served inside the job, so its performance score doesn't include CloudFront's compression.
   The reports are in the run's `lighthouse-<sha>` artifact. Locally:
   `scripts/dev.sh npm run build`, then `scripts/dev.sh npm run lighthouse` (reports in
   `test-results/lighthouse/`).

**Open it.** Get the password (read-only access is enough), then open
`https://qa.spellcaster.foo/` and sign in as `qa`:

```bash
aws sso login --profile portfolio-read
aws ssm get-parameter --profile portfolio-read --region us-east-1 --name /portfolio/qa/basic-auth-password --with-decryption --query Parameter.Value --output text
```

A phone keeps the sign-in for the session. Private browsing asks again.

**Take it down.** **Actions** → **QA down** → **Run workflow** (any branch). Or leave it for
the nightly run. QA down destroys everything `infra/envs/qa` made, then lists anything left
(`scripts/ci/leftovers.py --scope qa`) and fails if it finds something. It's safe to run when
QA is already down.

QA up's deploy and QA down never run Terraform at the same time: one waits for the other.
GitHub keeps only one waiting, though, so a newer run replaces an older one that hasn't
started. If a night's QA down was replaced that way, the next night's takes QA down.

## Checking on real devices

The plan's device pass, each against QA:

- **iPhone, Safari**: the header's frosted glass while scrolling; the menu opens, closes and
  its glass reads well (WebKit draws no blur in the menu's layer, hence its 0.92 tint);
  VoiceOver reads the headings in order (rotor → Headings).
- **Android, Chrome**: the same pages and the menu.
- **Mac, Safari and Firefox**: the header glass, the horizon under the pitch, the case study.

## Checking it from your Mac (read-only)

```bash
curl -sI https://qa.spellcaster.foo/ | grep -iE '^(HTTP|www-authenticate|x-robots-tag)'
curl -sI -u "qa:$(aws ssm get-parameter --profile portfolio-read --region us-east-1 --name /portfolio/qa/basic-auth-password --with-decryption --query Parameter.Value --output text)" https://qa.spellcaster.foo/ | grep -iE '^(HTTP|x-robots-tag)'
AWS_PROFILE=portfolio-read AWS_REGION=us-east-1 python3 -I scripts/ci/leftovers.py --scope qa
```

The first should print `HTTP/2 401`, a `Basic` challenge and `noindex, nofollow`; the second
`HTTP/2 200` and `noindex, nofollow`. With QA down, the first two can't connect, and the last
prints `0 left behind`.

## If QA down leaves something

The check names each thing. Usually a run was stopped halfway, and running QA down again
finishes the job. If it doesn't, sign in as `portfolio-admin` and, from `infra/envs/qa`:

```bash
export AWS_PROFILE=portfolio-admin TF_VAR_account_id=<account id> TF_VAR_origin_access_control_id=<oac id> TF_VAR_basic_auth_sha256=$(printf '0%.0s' {1..64})
terraform init -backend-config="bucket=<state bucket>"
```

(Destroying doesn't use the password, so any 64 hex characters will do.) Then, depending on
what the log says:

- **"Error acquiring the state lock"**: `terraform force-unlock <lock id>`, with the ID from
  the log, then run QA down again.
- **A distribution, function, bucket or record that Terraform doesn't know about** (its state
  was lost): delete it in the console. A distribution has to be disabled first, and that
  takes a few minutes. Records: **Route 53** → **Hosted zones** → `qa.spellcaster.foo`; only
  the A and AAAA records at `qa.spellcaster.foo` belong to QA. Never delete the NS, SOA, TXT,
  MX, CAA or `_dmarc` records, or the `_…` CNAME: bootstrap owns them.

Delete the `.terraform` folder when you're done, then run the check above.

## Changing the password

Make a new long random one, and store it over the old:

```bash
aws ssm put-parameter --profile portfolio-admin --region us-east-1 --name /portfolio/qa/basic-auth-password --type SecureString --overwrite --value "$(openssl rand -base64 30)"
```

The next QA up uses it. QA up refuses a password under 24 characters, or on more than one line.

## Cost

Nothing, in practice. A QA that's up for a day costs cents for the bucket, and CloudFront's
always-free allowance covers its traffic. The hosted zone (bootstrap's) costs $0.50 a month
whether QA is up or not.
