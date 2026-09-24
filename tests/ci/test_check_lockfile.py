"""check_lockfile: every locked package must be its own registry tarball, with a sha512 hash."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import check_lockfile
from check_lockfile import problems


def entry(name, version="1.0.0", **extra):
    base = name.rsplit("/", 1)[-1]
    return {"version": version, "resolved": f"https://registry.npmjs.org/{name}/-/{base}-{version}.tgz",
            "integrity": "sha512-abc", **extra}


def lock(packages, version=3, dependencies=None):
    root = {"name": "site", **({"dependencies": dependencies} if dependencies else {})}
    return {"lockfileVersion": version, "packages": {"": root, **packages}}


def check(packages, version=3, dependencies=None):
    """problems() for a lockfile and a package.json that agree on the direct dependencies."""
    return problems(lock(packages, version, dependencies), {"dependencies": dependencies or {}})


class Passes(unittest.TestCase):
    def test_plain_scoped_and_nested_entries(self):
        packages = {
            "node_modules/astro": entry("astro"),
            "node_modules/@astrojs/check": entry("@astrojs/check", "0.9.4"),
            "node_modules/a/node_modules/b": entry("b", "2.0.0"),
            "node_modules/a/node_modules/@s/b": entry("@s/b", "3.1.0-beta.1"),
        }
        self.assertEqual(check(packages), [])

    def test_alias_in_package_json_uses_its_name_field(self):
        alias = {**entry("string-width", "4.2.3"), "name": "string-width"}
        deps = {"string-width-cjs": "npm:string-width@^4.2.0"}
        self.assertEqual(check({"node_modules/string-width-cjs": alias}, dependencies=deps), [])

    def test_reviewed_alias_of_a_dependency(self):
        alias = {**entry("string-width", "4.2.3"), "name": "string-width"}
        parent = entry("@isaacs/cliui", "8.0.2", dependencies={"string-width-cjs": "npm:string-width@^4.2.0"})
        packages = {"node_modules/@isaacs/cliui": parent, "node_modules/string-width-cjs": alias}
        self.assertEqual(len(check(packages)), 1)
        with mock.patch.object(check_lockfile, "REVIEWED_ALIASES", {("string-width-cjs", "string-width")}):
            self.assertEqual(check(packages), [])


class Rejects(unittest.TestCase):
    def test_bad_resolved(self):
        cases = {
            "git URL": ("node_modules/astro", "git+ssh://git@github.com/withastro/astro.git#abc123"),
            "another host": ("node_modules/astro", "https://evil.test/astro/-/astro-1.0.0.tgz"),
            "lookalike host": ("node_modules/astro", "https://registry.npmjs.org.evil.test/astro/-/astro-1.0.0.tgz"),
            "plain http": ("node_modules/astro", "http://registry.npmjs.org/astro/-/astro-1.0.0.tgz"),
            "empty": ("node_modules/astro", ""),
            "another package": ("node_modules/astro", "https://registry.npmjs.org/evil-astro/-/evil-astro-1.0.0.tgz"),
            "another scope": ("node_modules/@astrojs/check", "https://registry.npmjs.org/@evil/check/-/check-1.0.0.tgz"),
            "wrong version": ("node_modules/astro", "https://registry.npmjs.org/astro/-/astro-0.9.0.tgz"),
        }
        for label, (path, resolved) in cases.items():
            with self.subTest(label):
                found = check({path: {**entry("x"), "resolved": resolved}})
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].startswith(f"{path}: resolved from"))

    def test_unreviewed_alias(self):
        # A lockfile edit can't rename an entry to swap in another package's tarball, even if
        # the same edit declares the alias in an entry's dependencies or in the lockfile's root.
        swapped = {**entry("evil-react", "19.3.0"), "name": "evil-react"}
        self.assertEqual(check({"node_modules/react": swapped}),
                         ["node_modules/react: named evil-react, an alias not in package.json or REVIEWED_ALIASES"])
        self_declared = {**swapped, "dependencies": {"react": "npm:evil-react@19.3.0"}}
        self.assertEqual(len(check({"node_modules/react": self_declared})), 1)
        root_only = problems(lock({"node_modules/react": swapped}, dependencies={"react": "npm:evil-react@19.3.0"}),
                             {"dependencies": {"react": "19.3.0"}})
        self.assertEqual(root_only, ["the lockfile's dependencies don't match package.json",
                                     "node_modules/react: named evil-react, an alias not in package.json or REVIEWED_ALIASES"])
        self.assertEqual(len(check({"node_modules/string-width-cjs": entry("string-width", "4.2.3")})), 1)

    def test_links_and_odd_paths(self):
        # Two more ways a lockfile edit could put another package at node_modules/react.
        link = {"node_modules/react": {"link": True, "resolved": "node_modules/evil-react"},
                "node_modules/evil-react": entry("evil-react")}
        self.assertEqual(check(link), ["node_modules/react: a link (this project has no workspaces)"])
        dotted = "node_modules/evil-react/-/evil-react-1.0.0.tgz?/../../../react"
        self.assertEqual(check({dotted: entry("react")}), [f"{dotted}: not a plain node_modules path"])
        for path in ("node_modules/../react", "node_modules/./react", "node_modules//react", "react"):
            with self.subTest(path):
                self.assertEqual(len(check({path: entry("react")})), 1)

    def test_odd_versions(self):
        for version in ("1.0", "1.0.0?x=1", "1.0.0/../../evil", "latest"):
            with self.subTest(version):
                found = check({"node_modules/astro": entry("astro", version)})
                self.assertIn(f"node_modules/astro: version {version!r} isn't a plain semver version", found)

    def test_missing_resolved(self):
        pkg = entry("astro")
        del pkg["resolved"]
        self.assertEqual(check({"node_modules/astro": pkg}),
                         ["node_modules/astro: resolved from nowhere, expected "
                          "https://registry.npmjs.org/astro/-/astro-1.0.0.tgz"])

    def test_missing_or_weak_integrity(self):
        for integrity in (None, "", "sha1-abc", "sha256-abc"):
            with self.subTest(integrity=integrity):
                pkg = entry("astro")
                if integrity is None:
                    del pkg["integrity"]
                else:
                    pkg["integrity"] = integrity
                self.assertEqual(check({"node_modules/astro": pkg}),
                                 ["node_modules/astro: no sha512 integrity hash"])

    def test_old_lockfile_version(self):
        self.assertEqual(check({"node_modules/astro": entry("astro")}, version=2),
                         ["lockfileVersion is 2, expected 3"])


class Main(unittest.TestCase):
    def run_main(self, data, manifest):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package-lock.json"
            path.write_text(json.dumps(data))
            (Path(tmp) / "package.json").write_text(json.dumps(manifest))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = check_lockfile.main([str(path)])
        return code, out.getvalue()

    def test_exit_codes(self):
        code, out = self.run_main(lock({"node_modules/astro": entry("astro")}), {})
        self.assertEqual(code, 0)
        self.assertIn("0 problems in 1 locked packages", out)
        code, out = self.run_main(lock({"node_modules/astro": {**entry("astro"), "resolved": ""}}), {})
        self.assertEqual(code, 1)
        self.assertIn("1 problems in 1 locked packages", out)

    def test_the_real_lockfile(self):
        repo = Path(__file__).resolve().parents[2]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_lockfile.main([str(repo / "package-lock.json")]), 0)


if __name__ == "__main__":
    unittest.main()
