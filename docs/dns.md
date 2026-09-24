# DNS

`spellcaster.foo` stays at Cloudflare, and every record there is added by hand. There's no
Cloudflare API token: a token that can edit the zone could also break mail. Only
`qa.spellcaster.foo` is handed to AWS (a Route 53 zone in the portfolio-site account), so
the QA pipeline can manage its own records.

**Never touch the mail records:** MX, SPF, the Purelymail TXT, `_dmarc`,
`purelymail1._domainkey` to `purelymail3._domainkey`, and `autoconfig`.

Every record below is **DNS only** (grey cloud). Cloudflare's proxy would sit in front of
CloudFront and break certificate validation.

## Records for M4a

The values come from `infra/bootstrap`'s outputs, after the first apply ([aws.md](aws.md)):

```bash
cd infra/bootstrap
AWS_PROFILE=portfolio-admin terraform output cloudflare_qa_name_servers
AWS_PROFILE=portfolio-admin terraform output cloudflare_validation_records
```

In Cloudflare: **dash.cloudflare.com** → **spellcaster.foo** → **DNS** → **Records** →
**Add record**.

**Delegate qa (4 records).** For each of the four name servers:

| Field | Value |
|---|---|
| Type | NS |
| Name | `qa` |
| Nameserver | the name server, without a trailing dot (for example `ns-123.awsdns-45.com`) |
| TTL | Auto |

Don't add a DS record for `qa`. The qa zone isn't signed, and a DS record would make it
fail to resolve.

**Validate the production certificate (2 records).** For each entry in
`cloudflare_validation_records`:

| Field | Value |
|---|---|
| Type | CNAME |
| Name | its `name` (for example `_0a1b2c….www`), which Cloudflare completes with `.spellcaster.foo` |
| Target | its `content` (ends in `acm-validations.aws`) |
| Proxy status | DNS only |
| TTL | Auto |

Keep both CNAMEs for as long as the site exists: ACM renews the certificate through them.

## Checking

```bash
dig +short NS qa.spellcaster.foo
dig +short TXT _dmarc.qa.spellcaster.foo
dig +short MX qa.spellcaster.foo
dig +short CAA qa.spellcaster.foo
```

Expect four `awsdns` servers, `"v=DMARC1; p=reject; …"`, `0 .` and `0 issue "amazon.com"`.
For each validation record, `dig +short CNAME <name>.spellcaster.foo` should print its
target.

## Records for M4b (later)

The apex and `www` point at the production distribution. They're added after production is
live on its `cloudfront.net` name; M4b's steps have the values.
