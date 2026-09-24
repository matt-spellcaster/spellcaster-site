"""Check PDFs for personal details before they reach this public repository.

    python3 -I scripts/ci/check_pdfs.py --staged    # what `git commit` is about to add (the hook)
    python3 -I scripts/ci/check_pdfs.py --history   # every PDF in the checked-out history (CI)
    python3 -I scripts/ci/check_pdfs.py FILE...

A PDF keeps its text compressed and drawn through font tables, so the pre-commit hook's line
scan and gitleaks can't see a phone number in one. This reads the text the way a viewer does
(each page's content through its fonts' ToUnicode maps), every string in the file's objects
(metadata, links, bookmarks, alt text) and its XMP metadata, and fails on a phone number, a
street address or a path from someone's computer. It fails closed: a PDF it can't read fully
(encrypted, saved incrementally, an attachment, a font with no map, no text) is an error. A
file is a PDF by its first bytes, whatever its name. Findings are printed with their letters
and digits masked, because CI logs are public. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, NamedTuple

MAGIC = b"%PDF-"
SEP = r"[\s.\-‐-―]"
STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
    "NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
STREET = (
    "St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ct|Court|Way|Pl|Place|Cir|"
    "Circle|Pkwy|Parkway|Ter|Terrace|Trl|Trail|Hwy|Highway|Sq|Square"
)
PATTERNS = {
    "phone number": re.compile(rf"(?<!\d)(?:\+?1{SEP}*)?\(?\d{{3}}\)?{SEP}*\d{{3}}{SEP}*\d{{4}}(?!\d)"),
    "international phone number": re.compile(rf"\+\d(?:{SEP}*\d){{7,13}}(?!\d)"),
    "street address": re.compile(rf"\b\d{{1,6}}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z'-]*\s+){{1,3}}(?:{STREET})\b"),
    "PO box": re.compile(r"\bP\.?\s*O\.?\s*Box\s+\d", re.I),
    "state and ZIP code": re.compile(rf"\b(?:{STATES}),?\s+\d{{5}}(?:-\d{{4}})?\b"),
    "local file path": re.compile(r"(?<![\w.])/(?:Users|home)/[^/\s]+|\b[A-Za-z]:\\(?:Users|Documents and Settings)\\", re.I),
}
# Glyph names a font's /Differences may give the characters those patterns look for.
GLYPHS = {
    **{n: str(i) for i, n in enumerate("zero one two three four five six seven eight nine".split())},
    "space": " ", "hyphen": "-", "minus": "-", "endash": "–", "emdash": "—", "period": ".",
    "parenleft": "(", "parenright": ")", "plus": "+", "slash": "/", "backslash": "\\", "colon": ":",
}
CODECS = {"WinAnsiEncoding": "cp1252", "MacRomanEncoding": "mac_roman"}


class Unreadable(Exception):
    """The file can't be checked fully, so it doesn't pass."""


class Ref(NamedTuple):
    num: int
    gen: int


class Name(str):
    """A PDF name, like /Font. Strings stay bytes, so the two never mix."""


class Op(str):
    """A bare keyword: an operator in a content stream, or obj, R, true and so on."""


# ---- Reading the syntax ---------------------------------------------------------------------

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"
ESCAPES = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f"}
NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")
END_OF_IMAGE = re.compile(rb"\sEI(?=\s|$)")


def word_end(data: bytes, i: int) -> int:
    while i < len(data) and data[i] not in WHITESPACE + DELIMITERS:
        i += 1
    return i


def tokens(data: bytes) -> Iterator[object]:
    """PDF tokens: numbers, Names, byte strings, Ops, and the brackets "[", "]", "<<" and ">>"."""
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c in WHITESPACE:
            i += 1
        elif c == ord("%"):
            while i < n and data[i] not in b"\r\n":
                i += 1
        elif data[i : i + 2] in (b"<<", b">>"):
            yield data[i : i + 2].decode()
            i += 2
        elif c in b"[]{}":
            yield chr(c)
            i += 1
        elif c == ord("<"):
            end = data.find(b">", i)
            if end < 0:
                raise Unreadable("a hex string never ends")
            digits = bytes(b for b in data[i + 1 : end] if b not in WHITESPACE)
            yield bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode("latin-1"))
            i = end + 1
        elif c == ord("("):
            s, i = literal(data, i + 1)
            yield s
        elif c == ord("/"):
            j = word_end(data, i + 1)
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes.fromhex(m[1].decode()), data[i + 1 : j])
            yield Name(raw.decode("latin-1"))
            i = j
        else:
            j = max(word_end(data, i), i + 1)
            word = data[i:j].decode("latin-1")
            i = j
            if NUMBER.fullmatch(word):
                yield float(word) if "." in word else int(word)
            else:
                yield Op(word)
                if word == "ID":  # an inline image's data runs to EI
                    m = END_OF_IMAGE.search(data, i)
                    i = m.end() if m else n


def literal(data: bytes, i: int) -> tuple[bytes, int]:
    """The (literal string) that starts at data[i], just after its "(", and where it ends."""
    out, depth, n = bytearray(), 1, len(data)
    while i < n:
        c = data[i]
        if c == ord("\\") and i + 1 < n:
            e = data[i + 1]
            if e in ESCAPES:
                out += ESCAPES[e]
                i += 2
            elif e in b"01234567":
                m = re.compile(rb"[0-7]{1,3}").match(data, i + 1)
                out.append(int(m[0], 8) & 0xFF)
                i = m.end()
            elif e in b"\r\n":  # a line continuation
                i += 3 if data[i + 1 : i + 3] == b"\r\n" else 2
            else:
                out.append(e)
                i += 2
            continue
        depth += (c == ord("(")) - (c == ord(")"))
        if depth == 0:
            return bytes(out), i + 1
        out.append(c)
        i += 1
    raise Unreadable("a string never ends")


def parse(items: list[object]) -> list[object]:
    """Tokens to values: dicts, lists and Refs."""
    stack: list[list[object]] = [[]]
    for t in items:
        if t in ("[", "<<"):
            stack.append([t])
        elif t in ("]", ">>") and len(stack) > 1:
            opener, *values = stack.pop()
            stack[-1].append(values if opener == "[" else dict(zip(values[::2], values[1::2])))
        elif t == "R" and len(stack[-1]) >= 2 and all(type(v) is int for v in stack[-1][-2:]):
            gen, num = stack[-1].pop(), stack[-1].pop()
            stack[-1].append(Ref(num, gen))
        else:
            stack[-1].append(t)
    return stack[0]


# ---- The file's objects ---------------------------------------------------------------------


@dataclass
class Obj:
    value: object
    stream: bytes | None = None


@dataclass
class Pdf:
    objects: dict[int, Obj] = field(default_factory=dict)
    trailers: list[dict] = field(default_factory=list)

    def get(self, v: object) -> object:
        """v, with indirect references followed."""
        for _ in range(32):
            if not isinstance(v, Ref):
                return v
            v = self.objects[v.num].value if v.num in self.objects else None
        raise Unreadable("references go round in a loop")

    def dict(self, v: object) -> dict:
        v = self.get(v)
        return v if isinstance(v, dict) else {}

    def stream(self, ref: object) -> bytes:
        """The decoded data of the stream ref points to."""
        obj = self.objects.get(ref.num) if isinstance(ref, Ref) else None
        if obj is None or obj.stream is None or not isinstance(obj.value, dict):
            raise Unreadable("a content, font or metadata stream is missing")
        return decode(self, obj.value, obj.stream)


OBJECT = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
STREAM = re.compile(rb">>\s*stream\r?\n")


def load(data: bytes) -> Pdf:
    pdf = Pdf()
    starts = list(OBJECT.finditer(data))
    for k, m in enumerate(starts):
        body = data[m.end() : starts[k + 1].start() if k + 1 < len(starts) else len(data)]
        stream = None
        if s := STREAM.search(body):
            stop = body.rfind(b"endstream")
            stream = body[s.end() : stop if stop > s.end() else len(body)].rstrip(b"\r\n")
            body = body[: s.start() + 2]
        values = parse(list(tokens(body.split(b"endobj")[0])))
        pdf.objects[int(m[1])] = Obj(values[0] if values else None, stream)
    for t in re.finditer(rb"trailer\s*(<<.*?>>)\s*startxref", data, re.S):
        pdf.trailers += [v for v in parse(list(tokens(t[1]))) if isinstance(v, dict)]
    for obj in list(pdf.objects.values()):
        d = obj.value if isinstance(obj.value, dict) else {}
        if d.get("Type") == "XRef":
            pdf.trailers.append(d)
        elif d.get("Type") == "ObjStm" and obj.stream is not None:
            unpack(pdf, d, decode(pdf, d, obj.stream))
    return pdf


def unpack(pdf: Pdf, d: dict, data: bytes) -> None:
    """Add the objects an object stream holds."""
    count, first = pdf.get(d.get("N")), pdf.get(d.get("First"))
    if type(count) is not int or type(first) is not int:
        raise Unreadable("an object stream has no /N or /First")
    header = [t for t in tokens(data[:first]) if type(t) is int]
    pairs = list(zip(header[::2], header[1::2]))[:count]
    for k, (num, offset) in enumerate(pairs):
        end = first + pairs[k + 1][1] if k + 1 < len(pairs) else len(data)
        values = parse(list(tokens(data[first + offset : end])))
        pdf.objects.setdefault(num, Obj(values[0] if values else None))


def decode(pdf: Pdf, d: dict, data: bytes) -> bytes:
    filters = pdf.get(d.get("Filter"))
    filters = [] if filters is None else filters if isinstance(filters, list) else [filters]
    parms = pdf.get(d.get("DecodeParms"))
    for p in parms if isinstance(parms, list) else [parms]:
        if isinstance(p, dict) and pdf.get(p.get("Predictor", 1)) != 1:
            raise Unreadable("a stream uses a predictor")
    for f in map(pdf.get, filters):
        if f != "FlateDecode":
            raise Unreadable(f"a stream uses the {f} filter")
        try:
            data = zlib.decompressobj().decompress(data)
        except zlib.error as e:
            raise Unreadable(f"a stream doesn't inflate ({e})") from e
    return data


# ---- The text on the pages ------------------------------------------------------------------


@dataclass
class Font:
    codes: dict[bytes, str]
    widths: list[int]  # how many bytes a character code takes
    codec: str | None  # for codes the map leaves out; None for a composite font, which has none

    def text(self, s: bytes) -> str:
        out, i = [], 0
        while i < len(s):
            w = next((w for w in self.widths if s[i : i + w] in self.codes), None)
            if w:
                out.append(self.codes[s[i : i + w]])
            elif self.codec:
                w = 1
                out.append(s[i : i + 1].decode(self.codec, "replace"))
            else:
                w = self.widths[-1]
                out.append("�")
            i += w
        return "".join(out)


def utf16(b: bytes) -> str:
    return b.decode("utf-16-be", "replace")


def font(pdf: Pdf, ref: object) -> Font:
    d = pdf.dict(ref)
    composite = d.get("Subtype") == "Type0"
    codes: dict[bytes, str] = {}
    widths = set() if composite else {1}
    encoding = pdf.get(d.get("Encoding"))
    codec = None if composite else CODECS.get(str(encoding), "cp1252")
    if not composite and isinstance(encoding, dict):
        codec = CODECS.get(str(pdf.get(encoding.get("BaseEncoding"))), "cp1252")
        code = 0
        for item in pdf.get(encoding.get("Differences")) or []:
            if type(item) is int:
                code = item
            elif isinstance(item, Name):
                uni = re.fullmatch(r"uni([0-9A-Fa-f]{4})", item)
                char = chr(int(uni[1], 16)) if uni else GLYPHS.get(item, item if len(item) == 1 else "�")
                codes[bytes([code & 0xFF])] = char
                code += 1
    if "ToUnicode" in d:
        cmap = pdf.stream(d["ToUnicode"])
        for block in re.findall(rb"begincodespacerange(.*?)endcodespacerange", cmap, re.S):
            widths.update(len(t) for t in tokens(block) if isinstance(t, bytes))
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.S):
            t = [x for x in tokens(block) if isinstance(x, bytes)]
            codes.update((src, utf16(dst)) for src, dst in zip(t[::2], t[1::2]))
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", cmap, re.S):
            items = parse(list(tokens(block)))
            for lo, hi, dst in zip(items[::3], items[1::3], items[2::3]):
                if not isinstance(lo, bytes) or not isinstance(hi, bytes):
                    continue
                start = int.from_bytes(lo, "big")
                for k in range(min(int.from_bytes(hi, "big") - start + 1, 65536)):
                    src = (start + k).to_bytes(len(lo), "big")
                    if isinstance(dst, list):
                        codes[src] = utf16(dst[k]) if k < len(dst) and isinstance(dst[k], bytes) else "�"
                    elif isinstance(dst, bytes) and len(dst) >= 2:
                        codes[src] = utf16(dst[:-2] + ((int.from_bytes(dst[-2:], "big") + k) & 0xFFFF).to_bytes(2, "big"))
        widths.update(len(k) for k in codes)
    elif composite:
        raise Unreadable(f"font {pdf.get(d.get('BaseFont'))} has no ToUnicode map, so its text can't be read")
    return Font(codes, sorted(widths or {2}), codec)


def pages(pdf: Pdf) -> list[dict]:
    """The pages in reading order, then any page object the page tree leaves out."""
    found: list[dict] = []
    seen: set[int] = set()

    def walk(ref: object, depth: int) -> None:
        if depth > 64 or (isinstance(ref, Ref) and ref.num in seen):
            return
        if isinstance(ref, Ref):
            seen.add(ref.num)
        node = pdf.dict(ref)
        if node.get("Type") == "Page":
            found.append(node)
        for kid in pdf.get(node.get("Kids")) or []:
            walk(kid, depth + 1)

    for t in pdf.trailers:
        walk(pdf.dict(t.get("Root")).get("Pages"), 0)
    for num, obj in pdf.objects.items():
        if num not in seen and isinstance(obj.value, dict) and obj.value.get("Type") == "Page":
            found.append(obj.value)
    return found


def resources(pdf: Pdf, node: dict) -> dict:
    """A page's resources, inherited from the page tree if it has none of its own."""
    for _ in range(64):
        if isinstance(res := pdf.get(node.get("Resources")), dict):
            return res
        node = pdf.dict(node.get("Parent"))
    return {}


def text(pdf: Pdf, content: bytes, res: dict, depth: int = 0) -> tuple[str, str]:
    """A content stream's text twice: with a break at every move, and with no breaks at all,
    so a number drawn a piece at a time still reads as one."""
    spaced: list[str] = []
    joined: list[str] = []
    fonts, xobjects = pdf.dict(res.get("Font")), pdf.dict(res.get("XObject"))
    current: Font | None = None
    operands: list[object] = []
    for t in parse(list(tokens(content))):
        if not isinstance(t, Op):
            operands.append(t)
            continue
        if t == "Tf" and len(operands) >= 2:
            if operands[-2] not in fonts:
                raise Unreadable(f"a page uses font {operands[-2]}, which it doesn't define")
            current = font(pdf, fonts[operands[-2]])
        elif t in ("Tj", "TJ", "'", '"') and operands:
            if current is None:
                raise Unreadable("text is drawn before a font is chosen")
            if t != "Tj":
                spaced.append("\n")
            for part in operands[-1] if isinstance(operands[-1], list) else [operands[-1]]:
                if isinstance(part, bytes):
                    s = current.text(part)
                    spaced.append(s)
                    joined.append(s)
                elif isinstance(part, (int, float)) and part < -250:
                    spaced.append(" ")
        elif t in ("Td", "TD", "Tm", "T*", "BT", "ET"):
            spaced.append("\n")
        elif t == "Do" and operands and depth < 8:
            xo = xobjects.get(operands[-1])
            form = pdf.dict(xo)
            if form.get("Subtype") == "Form":
                inner = form.get("Resources")
                s, j = text(pdf, pdf.stream(xo), pdf.dict(inner) if inner is not None else res, depth + 1)
                spaced.append(f"\n{s}\n")
                joined.append(j)
        operands = []
    return "".join(spaced), "".join(joined)


# ---- The check ------------------------------------------------------------------------------


def strings(v: object) -> Iterator[bytes]:
    if isinstance(v, bytes):
        yield v
    elif isinstance(v, (list, dict)):
        for x in v.values() if isinstance(v, dict) else v:
            yield from strings(x)


def as_text(b: bytes) -> str:
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    return b.decode("latin-1")


def mask(s: str) -> str:
    return re.sub(r"[^\W_]", "•", " ".join(s.split()))


def check(data: bytes) -> tuple[list[str], str]:
    """The problems in one PDF, already masked, and a summary of what was read."""
    pdf = load(data)
    if data.count(b"startxref") > 1 or any("Prev" in t for t in pdf.trailers):
        raise Unreadable("it was saved incrementally, so an earlier version can still be inside; export it again")
    if any("Encrypt" in t for t in pdf.trailers):
        raise Unreadable("it's encrypted")
    places: list[tuple[str, str]] = []
    chars = 0
    for n, page in enumerate(pages(pdf), 1):
        contents = page.get("Contents")
        refs = pdf.get(contents)
        refs = refs if isinstance(refs, list) else [] if contents is None else [contents]
        spaced, joined = text(pdf, b"\n".join(pdf.stream(r) for r in refs), resources(pdf, page))
        places += [(f"the text of page {n}", spaced), (f"the text of page {n}", joined)]
        chars += len(joined)
    if not places:
        raise Unreadable("it has no pages")
    if not chars:
        raise Unreadable("it has no readable text (a scan or a picture?), so it can't be checked")
    for obj in pdf.objects.values():
        d = obj.value if isinstance(obj.value, dict) else {}
        if d.get("Type") == "EmbeddedFile" or "EF" in d or "EmbeddedFiles" in d or "EmbeddedFiles" in pdf.dict(d.get("Names")):
            raise Unreadable("it has an attached file")
        if d.get("Type") == "Metadata" or d.get("Subtype") == "XML":
            places.append(("the XMP metadata", decode(pdf, d, obj.stream or b"").decode("utf-8", "replace")))
        places += [("the metadata, a link or alt text", as_text(s)) for s in strings(obj.value)]
    for t in pdf.trailers:
        if isinstance(info := t.get("Info"), dict):  # written into the trailer, not as an object
            places += [("the metadata, a link or alt text", as_text(s)) for s in strings(info)]
    found = {f"{label} in {where}: {mask(m[0])}" for where, s in places for label, p in PATTERNS.items() for m in p.finditer(s)}
    return sorted(found), f"{len(pages(pdf))} pages, {chars} characters of text"


# ---- Where the files come from --------------------------------------------------------------


def git(*args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], input=stdin, check=True, capture_output=True).stdout


def staged() -> Iterator[tuple[str, bytes]]:
    """Each file staged for commit, as the index has it (not the working tree)."""
    for path in git("-c", "core.quotePath=false", "diff", "--cached", "--name-only", "-z", "--diff-filter=d").split(b"\0"):
        if path:
            name = path.decode("utf-8", "surrogateescape")
            yield name, git("cat-file", "blob", f":{name}")


def history() -> Iterator[tuple[str, bytes]]:
    """Every file in HEAD's history, once each, under a path it had."""
    names: dict[str, str] = {}
    for line in git("rev-list", "--objects", "HEAD").decode("utf-8", "surrogateescape").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            names.setdefault(sha, path)
    kinds = git("cat-file", "--batch-check=%(objectname) %(objecttype)", stdin="\n".join(names).encode()).split()
    for sha, kind in zip(kinds[::2], kinds[1::2]):
        if kind == b"blob":
            sha = sha.decode()
            yield f"{names[sha]} (blob {sha[:12]})", git("cat-file", "blob", sha)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--staged", action="store_true", help="check the files staged for commit")
    p.add_argument("--history", action="store_true", help="check every file in HEAD's history")
    p.add_argument("files", nargs="*", help="files to check")
    args = p.parse_args(argv)
    if (args.staged, args.history, bool(args.files)).count(True) != 1:
        p.error("give files, --staged or --history (one of them)")
    source = staged() if args.staged else history() if args.history else ((f, Path(f).read_bytes()) for f in args.files)
    checked = failed = 0
    for label, data in source:
        if MAGIC not in data[:1024]:
            continue
        checked += 1
        try:
            found, summary = check(data)
        except Exception as e:  # anything it can't read is a failure, never a pass
            found, summary = [f"can't be checked: {e if isinstance(e, Unreadable) else type(e).__name__}"], ""
        if found:
            failed += 1
            print("\n".join(f"{label}: {line}" for line in found))
        else:
            print(f"{label}: ok ({summary})")
    print(f"{checked} PDFs checked for phone numbers, street addresses and local paths, {failed} with problems")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
