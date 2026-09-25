# AWS

The site runs in one AWS account, `portfolio-site`, in its own organization. Everything is
in us-east-1, because CloudFront only uses certificates from there. Account IDs never go in
this repository: they live in your AWS profiles, in git-ignored files and in GitHub secrets.

| Profile | Used for |
|---|---|
| `portfolio-admin` | Applying `infra/bootstrap` by hand |
| `portfolio-read` | Looking around, and `scripts/ci/iam_policy_tests.py` |

## What's where

| Terraform root | Applied by | Holds |
|---|---|---|
| `infra/bootstrap` | You, by hand | The state bucket, GitHub's OIDC provider, the two CI roles, the `qa.spellcaster.foo` zone and its fixed records, both certificates (production and QA), the origin access control, both security-header policies, the alerts topic and a $5 budget |
| `infra/envs/prod` (M4b) | CI, `portfolio-prod` role | The production bucket, CloudFront function and distribution, traffic alarms |
| `infra/envs/qa` (M4c) | CI, `portfolio-qa` role | The same for QA, plus its DNS record; built and torn down on demand |

Bootstrap holds everything that must outlive a deploy, or that CI must never change. Both
`infra/envs` roots build their site with the same module, `infra/modules/site`.

## The CI roles

GitHub Actions reaches AWS through OIDC, so no AWS keys exist anywhere. Each role trusts one
GitHub environment of this repository, matched by the owner's and the repository's numeric
IDs. A renamed repository keeps working, and a new repository with an old name gets nothing.

- **`portfolio-qa`** (the `qa` environment): its own state key, the QA bucket, CloudFront
  resources tagged `Environment=qa`, A/AAAA records at `qa.spellcaster.foo`, and the QA
  password in SSM.
- **`portfolio-prod`** (the `production` environment, main only): its own state key, the
  production bucket, CloudFront resources tagged `Environment=production`, and its alarms.
  It can't delete the distribution, the bucket or old versions of files, or set a lifecycle
  rule that would expire them, and it can't touch DNS. (It can pause versioning, which keeps
  every version made until then.)

A separate guardrails policy on each role denies what neither may ever do: IAM,
Organizations, billing, moving a domain between distributions, the shared CloudFront
policies, moving a resource across the `Environment` tag in either direction, any change to
a certificate (bootstrap issues both), and hosted zones.

Two things IAM can't fence:

- **A distribution's domain names and certificate.** No condition key covers them, so a role
  could put a name nobody holds yet on its own distribution. CloudFront refuses a name that
  another distribution already holds. So production takes `spellcaster.foo` and `www` first
  (M4b), and the `qa` environment stays locked until M4c (bring-up step 6).
- **What a bucket policy says.** Each role writes its own bucket's policy, so it could grant
  another AWS account access. That isn't "public", so the account's public access block
  allows it. Accepted: only this repository's CI can use the roles.

To check the roles as deployed (read-only access is enough):

```bash
aws sso login --profile portfolio-read
python3 -I scripts/ci/iam_policy_tests.py
```

It checks both trust policies, runs every policy through IAM Access Analyzer, then puts 101
requests through the IAM policy simulator: what each role may do, what it may not, and
what a guardrail must block.

## Bring-up (M4a, one sitting)

Do steps 1 to 4 on the same day: ACM gives up on validation after 72 hours.

**1. Apply bootstrap with local state.** The state bucket doesn't exist yet, so the first run
keeps state on your Mac. `override.tf` is git-ignored.

```bash
aws sso login --profile portfolio-admin
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars
```

Fill in `terraform.tfvars`: the account ID and the address for alerts. Then:

```bash
printf 'terraform {\n  backend "local" {}\n}\n' > override.tf
AWS_PROFILE=portfolio-admin terraform init
AWS_PROFILE=portfolio-admin terraform plan -out=tfplan
```

Read the plan. It should say `Plan: 30 to add, 0 to change, 0 to destroy`. Then:

```bash
AWS_PROFILE=portfolio-admin terraform apply tfplan
```

**2. Move the state into the bucket.**

```bash
cp backend.hcl.example backend.hcl
terraform output -raw state_bucket
```

In `backend.hcl`, replace the bucket name with the name that printed. Then:

```bash
rm override.tf tfplan
AWS_PROFILE=portfolio-admin terraform init -backend-config=backend.hcl -migrate-state
AWS_PROFILE=portfolio-admin terraform plan
```

Answer `yes` to copy the state. The plan should say "No changes". Then delete the local
copies: `rm terraform.tfstate terraform.tfstate.backup`.

**3. Add the Cloudflare records** in [dns.md](dns.md): 4 NS records for `qa`, and the 2
validation CNAMEs.

**4. Confirm the alerts subscription from the command line.** AWS emails the alert address
"AWS Notification - Subscription Confirmation". Don't click its link: a subscription confirmed
by a click can be cancelled by anyone who clicks the unsubscribe link in any alert. Copy the
link instead. The token is the long value after `Token=`, up to the next `&`. Then, still in
`infra/bootstrap`:

```bash
AWS_PROFILE=portfolio-admin aws sns confirm-subscription --region us-east-1 \
  --topic-arn "$(AWS_PROFILE=portfolio-admin terraform output -raw alerts_topic_arn)" \
  --token <token> --authenticate-on-unsubscribe true
```

It prints the subscription's ARN. Check the protection took: this should print `true`.

```bash
AWS_PROFILE=portfolio-admin aws sns get-subscription-attributes --region us-east-1 \
  --subscription-arn <the ARN it printed> --query Attributes.ConfirmationWasAuthenticated
```

**5. Wait for both certificates.** Usually minutes after the Cloudflare records resolve. The
QA certificate validates by itself once the `qa` NS records are in:

```bash
aws acm list-certificates --profile portfolio-read --region us-east-1 \
  --query "CertificateSummaryList[].[DomainName,Status]"
```

**6. Give GitHub the names it needs.** Each command reads the value from Terraform, so
nothing is printed or pasted. Run them in `infra/bootstrap`:

```bash
AWS_PROFILE=portfolio-admin terraform output -raw state_bucket | gh secret set TF_STATE_BUCKET --repo matt-spellcaster/spellcaster-site-WIP
AWS_PROFILE=portfolio-admin terraform output -raw production_role_arn | gh secret set AWS_ROLE_ARN --env production --repo matt-spellcaster/spellcaster-site-WIP
aws sts get-caller-identity --profile portfolio-admin --query Account --output text | gh secret set AWS_ACCOUNT_ID --repo matt-spellcaster/spellcaster-site-WIP
```

`AWS_ACCOUNT_ID` is there so the jobs that use AWS can mask it in their logs
(`::add-mask::`). Bucket names and AWS error messages contain it, and GitHub masks only
whole secrets, so a masked role ARN doesn't hide it.

Then lock the `qa` environment, so no branch can use it (and so assume `portfolio-qa`) until
M4c. By then production's distribution holds `spellcaster.foo` and `www` (see "Two things
IAM can't fence" above). Keeping the role ARN out of GitHub isn't enough on its own, because
the ARN can be worked out.

```bash
echo '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' \
  | gh api -X PUT repos/matt-spellcaster/spellcaster-site-WIP/environments/qa --input -
gh api repos/matt-spellcaster/spellcaster-site-WIP/environments/qa/deployment-branch-policies --jq .total_count
```

The second command should print `0`: custom branch rules are on, and none exist, so no
branch matches. M4c adds the `qa` role ARN and the branches that may deploy. The QA password
stays in SSM (`/portfolio/qa/basic-auth-password`), not in GitHub.

**7. Check the roles,** from the repository root: `cd ../..`, then
`python3 -I scripts/ci/iam_policy_tests.py` (see above).

**Done when** the IAM checks pass, `dig +short NS qa.spellcaster.foo` shows four
`awsdns` servers, `dig +short TXT _dmarc.qa.spellcaster.foo` shows `p=reject`, and both
certificates are `ISSUED`.

## Production deploys (M4b)

Every merge to `main` that passes its checks runs **Deploy production**, once you approve
it on the run's page (you're the `production` environment's reviewer). As `portfolio-prod`,
it:

1. Stops if `main` has moved on while it waited, so an older commit never replaces a newer one.
2. Checks the site it downloaded is the one the Build job hashed and E2E tested.
3. Plans `infra/envs/prod`, and stops if the plan would remove the bucket or the
   distribution, or remove or turn off the bucket's versioning, public access block or
   policy. The run's summary lists each change by name, with no values.
4. Applies the plan, publishes the site (`scripts/ci/publish_site.py`) and clears
   CloudFront's cache.
5. Runs the smoke test (`scripts/ci/smoke.py`) against the distribution's `cloudfront.net`
   name. It asks for `spellcaster.foo` the way a browser will, so it works before DNS
   points there.
6. Saves what happened as `deploy-evidence-<sha>` (90 days).

Terraform's own output never reaches the public log: only its summary line, the list of
changes and any error.

**Turning it on.** Once, from `infra/bootstrap`:

```bash
AWS_PROFILE=portfolio-admin terraform output -json shared | jq -r .origin_access_control_id | gh variable set ORIGIN_ACCESS_CONTROL_ID --repo matt-spellcaster/spellcaster-site-WIP
gh variable set DEPLOY_ENABLED --body true --repo matt-spellcaster/spellcaster-site-WIP
```

The origin access control's ID isn't secret, and Terraform has no way to look one up by
name, so it's a variable. The first deploy then runs on the next merge to `main`. Creating
the distribution takes 5 to 15 minutes.

**Checking it** (read-only):

```bash
aws cloudfront list-distributions --profile portfolio-read --query "DistributionList.Items[].[Id,DomainName,Aliases.Items[0],Status]" --output table
curl -sI https://<distribution>.cloudfront.net/ | grep -iE '^(HTTP|location)'
curl -sI --connect-to spellcaster.foo:443:<distribution>.cloudfront.net:443 https://spellcaster.foo/ | head -1
aws cloudwatch describe-alarms --profile portfolio-read --alarm-name-prefix portfolio-production- --query "MetricAlarms[].[AlarmName,StateValue]" --output table
```

The first `curl` should print a 301 to `https://spellcaster.foo/`, the second `HTTP/2 200`,
and there should be two alarms. Nobody sees the site at `spellcaster.foo` until the
Cloudflare records at launch (M5, [dns.md](dns.md)).

**Undoing a deploy.** Revert the pull request. The merge deploys the reverted site. The
production bucket keeps every old version of every file, and the role can't delete them.

**If a deploy stops halfway.** Most often the first one, while CloudFront creates the
distribution. The role can't clean up after it, so you do it as `portfolio-admin`, from
`infra/envs/prod`:

```bash
export AWS_PROFILE=portfolio-admin TF_VAR_account_id=<account id> TF_VAR_origin_access_control_id=<oac id>
terraform init -backend-config="bucket=<state bucket>"
```

Then, depending on what the next run's log says:

- **"Error acquiring the state lock"**: the stopped run still holds the lock. Run
  `terraform force-unlock <lock id>` with the ID from the log.
- **The plan guard refuses `module.site.aws_cloudfront_distribution.site (replace, tainted)`**:
  the distribution was made, but Terraform stopped waiting for it. Once the first `aws
  cloudfront list-distributions` command above shows it `Deployed`, run
  `terraform untaint module.site.aws_cloudfront_distribution.site`.
- **`CNAMEAlreadyExists`**: a distribution Terraform doesn't know about holds the names. Find
  its ID with the same command, then run
  `terraform import module.site.aws_cloudfront_distribution.site <distribution id>`.

Then rerun the failed job from the run's page. Delete the `.terraform` folder when you're done.

## Changing bootstrap later

Always plan first, from `infra/bootstrap` with `backend.hcl` in place:

```bash
aws sso login --profile portfolio-admin
AWS_PROFILE=portfolio-admin terraform init -backend-config=backend.hcl
AWS_PROFILE=portfolio-admin terraform plan -out=tfplan
AWS_PROFILE=portfolio-admin terraform apply tfplan
```

The state bucket and the qa zone have `prevent_destroy`, so a plan that would delete either
one fails. After any change to `ci_roles.tf`, run the IAM checks again.

## Known limits

What the M4a review left open. `infra/envs/prod` (M4b) handles the first two; `infra/envs/qa`
(M4c) must do the same.

- **A CloudFront resource without an `Environment` tag can be claimed.** Either role may tag
  one as its own, then change or delete it. Everything bootstrap makes carries the tag. Keep
  it that way: every distribution and function in `infra/envs` gets its environment's tag
  (the provider's `default_tags` do this).
- **Replacing a certificate takes two applies.** Bootstrap makes the new certificate before
  deleting the old one, but AWS won't delete a certificate CloudFront still uses, so that
  apply stops with an error. Apply `infra/envs` to move the distribution to the new
  certificate, then apply bootstrap again. For this to work, `infra/envs` must look the
  certificate up with `most_recent = true`.
- **Checkov's dependencies wait 7 days, but aren't locked.** CI installs only releases at
  least a week old, but the exact set can change from day to day. A new `CHECKOV_VERSION`
  also has to be a week old, or the job fails.
- **Production can read any CloudFront function** (`cloudfront:Get*`). If M4c checks the QA
  password in a function, the function holds only a SHA-256 hash of it. So make the password
  long and random (for example `openssl rand -base64 24`), so the hash can't be guessed back.

## Cost

About $0.50 a month for the hosted zone, plus cents for state storage. The certificate,
origin access control, header policies, email alerts and the budget are free at this size.

Production adds cents for the bucket. CloudFront's always-free allowance covers 1 TB, 10
million requests and 2 million function runs a month, and the first 10 alarms are free. The
traffic alarms go off long before the site could use that allowance up.
