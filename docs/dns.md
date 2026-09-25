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
The QA certificate needs nothing here: its validation record is in the qa zone.

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

## Records for launch (M5)

The apex and `www` point at the production distribution. Add them only after the launch
pull request has merged and its Deploy production job is green (not skipped). Find the
distribution's name (read-only):

```bash
aws sso login --profile portfolio-read
aws cloudfront list-distributions --profile portfolio-read --query "DistributionList.Items[?Aliases.Items[?@=='spellcaster.foo']].DomainName" --output text
```

In Cloudflare: **dash.cloudflare.com** → **spellcaster.foo** → **DNS** → **Records** →
**Add record**, twice:

| Field | The apex | www |
|---|---|---|
| Type | CNAME | CNAME |
| Name | `@` | `www` |
| Target | the distribution's name (`d….cloudfront.net`) | the same |
| Proxy status | DNS only (Cloudflare starts it on Proxied: switch it off) | DNS only |
| TTL | Auto | Auto |

Cloudflare can't put a real CNAME at the apex next to the mail records, so it answers the
`@` record with CloudFront's addresses instead (CNAME flattening). That's expected, and it
leaves MX and the TXT records alone. `www` redirects to `spellcaster.foo` at CloudFront.

**Checking.** Ask Cloudflare's own name server first, which answers at once:

```bash
dig +short A spellcaster.foo @cortney.ns.cloudflare.com
dig +short AAAA spellcaster.foo @cortney.ns.cloudflare.com
```

Expect CloudFront addresses from both. Addresses starting `104.21`, `172.67` or `2606:4700`
are Cloudflare's own: the record is still Proxied. Your own resolver may remember "no such
record" for up to 30 minutes (the zone's negative cache time), so if the next commands fail,
wait and try again before undoing anything:

```bash
curl -sSI https://spellcaster.foo/ | grep -iE '^(HTTP|strict-transport|server|via)'
curl -sSI https://www.spellcaster.foo/ | grep -iE '^(HTTP|location)'
curl -sSI http://spellcaster.foo/ | grep -iE '^(HTTP|location)'
dig +short MX spellcaster.foo
```

Expect `HTTP/2 200`, `server: AmazonS3`, a `via` line ending in `(CloudFront)` and a
`strict-transport-security` header. `server: cloudflare` means a record is still Proxied. Then a
301 from `www` and a 301 from `http`, each to `https://spellcaster.foo/`, and
`0 mailserver.purelymail.com.` unchanged. Last, send a test email to `hello@spellcaster.foo`
from an outside address (Gmail, say), so it really goes through MX.

**Undoing the launch.** Delete the two records. Visitors stop reaching the site once their
resolvers forget the records (minutes, up to the TTL). The distribution itself keeps
answering anyone who connects to it directly and asks for `spellcaster.foo`, as the smoke
test does, so removing the records hides the site but doesn't withdraw anything. To take a
page down, revert its pull request ([aws.md](aws.md)).
