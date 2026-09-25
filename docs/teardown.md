# Taking the whole site down

The order matters. A name must leave Cloudflare before the distribution that answers for it
goes, or for a while `spellcaster.foo` points at nothing that's yours. Bootstrap goes last,
because it holds the state, the roles and the certificates everything else uses. Nothing
here runs in CI; the production role can't delete the site by design.

Mail is never part of this. Don't touch Cloudflare's MX, SPF, DKIM, DMARC or `autoconfig`
records.

1. **QA.** **Actions** → **QA down** → **Run workflow**. It fails if anything is left
   ([qa.md](qa.md)). Then turn the nightly run off: **Actions** → **QA down** → **⋯** →
   **Disable workflow**.
2. **Cloudflare, the site's names** (only after launch, M5): delete the `@` and `www`
   records that point at CloudFront. Wait for their TTL (5 minutes on Auto).
3. **Production.** Turn deploys off first, so a merge can't rebuild it:
   `gh variable set DEPLOY_ENABLED --body false --repo matt-spellcaster/spellcaster-site-WIP`.
   The production role can't delete the bucket, its old versions or the distribution, so you
   do it as `portfolio-admin`, from `infra/envs/prod`:

   ```bash
   aws sso login --profile portfolio-admin
   export AWS_PROFILE=portfolio-admin TF_VAR_account_id=<account id> TF_VAR_origin_access_control_id=<oac id>
   terraform init -backend-config="bucket=<state bucket>"
   ```

   The bucket keeps every old version, and Terraform won't delete a bucket that isn't empty.
   Empty it in the console: **S3** → the `portfolio-production-…` bucket → **Empty**, then
   type `permanently delete`. Then run `terraform destroy` and read the plan before answering
   `yes`: it should destroy the bucket and its settings, the function, the distribution and
   the two alarms. Disabling the distribution takes 5 to 15 minutes.
4. **Cloudflare, delegation and validation**: delete the 4 `NS` records named `qa` and the 2
   `_…` validation CNAMEs ([dns.md](dns.md)).
5. **Bootstrap.** Two resources refuse to be destroyed (`prevent_destroy`): the state bucket
   and the qa zone. And the state bucket holds bootstrap's own state. So, from
   `infra/bootstrap`:
   1. Move the state back to your Mac: `printf 'terraform {\n  backend "local" {}\n}\n' > override.tf`,
      then `AWS_PROFILE=portfolio-admin terraform init -migrate-state` and answer `yes`.
   2. In `state.tf` and `dns.tf`, delete the two `prevent_destroy = true` lines (don't commit
      that).
   3. Empty the state bucket in the console, the same way as step 3. The qa zone must hold
      only its NS and SOA records before Route 53 deletes it, and Terraform removes the
      others first.
   4. `AWS_PROFILE=portfolio-admin terraform destroy`, and read the plan: 30 to destroy.
6. **By hand**, what Terraform never made: the QA password (`aws ssm delete-parameter
   --profile portfolio-admin --region us-east-1 --name /portfolio/qa/basic-auth-password`),
   and in GitHub the secrets `TF_STATE_BUCKET`, `AWS_ACCOUNT_ID` and each environment's
   `AWS_ROLE_ARN`, and the variables `DEPLOY_ENABLED` and `ORIGIN_ACCESS_CONTROL_ID`.
7. **Check nothing is left**, from the repository root:

   ```bash
   aws sso login --profile portfolio-read
   AWS_PROFILE=portfolio-read AWS_REGION=us-east-1 python3 -I scripts/ci/leftovers.py --scope all
   ```

   It prints `0 left behind`, or lists each distribution, function, bucket, zone,
   certificate, role, OIDC provider, CloudFront policy, alarm, topic or budget of the site's
   that's still there.

The account itself, the organization and Identity Center are outside this repository.
