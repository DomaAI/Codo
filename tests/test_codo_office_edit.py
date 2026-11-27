"""Codo 27.11.2026: office_edit, edycja DOCX/XLSX/PPTX/ODT/ODS w miejscu. Offline, bez backendu i bez modeli.

Dokumenty budowane z zipa (jak z Worda/Excela/PowerPointa: przestrzenie nazw, relacje, typy zawartości),
a gdy są python-docx, openpyxl albo python-pptx, także prawdziwe pliki z tych bibliotek i ponowne otwarcie
wyniku. Gdy na komputerze jest LibreOffice, wynik przechodzi przez `soffice --headless --convert-to pdf`."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.dom import minidom

os.environ["CODO_MADDLABS_DIRECT"] = "1"
os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-test-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
os.environ.setdefault("CODO_LANG", "pl")
loader = importlib.machinery.SourceFileLoader(
    "codo_office_edit", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


SOFFICE = shutil.which("soffice") or next((p for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",)
                                          if os.path.exists(p)), None)

DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NS_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
NS_MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
NS_W14 = 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT = "application/vnd.openxmlformats-officedocument."
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _zip(files: dict, stored: tuple = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(zipfile.ZipInfo(name), body,
                       compress_type=zipfile.ZIP_STORED if name in stored else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _rels(*items) -> str:
    return DECL + f'<Relationships xmlns="{PKG_RELS}">' + "".join(
        f'<Relationship Id="{i}" Type="{RT}{t}" Target="{tg}"/>' for i, t, tg in items) + "</Relationships>"


def _types(defaults: dict, overrides: dict) -> str:
    return (DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + "".join(f'<Default Extension="{e}" ContentType="{c}"/>' for e, c in defaults.items())
            + "".join(f'<Override PartName="/{p}" ContentType="{c}"/>' for p, c in overrides.items()) + "</Types>")


BASE_DEFAULTS = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}


def make_docx(styles_heading: bool = False, extra: str = "") -> bytes:
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Tytul"/></w:pPr><w:r><w:t>Umowa najmu</w:t></w:r></w:p>'
        # zdanie pocięte przez Worda na runy (sprawdzanie pisowni, zmiana formatu w środku słowa)
        '<w:p w14:paraId="1A2B3C4D"><w:pPr><w:jc w:val="both"/></w:pPr>'
        '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">Najemca </w:t></w:r>'
        '<w:r><w:rPr><w:b/></w:rPr><w:t>Jan Kow</w:t></w:r><w:proofErr w:type="spellStart"/>'
        '<w:r><w:rPr><w:b/></w:rPr><w:t>alski</w:t></w:r><w:proofErr w:type="spellEnd"/>'
        '<w:r><w:t xml:space="preserve"> płaci 2000 zł do 10. dnia miesiąca.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Kaucja wynosi 2000 zł.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Punkt do usunięcia.</w:t></w:r></w:p>' + extra +
        '<w:p><w:r><w:t>Kolumna</w:t></w:r><w:r><w:tab/><w:t>po tabulatorze</w:t></w:r></w:p>'
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/>'
        '<w:gridCol w:w="3000"/></w:tblGrid>'
        '<w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Pozycja</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Kwota</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Czynsz</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:rPr><w:color w:val="FF0000"/></w:rPr><w:t>2000</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl>'
        '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr><w:r><w:t>Koniec sekcji</w:t></w:r></w:p>'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>')
    doc = (DECL + f'<w:document {NS_W} {NS_R} {NS_MC} {NS_W14} mc:Ignorable="w14"><w:body>{body}</w:body></w:document>')
    styles = (DECL + f'<w:styles {NS_W}><w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
              '<w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Tytul"><w:name w:val="Title"/>'
              '</w:style>' + ('<w:style w:type="paragraph" w:styleId="Nagwek1"><w:name w:val="heading 1"/></w:style>'
                              if styles_heading else "") + '</w:styles>')
    footer = DECL + f'<w:ftr {NS_W}><w:p><w:r><w:t>Strona stopki 2000</w:t></w:r></w:p></w:ftr>'
    return _zip({
        "[Content_Types].xml": _types(BASE_DEFAULTS, {
            "word/document.xml": CT + "wordprocessingml.document.main+xml",
            "word/styles.xml": CT + "wordprocessingml.styles+xml",
            "word/footer1.xml": CT + "wordprocessingml.footer+xml"}),
        "_rels/.rels": _rels(("rId1", "officeDocument", "word/document.xml")),
        "word/_rels/document.xml.rels": _rels(("rId1", "styles", "styles.xml"), ("rId2", "footer", "footer1.xml")),
        "word/document.xml": doc, "word/styles.xml": styles, "word/footer1.xml": footer,
    })


S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def make_xlsx() -> bytes:
    sheet1 = (DECL + f'<worksheet {S_NS} {NS_R}><dimension ref="A1:C4"/><sheetData>'
              '<row r="1" spans="1:3"><c r="A1" s="1" t="s"><v>0</v></c><c r="B1" s="1" t="s"><v>1</v></c>'
              '<c r="C1" s="1" t="s"><v>2</v></c></row>'
              '<row r="2" spans="1:3"><c r="A2" t="s"><v>3</v></c><c r="B2" s="2"><v>7</v></c>'
              '<c r="C2"><f t="shared" ref="C2:C4" si="0">B2*2+$B$2</f><v>21</v></c></row>'
              '<row r="3" spans="1:3"><c r="A3" t="s"><v>4</v></c><c r="B3" s="2"><v>5</v></c>'
              '<c r="C3"><f t="shared" si="0"/><v>17</v></c></row>'
              '<row r="4" spans="1:3"><c r="A4" t="s"><v>3</v></c><c r="B4" s="2"><v>1</v></c>'
              '<c r="C4"><f t="shared" si="0"/><v>9</v></c></row>'
              '</sheetData><tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>')
    sheet2 = (DECL + f'<worksheet {S_NS}><sheetData><row r="1"><c r="A1" t="s"><v>3</v></c>'
              '<c r="B1"><f>SUM(Dane!B2:B4)</f><v>13</v></c></row></sheetData></worksheet>')
    sst = (DECL + f'<sst {S_NS} count="7" uniqueCount="5"><si><t>Produkt</t></si><si><t>Ilość</t></si>'
           '<si><t>Razem</t></si><si><r><rPr><b/></rPr><t>Jabł</t></r><r><t>ka</t></r></si><si><t>Gruszki</t></si></sst>')
    wb = (DECL + f'<workbook {S_NS} {NS_R}><bookViews><workbookView/></bookViews><sheets>'
          '<sheet name="Dane" sheetId="1" r:id="rId1"/><sheet name="Inne" sheetId="2" r:id="rId2"/></sheets>'
          '<calcPr calcId="191029"/></workbook>')
    table = (DECL + f'<table {S_NS} id="1" name="Tabela1" displayName="Tabela1" ref="A1:C4">'
             '<autoFilter ref="A1:C4"/><tableColumns count="3"><tableColumn id="1" name="Produkt"/>'
             '<tableColumn id="2" name="Ilość"/><tableColumn id="3" name="Razem"/></tableColumns>'
             '<tableStyleInfo name="TableStyleMedium2" showRowStripes="1"/></table>')
    styles = (DECL + f'<styleSheet {S_NS}><numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/></font><font><b/><sz val="11"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/>'
              '</fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="3"><xf/><xf fontId="1" applyFont="1"/><xf numFmtId="164" applyNumberFormat="1"/>'
              '</cellXfs></styleSheet>')
    return _zip({
        "[Content_Types].xml": _types(BASE_DEFAULTS, {
            "xl/workbook.xml": CT + "spreadsheetml.sheet.main+xml",
            "xl/worksheets/sheet1.xml": CT + "spreadsheetml.worksheet+xml",
            "xl/worksheets/sheet2.xml": CT + "spreadsheetml.worksheet+xml",
            "xl/sharedStrings.xml": CT + "spreadsheetml.sharedStrings+xml",
            "xl/styles.xml": CT + "spreadsheetml.styles+xml",
            "xl/calcChain.xml": CT + "spreadsheetml.calcChain+xml",
            "xl/tables/table1.xml": CT + "spreadsheetml.table+xml"}),
        "_rels/.rels": _rels(("rId1", "officeDocument", "xl/workbook.xml")),
        "xl/_rels/workbook.xml.rels": _rels(("rId1", "worksheet", "worksheets/sheet1.xml"),
                                            ("rId2", "worksheet", "worksheets/sheet2.xml"),
                                            ("rId3", "sharedStrings", "sharedStrings.xml"),
                                            ("rId4", "styles", "styles.xml"), ("rId5", "calcChain", "calcChain.xml")),
        "xl/worksheets/_rels/sheet1.xml.rels": _rels(("rId1", "table", "../tables/table1.xml")),
        "xl/workbook.xml": wb, "xl/worksheets/sheet1.xml": sheet1, "xl/worksheets/sheet2.xml": sheet2,
        "xl/sharedStrings.xml": sst, "xl/styles.xml": styles, "xl/tables/table1.xml": table,
        "xl/calcChain.xml": DECL + f'<calcChain {S_NS}><c r="C2" i="1"/><c r="B1" i="2"/></calcChain>',
    })


P_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
GRP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>')


def _sp(i: int, ph: str, paras: str) -> str:
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr>'
            f'<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paras}</p:txBody></p:sp>')


def make_pptx() -> bytes:
    slide1 = (DECL + f'<p:sld {P_NS}><p:cSld><p:spTree>{GRP}'
              + _sp(2, '<p:ph type="title"/>', '<a:p><a:r><a:rPr lang="pl-PL" b="1"/><a:t>Plan na </a:t></a:r>'
                     '<a:r><a:rPr lang="pl-PL" b="1" i="1"/><a:t>rok 2025</a:t></a:r></a:p>')
              + _sp(3, '<p:ph idx="1"/>', '<a:p><a:r><a:t>Wstęp</a:t></a:r></a:p>'
                    '<a:p><a:fld id="{1}" type="slidenum"><a:t>1</a:t></a:fld></a:p>')
              + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
    slide2 = (DECL + f'<p:sld {P_NS}><p:cSld><p:spTree>{GRP}'
              + _sp(2, '<p:ph type="title"/>', '<a:p><a:r><a:t>Budżet 2025</a:t></a:r></a:p>')
              + '</p:spTree></p:cSld></p:sld>')
    layout_obj = (DECL + f'<p:sldLayout {P_NS} type="obj" preserve="1"><p:cSld name="Tytuł i zawartość"><p:spTree>{GRP}'
                  + _sp(2, '<p:ph type="title"/>', '<a:p><a:r><a:t>Tytuł</a:t></a:r></a:p>')
                  + _sp(3, '<p:ph idx="1"/>', '<a:p><a:r><a:t>Treść</a:t></a:r></a:p>')
                  + _sp(4, '<p:ph type="sldNum" sz="quarter" idx="12"/>', '<a:p/>')
                  + '</p:spTree></p:cSld></p:sldLayout>')
    layout_title = (DECL + f'<p:sldLayout {P_NS} type="title"><p:cSld name="Slajd tytułowy"><p:spTree>{GRP}'
                    + _sp(2, '<p:ph type="ctrTitle"/>', '<a:p/>') + _sp(3, '<p:ph type="subTitle" idx="1"/>', '<a:p/>')
                    + '</p:spTree></p:cSld></p:sldLayout>')
    master = (DECL + f'<p:sldMaster {P_NS}><p:cSld><p:spTree>{GRP}</p:spTree></p:cSld>'
              '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
              'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
              '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/><p:sldLayoutId id="2147483650" r:id="rId2"/>'
              '</p:sldLayoutIdLst></p:sldMaster>')
    theme = DECL + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Motyw"><a:themeElements/></a:theme>'
    pres = (DECL + f'<p:presentation {P_NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
            '</p:sldMasterIdLst><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
            '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    return _zip({
        "[Content_Types].xml": _types(BASE_DEFAULTS, {
            "ppt/presentation.xml": CT + "presentationml.presentation.main+xml",
            "ppt/slides/slide1.xml": CT + "presentationml.slide+xml",
            "ppt/slides/slide2.xml": CT + "presentationml.slide+xml",
            "ppt/slideLayouts/slideLayout1.xml": CT + "presentationml.slideLayout+xml",
            "ppt/slideLayouts/slideLayout2.xml": CT + "presentationml.slideLayout+xml",
            "ppt/slideMasters/slideMaster1.xml": CT + "presentationml.slideMaster+xml",
            "ppt/theme/theme1.xml": CT + "theme+xml"}),
        "_rels/.rels": _rels(("rId1", "officeDocument", "ppt/presentation.xml")),
        "ppt/_rels/presentation.xml.rels": _rels(("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
                                                 ("rId2", "slide", "slides/slide1.xml"),
                                                 ("rId3", "slide", "slides/slide2.xml"),
                                                 ("rId4", "theme", "theme/theme1.xml")),
        "ppt/presentation.xml": pres,
        "ppt/slides/slide1.xml": slide1, "ppt/slides/slide2.xml": slide2,
        "ppt/slides/_rels/slide1.xml.rels": _rels(("rId1", "slideLayout", "../slideLayouts/slideLayout2.xml")),
        "ppt/slides/_rels/slide2.xml.rels": _rels(("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")),
        "ppt/slideLayouts/slideLayout1.xml": layout_title, "ppt/slideLayouts/slideLayout2.xml": layout_obj,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels(("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")),
        "ppt/slideLayouts/_rels/slideLayout2.xml.rels": _rels(("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")),
        "ppt/slideMasters/slideMaster1.xml": master,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels(("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
                                                             ("rId2", "slideLayout", "../slideLayouts/slideLayout2.xml"),
                                                             ("rId3", "theme", "../theme/theme1.xml")),
        "ppt/theme/theme1.xml": theme,
    })


ODF_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" office:version="1.3"')


def make_odf(kind: str, body: str) -> bytes:
    mime = {"odt": "application/vnd.oasis.opendocument.text",
            "ods": "application/vnd.oasis.opendocument.spreadsheet"}[kind]
    tag = {"odt": "text", "ods": "spreadsheet"}[kind]
    content = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {ODF_NS}><office:body>'
               f'<office:{tag}>{body}</office:{tag}></office:body></office:document-content>')
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    return _zip({"mimetype": mime, "content.xml": content, "META-INF/manifest.xml": manifest}, stored=("mimetype",))


def part(path, name: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def names(path) -> list:
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def well_formed(test, path) -> None:
    """Każda część XML parsuje się, relacje wskazują istniejące części, każda część ma typ zawartości."""
    with zipfile.ZipFile(path) as z:
        test.assertIsNone(z.testzip())
        files = set(z.namelist())
        for n in files:
            if n.endswith((".xml", ".rels")):
                minidom.parseString(z.read(n))
        if "[Content_Types].xml" not in files:
            return
        ct = minidom.parseString(z.read("[Content_Types].xml")).documentElement
        defaults = {d.getAttribute("Extension").lower() for d in ct.getElementsByTagName("Default")}
        overrides = {o.getAttribute("PartName").lstrip("/") for o in ct.getElementsByTagName("Override")}
        for o in overrides:
            test.assertIn(o, files, f"Override dla nieistniejącej części {o}")
        for n in files:
            if n != "[Content_Types].xml" and not n.endswith("/"):
                test.assertTrue(n in overrides or n.rsplit(".", 1)[-1].lower() in defaults, f"brak typu dla {n}")
        for n in files:
            if not n.endswith(".rels"):
                continue
            src = n.replace("_rels/", "")[:-5]
            for r in minidom.parseString(z.read(n)).getElementsByTagName("Relationship"):
                if r.getAttribute("TargetMode") == "External":
                    continue
                test.assertIn(cli._OfficePkg.resolve(src, r.getAttribute("Target")) if src else
                              r.getAttribute("Target").lstrip("/"), files, f"relacja z {n} do brakującej części")


class InFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        cli.EDIT_LOG.clear()
        cli._FILE_OP_LOG.clear()
        cli.SESSION["edited"] = []

    def tearDown(self):
        os.chdir(self.prev)
        for p in Path(self.tmp.name).rglob("*"):
            with contextlib.suppress(OSError):
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
        self.tmp.cleanup()

    def edit(self, path, **args):
        seq = cli._EDIT_SEQ[0]
        out = cli.run_tool("office_edit", {"path": path, **args}, True)
        for e in cli.EDIT_LOG:
            if e["seq"] > seq and e["path"] not in cli.SESSION["edited"]:
                cli.SESSION["edited"].append(e["path"])
        return out

    def ok(self, path, **args):
        out = self.edit(path, **args)
        self.assertNotIn("BŁĄD", out, out)
        return out

    def text(self, path) -> str:
        return cli.t_read_file({"path": path})

    def soffice(self, path):
        """Prawdziwy test otwarcia: LibreOffice konwertuje dokument do PDF (gdy jest na komputerze)."""
        if not SOFFICE:
            return
        out = Path(self.tmp.name) / "pdf"
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(out), str(path)],
                           capture_output=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / (Path(path).stem + ".pdf")).exists(), r.stdout)


class Docx(InFolder):
    def setUp(self):
        super().setUp()
        Path("u.docx").write_bytes(make_docx())

    def test_replace_across_runs_keeps_formatting_and_namespaces(self):
        before = part("u.docx", "word/document.xml")
        out = self.ok("u.docx", action="replace", find="Najemca Jan Kowalski płaci", replace="Najemca Anna Nowak płaci")
        self.assertIn("zamiana 1×", out)
        xml = part("u.docx", "word/document.xml")
        # nagłówek głównego elementu (deklaracje xmlns i mc:Ignorable) bez zmian: Word inaczej odrzuca plik
        self.assertEqual(before.split("<w:body>")[0], xml.split("<w:body>")[0])
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'))
        doc = minidom.parseString(xml)
        p = doc.getElementsByTagNameNS(cli._OX_W, "p")[1]
        runs = [(bool(r.getElementsByTagNameNS(cli._OX_W, "b")), bool(r.getElementsByTagNameNS(cli._OX_W, "i")),
                 "".join(t.firstChild.data for t in r.getElementsByTagNameNS(cli._OX_W, "t") if t.firstChild))
                for r in p.getElementsByTagNameNS(cli._OX_W, "r")]
        self.assertEqual("".join(r[2] for r in runs), "Najemca Anna Nowak płaci 2000 zł do 10. dnia miesiąca.")
        self.assertIn((False, True, "Najemca "), runs)                    # kursywa zostaje
        bold = "".join(r[2] for r in runs if r[0])
        self.assertEqual(bold, "Anna Nowak")                             # nowe nazwisko w formacie starego
        self.assertIn('w:jc w:val="both"', xml)
        self.assertIn('w14:paraId="1A2B3C4D"', xml)
        self.assertIn("Anna Nowak", self.text("u.docx"))
        well_formed(self, "u.docx")
        self.soffice("u.docx")

    def test_replace_ambiguous_all_and_footer(self):
        out = self.edit("u.docx", action="replace", find="2000", replace="2100")
        self.assertIn("BŁĄD", out)
        self.assertIn("4×", out)
        self.assertIn("tabela", out)
        self.assertEqual(part("u.docx", "word/document.xml").count("2000"), 3)   # plik bez zmian
        self.ok("u.docx", action="replace", find="2000", replace="2100", all=True)
        self.assertNotIn("2000", part("u.docx", "word/document.xml"))
        self.assertIn("2100", part("u.docx", "word/footer1.xml"))   # stopka też

    def test_replace_not_found_hints(self):
        self.assertIn("inna wielkość liter", self.edit("u.docx", action="replace", find="najemca", replace="x"))
        self.assertIn("read_file", self.edit("u.docx", action="replace", find="Nie ma takiego", replace="x"))
        self.assertIn("akapit", self.edit("u.docx", action="replace", find="Umowa\nNajemca", replace="x"))

    def test_typographic_quotes_and_tab_and_newline(self):
        self.ok("u.docx", action="replace", find="Kolumna\tpo", replace="Kolumna przed")
        xml = part("u.docx", "word/document.xml")
        self.assertIn("Kolumna przed", self.text("u.docx").replace("\t", ""))
        self.assertNotIn("<w:tab/><w:t>po", xml)
        self.ok("u.docx", action="replace", find="Kaucja wynosi", replace="Kaucja\nwynosi")
        self.assertIn("<w:br/>", part("u.docx", "word/document.xml"))
        self.ok("u.docx", action="replace", find="do 10. dnia", replace="do 15. dnia")
        Path("q.docx").write_bytes(make_docx(extra="<w:p><w:r><w:t>Termin „do końca” roku – stały</w:t></w:r></w:p>"))
        self.ok("q.docx", action="replace", find='Termin "do końca" roku - stały', replace="Termin stały")
        self.assertIn("Termin stały", self.text("q.docx"))

    def test_insert_paragraph_after_before_end_heading(self):
        self.ok("u.docx", action="insert_paragraph", after="Kaucja wynosi", text="Kaucja jest zwrotna.")
        self.ok("u.docx", action="insert_paragraph", before="Umowa najmu", text="Wersja 2")
        self.ok("u.docx", action="insert_paragraph", text="Załączniki", heading=1)
        self.ok("u.docx", action="insert_paragraph", after="Załączniki", text="Załącznik A\nZałącznik B")
        d = minidom.parseString(part("u.docx", "word/document.xml"))
        body = d.getElementsByTagNameNS(cli._OX_W, "body")[0]
        texts = [cli._ox_par_text(p, "w") for p in cli._ox_kids(body, cli._OX_W, "p")]
        self.assertEqual(texts[0], "Wersja 2")
        self.assertEqual(texts[texts.index("Kaucja wynosi 2000 zł.") + 1], "Kaucja jest zwrotna.")
        self.assertEqual(texts[-3:], ["Załączniki", "Załącznik A", "Załącznik B"])
        self.assertEqual(cli._ox_kids(body)[-1].localName, "sectPr")      # sectPr zostaje ostatni
        heading = [p for p in cli._ox_kids(body, cli._OX_W, "p") if cli._ox_par_text(p, "w") == "Załączniki"][0]
        self.assertIn('w:pStyle w:val="Heading1"', heading.toxml())
        styles = part("u.docx", "word/styles.xml")
        self.assertIn('w:styleId="Heading1"', styles)                      # brakujący styl dopisany
        self.assertIn('<w:name w:val="heading 1"/>', styles)
        after = [p for p in cli._ox_kids(body, cli._OX_W, "p") if cli._ox_par_text(p, "w") == "Załącznik A"][0]
        self.assertNotIn("pStyle", after.toxml())                           # po nagłówku zwykły akapit
        self.assertIn("Kaucja jest zwrotna.", self.text("u.docx"))
        well_formed(self, "u.docx")

    def test_heading_uses_existing_localized_style(self):
        Path("h.docx").write_bytes(make_docx(styles_heading=True))
        self.ok("h.docx", action="insert_paragraph", text="Rozdział", heading=1)
        self.assertIn('w:pStyle w:val="Nagwek1"', part("h.docx", "word/document.xml"))
        self.assertEqual(part("h.docx", "word/styles.xml").count("heading 1"), 1)
        self.ok("h.docx", action="insert_paragraph", text="Tytuł 2", style="Title")
        self.assertIn('w:pStyle w:val="Tytul"', part("h.docx", "word/document.xml"))
        self.assertIn("Dostępne", self.edit("h.docx", action="insert_paragraph", text="x", style="Brak"))

    def test_delete_paragraph(self):
        self.ok("u.docx", action="delete_paragraph", find="Punkt do usunięcia")
        self.assertNotIn("Punkt do usunięcia", self.text("u.docx"))
        out = self.ok("u.docx", action="delete_paragraph", find="Koniec sekcji")   # akapit z sectPr: czyszczenie
        self.assertIn("wyczyszczono", out)
        self.assertIn("w:sectPr", part("u.docx", "word/document.xml").split("<w:tbl>")[1])
        self.ok("u.docx", action="delete_paragraph", find="Czynsz")             # jedyny akapit komórki
        self.assertEqual(part("u.docx", "word/document.xml").count("<w:tc>"), 4)
        self.assertIn("BŁĄD", self.edit("u.docx", action="delete_paragraph", find="nie ma"))

    def test_table_cells_and_rows(self):
        self.ok("u.docx", action="set_cell", table=1, row=2, col=2, text="2500")
        xml = part("u.docx", "word/document.xml")
        self.assertIn('<w:color w:val="FF0000"/></w:rPr><w:t xml:space="preserve">2500</w:t>', xml)
        self.ok("u.docx", action="add_row", table=1, values=["Media", "300"])
        self.ok("u.docx", action="add_row", table=1, values=["Parking"], after_row=1)
        d = minidom.parseString(part("u.docx", "word/document.xml"))
        tbl = d.getElementsByTagNameNS(cli._OX_W, "tbl")[0]
        rows = [[cli._ox_par_text(p, "w") for p in tr.getElementsByTagNameNS(cli._OX_W, "p")]
                for tr in cli._ox_kids(tbl, cli._OX_W, "tr")]
        self.assertEqual(rows, [["Pozycja", "Kwota"], ["Parking", ""], ["Czynsz", "2500"], ["Media", "300"]])
        self.assertEqual(tbl.toxml().count("tblHeader"), 1)   # kopia wiersza nagłówka nie jest nagłówkiem
        self.assertIn("ma 1 tabel", self.edit("u.docx", action="set_cell", table=3, row=1, col=1, text="x"))
        self.assertIn("ma 2 komórek", self.edit("u.docx", action="set_cell", table=1, row=1, col=5, text="x"))
        self.assertIn("Media | 300", self.text("u.docx"))
        well_formed(self, "u.docx")
        self.soffice("u.docx")

    @unittest.skipUnless(_have("docx"), "python-docx niedostępne")
    def test_real_python_docx_file_roundtrip(self):
        import docx
        d = docx.Document()
        d.add_heading("Raport", 1)
        p = d.add_paragraph("Sprzedaż w roku ")
        p.add_run("2025").bold = True
        p.add_run(" wzrosła o 10%.")
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(1, 0).text, t.cell(1, 1).text = "Nazwa", "Kawa", "12"
        d.save("r.docx")
        self.ok("r.docx", edits=[{"action": "replace", "find": "roku 2025 wzrosła", "replace": "roku 2026 spadła"},
                                 {"action": "insert_paragraph", "after": "Raport", "text": "Wprowadzenie"},
                                 {"action": "insert_paragraph", "text": "Wnioski", "heading": 2},
                                 {"action": "set_cell", "table": 1, "row": 2, "col": 2, "text": "15"},
                                 {"action": "add_row", "table": 1, "values": ["Herbata", "9"]}])
        d2 = docx.Document("r.docx")
        self.assertEqual([x.text for x in d2.paragraphs],
                         ["Raport", "Wprowadzenie", "Sprzedaż w roku 2026 spadła o 10%.", "Wnioski"])
        self.assertEqual([r.bold for r in d2.paragraphs[2].runs if r.text == "2026"], [True])
        self.assertEqual(d2.paragraphs[3].style.name, "Heading 2")
        self.assertEqual([[c.text for c in r.cells] for r in d2.tables[0].rows],
                         [["Nazwa", ""], ["Kawa", "15"], ["Herbata", "9"]])
        well_formed(self, "r.docx")
        self.soffice("r.docx")


class Xlsx(InFolder):
    def setUp(self):
        super().setUp()
        Path("k.xlsx").write_bytes(make_xlsx())

    def sheet(self, n=1):
        return part("k.xlsx", f"xl/worksheets/sheet{n}.xml")

    def test_set_values_formulas_shared_strings_styles(self):
        sheet2 = self.sheet(2)
        out = self.ok("k.xlsx", action="set_cell", cell="B2", value=9)
        self.assertIn("przeliczą", out)
        self.assertIn('<c r="B2" s="2"><v>9</v></c>', self.sheet())            # styl komórki zostaje
        self.ok("k.xlsx", action="set_cell", cell="A5", value="Śliwki ")
        self.ok("k.xlsx", action="set_cell", cell="D1", value="Produkt")          # istniejący wspólny ciąg
        self.ok("k.xlsx", action="set_cell", sheet="Dane", cell="E2", value="=SUM(B2:B4)")
        xml = self.sheet()
        self.assertIn('<c r="E2"><f>SUM(B2:B4)</f></c>', xml)
        self.assertIn('<c r="D1" t="s"><v>0</v></c>', xml)
        self.assertNotIn("spans=", xml.split('<row r="3"')[0])                    # wiersze zmienione
        self.assertIn('<dimension ref="A1:E5"/>', xml)
        sst = part("k.xlsx", "xl/sharedStrings.xml")
        self.assertIn('<si><t xml:space="preserve">Śliwki </t></si>', sst)
        self.assertIn('uniqueCount="6"', sst)
        self.assertIn('count="9"', sst)
        # inne arkusze bez zmian, łańcuch obliczeń usunięty, Excel przeliczy formuły przy otwarciu
        self.assertEqual(self.sheet(2), sheet2)
        self.assertNotIn("xl/calcChain.xml", names("k.xlsx"))
        self.assertNotIn("calcChain", part("k.xlsx", "[Content_Types].xml"))
        self.assertNotIn("calcChain", part("k.xlsx", "xl/_rels/workbook.xml.rels"))
        self.assertIn('fullCalcOnLoad="1"', part("k.xlsx", "xl/workbook.xml"))
        text = self.text("k.xlsx")
        self.assertIn("Śliwki", text)
        self.assertIn("{=SUM(B2:B4)}", text)
        well_formed(self, "k.xlsx")

    def test_range_values_and_types(self):
        self.ok("k.xlsx", action="set_cell", range="A6:C7",
                values=[["Kiwi", "3", "=B6*2"], ["Mango", True, "'=nie formuła"]])
        xml = self.sheet()
        self.assertIn('<c r="B6"><v>3</v></c>', xml)                              # „3” jako liczba
        self.assertIn('<c r="B7" t="b"><v>1</v></c>', xml)
        self.assertIn("=nie formuła", part("k.xlsx", "xl/sharedStrings.xml"))
        self.ok("k.xlsx", action="set_cell", range="D2:D4", value=0)               # jedna wartość na zakres
        self.assertEqual(self.sheet().count("<v>0</v></c>"), 3 + 1)               # D2:D4 + A1 (indeks 0)
        self.ok("k.xlsx", action="set_cell", cell="B4", value="")                  # czyszczenie
        self.assertIn('<c r="B4" s="2"/>', self.sheet())
        self.assertIn("ma 2×2", self.edit("k.xlsx", action="set_cell", range="A1:B2", values=[[1, 2, 3]]))
        self.assertIn("Arkusze: Dane, Inne", self.edit("k.xlsx", action="set_cell", sheet="Nie", cell="A1", value=1))
        self.assertIn("adres", self.edit("k.xlsx", action="set_cell", cell="1A", value=1))

    def test_shared_formula_master_overwritten_expands_group(self):
        self.ok("k.xlsx", action="set_cell", cell="C2", value=100)
        xml = self.sheet()
        self.assertIn('<c r="C2"><v>100</v></c>', xml)
        self.assertIn("<f>B3*2+$B$2</f>", xml)
        self.assertIn("<f>B4*2+$B$2</f>", xml)
        self.assertNotIn('t="shared"', xml)

    def test_table_header_and_add_row_extend_table(self):
        self.ok("k.xlsx", action="set_cell", cell="B1", value="Sztuk")
        table = part("k.xlsx", "xl/tables/table1.xml")
        self.assertIn('<tableColumn id="2" name="Sztuk"/>', table)
        out = self.ok("k.xlsx", action="add_row", values=["Kiwi", 2, "=B5*2+$B$2"])
        self.assertIn("nowy wiersz 5", out)
        xml = self.sheet()
        self.assertIn('<c r="B5" s="2"><v>2</v></c>', xml)                          # styl z wiersza powyżej
        table = part("k.xlsx", "xl/tables/table1.xml")
        self.assertIn('ref="A1:C5"', table)
        self.assertIn('<autoFilter ref="A1:C5"/>', table)
        self.assertIn("nie jest pusty", self.edit("k.xlsx", action="add_row", values=["x"], row=2))

    def test_add_sheet(self):
        self.ok("k.xlsx", action="add_sheet", name="Podsumowanie", values=[["Suma", "=SUM(Dane!C2:C4)"]])
        wb = part("k.xlsx", "xl/workbook.xml")
        self.assertIn('<sheet name="Podsumowanie" sheetId="3" r:id="rId6"/>', wb)
        self.assertIn("xl/worksheets/sheet3.xml", names("k.xlsx"))
        self.assertIn("worksheets/sheet3.xml", part("k.xlsx", "xl/_rels/workbook.xml.rels"))
        self.assertIn("/xl/worksheets/sheet3.xml", part("k.xlsx", "[Content_Types].xml"))
        self.assertIn("## Arkusz: Podsumowanie", self.text("k.xlsx"))
        self.assertIn("już jest", self.edit("k.xlsx", action="add_sheet", name="dane"))
        self.assertIn("31 znaków", self.edit("k.xlsx", action="add_sheet", name="a/b"))
        well_formed(self, "k.xlsx")

    def test_replace_shared_strings(self):
        out = self.edit("k.xlsx", action="replace", find="Jabłka", replace="Jabłka czerwone")
        self.assertIn("3×", out)                                                    # A2, A4 i Inne!A1 dzielą ciąg
        self.assertIn("Dane!A2", out)
        self.ok("k.xlsx", action="replace", find="Jabłka", replace="Jabłka zielone", sheet="Inne")
        sst = part("k.xlsx", "xl/sharedStrings.xml")
        self.assertIn("<r><rPr><b/></rPr><t", sst)                                  # formatowanie w ciągu zostaje
        self.assertIn('<c r="A2" t="s"><v>3</v></c>', self.sheet())                # Dane bez zmian
        text = self.text("k.xlsx")
        self.assertIn("Jabłka zielone", text)
        self.ok("k.xlsx", action="replace", find="Jabłka", replace="Jabłko", all=True, sheet="Dane")
        self.assertEqual(self.text("k.xlsx").count("Jabłko"), 2)
        self.assertIn("formuł", self.edit("k.xlsx", action="replace", find="SUM", replace="AVERAGE"))

    def test_formula_shift_helper(self):
        f = cli._xl_shift_formula
        self.assertEqual(f("B2*2+$B$2", 1, 0), "B3*2+$B$2")
        self.assertEqual(f('SUM(A1:B2)&"A1"', 2, 1), 'SUM(B3:C4)&"A1"')
        self.assertEqual(f("Arkusz2!A$1+LOG10(A1)", 1, 1), "Arkusz2!B$1+LOG10(B2)")

    @unittest.skipUnless(_have("openpyxl"), "openpyxl niedostępne")
    def test_openpyxl_reads_result(self):
        import openpyxl
        self.ok("k.xlsx", edits=[{"action": "set_cell", "cell": "B2", "value": 9},
                                 {"action": "add_row", "values": ["Kiwi", 2, "=B5*2"]},
                                 {"action": "add_sheet", "name": "Nowy", "values": [["a", 1]]},
                                 {"action": "replace", "find": "Gruszki", "replace": "Gruszki konferencja"}])
        wb = openpyxl.load_workbook("k.xlsx")
        self.assertEqual(wb.sheetnames, ["Dane", "Inne", "Nowy"])
        ws = wb["Dane"]
        self.assertEqual([c.value for c in ws[3]], ["Gruszki konferencja", 5, "=B3*2+$B$2"])
        self.assertEqual([c.value for c in ws[5]], ["Kiwi", 2, "=B5*2"])
        self.assertEqual(ws["B2"].number_format, "0.00")
        self.assertEqual(ws.tables["Tabela1"].ref, "A1:C5")
        self.assertEqual([c.value for c in wb["Nowy"][1]], ["a", 1])
        self.soffice("k.xlsx")

    @unittest.skipUnless(_have("openpyxl"), "openpyxl niedostępne")
    def test_real_openpyxl_file(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lista"
        ws.append(["Produkt", "Cena"])
        ws.append(["Kawa", 12.5])
        ws["B2"].number_format = "#,##0.00 zł"
        wb.create_sheet("Drugi")["A1"] = "zostaje"
        wb.save("o.xlsx")
        self.ok("o.xlsx", edits=[{"action": "set_cell", "cell": "B2", "value": 13.75},
                                 {"action": "add_row", "values": ["Herbata", 9]},
                                 {"action": "set_cell", "cell": "B4", "value": "=SUM(B2:B3)"}])
        wb2 = openpyxl.load_workbook("o.xlsx")
        self.assertEqual([[c.value for c in r] for r in wb2["Lista"].iter_rows()],
                         [["Produkt", "Cena"], ["Kawa", 13.75], ["Herbata", 9], [None, "=SUM(B2:B3)"]])
        self.assertEqual(wb2["Lista"]["B3"].number_format, "#,##0.00 zł")
        self.assertEqual(wb2["Drugi"]["A1"].value, "zostaje")
        self.soffice("o.xlsx")


class Pptx(InFolder):
    def setUp(self):
        super().setUp()
        Path("p.pptx").write_bytes(make_pptx())

    def test_replace_across_runs_and_slide_filter(self):
        out = self.edit("p.pptx", action="replace", find="2025", replace="2026")
        self.assertIn("slajd 1", out)
        self.assertIn("slajd 2", out)
        self.ok("p.pptx", action="replace", find="Plan na rok 2025", replace="Plan na rok 2026", slide=1)
        xml = part("p.pptx", "ppt/slides/slide1.xml")
        self.assertIn('<a:rPr lang="pl-PL" b="1" i="1"/><a:t>rok 2026</a:t>', xml)
        self.assertIn("Budżet 2025", part("p.pptx", "ppt/slides/slide2.xml"))
        self.assertIn('<a:fld id="{1}" type="slidenum"><a:t>1</a:t></a:fld>', xml)   # pole numeru nietknięte
        self.ok("p.pptx", action="replace", find="Wstęp", replace="Wstęp\nCele")
        self.assertIn("<a:br/>", part("p.pptx", "ppt/slides/slide1.xml"))
        text = self.text("p.pptx")
        self.assertIn("Plan na rok 2026", text)
        self.assertIn("Cele", text)

    def test_notes_created_with_master_then_updated(self):
        out = self.ok("p.pptx", action="notes", slide=2, text="Pokaż wykres kosztów\nPotem pytania")
        self.assertIn("(nowe)", out)
        files = names("p.pptx")
        self.assertIn("ppt/notesMasters/notesMaster1.xml", files)
        self.assertIn("ppt/notesSlides/notesSlide1.xml", files)
        self.assertIn("ppt/theme/theme2.xml", files)
        pres = part("p.pptx", "ppt/presentation.xml")
        self.assertLess(pres.index("sldMasterIdLst"), pres.index("notesMasterIdLst"))
        self.assertLess(pres.index("notesMasterIdLst"), pres.index("sldIdLst"))
        self.assertIn("notesSlide", part("p.pptx", "ppt/slides/_rels/slide2.xml.rels"))
        rels = part("p.pptx", "ppt/notesSlides/_rels/notesSlide1.xml.rels")
        self.assertIn("../notesMasters/notesMaster1.xml", rels)
        self.assertIn("../slides/slide2.xml", rels)
        self.assertIn("Notatki prelegenta: Pokaż wykres kosztów", self.text("p.pptx"))
        self.ok("p.pptx", action="notes", slide=1, text="Pierwsza")
        self.ok("p.pptx", action="notes", slide=2, text="Nowa treść")              # istniejące notatki
        self.assertEqual(names("p.pptx").count("ppt/notesMasters/notesMaster1.xml"), 1)
        notes = part("p.pptx", "ppt/notesSlides/notesSlide1.xml")
        self.assertIn("Nowa treść", notes)
        self.assertNotIn("Pokaż wykres", notes)
        self.assertIn("nie istnieje", self.edit("p.pptx", action="notes", slide=9, text="x"))
        well_formed(self, "p.pptx")

    def test_add_slide_from_layout(self):
        out = self.ok("p.pptx", action="add_slide", title="Harmonogram", body="Etap 1\n  - szczegół\nEtap 2", after=1)
        self.assertIn("Tytuł i zawartość", out)
        self.assertIn("nowy slajd 2", out)
        files = names("p.pptx")
        self.assertIn("ppt/slides/slide3.xml", files)
        pres = minidom.parseString(part("p.pptx", "ppt/presentation.xml"))
        ids = [(s.getAttribute("id"), s.getAttribute("r:id")) for s in pres.getElementsByTagName("p:sldId")]
        self.assertEqual([i for i, _r in ids], ["256", "258", "257"])
        rels = part("p.pptx", "ppt/_rels/presentation.xml.rels")
        self.assertIn(f'Id="{ids[1][1]}"', rels)
        self.assertIn("slides/slide3.xml", rels)
        slide = part("p.pptx", "ppt/slides/slide3.xml")
        self.assertIn('<p:ph type="title"/>', slide)
        self.assertIn('<p:ph idx="1"/>', slide)
        self.assertIn('<a:pPr lvl="1"/>', slide)
        self.assertIn("../slideLayouts/slideLayout2.xml", part("p.pptx", "ppt/slides/_rels/slide3.xml.rels"))
        self.assertIn("/ppt/slides/slide3.xml", part("p.pptx", "[Content_Types].xml"))
        text = self.text("p.pptx")
        self.assertLess(text.index("Plan na rok"), text.index("Harmonogram"))
        self.assertLess(text.index("Harmonogram"), text.index("Budżet"))
        self.ok("p.pptx", action="add_slide", title="Koniec", layout="Slajd tytułowy")
        self.assertIn('type="ctrTitle"', part("p.pptx", "ppt/slides/slide4.xml"))
        self.assertIn("Układy:", self.edit("p.pptx", action="add_slide", title="x", layout="Nie ma"))
        well_formed(self, "p.pptx")
        self.soffice("p.pptx")

    @unittest.skipUnless(_have("pptx"), "python-pptx niedostępne")
    def test_real_python_pptx_file(self):
        import pptx
        pr = pptx.Presentation()
        s = pr.slides.add_slide(pr.slide_layouts[1])
        s.shapes.title.text = "Plan na rok"
        s.placeholders[1].text = "Wstęp"
        pr.save("r.pptx")
        self.ok("r.pptx", edits=[{"action": "replace", "find": "Plan na rok", "replace": "Plan na 2026"},
                                 {"action": "notes", "slide": 1, "text": "Powiedz o budżecie"},
                                 {"action": "add_slide", "title": "Budżet", "body": "Koszty\nPrzychody"}])
        p2 = pptx.Presentation("r.pptx")
        self.assertEqual([[sh.text_frame.text for sh in sl.shapes if sh.has_text_frame] for sl in p2.slides],
                         [["Plan na 2026", "Wstęp"], ["Budżet", "Koszty\nPrzychody"]])
        self.assertEqual(p2.slides[0].notes_slide.notes_text_frame.text, "Powiedz o budżecie")
        well_formed(self, "r.pptx")
        self.soffice("r.pptx")


class Odf(InFolder):
    def test_odt_replace_spans_spaces(self):
        Path("t.odt").write_bytes(make_odf("odt", '<text:h text:outline-level="1">Raport</text:h>'
                                                  '<text:p>Rok <text:span text:style-name="B">20</text:span>25 '
                                                  'był<text:s text:c="2"/>dobry.</text:p>'
                                                  '<text:p>Notka<office:annotation><text:p>Rok 2025</text:p>'
                                                  '</office:annotation></text:p>'))
        self.ok("t.odt", action="replace", find="Rok 2025", replace="Rok 2026")
        xml = part("t.odt", "content.xml")
        self.assertIn('<text:span text:style-name="B">2026</text:span>', xml)
        self.assertIn("<text:p>Rok 2025</text:p>", xml)                              # komentarz nietknięty
        self.ok("t.odt", action="replace", find="był  dobry", replace="był świetny")
        self.ok("t.odt", action="replace", find="Raport", replace="Raport\troczny")
        xml = part("t.odt", "content.xml")
        self.assertIn("był świetny", self.text("t.odt"))
        self.assertIn("<text:tab/>", xml)
        with zipfile.ZipFile("t.odt") as z:
            first = z.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
        self.assertIn("tylko replace", self.edit("t.odt", action="insert_paragraph", text="x").replace(
            "obsługuje akcje: replace", "tylko replace"))
        self.soffice("t.odt")

    def test_ods_skips_numeric_cells(self):
        Path("a.ods").write_bytes(make_odf("ods", '<table:table table:name="A"><table:table-row>'
                                                  '<table:table-cell office:value-type="string" office:string-value="12 szt">'
                                                  '<text:p>12 szt</text:p></table:table-cell>'
                                                  '<table:table-cell office:value-type="float" office:value="12">'
                                                  '<text:p>12</text:p></table:table-cell></table:table-row></table:table>'))
        self.ok("a.ods", action="replace", find="12", replace="15")
        xml = part("a.ods", "content.xml")
        self.assertIn("<text:p>15 szt</text:p>", xml)
        self.assertNotIn("string-value", xml)
        self.assertIn('office:value="12"><text:p>12</text:p>', xml)


class Integration(InFolder):
    def test_backup_undo_diff_event_dry_run(self):
        Path("u.docx").write_bytes(make_docx())
        original = Path("u.docx").read_bytes()
        out = self.edit("u.docx", action="replace", find="Kaucja wynosi", replace="Depozyt wynosi", dry_run=True)
        self.assertTrue(out.startswith("PODGLĄD"), out)
        self.assertIn("-Kaucja wynosi 2000 zł.", out)
        self.assertIn("+Depozyt wynosi 2000 zł.", out)
        self.assertEqual(Path("u.docx").read_bytes(), original)
        events = []
        with patch.object(cli.SYNC, "add", lambda kind, tresc: events.append((kind, tresc))):
            self.ok("u.docx", action="replace", find="Kaucja wynosi", replace="Depozyt wynosi")
            entry = cli.EDIT_LOG[-1]
            with contextlib.redirect_stdout(io.StringIO()):
                cli._print_edit(entry)
        self.assertEqual(entry["format"], "DOCX")
        self.assertEqual((entry["added"], entry["removed"]), (1, 1))
        kind, ev = events[-1]
        self.assertEqual(kind, "edit")
        self.assertEqual(ev["format"], "DOCX")
        self.assertIn("+Depozyt wynosi 2000 zł.", ev["diff"])
        self.assertIn("u.docx", ev["plik"])
        baks = list(Path(".doma/backups").glob("u.docx.*.bak"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_bytes(), original)
        with contextlib.redirect_stdout(io.StringIO()):
            cli._undo_last()
        self.assertEqual(Path("u.docx").read_bytes(), original)

    def test_batch_is_atomic(self):
        Path("k.xlsx").write_bytes(make_xlsx())
        original = Path("k.xlsx").read_bytes()
        out = self.edit("k.xlsx", edits=[{"action": "set_cell", "cell": "B2", "value": 1},
                                         {"action": "set_cell", "sheet": "Brak", "cell": "A1", "value": 1}])
        self.assertIn("edycja 2", out)
        self.assertIn("Plik bez zmian", out)
        self.assertEqual(Path("k.xlsx").read_bytes(), original)
        self.assertFalse(cli.EDIT_LOG)
        self.assertIn("obsługuje akcje", self.edit("k.xlsx", action="notes", slide=1, text="x"))

    def test_read_only_and_wrong_types(self):
        Path("u.docx").write_bytes(make_docx())
        os.chmod("u.docx", 0o444)
        out = self.edit("u.docx", action="replace", find="Kaucja", replace="Depozyt")
        self.assertIn("tylko do odczytu", out)
        Path("a.txt").write_text("x", encoding="utf-8")
        self.assertIn("edit_file", self.edit("a.txt", action="replace", find="x", replace="y"))
        self.assertIn("nie ma pliku", self.edit("brak.docx", action="replace", find="x", replace="y"))
        Path("zly.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 40)
        self.assertIn("BŁĄD", self.edit("zly.docx", action="replace", find="x", replace="y"))

    def test_hints_point_to_office_edit(self):
        Path("u.docx").write_bytes(make_docx())
        self.assertIn("office_edit", cli.t_edit_file({"path": "u.docx", "old_string": "Kaucja", "new_string": "x"}))
        self.assertIn("office_edit", self.text("u.docx").split("\n")[0])
        Path("d.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.assertIn("run_code", cli.t_edit_file({"path": "d.pdf", "old_string": "x", "new_string": "y"}))

    def test_tool_registered(self):
        tool = next(t for t in cli.TOOLS if t["function"]["name"] == "office_edit")
        self.assertIn("replace", tool["function"]["description"])
        self.assertIn("office_edit", next(g for g in cli._TOOL_GROUPS if g[0] == "write")[4])
        self.assertEqual(cli._TOOL_KIND["office_edit"], "edit")
        self.assertIn("office_edit", cli.SYSTEM_PROMPT)
        self.assertIn("office_edit", [t["function"]["name"] for t in cli.enabled_tools()])

    def test_outside_project_needs_consent(self):
        other = tempfile.mkdtemp()
        try:
            Path(other, "u.docx").write_bytes(make_docx())
            with patch.object(cli, "_can_ask_outside", lambda: False):
                out = self.edit(str(Path(other, "u.docx")), action="replace", find="Kaucja", replace="x")
            self.assertIn("poza", out)
            self.assertIn(b"Kaucja", zipfile.ZipFile(Path(other, "u.docx")).read("word/document.xml"))
        finally:
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
