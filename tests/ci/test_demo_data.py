"""demo_data: the demo's data is the tool's own export at a commit on its master branch."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import demo_data

COMMIT = "b" * 40


def page(commit=COMMIT, extra=""):
    return (json.dumps({"format": 1, "source": {"commit": commit}, "extra": extra}) + "\n").encode()


class FakeRun:
    """git and uv, as far as demo_data uses them. The export writes page() and a golden file."""

    def __init__(self, stamped=COMMIT, on_master=True, fail=None, writes=None):
        self.calls, self.stamped, self.on_master, self.fail = [], stamped, on_master, fail
        self.writes = writes if writes is not None else {"okta.json": page(stamped), "okta.golden.json": b"{}\n"}

    def __call__(self, args, cwd=None, capture_output=True, text=True):
        self.calls.append((args, cwd))
        code = 1 if self.fail and self.fail in args else 0
        if args[:4] == ["git", "-C", args[2], "merge-base"]:
            code = 0 if self.on_master else 1
        if args[0] == "uv" and not code:
            out = Path(args[args.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            for name, body in self.writes.items():
                (out / name).write_bytes(body)
        return subprocess.CompletedProcess(args, code, "", "boom" if code else "")


class Repo:
    """A checkout with the committed demo files in it."""

    def __init__(self, files=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel, body in (files or {}).items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(body)

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        self.tmp.cleanup()


COMMITTED = {"src/data/demo/okta.json": page(), "tests/fixtures/demo/okta.golden.json": b"{}\n"}


def main(argv, run, root):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = demo_data.main(argv, run=run, root=root)
    return code, err.getvalue()


class PinnedTest(unittest.TestCase):
    def test_reads_the_commit_the_page_data_is_stamped_with(self):
        with Repo(COMMITTED) as root:
            self.assertEqual(demo_data.pinned(root), COMMIT)

    def test_refuses_missing_data_or_a_short_commit(self):
        with Repo() as root, self.assertRaisesRegex(demo_data.DemoDataError, "can't be read"):
            demo_data.pinned(root)
        with Repo({"src/data/demo/okta.json": page("b4f6b8c")}) as root, \
                self.assertRaisesRegex(demo_data.DemoDataError, "no full commit"):
            demo_data.pinned(root)


class ExportTest(unittest.TestCase):
    def export(self, run, commit=COMMIT):
        with tempfile.TemporaryDirectory() as tmp:
            return demo_data.export(commit, Path(tmp), run)

    def test_clones_checks_out_and_runs_the_tools_own_export_with_its_lockfile(self):
        run = FakeRun()
        files = self.export(run)
        self.assertEqual(set(files), {"okta.json", "okta.golden.json"})
        commands = [args[:4] for args, _ in run.calls]
        self.assertEqual(commands[0], ["git", "clone", "--quiet", "--no-checkout"])
        self.assertIn(f"https://github.com/{demo_data.REPO}.git", run.calls[0][0])
        self.assertEqual(run.calls[1][0][3:], ["checkout", "--quiet", "--detach", COMMIT])
        self.assertEqual(run.calls[2][0][3:], ["merge-base", "--is-ancestor", COMMIT, "origin/master"])
        uv, cwd = run.calls[3]
        self.assertEqual(uv[:4], ["uv", "run", "--frozen", "python"])
        self.assertEqual(uv[-2:], ["--variant", "okta"])
        self.assertEqual(cwd.name, "tool")

    def test_refuses_a_commit_that_is_not_on_master(self):
        with self.assertRaisesRegex(demo_data.DemoDataError, "not on .* master branch"):
            self.export(FakeRun(on_master=False))

    def test_refuses_anything_but_a_full_commit_before_running_anything(self):
        run = FakeRun()
        with self.assertRaisesRegex(demo_data.DemoDataError, "not a full commit"):
            self.export(run, commit="master")
        self.assertEqual(run.calls, [])

    def test_stops_when_a_command_fails_or_a_file_is_missing(self):
        with self.assertRaisesRegex(demo_data.DemoDataError, "failed: boom"):
            self.export(FakeRun(fail="clone"))
        with self.assertRaisesRegex(demo_data.DemoDataError, "wrote no okta.golden.json"):
            self.export(FakeRun(writes={"okta.json": page()}))

    def test_refuses_an_export_stamped_with_another_commit(self):
        with self.assertRaisesRegex(demo_data.DemoDataError, "stamped"):
            self.export(FakeRun(stamped="c" * 40))


class MainTest(unittest.TestCase):
    def test_check_passes_when_every_file_is_the_export_byte_for_byte(self):
        with Repo(COMMITTED) as root:
            self.assertEqual(main(["check"], FakeRun(), root), (0, ""))

    def test_check_fails_on_a_hand_edit_or_a_missing_file(self):
        edited = {**COMMITTED, "src/data/demo/okta.json": page(extra="edited")}
        with Repo(edited) as root:
            code, err = main(["check"], FakeRun(), root)
        self.assertEqual(code, 1)
        self.assertIn("src/data/demo/okta.json differs from the export", err)
        self.assertIn("never edit it by hand", err)
        with Repo({"src/data/demo/okta.json": page()}) as root:
            code, err = main(["check"], FakeRun(), root)
        self.assertEqual(code, 1)
        self.assertIn("okta.golden.json is missing", err)

    def test_check_exports_at_the_pinned_commit(self):
        run = FakeRun()
        with Repo(COMMITTED) as root:
            main(["check"], run, root)
        self.assertEqual(run.calls[1][0][-1], COMMIT)

    def test_sync_writes_the_export_into_place(self):
        with Repo() as root:
            code, _ = main(["sync", "--commit", COMMIT], FakeRun(), root)
            self.assertEqual(code, 0)
            self.assertEqual((root / "src/data/demo/okta.json").read_bytes(), page())
            self.assertEqual((root / "tests/fixtures/demo/okta.golden.json").read_bytes(), b"{}\n")

    def test_never_copies_a_pdf(self):
        self.assertFalse(any(name.endswith(".pdf") for name in demo_data.targets()))


if __name__ == "__main__":
    unittest.main()
