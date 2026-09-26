"""The pre-commit guard: refuses private files and account IDs, in any folder and any file name."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "pre-commit"
# The user's own git settings (global ignores, diff drivers) mustn't change the result.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class PreCommit(unittest.TestCase):
    def hook(self, files, env=ENV):
        """Stage {path: text or bytes} in a new repository and run the hook; its exit code."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True, env=ENV)
            for name, content in files.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
                subprocess.run(["git", "add", "-f", "--", name], cwd=tmp, check=True, env=ENV)
            return subprocess.run(["bash", str(HOOK)], cwd=tmp, env=env, capture_output=True).returncode

    def test_ordinary_changes_pass(self):
        self.assertEqual(self.hook({"src/page.astro": "<p>Version 1.2.3, 2026-09-23</p>\n",
                                    "prod.tfvars.example": 'region = "us-east-1"\n'}), 0)

    def test_private_files_are_refused_anywhere(self):
        names = [".env", "infra/.env", "infra/.env.local", "keys/site.pem", "a.key", "my key.p12", "AuthKey.p8",
                 "terraform.tfstate", "infra/terraform.tfstate.backup", "prod.tfvars", "résumé.tfvars",
                 "terraform.tfvars.json", "infra/prod.tfbackend", "backend.hcl", "infra/backend copy.hcl",
                 "tfplan", "prod.tfplan", "infra/plan.out"]
        for name in names:
            with self.subTest(name):
                self.assertEqual(self.hook({name: "x\n"}), 1)

    def test_account_ids_and_keys_in_content(self):
        # Built at run time, so this file doesn't trip the hook it tests.
        digits = ["1234", "5678", "9012"]
        cases = {"plain ID": f"owner = {''.join(digits)}\n", "console ID": f"owner = {'-'.join(digits)}\n",
                 "private key": "-----BEGIN RSA " + "PRIVATE KEY-----\n"}
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(self.hook({"notes.txt": text}), 1)

    def test_the_tools_decision_record_names_pass_and_nothing_else_with_them(self):
        # The demo data names records like 20260918T160000000000Z-000000000001.json, with two
        # 12-digit runs in each. Built at run time, so this file doesn't trip the hook it tests.
        stamp, digits = "20260918T" + "160000" + "000000Z", "1234" + "56789012"
        name = f"{stamp}-{'0' * 11}1.json"
        self.assertEqual(self.hook({"src/data/demo/web.json": f'"record": "{name}",\n'
                                    f'"record_name": "{stamp}-{{n:012x}}.json"\n'}), 0)
        cases = {"an ID beside a record name": f'"{name}" owner = {digits}\n',
                 "an ID as the counter": f'"{stamp}-{digits}.json"\n',
                 "an ID in a name that isn't a record's": f'"20260918T{digits}Z.json"\n'}
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(self.hook({"src/data/demo/web.json": text}), 1)

    def test_record_names_are_set_aside_only_in_the_demo_data(self):
        name = "20260918T" + "160000" + "000000Z-" + "0" * 11 + "1.json"
        self.assertEqual(self.hook({"tests/fixtures/demo/web.golden.json": f'"{name}"\n'}), 0)
        self.assertEqual(self.hook({"src/pages/notes.txt": f'"{name}"\n'}), 1)

    def test_a_sha256_with_12_digits_in_a_row_passes_and_an_id_beside_it_does_not(self):
        # Built at run time, so this file doesn't trip the hook it tests.
        digits = "1234" + "56789012"
        sha = "ab" + digits + "c" * 50
        self.assertEqual(len(sha), 64)
        for label, text in {"alone": f'"{sha}"\n', "three in a row": f"{sha},{sha},{sha}\n",
                            "in the demo data too": f'"sha256": "{sha}"\n'}.items():
            with self.subTest(label):
                self.assertEqual(self.hook({"src/data/demo/web.json": text}), 0)
        cases = {"an ID beside a hash": f"{sha} owner = {digits}\n",
                 "an ID in 63 hex characters": f"{sha[:-1]}\n",
                 "an ID in 65 hex characters": f"{sha}d\n"}
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(self.hook({"notes.txt": text}), 1)

    def test_pdfs_are_refused_by_name_or_content(self):
        pdf = b"%" + b"PDF-1.7\n%%EOF\n"  # in pieces, so this file has no PDF header
        for name in ("docs/resume.pdf", "notes.bin"):
            with self.subTest(name):
                self.assertEqual(self.hook({name: pdf}), 1)

    def test_a_pdf_check_that_fails_to_run_blocks_the_commit(self):
        with tempfile.TemporaryDirectory() as bin_dir:
            stub = Path(bin_dir) / "python3"
            stub.write_text("#!/bin/sh\nexit 2\n")
            stub.chmod(0o755)
            env = {**ENV, "PATH": f"{bin_dir}{os.pathsep}{ENV['PATH']}"}
            self.assertEqual(self.hook({"src/page.astro": "<p>hi</p>\n"}, env=env), 1)

    def test_a_file_marked_binary_is_still_scanned(self):
        self.assertEqual(self.hook({".gitattributes": "*.txt -diff\n", "ids.txt": "owner = 1234" + "56789012\n"}), 1)


if __name__ == "__main__":
    unittest.main()
