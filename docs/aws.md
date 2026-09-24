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
| `infra/bootstrap` | You, by hand | The state bucket, GitHub's OIDC provider, the two CI roles, the `qa.spellcaster.foo` zone and its fixed records, the production certificate, the origin access control, both security-header policies, the alerts topic and a $5 budget |
| `infra/envs/prod` (M4b) | CI, `portfolio-prod` role | The production bucket, CloudFront function and distribution, traffic alarms |
| `infra/envs/qa` (M4c) | CI, `portfolio-qa` role | The same for QA, plus its certificate and DNS records; built and torn down on demand |

Bootstrap holds everything that must outlive a deploy, or that CI must never change.

## The CI roles

GitHub Actions reaches AWS through OIDC, so no AWS keys exist anywhere. Each role trusts one
GitHub environment of this repository, matched by the owner's and the repository's numeric
IDs. A renamed repository keeps working, and a new repository with an old name gets nothing.

- **`portfolio-qa`** (the `qa` environment): its own state key, the QA bucket, CloudFront
  resources tagged `Environment=qa`, a certificate for `qa.spellcaster.foo` only, A/AAAA
  records at `qa.spellcaster.foo` and ACM's validation CNAMEs, and the QA password in SSM.
- **`portfolio-prod`** (the `production` environment, main only): its own state key, the
  production bucket, CloudFront resources tagged `Environment=production`, and its alarms.
  It can't delete the distribution, the bucket or old versions of files, and it can't
  touch certificates or DNS.

A separate guardrails policy on each role denies what neither may ever do: IAM,
Organizations, billing, moving a domain between distributions, the shared CloudFront
policies, re-tagging another environment's resources, exportable certificates and hosted
zones.

To check the roles as deployed (read-only access is enough):

```bash
aws sso login --profile portfolio-read
python3 -I scripts/ci/iam_policy_tests.py
```

It checks both trust policies, runs every policy through IAM Access Analyzer, then puts about
90 requests through the IAM policy simulator: what each role may do, what it may not, and
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

Read the plan. It should say `Plan: 28 to add, 0 to change, 0 to destroy`. Then:

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

**4. Confirm the alerts subscription.** AWS emails the alert address a link titled "AWS
Notification - Subscription Confirmation". Click it.

**5. Wait for the certificate.** Usually minutes after the CNAMEs resolve:

```bash
aws acm list-certificates --profile portfolio-read \
  --query "CertificateSummaryList[?DomainName=='spellcaster.foo'].Status"
```

**6. Give GitHub the names it needs.** Each command reads the value from Terraform, so
nothing is printed or pasted. Run them in `infra/bootstrap`:

```bash
AWS_PROFILE=portfolio-admin terraform output -raw state_bucket | gh secret set TF_STATE_BUCKET --repo matt-spellcaster/spellcaster-site-WIP
AWS_PROFILE=portfolio-admin terraform output -raw production_role_arn | gh secret set AWS_ROLE_ARN --env production --repo matt-spellcaster/spellcaster-site-WIP
AWS_PROFILE=portfolio-admin terraform output -raw qa_role_arn | gh secret set AWS_ROLE_ARN --env qa --repo matt-spellcaster/spellcaster-site-WIP
```

The QA password stays in SSM (`/portfolio/qa/basic-auth-password`), not in GitHub.

**7. Check the roles:** `python3 -I scripts/ci/iam_policy_tests.py` (see above).

**Done when** the IAM checks pass, `dig +short NS qa.spellcaster.foo` shows four
`awsdns` servers, `dig +short TXT _dmarc.qa.spellcaster.foo` shows `p=reject`, and the
certificate is `ISSUED`.

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

## Cost

About $0.50 a month for the hosted zone, plus cents for state storage. The certificate,
origin access control, header policies, email alerts and the budget are free at this size.
