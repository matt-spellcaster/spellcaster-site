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
    def hook(self, files):
        """Stage {path: text} in a new repository and run the hook; its exit code."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True, env=ENV)
            for name, text in files.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                subprocess.run(["git", "add", "-f", "--", name], cwd=tmp, check=True, env=ENV)
            return subprocess.run(["bash", str(HOOK)], cwd=tmp, env=ENV, capture_output=True).returncode

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

    def test_a_file_marked_binary_is_still_scanned(self):
        self.assertEqual(self.hook({".gitattributes": "*.txt -diff\n", "ids.txt": "owner = 1234" + "56789012\n"}), 1)


if __name__ == "__main__":
    unittest.main()
