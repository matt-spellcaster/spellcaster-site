"""check_pdfs: no PDF gets into the repository, whatever it's called and wherever it hides."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_pdfs.py"
# The user's own git settings mustn't change the result.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# Built in pieces, so this file doesn't carry a PDF header near its top.
PDF = b"%" + b"PDF-1.7\n1 0 obj <</Type /Catalog>> endobj\ntrailer <</Root 1 0 R>>\n%%EOF\n"


class CheckPdfs(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        """A new, empty repository to work in."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git("init", "-q")

    def git(self, *args):
        who = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(["git", "--literal-pathspecs", *who, *args], cwd=self.root, check=True, env=ENV,
                       capture_output=True)

    def add(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.git("add", "--", name)

    def check(self, mode):
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), mode], cwd=self.root, env=ENV,
                                capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_other_files_pass(self):
        self.add("src/page.astro", b"<p>Our PDF guide</p>\n")
        # A PDF header past the first 1024 bytes is text about PDFs, not a PDF.
        self.add("docs/pdf.md", b"Some notes.\n" * 100 + b"A PDF starts with %" + b"PDF-1.7.\n")
        self.add("public/og/home.png", b"\x89PNG\r\n\x1a\n" + bytes(2000))
        self.assertEqual(self.check("--staged"), (0, "3 files checked, 0 PDFs found\n"))

    def test_a_pdf_is_refused_by_name_or_by_content(self):
        cases = {"public/resume.pdf": b"", "CV.PDF": b"not really a pdf", "notes.bin": PDF,
                 "cv": b"\n" * 500 + PDF, "0:README.md": PDF}
        for name, data in cases.items():
            with self.subTest(name):
                self.fresh()
                self.add("README.md", b"# site\n")
                self.add(name, data)
                code, out = self.check("--staged")
                self.assertEqual(code, 1, out)
                self.assertIn(f"PDF: {name}, by its", out)
                self.assertIn("2 files checked, 1 PDFs found", out)

    def test_the_index_is_read_not_the_working_tree(self):
        self.add("notes.bin", PDF)
        (self.root / "notes.bin").write_bytes(b"plain text now\n")
        self.assertEqual(self.check("--staged")[0], 1)

    def test_a_deleted_pdf_can_be_committed(self):
        self.add("resume.pdf", PDF)
        self.git("commit", "-q", "--no-verify", "-m", "add")
        self.git("rm", "-q", "resume.pdf")
        self.assertEqual(self.check("--staged"), (0, "0 files checked, 0 PDFs found\n"))

    def test_history_covers_every_branch_and_a_pdf_removed_later(self):
        self.add("README.md", b"# site\n")
        self.git("commit", "-q", "-m", "start")
        self.assertEqual(self.check("--history")[0], 0)
        self.git("checkout", "-q", "-b", "side")
        self.add("resume.pdf", PDF)
        self.git("commit", "-q", "--no-verify", "-m", "add")
        self.git("rm", "-q", "resume.pdf")
        self.git("commit", "-q", "-m", "remove")
        self.git("checkout", "-q", "-")  # back on the first branch, which never had it
        code, out = self.check("--history")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"PDF: resume\.pdf \(blob [0-9a-f]{12}\), by its name")

    def test_the_header_counts_if_it_starts_in_the_first_1024_bytes(self):
        for offset, expected in ((1023, 1), (1024, 0)):
            with self.subTest(offset):
                self.fresh()
                self.add("blob.bin", b" " * offset + PDF)
                self.assertEqual(self.check("--staged")[0], expected)

    def test_every_name_is_checked_even_when_contents_match(self):
        self.add("resume.pdf", b"hello\n")
        self.add("z.txt", b"hello\n")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("PDF: resume.pdf, by its name", out)

    def test_renames_and_submodules(self):
        self.add("notes.txt", b"notes\n")
        self.add("keep.txt", b"keep\n")
        self.git("commit", "-q", "-m", "start")
        self.git("mv", "keep.txt", "kept.txt")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},sub")
        self.assertEqual(self.check("--staged"), (0, "1 files checked, 0 PDFs found\n"))
        self.git("mv", "notes.txt", "notes.pdf")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("PDF: notes.pdf, by its name", out)

    def test_history_reads_odd_names_and_skips_folders(self):
        self.add("x.pdf/inside.txt", b"a folder with a .pdf name\n")
        self.add("odd\rname.txt", b"text\n")
        self.git("commit", "-q", "-m", "start")
        self.assertEqual(self.check("--history"), (0, "2 files checked, 0 PDFs found\n"))
        self.add("cv\r\n.pdf", b"no header\n")
        self.git("commit", "-q", "--no-verify", "-m", "add")
        code, out = self.check("--history")
        self.assertEqual(code, 1, out)
        self.assertIn("PDF: cv\\r\\n.pdf (blob", out)

    def test_history_covers_a_pdf_a_tag_points_at(self):
        self.add("README.md", b"# site\n")
        self.git("commit", "-q", "-m", "start")
        (self.root / "blob").write_bytes(PDF)
        sha = subprocess.run(["git", "hash-object", "-w", "blob"], cwd=self.root, env=ENV, check=True,
                             capture_output=True, text=True).stdout.strip()
        self.git("tag", "loose", sha)
        code, out = self.check("--history")
        self.assertEqual(code, 1, out)
        self.assertIn(f"(blob {sha[:12]}), by its header", out)

    def test_staged_ignores_diff_relative_in_a_subfolder(self):
        self.git("config", "diff.relative", "true")
        (self.root / "sub").mkdir()
        self.add("top.bin", PDF)
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--staged"], cwd=self.root / "sub", env=ENV,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_missing_object_is_a_failure(self):
        self.git("update-index", "--add", "--cacheinfo", f"100644,{'2' * 40},ghost.txt")
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--staged"], cwd=self.root, env=ENV,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("git has no object", result.stderr)

    def test_a_failure_is_not_mistaken_for_a_pdf(self):
        (self.root / ".git" / "index").write_bytes(b"not an index")
        code, _ = self.check("--staged")
        self.assertEqual(code, 2)

    def test_a_path_cannot_become_a_workflow_command(self):
        self.add("::warning::x.pdf", PDF)
        self.add("a\n::error::b.pdf", PDF)
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertFalse([line for line in out.splitlines() if line.startswith("::")], out)


if __name__ == "__main__":
    unittest.main()
