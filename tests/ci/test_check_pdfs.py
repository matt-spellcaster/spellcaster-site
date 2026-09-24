"""check_pdfs: a PDF with a phone number, an address or a local path in it never reaches the repo."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "check_pdfs.py"
HOOK = ROOT / ".githooks" / "pre-commit"
sys.path.insert(0, str(SCRIPT.parent))

import check_pdfs

# Fictional numbers (555-01xx is reserved for fiction).
PHONE = "(312) 555-0147"
CLEAN = ["Jordan Example", "Chicago, IL | jordan@example.com", "Okta and AWS, 2019 - 2023, 18 checks, SOC 2"]
# The user's own git settings mustn't change the result.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def stream(data: bytes, extra: bytes = b"", compress: bool = True) -> bytes:
    if compress:
        data, extra = zlib.compress(data), extra + b" /Filter /FlateDecode"
    return b"<</Length %d%s>>\nstream\n%s\nendstream" % (len(data), extra, data)


def build(objects: list[bytes], trailer: bytes = b"") -> bytes:
    """A PDF from object bodies (object 1 is the catalog), with a real xref table."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<</Size %d /Root 1 0 R %s>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, trailer, start)
    return bytes(out)


def pdf(lines=CLEAN, *, simple=False, to_unicode=True, extra=(), trailer=b"", catalog=b"", content=None) -> bytes:
    """A one-page PDF. Each line is a str (one Tj), a tuple (pieces drawn with moves between them)
    or a list (one TJ with kerning). Composite fonts draw glyph ids, as real exports do; simple
    ones draw WinAnsi bytes."""
    chars = sorted({c for line in lines for piece in ([line] if isinstance(line, str) else line) for c in piece})
    glyph = {c: (i + 3).to_bytes(2, "big") for i, c in enumerate(chars)}

    def show(s: str) -> bytes:
        return b"(%s)" % s.encode("cp1252").replace(b"(", b"\\(").replace(b")", b"\\)") if simple else b"<%s>" % b"".join(glyph[c] for c in s).hex().encode()

    ops = [b"BT /F1 11 Tf 72 720 Td"]
    for line in lines:
        if isinstance(line, str):
            ops.append(show(line) + b" Tj")
        elif isinstance(line, tuple):
            ops.append(b" 20 0 Td ".join(show(p) + b" Tj" for p in line))
        else:
            ops.append(b"[" + b" -20 ".join(map(show, line)) + b"] TJ")
        ops.append(b"0 -14 Td")
    ops.append(b"ET")
    cmap = b"begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange %d beginbfchar %s endbfchar endcmap" % (
        len(chars), b" ".join(b"<%s> <%s>" % (glyph[c].hex().encode(), c.encode("utf-16-be").hex().encode()) for c in chars))
    if simple:
        font = b"<</Type /Font /Subtype /TrueType /BaseFont /Arial /Encoding /WinAnsiEncoding>>"
    else:
        font = b"<</Type /Font /Subtype /Type0 /BaseFont /ABCDEF+Body /Encoding /Identity-H%s>>" % (b" /ToUnicode 6 0 R" if to_unicode else b"")
    return build([
        b"<</Type /Catalog /Pages 2 0 R%s>>" % catalog,
        b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
        b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources <</Font <</F1 5 0 R>>>> /Contents 4 0 R>>",
        stream(b"\n".join(ops) if content is None else content),
        font,
        stream(cmap),
        *extra,
    ], trailer)


def run(data: bytes) -> tuple[int, str]:
    """main() on one PDF file: its exit code and what it printed."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume.pdf"
        path.write_bytes(data)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_pdfs.main([str(path)])
    return code, out.getvalue()


class Text(unittest.TestCase):
    def assertFinds(self, data: bytes, what: str):
        code, out = run(data)
        self.assertEqual(code, 1, out)
        self.assertIn(what, out)
        for digits in ("312", "555", "0147"):
            self.assertNotIn(digits, out, "findings are printed masked")

    def test_a_clean_resume_passes(self):
        for simple in (False, True):
            with self.subTest(simple=simple):
                code, out = run(pdf(simple=simple))
                self.assertEqual(code, 0, out)
                self.assertIn("ok (1 pages", out)

    def test_phone_numbers_are_found_in_every_usual_format(self):
        for number in (PHONE, "312-555-0147", "312.555.0147", "+1 312 555 0147", "3125550147", "312\u2013555\u20130147"):
            with self.subTest(number):
                self.assertFinds(pdf([*CLEAN, f"Chicago | {number}"]), "phone number in the text of page 1")
        self.assertFinds(pdf([*CLEAN, "+44 20 7946 0958"]), "international phone number")

    def test_a_number_drawn_in_pieces_is_found(self):
        self.assertFinds(pdf([*CLEAN, ("(31", "2) 55", "5-01", "47")]), "phone number")
        self.assertFinds(pdf([*CLEAN, ["(3", "12) 5", "55-01", "47"]]), "phone number")

    def test_simple_fonts_are_read_too(self):
        self.assertFinds(pdf([*CLEAN, PHONE], simple=True), "phone number in the text of page 1")

    def test_glyph_names_from_an_encoding_are_read(self):
        # Codes 1 to 11 draw the digits and the hyphen; the rest keep the font's usual encoding.
        names = b"/zero /one /two /three /four /five /six /seven /eight /nine /hyphen"
        codes = bytes(int(c) + 1 if c.isdigit() else 11 for c in "312-555-0147")
        data = build([
            b"<</Type /Catalog /Pages 2 0 R>>",
            b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
            b"<</Type /Page /Parent 2 0 R /Resources <</Font <</F1 5 0 R>>>> /Contents 4 0 R>>",
            stream(b"BT /F1 11 Tf 72 720 Td (Jordan) Tj 0 -14 Td <%s> Tj ET" % codes.hex().encode()),
            b"<</Type /Font /Subtype /Type1 /BaseFont /Custom /Encoding <</Differences [1 %s]>>>>" % names,
        ])
        self.assertFinds(data, "phone number in the text of page 1")

    def test_addresses_and_paths_are_found(self):
        cases = {"street address": "1234 N Main St", "PO box": "PO Box 42", "state and ZIP code": "Chicago, IL 60601",
                 "local file path": "Saved from /Users/jordan/Documents"}
        for label, line in cases.items():
            with self.subTest(label):
                self.assertFinds(pdf([*CLEAN, line]), f"{label} in the text of page 1")

    def test_ordinary_resume_lines_are_not_mistaken_for_details(self):
        lines = ["Built 18 checks across 3 AWS accounts, 2019 - 2023", "Cut review time 40% (2 days to 1)",
                 "linkedin.com/in/jordan-example-065b9483", "ISO 27001 A.8.12, SOC 2 CC6.1", "github.com/home/x"]
        code, out = run(pdf([*CLEAN, *lines]))
        self.assertEqual(code, 0, out)


class Hidden(unittest.TestCase):
    def assertFinds(self, data: bytes, what: str):
        code, out = run(data)
        self.assertEqual(code, 1, out)
        self.assertIn(what, out)

    def test_document_info_and_xmp(self):
        info = pdf(extra=[b"<</Author <%s>>>" % ("\ufeffJordan " + PHONE).encode("utf-16-be").hex().encode()], trailer=b"/Info 7 0 R")
        self.assertFinds(info, "phone number in the metadata")
        creator = pdf(extra=[b"<</Creator (/Users/jordan/Documents/resume.odt)>>"], trailer=b"/Info 7 0 R")
        self.assertFinds(creator, "local file path in the metadata")
        inline = pdf(trailer=b"/Info <</Producer (C:\\\\Users\\\\jordan\\\\resume.docx)>>")
        self.assertFinds(inline, "local file path in the metadata")
        xmp = b'<x:xmpmeta><rdf:Description xmp:CreatorTool="Writer" dc:source="file:///home/jordan/cv.odt"/></x:xmpmeta>'
        self.assertFinds(pdf(extra=[stream(xmp, b" /Type /Metadata /Subtype /XML")], catalog=b" /Metadata 7 0 R"),
                         "local file path in the XMP metadata")

    def test_links_and_alt_text(self):
        link = b"<</Type /Annot /Subtype /Link /Rect [0 0 1 1] /A <</S /URI /URI (tel:+13125550147)>>>>"
        self.assertFinds(pdf(extra=[link]), "phone number in the metadata, a link or alt text")
        alt = b"<</Type /StructElem /S /Figure /Alt (Call me on 312 555 0147)>>"
        self.assertFinds(pdf(extra=[alt]), "phone number in the metadata, a link or alt text")

    def test_objects_packed_in_an_object_stream(self):
        body = b"<</Type /Annot /Subtype /Link /A <</S /URI /URI (tel:312-555-0147)>>>>"
        header = b"8 0 "
        packed = stream(header + body, b" /Type /ObjStm /N 1 /First %d" % len(header))
        self.assertFinds(pdf(extra=[packed]), "phone number")


class FailsClosed(unittest.TestCase):
    def assertRefused(self, data: bytes, why: str):
        code, out = run(data)
        self.assertEqual(code, 1, out)
        self.assertIn(f"can't be checked: {why}", out)

    def test_a_font_without_a_map(self):
        self.assertRefused(pdf(to_unicode=False), "font ABCDEF+Body has no ToUnicode map")

    def test_no_text(self):
        self.assertRefused(pdf(content=b"q 100 0 0 100 0 0 cm Q"), "it has no readable text")

    def test_an_incremental_save(self):
        data = pdf()
        self.assertRefused(data + b"trailer\n<</Size 7 /Root 1 0 R /Prev 9>>\nstartxref\n9\n%%EOF\n", "it was saved incrementally")

    def test_encryption_attachments_and_other_filters(self):
        self.assertRefused(pdf(trailer=b"/Encrypt 7 0 R", extra=[b"<</Filter /Standard>>"]), "it's encrypted")
        self.assertRefused(pdf(catalog=b" /Names <</EmbeddedFiles 7 0 R>>", extra=[b"<</Names []>>"]), "it has an attached file")
        lzw = pdf().replace(b"/Filter /FlateDecode>>\nstream", b"/Filter /LZWDecode>>\nstream", 1)
        self.assertRefused(lzw, "a stream uses the LZWDecode filter")

    def test_a_broken_file(self):
        self.assertRefused(pdf()[:300], "")


class Git(unittest.TestCase):
    """--staged reads the index, --history every commit, and a PDF is found by its content."""

    def repo(self, tmp: str):
        subprocess.run(["git", "init", "-q", tmp], check=True, env=ENV)

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                                  cwd=tmp, check=True, env=ENV, capture_output=True)
        return git

    def script(self, tmp: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=tmp, env=ENV, capture_output=True, text=True)

    def test_staged_reads_the_index_and_ignores_the_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            git = self.repo(tmp)
            path = Path(tmp) / "notes.bin"
            path.write_bytes(pdf([*CLEAN, PHONE]))
            git("add", "notes.bin")
            path.write_bytes(pdf())  # the working tree is clean; the index isn't
            result = self.script(tmp, "--staged")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("notes.bin: phone number", result.stdout)

    def test_history_finds_a_pdf_a_later_commit_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            git = self.repo(tmp)
            path = Path(tmp) / "public" / "resume.pdf"
            path.parent.mkdir()
            path.write_bytes(pdf([*CLEAN, PHONE]))
            git("add", ".")
            git("commit", "-q", "-m", "add")
            path.write_bytes(pdf())
            git("commit", "-q", "-am", "fix")
            result = self.script(tmp, "--history")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("public/resume.pdf (blob", result.stdout)
            self.assertIn("2 PDFs checked", result.stdout)

    def test_the_pre_commit_hook_runs_it(self):
        for data, expected in ((pdf(), 0), (pdf([*CLEAN, PHONE]), 1)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                git = self.repo(tmp)
                (Path(tmp) / "resume.pdf").write_bytes(data)
                git("add", "resume.pdf")
                result = subprocess.run(["bash", str(HOOK)], cwd=tmp, env=ENV, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
