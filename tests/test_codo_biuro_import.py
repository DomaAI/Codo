"""Biuro w oknie Codo (Windows, Linux): import plików z innych programów jak na Macu.
DOCX, PPTX, XLSX czytane zipfile + wyrażeniami, PDF przez zlib; pliki testowe powstają tutaj."""
import base64
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

_CFG = tempfile.mkdtemp(prefix="codo-biuro-cfg-")
os.environ.setdefault("DOMA_CONFIG_DIR", _CFG)
os.environ.setdefault("DOMA_API_URL", "http://127.0.0.1:9")
_loader = importlib.machinery.SourceFileLoader(
    "codo_biuro_import", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _zip(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_docx() -> bytes:
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Tytu"/></w:pPr><w:r><w:t>Raport roczny</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Nagwek1"/></w:pPr><w:r><w:t>Wyniki</w:t></w:r></w:p>'
        '<w:p><w:r><w:t xml:space="preserve">Zwykły </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>pogrubiony</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Punkt A</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Punkt B</w:t></w:r></w:p>'
        '<w:p><w:r><w:drawing><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData>'
        '<a:blip r:embed="rId9"/></a:graphicData></a:graphic></w:drawing></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Kwartał</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Zysk</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>I</w:t></w:r></w:p></w:tc><w:tc><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>12 &amp; 5</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f'<?xml version="1.0"?><w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>',
        "word/styles.xml": f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Tytu"><w:name w:val="Title"/></w:style>'
                           '<w:style w:type="paragraph" w:styleId="Nagwek1"><w:name w:val="heading 1"/></w:style></w:styles>',
        "word/numbering.xml": f'<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                              '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>',
        "word/_rels/document.xml.rels": '<Relationships><Relationship Id="rId9" Type="image" Target="media/image1.png"/></Relationships>',
        "word/media/image1.png": PNG,
    })


def make_pptx() -> bytes:
    p = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="r" xmlns:p="p"'

    def sp(ph, *paras):
        return ("<p:sp><p:nvSpPr><p:nvPr>" + (f'<p:ph type="{ph}"/>' if ph else "") + "</p:nvPr></p:nvSpPr><p:txBody>"
                + "".join(f'<a:p>{f'<a:pPr lvl="{l}"/>' if l else ""}<a:r><a:t>{t}</a:t></a:r></a:p>' for t, l in paras)
                + "</p:txBody></p:sp>")
    s1 = f"<p:sld {p}><p:cSld><p:spTree>" + sp("ctrTitle", ("Plan na 2027", 0)) + sp("subTitle", ("Zespół sprzedaży", 0)) + "</p:spTree></p:cSld></p:sld>"
    s2 = (f"<p:sld {p}><p:cSld><p:spTree>" + sp("title", ("Cele", 0)) + sp("", ("Więcej klientów", 0), ("Polska", 1), ("Niemcy", 1), ("Niższe koszty", 0))
          + '<p:pic><p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>').replace('<p:nvPr></p:nvPr>', '<p:nvPr><p:ph idx="1"/></p:nvPr>')
    notes = f"<p:notes {p}><p:cSld><p:spTree>" + sp("body", ("Powiedz o budżecie", 0)) + "</p:spTree></p:cSld></p:notes>"
    return _zip({
        "ppt/presentation.xml": f'<p:presentation {p}><p:sldIdLst><p:sldId id="256" r:id="rId7"/><p:sldId id="257" r:id="rId8"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="rId7" Target="slides/slide1.xml"/><Relationship Id="rId8" Target="slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide1.xml": s1,
        "ppt/slides/slide2.xml": s2,
        "ppt/slides/_rels/slide2.xml.rels": '<Relationships><Relationship Id="rId2" Target="../media/zdjecie.png"/>'
                                            '<Relationship Id="rId3" Target="../notesSlides/notesSlide2.xml"/></Relationships>',
        "ppt/notesSlides/notesSlide2.xml": notes,
        "ppt/media/zdjecie.png": PNG,
    })


def make_xlsx() -> bytes:
    sheet = ('<worksheet><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>1250.5</v></c><c r="C2" s="1"><v>0.25</v></c></row>'
             '<row r="3"><c r="A3" t="inlineStr"><is><t>Razem</t></is></c><c r="B3"><f>SUM(B2:B2)</f><v>1250.5</v></c></row>'
             '</sheetData></worksheet>')
    return _zip({
        "xl/workbook.xml": '<workbook><sheets><sheet name="Sprzedaż" sheetId="1" r:id="rId1"/><sheet name="Koszty &amp; inne" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>',
        "xl/sharedStrings.xml": "<sst><si><t>Produkt</t></si><si><t>Kwota</t></si><si><r><t>Ma</t></r><r><t>rża</t></r></si><si><t>Jabłka</t></si></sst>",
        "xl/styles.xml": '<styleSheet><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="9"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row r="1"><c r="B1"><v>7</v></c></row></sheetData></worksheet>',
    })


def make_pdf(compressed: bool = True) -> bytes:
    """Dwie strony: pierwsza czcionką z ToUnicode (kody 2-bajtowe, polskie litery), druga zwykłym napisem."""
    cmap = (b"/CIDInit /ProcSet findresource begin\nbegincmap\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            b"2 beginbfchar\n<0001> <017B>\n<0002> <00F3>\nendbfchar\n1 beginbfrange\n<0010> <0013> <0061>\nendbfrange\nendcmap\n")
    c1 = b"BT /F1 12 Tf 72 720 Td <00010002> Tj 0 -14 Td [<0010> -300 <00110012>] TJ ET"
    c2 = b"BT /F2 12 Tf 1 0 0 1 72 700 Tm (Druga \\(strona\\)) Tj T* (koniec) Tj ET"

    def stream(d: bytes) -> bytes:
        if compressed:
            z = zlib.compress(d)
            return b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream"
        return b"<< /Length %d >>\nstream\n" % len(d) + d + b"\nendstream"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /Resources 9 0 R /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode 8 0 R >>",
        stream(c1), stream(c2), stream(cmap),
        b"<< /Font << /F2 10 0 R >> >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R /Size 11 >>\n%%EOF\n"


class BiuroImport(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="codo-biuro-"))
        os.environ["CODO_OFFICE_FOLDER"] = str(self.dir)

    def add(self, data, name):
        return cli._office_add_media(self.dir, data, name)

    def test_docx_headings_lists_tables_pictures(self):
        html = cli._office_docx_html(make_docx(), self.add)
        self.assertIn("<h1>Raport roczny</h1>", html)
        self.assertIn("<h2>Wyniki</h2>", html)
        self.assertIn("<p>Zwykły <b>pogrubiony</b></p>", html)
        self.assertIn("<ul>\n<li>Punkt A</li>\n<li>Punkt B</li>\n</ul>", html)
        self.assertIn('<figure><img src="media/image1.png" alt=""></figure>', html)
        self.assertEqual((self.dir / "media/image1.png").read_bytes(), PNG)
        self.assertIn("<th>Kwartał</th><th>Zysk</th>", html)
        self.assertIn('<td class="n">12 &amp; 5</td>', html)

    def test_pptx_slides_points_picture_notes(self):
        html = cli._office_pptx_html(make_pptx(), self.add)
        first, second = html.split("\n\n")
        self.assertIn('<section class="slide title">', first)
        self.assertIn("<h1>Plan na 2027</h1>", first)
        self.assertIn('<p class="lead">Zespół sprzedaży</p>', first)
        self.assertIn('<section class="slide media-right">', second)
        self.assertIn("<h2>Cele</h2>", second)
        self.assertIn("<li>Więcej klientów<ul><li>Polska</li><li>Niemcy</li></ul></li>", second)
        self.assertIn('<img src="media/zdjecie.png"', second)
        self.assertIn('<aside class="notes">Powiedz o budżecie</aside>', second)

    def test_xlsx_cells_sheets_formulas(self):
        html = cli._office_sheet_table(make_xlsx(), "xlsx")
        self.assertIn('<table data-name="Sprzedaż">', html)
        self.assertIn('<table data-name="Koszty &amp; inne">', html)
        self.assertIn("<th>Produkt</th><th>Kwota</th><th>Marża</th>", html)
        self.assertIn("<td>Jabłka</td><td>1250,50</td><td>25%</td>", html)
        self.assertIn('<td>Razem</td><td data-f="=SUM(B2:B2)">1250,50</td><td></td>', html)
        self.assertIn("<th></th><th>7</th>", html)

    def test_csv_semicolons_and_quotes(self):
        html = cli._office_sheet_table('Imię;Kwota\n"Kowalski; Jan";"1 ""200"""\n'.encode("utf-8"), "csv")
        self.assertIn("<th>Imię</th><th>Kwota</th>", html)
        self.assertIn("<td>Kowalski; Jan</td><td>1 &quot;200&quot;</td>", html)

    def test_pdf_text_flate_and_tounicode(self):
        for compressed in (True, False):
            text = cli._office_pdf_text(make_pdf(compressed))
            self.assertEqual(text, "Żó\na bc\n\nDruga (strona)\nkoniec")

    def test_pdf_object_stream(self):
        # Słownik strony i czcionki w strumieniu obiektów (PDF 1.5), jak w plikach z Worda
        content = zlib.compress(b"BT /F1 10 Tf (Z obiektu) Tj ET")
        page = b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> "
        font = b"<< /Type /Font /Subtype /Type1 >>"
        inner = b"3 0 4 %d " % len(page)
        first = len(inner)
        packed = inner + page + font
        pdf = (b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
               + (b"5 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)) + content + b"\nendstream\nendobj\n"
               + (b"6 0 obj\n<< /Type /ObjStm /N 2 /First %d /Filter /FlateDecode >>\nstream\n" % first) + zlib.compress(packed)
               + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
        self.assertEqual(cli._office_pdf_text(pdf), "Z obiektu")

    def test_pdf_not_a_pdf(self):
        self.assertIsNone(cli._office_pdf_text(b"hello"))

    def test_import_endpoint_open_and_source(self):
        b64 = lambda d: base64.b64encode(d).decode()
        code, r = cli._ui_office_post("/api/office/import", {"name": "Raport.docx", "b64": b64(make_docx()), "mode": "open"}, None)
        self.assertEqual((code, r["kind"], r["name"]), (200, "doc", "Raport"))
        code, r = cli._ui_office_post("/api/office/import", {"name": "Plan.pptx", "b64": b64(make_pptx()), "mode": "open"}, None)
        self.assertEqual((code, r["kind"]), (200, "deck"))
        code, r = cli._ui_office_post("/api/office/import", {"name": "Dane.xlsx", "b64": b64(make_xlsx()), "mode": "open"}, None)
        self.assertEqual((code, r["kind"]), (200, "sheet"))
        code, r = cli._ui_office_post("/api/office/import", {"name": "Umowa (wersja 2).pdf", "b64": b64(make_pdf()), "mode": "source"}, None)
        self.assertEqual((code, r["text"]), (200, ".office/sources/Umowa-wersja-2.txt"))
        self.assertIn("Druga (strona)", (self.dir / r["text"]).read_text(encoding="utf-8"))
        code, r = cli._ui_office_post("/api/office/import", {"name": "Dane.xlsx", "b64": b64(make_xlsx()), "mode": "source"}, None)
        self.assertEqual(r["text"], ".office/sources/Dane.html")
        code, r = cli._ui_office_post("/api/office/import", {"name": "Logo firmy.PNG", "b64": b64(PNG), "mode": "source"}, None)
        self.assertEqual(r["image"], "media/logo-firmy.png")
        code, r = cli._ui_office_post("/api/office/import", {"name": "notatki.md", "b64": b64("# Notatki".encode()), "mode": "source"}, None)
        self.assertEqual(r["text"], ".office/sources/notatki.md")
        code, r = cli._ui_office_post("/api/office/import", {"name": "zly.docx", "b64": b64(b"nie zip"), "mode": "source"}, None)
        self.assertEqual(code, 422)
        code, r = cli._ui_office_post("/api/office/import", {"name": "x.exe", "b64": b64(b"MZ\x00\x00"), "mode": "open"}, None)
        self.assertEqual(code, 400)

    def test_media_same_file_not_duplicated(self):
        self.assertEqual(self.add(PNG, "a.png"), "media/a.png")
        self.assertEqual(self.add(PNG, "a.png"), "media/a.png")
        self.assertEqual(self.add(PNG + b"x", "a.png"), "media/a-2.png")

    def test_reveal_stays_in_folder(self):
        code, _ = cli._ui_office_post("/api/office/reveal", {"p": "../../etc/passwd"}, None)
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
