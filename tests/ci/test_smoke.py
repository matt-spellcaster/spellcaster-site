"""smoke: each check passes on a correct deployment and names what's wrong on a broken one."""

import hashlib
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        sleep = mock.patch("smoke.time.sleep")  # check_brotli waits between tries
        sleep.start()
        self.addCleanup(sleep.stop)
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
        self.assertEqual(smoke.check_brotli(self.site, tries=2, wait=0),
                         ["_astro/big.css came back uncompressed, not br, 2 times"])

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


if __name__ == "__main__":
    unittest.main()
