"""smoke: each check passes on a correct deployment and names what's wrong on a broken one."""

import contextlib
import hashlib
import io
import ssl
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import smoke
from publish_site import IMMUTABLE, REVALIDATE
from smoke import CBC_CIPHERS, SECURITY_HEADERS, Response, Site

HOST, WWW, EDGE = "spellcaster.foo", "www.spellcaster.foo", "d111111abcdef8.cloudfront.net"
HSTS = SECURITY_HEADERS["strict-transport-security"]
FILES = {
    "index.html": b"<h1>home</h1>",
    "404.html": b"<h1>not found</h1>",
    "projects/demo/index.html": b"<h1>demo</h1>",
    "_astro/small.js": b"x",
    "_astro/big.css": b"body{}" * 400,
}


class FakeEdge:
    """A correct deployment. Tests break one thing at a time."""

    def __init__(self):
        self.overrides = {}
        self.brotli = True
        self.cbc_accepted = False

    def __call__(self, edge, host, path, scheme="https", headers=None):
        assert edge == EDGE
        key = (host, scheme, path, (headers or {}).get("Accept-Encoding"))
        if key in self.overrides:
            return self.overrides[key]
        if scheme == "http":
            return Response(301, {"location": f"https://{host}{path}"}, b"")
        if host != HOST:
            return Response(301, {"location": f"https://{HOST}{path}", "strict-transport-security": HSTS}, b"")
        if path == "/projects/demo":
            return Response(301, {"location": f"https://{HOST}/projects/demo/", "strict-transport-security": HSTS}, b"")
        name = path.lstrip("/") + ("index.html" if path.endswith("/") else "")
        if name not in FILES:
            return Response(404, dict(SECURITY_HEADERS), FILES["404.html"])
        encoding = {"content-encoding": "br"} if self.brotli and (headers or {}).get("Accept-Encoding") == "br" else {}
        asset = name.startswith("_astro/")
        return Response(200, {
            **SECURITY_HEADERS, **encoding,
            "permissions-policy": "camera=(), microphone=()",
            "cache-control": IMMUTABLE if asset else REVALIDATE,
            "content-type": "text/css; charset=utf-8" if name.endswith(".css") else
                            "text/javascript; charset=utf-8" if name.endswith(".js") else "text/html; charset=utf-8",
        }, FILES[name])

    def handshake(self, edge, host, ciphers=None):
        return self.cbc_accepted if ciphers == CBC_CIPHERS else True


class Smoke(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist = Path(tmp.name)
        for name, body in FILES.items():
            (dist / name).parent.mkdir(parents=True, exist_ok=True)
            (dist / name).write_bytes(body)
        self.edge = FakeEdge()
        self.site = Site(HOST, EDGE, [WWW], {n: hashlib.sha256(b).hexdigest() for n, b in FILES.items()}, dist,
                         fetch=self.edge, handshake=self.edge.handshake, policy=lambda: "TLSv1.2_2025")

    def failures(self):
        return {row["check"]: row["problems"] for row in smoke.run_checks(self.site) if not row["ok"]}

    def test_a_correct_deployment_passes_every_check(self):
        self.assertEqual(self.failures(), {})

    def test_a_different_home_page_fails(self):
        self.edge.overrides[(HOST, "https", "/", None)] = Response(200, {}, b"<h1>old build</h1>")
        problems = self.failures()["home page is the tested build, with its headers"]
        self.assertIn("the home page isn't the tested build's index.html", problems)
        self.assertIn("no Permissions-Policy header", problems)

    def test_noindex_on_production_fails_and_is_required_on_qa(self):
        self.assertEqual(smoke.security_headers(Response(200, {**SECURITY_HEADERS, "permissions-policy": "camera=()",
                                                               "x-robots-tag": "noindex, nofollow"}, b""), False),
                         ["x-robots-tag: 'noindex, nofollow' would keep search engines away"])
        self.assertEqual(smoke.security_headers(Response(200, {**SECURITY_HEADERS, "permissions-policy": "camera=()"},
                                                         b""), True),
                         ["x-robots-tag: None, expected 'noindex, nofollow'"])

    def test_www_serving_the_page_instead_of_redirecting_fails(self):
        self.edge.overrides[(WWW, "https", "/", None)] = Response(200, {}, FILES["index.html"])
        self.assertIn(f"{WWW}: status 200, expected 301", self.failures()["other host names redirect"])

    def test_a_redirect_without_hsts_fails(self):
        self.edge.overrides[(HOST, "https", "/projects/demo", None)] = Response(
            301, {"location": f"https://{HOST}/projects/demo/"}, b"")
        self.assertEqual(self.failures()["a page URL without its slash redirects"], ["HSTS on the redirect: None"])

    def test_a_folder_page_that_isnt_rewritten_to_index_fails(self):
        self.edge.overrides[(HOST, "https", "/projects/demo/", None)] = Response(404, dict(SECURITY_HEADERS), FILES["404.html"])
        self.assertEqual(self.failures()["a page in a folder is the tested build"],
                         ["status 404, expected 200", "/projects/demo/ isn't the tested build's projects/demo/index.html"])

    def test_s3_error_instead_of_the_404_page_fails(self):
        self.edge.overrides[(HOST, "https", smoke.MISSING_PAGE, None)] = Response(403, {}, b"<Error>AccessDenied</Error>")
        self.assertEqual(self.failures()["a missing page gets the 404 page"],
                         ["status 403, expected 404", "the body isn't the build's 404.html"])

    def test_largest_asset_is_checked_for_caching_and_compression(self):
        self.edge.overrides[(HOST, "https", "/_astro/big.css", None)] = Response(
            200, {"cache-control": REVALIDATE, "content-type": "text/css; charset=utf-8"}, FILES["_astro/big.css"])
        self.edge.brotli = False
        failures = self.failures()
        self.assertEqual(failures["_astro files are cached for a year"],
                         [f"cache-control: {REVALIDATE!r}, expected {IMMUTABLE!r}"])
        self.assertEqual(failures["brotli compression"], ["none of _astro/big.css, _astro/small.js came back as br"])

    def test_one_uncompressed_file_is_not_a_failure(self):
        # An edge that skipped compressing the largest file once caches it that way.
        self.edge.overrides[(HOST, "https", "/_astro/big.css", "br")] = Response(200, {}, FILES["_astro/big.css"])
        self.assertNotIn("brotli compression", self.failures())

    def test_old_ciphers_or_policy_fail(self):
        self.edge.cbc_accepted = True
        self.site.policy = lambda: "TLSv1.2_2021"
        self.assertEqual(self.failures()["TLS"], [
            "a TLS 1.2 handshake with only CBC ciphers succeeded",
            "the distribution's minimum protocol version is 'TLSv1.2_2021', expected 'TLSv1.2_2025'",
        ])

    def test_ciphers_this_machine_cant_offer_raise_rather_than_pass(self):
        with self.assertRaises(ssl.SSLError):  # before any connection, so no network needed
            smoke.tls_handshake("127.0.0.1", HOST, "NO-SUCH-CIPHER")

    def test_a_network_error_is_a_failed_check(self):
        def unreachable(*args, **kwargs):
            raise TimeoutError("timed out")

        self.site.fetch = unreachable
        failures = self.failures()
        self.assertEqual(failures["http redirects to https"], ["TimeoutError: timed out"])
        self.assertNotIn("TLS", failures)


QA, QA_EDGE = "qa.spellcaster.foo", "d222222abcdef8.cloudfront.net"
AUTH = "Basic cWE6c2VjcmV0"  # qa:secret


class FakeQaEdge(FakeEdge):
    """A correct QA deployment: FakeEdge behind a password, with noindex everywhere."""

    def __init__(self):
        super().__init__()
        self.seen = []  # (scheme, whether the password was sent)
        self.open = False  # a broken QA that forgot its password

    def __call__(self, edge, host, path, scheme="https", headers=None):
        assert edge == QA_EDGE
        headers = dict(headers or {})
        sent = headers.pop("Authorization", None)
        self.seen.append((scheme, sent is not None))
        robots = {"x-robots-tag": "noindex, nofollow"}
        if scheme == "https" and sent != AUTH and not self.open:
            return Response(401, {"www-authenticate": 'Basic realm="QA", charset="UTF-8"',
                                  "strict-transport-security": HSTS, **robots}, b"")
        r = super().__call__(EDGE, "spellcaster.foo" if host == QA else host, path, scheme, headers)
        location = r.headers.get("location", "").replace("https://spellcaster.foo", f"https://{QA}")
        return Response(r.status, {**r.headers, **robots, **({"location": location} if location else {})}, r.body)


class SmokeQa(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist = Path(tmp.name)
        for name, body in FILES.items():
            (dist / name).parent.mkdir(parents=True, exist_ok=True)
            (dist / name).write_bytes(body)
        self.edge = FakeQaEdge()
        self.site = Site(QA, QA_EDGE, [], {n: hashlib.sha256(b).hexdigest() for n, b in FILES.items()}, dist,
                         noindex=True, auth=AUTH, fetch=self.edge, handshake=self.edge.handshake)

    def failures(self):
        return {row["check"]: row["problems"] for row in smoke.run_checks(self.site) if not row["ok"]}

    def test_a_correct_qa_deployment_passes_every_check_including_the_password(self):
        rows = smoke.run_checks(self.site)
        self.assertEqual({r["check"]: r["problems"] for r in rows if not r["ok"]}, {})
        self.assertEqual(rows[0]["check"], "no password, no site")

    def test_the_password_goes_over_https_only(self):
        smoke.run_checks(self.site)
        self.assertIn(("https", True), self.edge.seen)
        self.assertNotIn(("http", True), self.edge.seen)

    def test_a_qa_site_that_forgot_its_password_fails(self):
        self.edge.open = True
        problems = self.failures()["no password, no site"]
        self.assertIn("without a password: status 200, expected 401", problems)
        self.assertIn("without a password: the home page came back", problems)
        self.assertIn("with a wrong password: status 200, expected 401", problems)

    def test_production_runs_no_password_check(self):
        site = Site(HOST, EDGE, [WWW], {}, Path("."))
        self.assertNotIn("no password, no site", [name for name, _ in smoke.CHECKS])
        self.assertIsNone(site.auth)

    def test_the_header_comes_only_from_the_environment(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            smoke.main(["--host", QA, "--edge", QA_EDGE, "--dist", ".", "--manifest", "m.json",
                        "--auth-header-env", "SMOKE_TEST_NO_SUCH_VARIABLE"])


if __name__ == "__main__":
    unittest.main()
