"""Codo 27.11.2026: narzędzia plików agenta (audyt silnika). Offline, bez backendu i bez modeli.

Kodowania (cp1250, UTF-16, BOM), końce linii, duże i binarne pliki, edycja z tolerancją,
zapis atomowy i pliki tylko do odczytu, ścieżki, kopie i /undo, formaty biurowe, obrazy, grep."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ["CODO_MADDLABS_DIRECT"] = "1"
os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-test-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
os.environ.setdefault("CODO_LANG", "pl")
loader = importlib.machinery.SourceFileLoader(
    "codo_silnik_pliki", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)

PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx() -> bytes:
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>'
           '<w:p><w:r><w:t>Zażółć gęślą jaźń</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Drugi akapit</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Nazwa</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>Cena</w:t></w:r></w:p></w:tc></w:tr>'
           '<w:tr><w:tc><w:p><w:r><w:t>Kawa</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": doc})


def make_xlsx() -> bytes:
    R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": f'<workbook {R}><sheets><sheet name="Dane" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": "<sst><si><t>Produkt</t></si><si><t>Ilość</t></si><si><t>Jabłka</t></si></sst>",
        "xl/worksheets/sheet1.xml": ('<worksheet><sheetData>'
                                     '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                     '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>7</v></c>'
                                     '<c r="C2"><f>B2*2</f><v>14</v></c></row>'
                                     '</sheetData></worksheet>'),
    })


def make_pptx() -> bytes:
    P = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

    def slide(title, body):
        return (f'<p:sld {P}><p:cSld><p:spTree>'
                f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>'
                f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:txBody>'
                + "".join(f"<a:p><a:r><a:t>{b}</a:t></a:r></a:p>" for b in body)
                + '</p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "ppt/presentation.xml": f'<p:presentation {P}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": ('<Relationships><Relationship Id="rId2" Target="slides/slide1.xml"/>'
                                            '<Relationship Id="rId3" Target="slides/slide2.xml"/></Relationships>'),
        "ppt/slides/slide1.xml": slide("Plan na rok", ["Wstęp"]),
        "ppt/slides/slide2.xml": slide("Budżet", ["Koszty spadną", "Przychody wzrosną"]),
    })


def make_pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


class InFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve()
        cli.EDIT_LOG.clear()
        cli._FILE_OP_LOG.clear()
        cli._OUTSIDE_OK.clear()
        cli._VISION_QUEUE.clear()
        cli.SESSION["edited"] = []

    def tearDown(self):
        os.chdir(self.prev)
        for p in self.root.rglob("*"):
            with contextlib.suppress(OSError):
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
        self.tmp.cleanup()

    def run_tool(self, name, args):
        """Jak pętla agenta: wynik narzędzia + zapamiętanie edytowanych plików dla /undo."""
        seq = cli._EDIT_SEQ[0]
        out = cli.run_tool(name, args, True)
        for e in cli.EDIT_LOG:
            if e["seq"] > seq and e["path"] not in cli.SESSION["edited"]:
                cli.SESSION["edited"].append(e["path"])
        return out

    def undo(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            cli._undo_last()
        return buf.getvalue()


class Encodings(InFolder):
    def test_cp1250_read_and_edit_keep_polish_bytes(self):
        Path("stara.html").write_bytes("<p>Zażółć gęślą jaźń</p>\r\n<p>Łódź</p>\r\n".encode("cp1250"))
        out = cli.t_read_file({"path": "stara.html"})
        self.assertIn("Zażółć gęślą jaźń", out)
        self.assertIn("kodowanie cp1250", out)
        r = self.run_tool("edit_file", {"path": "stara.html", "old_string": "Łódź", "new_string": "Kraków ąę"})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("stara.html").read_bytes(),
                         "<p>Zażółć gęślą jaźń</p>\r\n<p>Kraków ąę</p>\r\n".encode("cp1250"))

    def test_cp1250_refuses_chars_outside_encoding(self):
        Path("f.txt").write_bytes("zażółć\n".encode("cp1250"))
        r = cli.t_edit_file({"path": "f.txt", "old_string": "zażółć", "new_string": "emoji 😀"})
        self.assertIn("kodowaniu cp1250", r)
        self.assertEqual(Path("f.txt").read_bytes(), "zażółć\n".encode("cp1250"))

    def test_utf16_bom_is_text_and_round_trips(self):
        raw = "\ufeffimię=Łukasz\r\nmiasto=Gdańsk\r\n".encode("utf-16-le")
        Path("dane.txt").write_bytes(raw)
        self.assertFalse(cli._is_binary(Path("dane.txt")))
        out = cli.t_read_file({"path": "dane.txt"})
        self.assertIn("1\timię=Łukasz", out)
        self.assertNotIn("\ufeff", out)
        r = self.run_tool("edit_file", {"path": "dane.txt", "old_string": "Gdańsk", "new_string": "Poznań"})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("dane.txt").read_bytes(), "\ufeffimię=Łukasz\r\nmiasto=Poznań\r\n".encode("utf-16-le"))

    def test_utf16_be_and_without_bom(self):
        Path("be.txt").write_bytes("\ufeffzółw\n".encode("utf-16-be"))
        self.assertIn("1\tzółw", cli.t_read_file({"path": "be.txt"}))
        Path("nobom.txt").write_bytes("Windows PowerShell log\r\nlinia druga\r\n".encode("utf-16-le"))
        self.assertIn("2\tlinia druga", cli.t_read_file({"path": "nobom.txt"}))
        cli.t_edit_file({"path": "nobom.txt", "old_string": "druga", "new_string": "trzecia"})
        self.assertEqual(Path("nobom.txt").read_bytes(), "Windows PowerShell log\r\nlinia trzecia\r\n".encode("utf-16-le"))

    def test_utf8_bom_kept_and_hidden(self):
        Path("a.css").write_bytes(b"\xef\xbb\xbfbody { color: red; }\n")
        self.assertIn("1\tbody", cli.t_read_file({"path": "a.css"}))
        cli.t_edit_file({"path": "a.css", "old_string": "red", "new_string": "blue"})
        self.assertEqual(Path("a.css").read_bytes(), b"\xef\xbb\xbfbody { color: blue; }\n")

    def test_old_mac_cr_line_endings(self):
        Path("cr.txt").write_bytes(b"a\rb\rc\r")
        self.assertIn("2\tb", cli.t_read_file({"path": "cr.txt"}))
        cli.t_replace_lines({"path": "cr.txt", "start_line": 2, "new_string": "B"})
        self.assertEqual(Path("cr.txt").read_bytes(), b"a\rB\rc\r")


class LineEndings(InFolder):
    def setUp(self):
        super().setUp()
        Path("w.txt").write_bytes(b"jeden\r\ndwa\r\ntrzy\r\n")

    def test_edit_keeps_crlf(self):
        cli.t_edit_file({"path": "w.txt", "old_string": "dwa\ntrzy", "new_string": "2\n3\n3.5"})
        self.assertEqual(Path("w.txt").read_bytes(), b"jeden\r\n2\r\n3\r\n3.5\r\n")

    def test_multi_edit_replace_insert_write_keep_crlf(self):
        cli.t_multi_edit({"path": "w.txt", "edits": [{"old_string": "jeden", "new_string": "1"},
                                                      {"old_string": "trzy", "new_string": "3"}]})
        self.assertEqual(Path("w.txt").read_bytes(), b"1\r\ndwa\r\n3\r\n")
        cli.t_insert_lines({"path": "w.txt", "line": -1, "new_string": "4"})
        self.assertEqual(Path("w.txt").read_bytes(), b"1\r\ndwa\r\n3\r\n4\r\n")
        cli.t_replace_lines({"path": "w.txt", "start_line": 2, "new_string": "2"})
        self.assertEqual(Path("w.txt").read_bytes(), b"1\r\n2\r\n3\r\n4\r\n")
        cli.t_write_file({"path": "w.txt", "content": "x\ny\n"})
        self.assertEqual(Path("w.txt").read_bytes(), b"x\r\ny\r\n")


class BigAndBinary(InFolder):
    def test_big_file_read_in_chunks(self):
        Path("log.txt").write_text("".join(f"wiersz {i}\n" for i in range(1, 5001)), encoding="utf-8")
        with patch.object(cli, "_BIG_TEXT", 1000):
            out = cli._read_one("log.txt", 4000, 3)
            self.assertIn("4000\twiersz 4000", out)
            self.assertIn("4002\twiersz 4002", out)
            self.assertIn("dalej: offset=4003", out)
            self.assertIn("za końcem", cli._read_one("log.txt", 9000, 3))
            self.assertIn("5000\twiersz 5000", cli._read_one("log.txt", 4999, 10))

    def test_binary_reported_and_not_editable(self):
        Path("prog.bin").write_bytes(b"\x00\x01\x02\x03" * 100)
        self.assertIn("plik binarny", cli.t_read_file({"path": "prog.bin"}))
        r = cli.t_edit_file({"path": "prog.bin", "old_string": "\x01", "new_string": "x"})
        self.assertIn("binarny", r)
        Path("a.zip").write_bytes(_zip({"x.txt": "x"}))
        self.assertEqual(cli._binary_kind(Path("a.zip")), "ZIP")
        Path("d.docx").write_bytes(make_docx())
        self.assertIn("DOCX", cli.t_edit_file({"path": "d.docx", "old_string": "Zażółć", "new_string": "x"}))

    def test_huge_text_edit_blocked_with_hint(self):
        Path("big.sql").write_text("x\n" * 10, encoding="utf-8")
        with patch.object(cli, "_EDIT_TEXT_MAX", 5):
            self.assertIn("run_command", cli.t_edit_file({"path": "big.sql", "old_string": "x", "new_string": "y"}))


class EditTolerance(InFolder):
    def test_ambiguous_lists_line_numbers(self):
        Path("f.py").write_text("x = 1\ny = 2\nx = 1\n")
        r = cli.t_edit_file({"path": "f.py", "old_string": "x = 1", "new_string": "x = 3"})
        self.assertIn("2×", r)
        self.assertIn("linie 1, 3", r)
        self.assertEqual(Path("f.py").read_text(), "x = 1\ny = 2\nx = 1\n")

    def test_not_found_shows_most_similar_fragment(self):
        Path("f.py").write_text("def a():\n    pass\n\n\ndef policz(cena, ilosc):\n    return cena * ilosc\n")
        r = cli.t_edit_file({"path": "f.py", "old_string": "def policz(cena, ilość):\n    return cena * ilość",
                             "new_string": "x"})
        self.assertTrue(r.startswith("BŁĄD"), r)
        self.assertIn("linie 5-6", r)
        self.assertIn("5\tdef policz(cena, ilosc):", r)

    def test_trailing_whitespace_tolerated(self):
        Path("f.js").write_text("const a = 1;   \nconst b = 2;\t\n")
        r = cli.t_edit_file({"path": "f.js", "old_string": "const a = 1;\nconst b = 2;", "new_string": "const c = 3;"})
        self.assertIn("spacje na końcu", r)
        self.assertEqual(Path("f.js").read_text(), "const c = 3;\n")

    def test_indent_tolerated_and_new_string_reindented(self):
        Path("f.py").write_text("class A:\n    def f(self):\n        return 1\n")
        r = cli.t_edit_file({"path": "f.py", "old_string": "def f(self):\n    return 1",
                             "new_string": "def f(self):\n    x = 2\n    return x"})
        self.assertIn("inne wcięcie", r)
        self.assertEqual(Path("f.py").read_text(), "class A:\n    def f(self):\n        x = 2\n        return x\n")

    def test_line_number_prefixes_from_read_file_stripped(self):
        Path("f.txt").write_text("alfa\nbeta\ngamma\n")
        r = cli.t_edit_file({"path": "f.txt", "old_string": "     2\tbeta\n     3\tgamma", "new_string": "BETA\nGAMMA"})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("f.txt").read_text(), "alfa\nBETA\nGAMMA\n")

    def test_typographic_quotes_and_inline_spaces(self):
        Path("f.html").write_text('<p class="a">Mówi „cześć” — i idzie</p>\n')
        r = cli.t_edit_file({"path": "f.html", "old_string": 'Mówi "cześć" - i  idzie', "new_string": "Wychodzi"})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("f.html").read_text(), '<p class="a">Wychodzi</p>\n')

    def test_tolerance_never_guesses_between_two_places(self):
        Path("f.py").write_text("if a:\n    go()\nif b:\n  if a:\n      go()\n")
        r = cli.t_edit_file({"path": "f.py", "old_string": "if a:\n  go()", "new_string": "x"})
        self.assertIn("2 miejscach", r)

    def test_multi_edit_atomic_with_hint_and_replace_all(self):
        Path("f.txt").write_text("a\nb\na\n")
        r = cli.t_multi_edit({"path": "f.txt", "edits": [{"old_string": "b", "new_string": "B"},
                                                          {"old_string": "zzz", "new_string": "q"}]})
        self.assertIn("edit #2 z 2", r)
        self.assertIn("NIE zostały zapisane", r)
        self.assertEqual(Path("f.txt").read_text(), "a\nb\na\n")
        r = cli.t_multi_edit({"path": "f.txt", "edits": json.dumps([{"old_string": "a", "new_string": "A", "replace_all": True}])})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("f.txt").read_text(), "A\nb\nA\n")

    def test_identical_and_missing_file(self):
        Path("f.txt").write_text("a\n")
        self.assertIn("identyczne", cli.t_edit_file({"path": "f.txt", "old_string": "a", "new_string": "a"}))
        self.assertIn("write_file", cli.t_edit_file({"path": "nowy.txt", "old_string": "a", "new_string": "b"}))


class AtomicWrite(InFolder):
    def test_read_only_file_is_not_overwritten(self):
        Path("ro.txt").write_text("stare\n")
        os.chmod("ro.txt", 0o444)
        r = cli.t_edit_file({"path": "ro.txt", "old_string": "stare", "new_string": "nowe"})
        self.assertIn("tylko do odczytu", r)
        self.assertEqual(Path("ro.txt").read_text(), "stare\n")
        with self.assertRaises(PermissionError):
            cli._atomic_write(Path("ro.txt").resolve(), b"x")

    def test_mode_kept_and_no_temp_left(self):
        Path("run.sh").write_text("echo 1\n")
        os.chmod("run.sh", 0o750)
        cli.t_edit_file({"path": "run.sh", "old_string": "1", "new_string": "2"})
        self.assertEqual(stat.S_IMODE(os.stat("run.sh").st_mode), 0o750)
        self.assertEqual([p.name for p in Path(".").iterdir() if p.name.endswith(".codo-tmp")], [])

    def test_windows_lock_is_retried_then_explained(self):
        target = Path("f.txt").resolve()
        target.write_text("a")
        real = os.replace
        calls = []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "used by another process")
            return real(a, b)
        with patch.object(cli.os, "name", "nt"), patch.object(cli, "_long_path", lambda p: p), \
                patch.object(cli.os, "replace", flaky), patch.object(cli._time if hasattr(cli, "_time") else __import__("time"), "sleep", lambda s: None):
            cli._atomic_write(target, b"b")
        self.assertEqual(target.read_text(), "b")
        self.assertEqual(len(calls), 3)
        e = PermissionError(13, "x")
        e.winerror = 32
        self.assertIn("otwarty w innym programie", cli._write_error(target, e))


class Paths(InFolder):
    def test_quoted_file_url_and_at_paths(self):
        Path("moj plik.txt").write_text("treść\n")
        self.assertIn("treść", cli.t_read_file({"path": '"moj plik.txt"'}))
        self.assertIn("treść", cli.t_read_file({"path": "@moj plik.txt"}))
        self.assertIn("treść", cli.t_read_file({"path": (self.root / "moj plik.txt").as_uri()}))

    def test_outside_project_refused_without_consent(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        f = Path(other.name) / "sekret.txt"
        f.write_text("tajne")
        with patch.object(cli, "_can_ask_outside", lambda: False):
            r = cli.t_read_file({"path": str(f)})
            self.assertIn("poza folderem projektu", r)
            r = cli.run_tool("write_file", {"path": str(f), "content": "x"}, True)
            self.assertIn("poza", cli.t_read_file({"path": os.path.relpath(f, self.root)}))
        self.assertTrue(r.startswith("BŁĄD"), r)
        self.assertEqual(f.read_text(), "tajne")

    def test_outside_project_with_consent_has_backup_and_undo(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        f = Path(other.name).resolve() / "notatka.txt"
        f.write_text("stara\n")
        asked = []
        with patch.object(cli, "_can_ask_outside", lambda: True), \
                patch.object(cli, "confirm_action", lambda *a, **k: asked.append(a) or True):
            r = self.run_tool("edit_file", {"path": str(f), "old_string": "stara", "new_string": "nowa"})
            self.assertFalse(r.startswith("BŁĄD"), r)
            self.run_tool("edit_file", {"path": str(f), "old_string": "nowa", "new_string": "najnowsza"})
        self.assertEqual(len(asked), 1)   # zgoda zapamiętana na folder
        self.assertEqual(f.read_text(), "najnowsza\n")
        self.assertTrue(list((self.root / ".doma/backups/_poza").rglob("notatka.txt.*.bak")))
        self.undo()
        self.assertEqual(f.read_text(), "nowa\n")
        self.undo()
        self.assertEqual(f.read_text(), "stara\n")

    def test_parallel_read_outside_project_does_not_ask(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        f = Path(other.name) / "a.txt"
        f.write_text("x")
        Path("b.txt").write_text("y")
        calls = [{"id": "1", "function": {"name": "read_file", "arguments": json.dumps({"path": str(f)})}},
                 {"id": "2", "function": {"name": "read_file", "arguments": json.dumps({"path": "b.txt"})}}]
        with patch.object(cli, "_can_ask_outside", lambda: True), \
                patch.object(cli, "confirm_action", side_effect=AssertionError("pytanie w wątku")):
            out = cli._parallel_reads(calls, "ask")
        self.assertNotIn("1", out)   # policzy się po kolei, z pytaniem
        self.assertIn("y", out["2"])


class BackupsUndo(InFolder):
    def test_many_edits_of_one_file_undo_step_by_step(self):
        self.run_tool("write_file", {"path": "f.txt", "content": "v1\n"})
        for v in ("v2", "v3", "v4"):
            prev = Path("f.txt").read_text().strip()
            self.run_tool("edit_file", {"path": "f.txt", "old_string": prev, "new_string": v})
        self.assertEqual(Path("f.txt").read_text(), "v4\n")
        for want in ("v3\n", "v2\n", "v1\n"):
            self.undo()
            self.assertEqual(Path("f.txt").read_text(), want)
        self.undo()
        self.assertFalse(Path("f.txt").exists())   # nowy plik: cofnięcie = usunięcie
        self.assertIn("Nic do cofnięcia", self.undo())

    def test_every_write_tool_backs_up(self):
        Path("f.txt").write_text("a\nb\n")
        for name, args in (("edit_file", {"old_string": "a", "new_string": "A"}),
                           ("multi_edit", {"edits": [{"old_string": "b", "new_string": "B"}]}),
                           ("replace_lines", {"start_line": 1, "new_string": "1"}),
                           ("insert_lines", {"line": 0, "new_string": "0"}),
                           ("write_file", {"content": "nowe\n"})):
            r = self.run_tool(name, {"path": "f.txt", **args})
            self.assertFalse(r.startswith("BŁĄD"), (name, r))
        _, baks = cli._backups_for(self.root / "f.txt")
        self.assertEqual(len(baks), 5)
        for want in ("0\n1\nB\n", "1\nB\n", "A\nB\n", "A\nb\n", "a\nb\n"):
            self.undo()
            self.assertEqual(Path("f.txt").read_text(), want)

    def test_file_ops_are_undoable(self):
        Path("a.txt").write_text("A")
        Path("b.txt").write_text("B")
        self.assertIn("Przeniesiono", self.run_tool("file_op", {"action": "rename", "path": "a.txt", "dest": "c.txt"}))
        self.assertIn("Skopiowano", self.run_tool("file_op", {"action": "copy", "path": "c.txt", "dest": "b.txt",
                                                               "overwrite": True}))
        self.assertEqual(Path("b.txt").read_text(), "A")
        self.assertIn("Usunięto", self.run_tool("file_op", {"action": "delete", "path": "c.txt"}))
        self.assertFalse(Path("c.txt").exists())
        self.undo()   # usunięcie
        self.assertEqual(Path("c.txt").read_text(), "A")
        self.undo()   # kopia z nadpisaniem: b.txt wraca
        self.assertEqual(Path("b.txt").read_text(), "B")
        self.undo()   # przeniesienie
        self.assertEqual(Path("a.txt").read_text(), "A")
        self.assertFalse(Path("c.txt").exists())

    def test_file_op_guards(self):
        Path("d").mkdir()
        self.assertIn("własnego wnętrza", cli.t_file_op({"action": "move", "path": "d", "dest": "d/x"}))
        self.assertIn(".doma", cli.t_file_op({"action": "mkdir", "path": ".doma/x"}) + cli.t_file_op(
            {"action": "delete", "path": ".doma"}, auto_yes=True))

    def test_rename_only_letter_case(self):
        """NTFS/APFS: „Raport.TXT” → „raport.txt” to ta sama pozycja; overwrite=true nie może usunąć pliku."""
        Path("Raport.TXT").write_text("treść\n")
        Path("Dir").mkdir()
        Path("Dir/x.txt").write_text("x")
        if not Path("raport.txt").exists():
            self.skipTest("system plików rozróżnia wielkość liter")
        r = cli.t_file_op({"action": "rename", "path": "Raport.TXT", "dest": "raport.txt", "overwrite": True})
        self.assertNotIn("BŁĄD", r)
        self.assertIn("raport.txt", os.listdir("."))
        self.assertEqual(Path("raport.txt").read_text(), "treść\n")
        r = cli.t_file_op({"action": "move", "path": "Dir", "dest": "dir"})
        self.assertNotIn("BŁĄD", r)
        self.assertIn("dir", os.listdir("."))
        self.assertEqual(Path("dir/x.txt").read_text(), "x")

    def test_scaffold_and_write_page_go_through_undo(self):
        r = self.run_tool("scaffold", {"template": "static", "path": "site"})
        self.assertIn("utworzono", r)
        created = [e["path"] for e in cli.EDIT_LOG]
        self.assertTrue(created and all(e["new_file"] for e in cli.EDIT_LOG))
        Path("p.html").write_bytes("<p>Łódź</p>\r\n".encode("cp1250"))
        self.assertIn("Łódź", cli.t_read_raw({"path": "p.html"}))
        r = self.run_tool("write_page", {"path": "p.html", "content": "<p>Gdańsk</p>\n"})
        self.assertFalse(r.startswith("BŁĄD"), r)
        self.assertEqual(Path("p.html").read_bytes(), "<p>Gdańsk</p>\r\n".encode("cp1250"))
        self.undo()
        self.assertEqual(Path("p.html").read_bytes(), "<p>Łódź</p>\r\n".encode("cp1250"))
        self.assertTrue(all(p.exists() for p in created))


class Formats(InFolder):
    def test_docx(self):
        Path("umowa.docx").write_bytes(make_docx())
        out = cli.t_read_file({"path": "umowa.docx"})
        self.assertIn("DOCX", out)
        self.assertIn("Zażółć gęślą jaźń", out)
        self.assertIn("Drugi akapit", out)
        self.assertIn("Kawa", out)
        self.assertIn("12", out)

    def test_xlsx(self):
        Path("dane.xlsx").write_bytes(make_xlsx())
        with patch.object(cli, "_xlsx_text_openpyxl", lambda p: None):   # wersja bez bibliotek
            out = cli.t_read_file({"path": "dane.xlsx"})
        self.assertIn("Produkt | Ilość", out)
        self.assertIn("Jabłka | 7 | 14 {=B2*2}", out)

    def test_pptx(self):
        Path("deck.pptx").write_bytes(make_pptx())
        out = cli.t_read_file({"path": "deck.pptx"})
        self.assertIn("--- slajd 1 ---", out)
        self.assertIn("Plan na rok", out)
        self.assertIn("--- slajd 2 ---", out)
        self.assertIn("Przychody wzrosną", out)

    def test_pdf_builtin(self):
        Path("f.pdf").write_bytes(make_pdf("Faktura numer 7"))
        with patch.object(cli.shutil if hasattr(cli, "shutil") else __import__("shutil"), "which", lambda n: None):
            out = cli.t_read_file({"path": "f.pdf"})
        self.assertIn("Faktura numer 7", out)

    def test_odt(self):
        Path("t.odt").write_bytes(_zip({"mimetype": "application/vnd.oasis.opendocument.text",
                                        "content.xml": "<office:document-content><office:body><office:text>"
                                                       "<text:h>Tytuł</text:h><text:p>Treść &amp; więcej</text:p>"
                                                       "</office:text></office:body></office:document-content>"}))
        out = cli.t_read_file({"path": "t.odt"})
        self.assertIn("Tytuł", out)
        self.assertIn("Treść & więcej", out)

    def test_ipynb(self):
        nb = {"cells": [{"cell_type": "markdown", "source": ["# Analiza\n"]},
                        {"cell_type": "code", "source": ["print(2+2)"], "outputs": [{"output_type": "stream", "text": ["4\n"]}]}],
              "metadata": {"kernelspec": {"language": "python"}}}
        Path("a.ipynb").write_text(json.dumps(nb), encoding="utf-8")
        out = cli.t_read_file({"path": "a.ipynb"})
        self.assertIn("komórka 2 [code, python]", out)
        self.assertIn("print(2+2)", out)
        self.assertIn("# 4", out)

    def test_csv_plain_text(self):
        Path("a.csv").write_bytes("nazwa;cena\r\nmąka;3,50\r\n".encode("cp1250"))
        self.assertIn("2\tmąka;3,50", cli.t_read_file({"path": "a.csv"}))


class Images(InFolder):
    def test_png_queued_for_model_and_detached_after_step(self):
        Path("logo.png").write_bytes(PNG_1x1)
        out = cli.t_read_file({"path": "logo.png"})
        self.assertIn("1×1 px", out)
        self.assertEqual(len(cli._VISION_QUEUE), 1)
        msgs = [{"role": "user", "content": "x"}]
        self.assertEqual(cli._vision_attach(msgs), 1)
        part = msgs[-1]["content"][1]
        self.assertTrue(part["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertLess(cli._content_len(msgs[-1]), 2000)
        cli._vision_detach(msgs)
        self.assertIsInstance(msgs[-1]["content"], str)
        self.assertIn("logo.png", msgs[-1]["content"])
        self.assertNotIn("_codo_image", msgs[-1])

    def _turn(self, fail_first_image=False):
        Path("logo.png").write_bytes(PNG_1x1)
        seen = []

        def step(creds, body):
            msgs = body["messages"]
            has_img = any(isinstance(m.get("content"), list) for m in msgs)
            seen.append(has_img)
            if fail_first_image and has_img:
                raise cli.ApiError(400, "image input not supported")
            if len(seen) == 1:
                return {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read_file",
                                                                  "arguments": json.dumps({"path": "logo.png"})}}]}}
            return {"message": {"role": "assistant", "content": "Widzę logo."}}
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "co jest na logo.png?"}]
        cli.SESSION.update(turn_steps=0, turn_spent=0)
        with patch.object(cli, "api_step", side_effect=step), patch.object(cli, "provider", lambda: "endpoint"), \
                contextlib.redirect_stdout(io.StringIO()):
            ok = cli._agent_turn({}, msgs, "@test/model", True, tools=cli.TOOLS, max_steps=4)
        return ok, seen, msgs

    def test_agent_turn_shows_image_once_and_keeps_history_text(self):
        ok, seen, msgs = self._turn()
        self.assertTrue(ok)
        self.assertEqual(seen, [False, True])
        self.assertTrue(all(isinstance(m.get("content"), (str, type(None))) for m in msgs))
        self.assertTrue(any("Obraz z read_file" in str(m.get("content")) for m in msgs))

    def test_agent_turn_model_without_vision_gets_text_only(self):
        ok, seen, msgs = self._turn(fail_first_image=True)
        self.assertTrue(ok)
        self.assertEqual(seen, [False, True, False])
        self.assertTrue(any("nie przyjął obrazu" in str(m.get("content")) for m in msgs))

    def test_budget_skips_too_big_image(self):
        Path("logo.png").write_bytes(PNG_1x1)
        cli.t_read_file({"path": "logo.png"})
        msgs = []
        self.assertEqual(cli._vision_attach(msgs, budget_chars=10), 0)
        self.assertEqual(msgs, [])

    def test_image_sizes(self):
        self.assertEqual(cli._image_size(PNG_1x1), (1, 1))
        gif = b"GIF89a" + (300).to_bytes(2, "little") + (200).to_bytes(2, "little") + b"\x00" * 10
        self.assertEqual(cli._image_size(gif), (300, 200))


class Search(InFolder):
    def test_grep_python_fallback_respects_gitignore_and_cp1250(self):
        if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
            self.skipTest("brak gita")
        subprocess.run(["git", "init", "-q"], check=True)
        Path(".gitignore").write_text("ignored/\n")
        Path("ignored").mkdir()
        Path("ignored/a.txt").write_text("szukane\n")
        Path("node_modules").mkdir()
        Path("node_modules/b.txt").write_text("szukane\n")
        Path("dobry.txt").write_bytes("szukane żółw\n".encode("cp1250"))
        Path("obraz.bin").write_bytes(b"\x00szukane\x00")
        with patch("shutil.which", lambda n: None):
            out = cli.t_grep({"pattern": "szukane"})
        self.assertIn("dobry.txt:1:szukane żółw", out)
        self.assertNotIn("ignored", out)
        self.assertNotIn("node_modules", out)
        self.assertNotIn("obraz.bin", out)

    def test_outline_markdown_and_go(self):
        Path("R.md").write_text("# Tytuł\n\n```\n# nie nagłówek\n```\n## Sekcja\n", encoding="utf-8")
        out = cli.t_outline({"path": "R.md"})
        self.assertIn("1  Tytuł", out)
        self.assertIn("Sekcja", out)
        self.assertNotIn("nie nagłówek", out)
        Path("m.go").write_text("package main\n\nfunc main() {}\n\ntype Klient struct {}\n")
        out = cli.t_outline({"path": "m.go"})
        self.assertIn("main", out)
        self.assertIn("Klient", out)


if __name__ == "__main__":
    unittest.main()
