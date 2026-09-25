"""Smoke-test a deployed site through its CloudFront name, before or after DNS points there.

    python3 scripts/ci/smoke.py --host spellcaster.foo --redirect-host www.spellcaster.foo \
        --edge dxxxx.cloudfront.net --dist site/dist --manifest site/dist-manifest.json \
        --distribution-id <id> --out results/smoke.json

Every request goes to --edge but names --host, in TLS and in the Host header, so it sees what
a visitor will once DNS points --host there. It checks that the home page and a page in a
folder are the tested build's own files, the security headers, caching, compression, every redirect (other
host names, http, a page URL without its slash), the 404 page, and TLS: modern TLS 1.2
works, the old CBC ciphers don't, and the distribution's policy is TLSv1.2_2025.

On QA (--noindex --auth-header-env QA_AUTH_HEADER) every HTTPS request carries the
Authorization header from that environment variable, never from the command line, and never
over plain http. It also checks that a request without it, or with a wrong one, gets 401.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from publish_site import CONTENT_TYPES, IMMUTABLE, REVALIDATE  # same folder

# From bootstrap's header policies (infra/bootstrap/cloudfront.tf).
SECURITY_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "content-security-policy": "frame-ancestors 'none'",
}
TLS_POLICY = "TLSv1.2_2025"
# TLS 1.2 ciphers that TLSv1.2_2021 and later refuse: CBC mode, with SHA-1 or SHA-2 MACs.
CBC_CIPHERS = "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384"
MISSING_PAGE = "/smoke-test-no-such-page/"
TIMEOUT = 15


@dataclass
class Response:
    status: int
    headers: dict[str, str]  # names in lower case
    body: bytes


def fetch(edge: str, host: str, path: str, scheme: str = "https", headers: dict[str, str] | None = None) -> Response:
    """GET path from edge, naming host. Redirects are returned, not followed."""
    if scheme == "https":
        sock = socket.create_connection((edge, 443), timeout=TIMEOUT)
        conn = http.client.HTTPConnection(host, 443, timeout=TIMEOUT)
        conn.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    else:
        conn = http.client.HTTPConnection(edge, 80, timeout=TIMEOUT)
    try:
        conn.request("GET", path, headers={"Host": host, "Accept-Encoding": "identity",
                                           "User-Agent": "spellcaster-smoke-test", **(headers or {})})
        r = conn.getresponse()
        return Response(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
    finally:
        conn.close()


def tls_handshake(edge: str, host: str, ciphers: str | None = None) -> bool:
    """Whether edge completes a TLS 1.2 handshake for host, offering only these ciphers."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    if ciphers:
        ctx.set_ciphers(ciphers)  # raises if this machine can't offer any of them: not a pass
    try:
        with socket.create_connection((edge, 443), timeout=TIMEOUT) as sock, \
                ctx.wrap_socket(sock, server_hostname=host):
            return True
    except ssl.SSLError:
        return False


def tls_policy(distribution_id: str) -> str:
    return subprocess.run(
        ["aws", "cloudfront", "get-distribution-config", "--id", distribution_id, "--output", "text",
         "--query", "DistributionConfig.ViewerCertificate.MinimumProtocolVersion"],
        check=True, capture_output=True, text=True).stdout.strip()


@dataclass
class Site:
    host: str
    edge: str
    redirect_hosts: list[str]
    files: dict[str, str]  # the manifest: path -> sha256
    dist: Path
    noindex: bool = False
    auth: str | None = None  # QA's Authorization header
    fetch: Callable[..., Response] = fetch
    handshake: Callable[..., bool] = tls_handshake
    policy: Callable[[], str] | None = None

    def get(self, path: str, host: str | None = None, auth: bool = True, **kwargs) -> Response:
        """GET path, with the password on QA unless auth is False. Never over plain http, where
        anyone on the way could read it: CloudFront redirects http before the function asks."""
        if self.auth and auth and kwargs.get("scheme", "https") == "https":
            kwargs["headers"] = {**kwargs.get("headers", {}), "Authorization": self.auth}
        return self.fetch(self.edge, host or self.host, path, **kwargs)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def status(r: Response, expected: int) -> list[str]:
    return [] if r.status == expected else [f"status {r.status}, expected {expected}"]


def redirect(r: Response, location: str) -> list[str]:
    problems = status(r, 301)
    if r.headers.get("location") != location:
        problems.append(f"redirects to {r.headers.get('location')!r}, expected {location!r}")
    if r.headers.get("strict-transport-security") != SECURITY_HEADERS["strict-transport-security"]:
        problems.append(f"HSTS on the redirect: {r.headers.get('strict-transport-security')!r}")
    return problems


def security_headers(r: Response, noindex: bool) -> list[str]:
    problems = [f"{name}: {r.headers.get(name)!r}, expected {value!r}"
                for name, value in SECURITY_HEADERS.items() if r.headers.get(name) != value]
    if "camera=()" not in r.headers.get("permissions-policy", ""):
        problems.append("no Permissions-Policy header")
    robots = r.headers.get("x-robots-tag")
    if noindex and robots != "noindex, nofollow":
        problems.append(f"x-robots-tag: {robots!r}, expected 'noindex, nofollow'")
    if not noindex and robots is not None:
        problems.append(f"x-robots-tag: {robots!r} would keep search engines away")
    return problems


def check_home(site: Site) -> list[str]:
    r = site.get("/")
    problems = status(r, 200)
    if sha256(r.body) != site.files["index.html"]:
        problems.append("the home page isn't the tested build's index.html")
    if r.headers.get("cache-control") != REVALIDATE:
        problems.append(f"cache-control: {r.headers.get('cache-control')!r}, expected {REVALIDATE!r}")
    if r.headers.get("content-type") != CONTENT_TYPES[".html"]:
        problems.append(f"content-type: {r.headers.get('content-type')!r}")
    return problems + security_headers(r, site.noindex)


def folder_page(site: Site) -> str:
    """The first page in a folder, like projects/x: the home page alone can't show the index.html
    rewrite works, because CloudFront's default root object serves / without it."""
    pages = sorted(m[1] for f in site.files if (m := re.fullmatch(r"(.+)/index\.html", f)))
    if not pages:
        raise ValueError("the build has no page in a folder to try")
    return pages[0]


def check_page(site: Site) -> list[str]:
    page = folder_page(site)
    r = site.get(f"/{page}/")
    problems = status(r, 200)
    if sha256(r.body) != site.files[f"{page}/index.html"]:
        problems.append(f"/{page}/ isn't the tested build's {page}/index.html")
    return problems


def check_page_without_slash(site: Site) -> list[str]:
    page = folder_page(site)
    return redirect(site.get(f"/{page}"), f"https://{site.host}/{page}/")


def check_missing_page(site: Site) -> list[str]:
    r = site.get(MISSING_PAGE)
    problems = status(r, 404)
    if sha256(r.body) != site.files["404.html"]:
        problems.append("the body isn't the build's 404.html")
    return problems


def check_password(site: Site) -> list[str]:
    """QA only: no password, or a wrong one, gets 401 with noindex and nothing else."""
    wrong = "Basic " + base64.b64encode(b"qa:not-the-password").decode()
    problems = []
    for label, headers in (("without a password", {}), ("with a wrong password", {"Authorization": wrong})):
        r = site.get("/", auth=False, headers=headers)
        problems += [f"{label}: {p}" for p in status(r, 401)]
        if not r.headers.get("www-authenticate", "").startswith("Basic "):
            problems.append(f"{label}: www-authenticate {r.headers.get('www-authenticate')!r}")
        if r.headers.get("x-robots-tag") != "noindex, nofollow":
            problems.append(f"{label}: x-robots-tag {r.headers.get('x-robots-tag')!r}")
        if r.headers.get("strict-transport-security") != SECURITY_HEADERS["strict-transport-security"]:
            problems.append(f"{label}: HSTS {r.headers.get('strict-transport-security')!r}")
        if sha256(r.body) == site.files["index.html"]:
            problems.append(f"{label}: the home page came back")
    return problems


def check_http(site: Site) -> list[str]:
    r = site.get("/", scheme="http")
    problems = status(r, 301)
    if r.headers.get("location") != f"https://{site.host}/":
        problems.append(f"redirects to {r.headers.get('location')!r}")
    return problems


def check_other_hosts(site: Site) -> list[str]:
    return [f"{h}: {p}" for h in [*site.redirect_hosts, site.edge]
            for p in redirect(site.get("/", host=h), f"https://{site.host}/")]


def assets_by_size(site: Site, suffixes: tuple[str, ...]) -> list[str]:
    """The build's _astro files with these suffixes, largest first."""
    assets = [f for f in site.files if f.startswith("_astro/") and f.endswith(suffixes)]
    if not assets:
        raise ValueError(f"the build has no _astro file ending in {'/'.join(suffixes)}")
    return sorted(assets, key=lambda f: ((site.dist / f).stat().st_size, f), reverse=True)


def check_asset(site: Site) -> list[str]:
    name = assets_by_size(site, (".css", ".js"))[0]
    r = site.get(f"/{name}")
    problems = status(r, 200)
    if sha256(r.body) != site.files[name]:
        problems.append(f"{name} isn't the tested build's")
    if r.headers.get("cache-control") != IMMUTABLE:
        problems.append(f"cache-control: {r.headers.get('cache-control')!r}, expected {IMMUTABLE!r}")
    if r.headers.get("content-type") != CONTENT_TYPES[PurePosixPath(name).suffix]:
        problems.append(f"content-type: {r.headers.get('content-type')!r}")
    return problems


def check_brotli(site: Site) -> list[str]:
    # CloudFront may skip compressing when an edge is busy, and then caches the uncompressed copy,
    # so asking again for the same file proves nothing. Each try is a different file instead.
    names = assets_by_size(site, (".css", ".js"))
    for name in names:
        if site.get(f"/{name}", headers={"Accept-Encoding": "br"}).headers.get("content-encoding") == "br":
            return []
    return [f"none of {', '.join(names)} came back as br"]


def check_tls(site: Site) -> list[str]:
    problems = []
    if not site.handshake(site.edge, site.host):
        problems.append("a modern TLS 1.2 handshake failed")
    if site.handshake(site.edge, site.host, CBC_CIPHERS):
        problems.append("a TLS 1.2 handshake with only CBC ciphers succeeded")
    if site.policy and (policy := site.policy()) != TLS_POLICY:
        problems.append(f"the distribution's minimum protocol version is {policy!r}, expected {TLS_POLICY!r}")
    return problems


CHECKS = [
    ("home page is the tested build, with its headers", check_home),
    ("a page in a folder is the tested build", check_page),
    ("a page URL without its slash redirects", check_page_without_slash),
    ("a missing page gets the 404 page", check_missing_page),
    ("http redirects to https", check_http),
    ("other host names redirect", check_other_hosts),
    ("_astro files are cached for a year", check_asset),
    ("brotli compression", check_brotli),
    ("TLS", check_tls),
]
PASSWORD_CHECK = ("no password, no site", check_password)


def run_checks(site: Site) -> list[dict]:
    rows = []
    for name, check in ([PASSWORD_CHECK] if site.auth else []) + CHECKS:
        try:
            problems = check(site)
        except Exception as e:  # a network error is a failed check, not a crash
            problems = [f"{type(e).__name__}: {e}"]
        rows.append({"check": name, "ok": not problems, "problems": problems})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", required=True, help="the site's name, e.g. spellcaster.foo")
    p.add_argument("--redirect-host", action="append", default=[], help="another name that must redirect (repeatable)")
    p.add_argument("--edge", required=True, help="the distribution's dxxxx.cloudfront.net name")
    p.add_argument("--dist", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--distribution-id", help="also check the TLS policy through the CloudFront API")
    p.add_argument("--noindex", action="store_true", help="expect X-Robots-Tag: noindex (QA)")
    p.add_argument("--auth-header-env", metavar="NAME",
                   help="send the Authorization header held in this environment variable, and check 401 without it (QA)")
    p.add_argument("--out", type=Path, help="write the results here as JSON")
    args = p.parse_args(argv)

    auth = None
    if args.auth_header_env:
        auth = os.environ.get(args.auth_header_env)
        if not auth:
            p.error(f"--auth-header-env: {args.auth_header_env} is empty or not set")
    site = Site(args.host, args.edge, args.redirect_host, json.loads(args.manifest.read_text())["files"], args.dist,
                args.noindex, auth, policy=(lambda: tls_policy(args.distribution_id)) if args.distribution_id else None)
    rows = run_checks(site)
    for row in rows:
        print(f"{'ok  ' if row['ok'] else 'FAIL'}  {row['check']}")
        for problem in row["problems"]:
            print(f"      {problem}", file=sys.stderr)
    failed = sum(not row["ok"] for row in rows)
    print(f"{len(rows)} checks, {failed} failed")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"host": args.host, "checks": rows}, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
