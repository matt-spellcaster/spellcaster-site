"""dist_manifest: --check passes only on the exact tree that was hashed."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import dist_manifest


def run(*argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        code = dist_manifest.main([str(a) for a in argv])
    return code, err.getvalue()


class DistManifest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dist, self.manifest = Path(tmp.name) / "dist", Path(tmp.name) / "dist-manifest.json"
        (self.dist / "_astro").mkdir(parents=True)
        (self.dist / "index.html").write_text("<h1>home</h1>")
        (self.dist / "_astro" / "app.css").write_text("body{}")

    def test_write_then_check_unchanged_tree(self):
        self.assertEqual(run(self.dist, self.manifest)[0], 0)
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["file_count"], 2)
        self.assertEqual(set(manifest["files"]), {"index.html", "_astro/app.css"})
        self.assertEqual(run("--check", self.dist, self.manifest), (0, ""))

    def test_check_fails_on_any_difference(self):
        css = self.dist / "_astro" / "app.css"
        cases = {
            "changed: _astro/app.css": lambda: css.write_text("body{color:red}"),
            "missing: _astro/app.css": css.unlink,
            "unexpected: extra.js": lambda: (self.dist / "extra.js").write_text("alert(1)"),
        }
        for message, change in cases.items():
            with self.subTest(message):
                css.write_text("body{}")
                (self.dist / "extra.js").unlink(missing_ok=True)
                self.assertEqual(run(self.dist, self.manifest)[0], 0)
                change()
                code, err = run("--check", self.dist, self.manifest)
                self.assertEqual(code, 1)
                self.assertEqual(err.strip(), message)

    def test_tree_without_index_fails(self):
        run(self.dist, self.manifest)
        (self.dist / "index.html").unlink()
        self.assertEqual(run("--check", self.dist, self.manifest)[0], 1)
        self.manifest.unlink()
        code, err = run(self.dist, self.manifest)
        self.assertEqual(code, 1)
        self.assertIn("index.html is missing", err)
        self.assertFalse(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
