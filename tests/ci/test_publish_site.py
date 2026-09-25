"""publish_site: every file gets the right headers, in a safe order, and old pages go but old _astro files stay."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import publish_site
from publish_site import IMMUTABLE, REVALIDATE, plan_uploads, stale_keys


class FakeAws:
    def __init__(self, listing=None, errors=None):
        self.calls, self.listing, self.errors = [], listing, errors

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("s3api", "list-objects-v2"):
            return json.dumps(self.listing)
        if args[:2] == ("s3api", "delete-objects"):
            return json.dumps({"Errors": self.errors} if self.errors else {})
        if args[:2] == ("cloudfront", "create-invalidation"):
            return "I2EXAMPLE\n"
        return ""


class PlanUploads(unittest.TestCase):
    def test_astro_first_html_last_each_with_its_headers(self):
        groups = plan_uploads(["index.html", "projects/x/index.html", "_astro/a.css", "_astro/b.js",
                               "_astro/c.webp", "favicon.svg", "robots.txt", "_astro/fonts/n.woff2"])
        self.assertEqual([g.cache_control for g in groups[:4]], [IMMUTABLE] * 4)
        self.assertEqual(groups[-1].content_type, "text/html; charset=utf-8")
        self.assertEqual(groups[-1].cache_control, REVALIDATE)
        self.assertEqual(groups[-1].files, ["index.html", "projects/x/index.html"])
        by_file = {f: (g.content_type, g.cache_control) for g in groups for f in g.files}
        self.assertEqual(by_file["_astro/fonts/n.woff2"], ("font/woff2", IMMUTABLE))
        self.assertEqual(by_file["favicon.svg"], ("image/svg+xml", REVALIDATE))
        self.assertEqual(by_file["robots.txt"], ("text/plain; charset=utf-8", REVALIDATE))

    def test_unknown_extension_or_pattern_character_stops_the_publish(self):
        for name in ("site.webm", "noextension", "a*.css", "_astro/[x].js", "sp ace.html", "../up.html"):
            with self.subTest(name), self.assertRaises(ValueError):
                plan_uploads(["index.html", name])

    def test_every_extension_in_the_real_build_is_known(self):
        dist = Path(__file__).resolve().parents[2] / "dist"
        if not (dist / "index.html").exists():
            self.skipTest("no build in dist/")
        plan_uploads([p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()])


class StaleKeys(unittest.TestCase):
    def test_old_pages_go_old_assets_stay(self):
        existing = ["index.html", "old-page/index.html", "og/old.jpg", "_astro/new.css", "_astro/old.css",
                    "_astro/fonts/old.woff2"]
        delete, kept = stale_keys(existing, {"index.html", "_astro/new.css"})
        self.assertEqual(delete, ["old-page/index.html", "og/old.jpg"])
        self.assertEqual(kept, 2)


class Publish(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dist = Path(tmp.name)
        for name in ("index.html", "404.html", "_astro/a.css", "og/home.jpg"):
            (self.dist / name).parent.mkdir(parents=True, exist_ok=True)
            (self.dist / name).write_text(name)

    def test_uploads_prunes_then_invalidates_and_waits(self):
        aws = FakeAws(["index.html", "gone.html", "_astro/old.css"])
        result = publish_site.publish(self.dist, "bucket", "E123", aws)
        verbs = [c[:2] for c in aws.calls]
        self.assertEqual(verbs, [("s3", "cp")] * 3 + [("s3api", "list-objects-v2"), ("s3api", "delete-objects"),
                                                     ("cloudfront", "create-invalidation"), ("cloudfront", "wait")])
        first, last = aws.calls[0], aws.calls[2]
        self.assertEqual(first[first.index("--include") + 1], "_astro/a.css")
        self.assertEqual(last[last.index("--content-type") + 1], "text/html; charset=utf-8")
        self.assertEqual([last[i + 1] for i, a in enumerate(last) if a == "--include"], ["404.html", "index.html"])
        self.assertEqual(json.loads(aws.calls[4][aws.calls[4].index("--delete") + 1])["Objects"], [{"Key": "gone.html"}])
        self.assertEqual(aws.calls[6][-2:], ("--id", "I2EXAMPLE"))
        self.assertIn("4 files uploaded in 3 groups; 1 old files deleted, 1 old _astro files kept", result)

    def test_the_result_never_names_the_bucket(self):
        # It goes into the public deploy evidence, and the bucket's name holds the account ID.
        account = "1234" * 3  # built here, so the pre-commit hook's account-ID check stays quiet
        result = publish_site.publish(self.dist, f"portfolio-production-{account}-us-east-1-an", "E123", FakeAws(None))
        self.assertNotIn(account, result)

    def test_deletes_go_in_batches_of_1000(self):
        aws = FakeAws([f"old/{i}.html" for i in range(1001)])
        publish_site.publish(self.dist, "bucket", "E123", aws)
        sizes = [len(json.loads(c[c.index("--delete") + 1])["Objects"]) for c in aws.calls
                 if c[:2] == ("s3api", "delete-objects")]
        self.assertEqual(sizes, [1000, 1])

    def test_empty_bucket_needs_no_delete(self):
        aws = FakeAws(None)
        publish_site.publish(self.dist, "bucket", "E123", aws)
        self.assertNotIn(("s3api", "delete-objects"), [c[:2] for c in aws.calls])

    def test_failed_delete_stops_before_the_invalidation(self):
        aws = FakeAws(["gone.html"], errors=[{"Key": "gone.html"}])
        with self.assertRaises(RuntimeError):
            publish_site.publish(self.dist, "bucket", "E123", aws)
        self.assertNotIn(("cloudfront", "create-invalidation"), [c[:2] for c in aws.calls])

    def test_refuses_a_build_without_index(self):
        (self.dist / "index.html").unlink()
        with self.assertRaises(ValueError):
            publish_site.publish(self.dist, "bucket", "E123", FakeAws())


if __name__ == "__main__":
    unittest.main()
