"""build_evidence: the summary's verdict and the manifest of the evidence bundle."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import build_evidence
import record
from build_evidence import summarize


def records(**codes):
    return {check: record.build_record(check, code, check.title(), ["SOC 2 CC8.1"], "tool", "detail", env={})
            for check, code in codes.items()}


class Summarize(unittest.TestCase):
    def test_all_expected_present_and_passing(self):
        text, ok = summarize(records(build=0, e2e=0), ["build", "e2e"], {})
        self.assertTrue(ok)
        self.assertIn("all checks passed", text)
        self.assertEqual(text.count("✅ pass"), 2)

    def test_missing_expected_check(self):
        text, ok = summarize(records(build=0), ["build", "e2e"], {})
        self.assertFalse(ok)
        self.assertIn("| ❌ missing | e2e |", text)
        self.assertIn("at least one check failed", text)

    def test_failing_expected_check(self):
        text, ok = summarize(records(build=0, e2e=1), ["build", "e2e"], {})
        self.assertFalse(ok)
        self.assertIn("| ❌ fail | E2E |", text)

    def test_unexpected_extra_check(self):
        self.assertFalse(summarize(records(build=0, extra=1), ["build"], {})[1])
        self.assertTrue(summarize(records(build=0, extra=0), ["build"], {})[1])


class Main(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.results, self.out = Path(tmp.name) / "results", Path(tmp.name) / "evidence"
        with contextlib.redirect_stdout(io.StringIO()):
            record.main(["build", "0", "--title", "Build", "--out", str(self.results / "result-build")])
            record.main(["e2e", "0", "--title", "E2E", "--out", str(self.results / "result-e2e")])
        (self.results / "result-build" / "lockfile.txt").write_text("0 problems\n")

    def build(self, *expect):
        argv = [str(self.results), str(self.out)] + [a for c in expect for a in ("--expect", c)]
        with contextlib.redirect_stdout(io.StringIO()):
            code = build_evidence.main(argv)
        return code, json.loads((self.out / "manifest.json").read_text())

    def test_manifest_hashes_every_file_but_itself(self):
        self.out.mkdir()
        (self.out / "stale.txt").write_text("from an earlier run")
        code, manifest = self.build("build", "e2e")
        self.assertEqual(code, 0)
        self.assertTrue(manifest["all_passed"])
        self.assertEqual(manifest["missing"], [])
        on_disk = {p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual(set(manifest["files"]), on_disk - {"manifest.json"})
        self.assertIn("summary.md", manifest["files"])
        self.assertIn("result-build/lockfile.txt", manifest["files"])
        self.assertNotIn("stale.txt", manifest["files"])
        for name, digest in manifest["files"].items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest)
                if name != "summary.md":
                    self.assertEqual(hashlib.sha256((self.results / name).read_bytes()).hexdigest(), digest)

    def test_a_job_manifest_is_hashed_too(self):
        (self.results / "result-build" / "manifest.json").write_text("{}\n")
        _, manifest = self.build("build", "e2e")
        self.assertIn("result-build/manifest.json", manifest["files"])

    def test_a_check_recorded_twice_fails(self):
        # A pass from one job must not hide a fail from another, whichever is read last.
        with contextlib.redirect_stdout(io.StringIO()):
            record.main(["e2e", "1", "--title", "E2E", "--out", str(self.results / "result-a")])
        code, manifest = self.build("build", "e2e")
        self.assertEqual(code, 1)
        self.assertFalse(manifest["all_passed"])
        self.assertIn("recorded more than once", (self.out / "summary.md").read_text())

    def test_missing_expected_check_fails(self):
        code, manifest = self.build("build", "e2e", "secret-scan")
        self.assertEqual(code, 1)
        self.assertFalse(manifest["all_passed"])
        self.assertEqual(manifest["missing"], ["secret-scan"])
        self.assertIn("| ❌ missing | secret-scan |", (self.out / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
