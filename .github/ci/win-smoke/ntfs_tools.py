"""Windows smoke: the engine's file tools on a real NTFS disk.
Locked file (held by another process), read-only file, path longer than 260, cp1250, CRLF, file_op move over a file.

usage: python ntfs_tools.py <path to codo script>
"""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-ntfs-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
os.environ["CODO_LANG"] = "pl"
script = sys.argv[1] if len(sys.argv) > 1 else "codo"
loader = importlib.machinery.SourceFileLoader("codo_ntfs", script)
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if detail:
        print("     " + str(detail).replace("\n", "\n     ")[:1500], flush=True)


def tool(name, **args):
    try:
        return cli.run_tool(name, args, True)
    except BaseException as e:  # noqa: BLE001
        return "EXCEPTION " + "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1500:]


def ugly(out):
    """A raw OS error the user (and the model) would not understand, or a Python traceback."""
    return "EXCEPTION" in out or "Traceback" in out


root = Path(os.environ.get("SMOKE_ROOT") or (Path("C:/") if os.name == "nt" else Path(tempfile.mkdtemp())))
proj = root / "codo ntfs ąę"
if proj.exists():
    shutil.rmtree(proj, ignore_errors=True)
proj.mkdir(parents=True)
os.chdir(proj)
print("python", sys.version, "cwd", Path.cwd(), "version", getattr(cli, "VERSION", "?"))


def hold(path, share):
    """Another process keeps the file open (like Word/Excel/an editor). share: None | Read | ReadWrite | ReadWriteDelete."""
    if os.name != "nt":
        return None
    sh = {"ReadWriteDelete": "'ReadWrite, Delete'"}.get(share, f"'{share}'")
    ps = (f"$f=[System.IO.File]::Open('{path}','Open','ReadWrite',{sh}); "
          "[Console]::Out.WriteLine('held'); [Console]::Out.Flush(); Start-Sleep -Seconds 600")
    p = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.PIPE, text=True)
    p.stdout.readline()
    time.sleep(0.5)
    return p


# ── CRLF ────────────────────────────────────────────────────────────────────────────────────────
Path("crlf.txt").write_bytes(b"alfa\r\nbeta\r\ngamma\r\n")
out = tool("read_file", path="crlf.txt")
check("CRLF read shows lines without \\r", "2\tbeta" in out and "\r" not in out, out[:300])
out = tool("edit_file", path="crlf.txt", old_string="beta\ngamma", new_string="BETA\nGAMMA\ndelta")
data = Path("crlf.txt").read_bytes()
check("CRLF edit across lines keeps CRLF", data == b"alfa\r\nBETA\r\nGAMMA\r\ndelta\r\n", f"{out[:300]}\n{data!r}")
out = tool("write_file", path="crlf.txt", content="jeden\ndwa\n")
data = Path("crlf.txt").read_bytes()
check("CRLF write_file keeps CRLF", data == b"jeden\r\ndwa\r\n", f"{out[:300]}\n{data!r}")
out = tool("multi_edit", path="crlf.txt", edits=[{"old_string": "jeden", "new_string": "1"},
                                                 {"old_string": "dwa", "new_string": "2"}])
check("CRLF multi_edit", Path("crlf.txt").read_bytes() == b"1\r\n2\r\n", out[:300])

# ── cp1250 ──────────────────────────────────────────────────────────────────────────────────────
Path("stary.txt").write_bytes("Zażółć gęślą jaźń\r\nŁódź\r\n".encode("cp1250"))
out = tool("read_file", path="stary.txt")
check("cp1250 read decoded", "Zażółć gęślą jaźń" in out and "Łódź" in out, out[:300])
out = tool("edit_file", path="stary.txt", old_string="Łódź", new_string="Kraków ść")
data = Path("stary.txt").read_bytes()
check("cp1250 edit stays cp1250 + CRLF", data == "Zażółć gęślą jaźń\r\nKraków ść\r\n".encode("cp1250"), f"{out[:300]}\n{data!r}")
out = tool("grep", pattern="gęślą", path=".")
check("grep finds text in cp1250 file", "stary.txt" in out, out[:300])

# ── read-only ──────────────────────────────────────────────────────────────────────────────────
ro = Path("tylko do odczytu.txt")
ro.write_text("stare\n", encoding="utf-8")
os.chmod(ro, 0o444)
out = tool("edit_file", path=str(ro), old_string="stare", new_string="nowe")
check("read-only: edit refused with a clear message", ro.read_text(encoding="utf-8") == "stare\n" and not ugly(out)
      and "odczytu" in out, out[:400])
out = tool("write_file", path=str(ro), content="x\n")
check("read-only: write_file refused", ro.read_text(encoding="utf-8") == "stare\n" and not ugly(out), out[:400])
out = tool("file_op", action="delete", path=str(ro))
print("   read-only delete ->", out[:300])
check("read-only: delete does not crash", not ugly(out), out[:400])
if ro.exists():
    os.chmod(ro, 0o666)

# ── long path > 260 ─────────────────────────────────────────────────────────────────────────────
deep = Path(*["katalog_o_dlugiej_nazwie_ąę_" + str(i) for i in range(10)])
rel = str(deep / "plik z długą nazwą zażółć.txt")
print("   long path length:", len(str(Path.cwd() / rel)))
out = tool("write_file", path=rel, content="długi\n")
check("long path: write_file", "BŁĄD" not in out and not ugly(out), out[:400])
out = tool("read_file", path=rel)
check("long path: read_file", "długi" in out, out[:400])
out = tool("edit_file", path=rel, old_string="długi", new_string="dłuższy")
check("long path: edit_file", "BŁĄD" not in out and not ugly(out), out[:400])
out = tool("list_dir", path=str(deep))
check("long path: list_dir", "plik z długą" in out, out[:400])
out = tool("file_op", action="copy", path=rel, dest=rel + ".kopia")
check("long path: file_op copy", "BŁĄD" not in out and not ugly(out), out[:400])
out = tool("file_op", action="move", path=rel + ".kopia", dest=rel, overwrite=True)
check("long path: file_op move over a file", "BŁĄD" not in out and not ugly(out), out[:400])
out = tool("find_files", pattern="*zażółć*")
check("long path: find_files", "plik z długą" in out, out[:400])
out = tool("file_op", action="delete", path=str(deep / "plik z długą nazwą zażółć.txt"))
check("long path: file_op delete (to trash)", "BŁĄD" not in out and not ugly(out), out[:400])

# ── file_op move with overwrite ────────────────────────────────────────────────────────────────
Path("a.txt").write_text("A\n", encoding="utf-8")
Path("b.txt").write_text("B\n", encoding="utf-8")
out = tool("file_op", action="move", path="a.txt", dest="b.txt")
check("move onto existing without overwrite refused", Path("a.txt").exists() and "BŁĄD" in out, out[:300])
out = tool("file_op", action="move", path="a.txt", dest="b.txt", overwrite=True)
check("move with overwrite", not Path("a.txt").exists() and Path("b.txt").read_text() == "A\n", out[:300])
Path("A.TXT").write_text("duze\n", encoding="utf-8") if not Path("A.TXT").exists() else None
out = tool("file_op", action="rename", path="A.TXT", dest="a.txt")
check("rename that only changes letter case", not ugly(out) and "a.txt" in os.listdir("."), f"{out[:300]} {os.listdir('.')}")
Path("dir1").mkdir()
Path("dir1/x.txt").write_text("x", encoding="utf-8")
out = tool("file_op", action="move", path="dir1", dest="dir2")
check("move folder", Path("dir2/x.txt").exists(), out[:300])

# ── locked files (another process holds them) ──────────────────────────────────────────────────
if os.name == "nt":
    for share in ("None", "Read", "ReadWrite", "ReadWriteDelete"):
        f = Path(f"trzymany {share}.txt").resolve()
        f.write_text("treść\n", encoding="utf-8")
        p = hold(str(f), share)
        try:
            t0 = time.time()
            r = tool("read_file", path=str(f))
            print(f"   [{share}] read ({time.time() - t0:.1f}s) -> {r[:200]}")
            readable = share != "None"
            check(f"locked {share}: read_file " + ("works" if readable else "clear error"),
                  ("treść" in r) if readable else (not ugly(r) and "treść" not in r), r[:400])
            t0 = time.time()
            r = tool("edit_file", path=str(f), old_string="treść", new_string="nowa")
            took = time.time() - t0
            print(f"   [{share}] edit ({took:.1f}s) -> {r[:300]}")
            check(f"locked {share}: edit_file no traceback, < 15 s", not ugly(r) and took < 15, r[:400])
            if share in ("ReadWrite", "ReadWriteDelete"):
                check(f"locked {share}: edit_file writes in place", "nowa" in f.read_text(encoding="utf-8"), r[:400])
            check(f"locked {share}: edit_file message mentions another program when it fails",
                  "BŁĄD" not in r or any(w in r.lower() for w in ("innym programie", "otwarty")), r[:400])
            r = tool("file_op", action="move", path=str(f), dest=str(f) + ".przeniesiony")
            print(f"   [{share}] move -> {r[:300]}")
            check(f"locked {share}: file_op move no traceback", not ugly(r), r[:400])
            r = tool("file_op", action="delete", path=str(f))
            print(f"   [{share}] delete -> {r[:300]}")
            check(f"locked {share}: file_op delete no traceback", not ugly(r), r[:400])
        finally:
            if p:
                p.kill()
                p.wait()
    # destination of a move is locked
    Path("src.txt").write_text("nowe\n", encoding="utf-8")
    dst = Path("cel zablokowany.txt").resolve()
    dst.write_text("stare\n", encoding="utf-8")
    p = hold(str(dst), "Read")
    try:
        r = tool("file_op", action="move", path="src.txt", dest=str(dst), overwrite=True)
        print("   move onto locked ->", r[:300])
        check("move onto locked destination: no traceback, source kept", not ugly(r) and
              (Path("src.txt").exists() or dst.read_text() == "nowe\n"), r[:400])
    finally:
        p.kill()
        p.wait()
    print("   after move onto locked:", sorted(os.listdir(".")))
    check("move onto locked destination: nothing lost", Path("src.txt").exists() or (dst.exists() and dst.read_text() == "nowe\n"),
          str(sorted(os.listdir("."))))

# ── names Windows does not allow ───────────────────────────────────────────────────────────────
for bad in ("CON.txt", "plik?.txt", "nazwa:strumień.txt", "spacja na końcu .txt"):
    r = tool("write_file", path=bad, content="x\n")
    print(f"   write {bad!r} -> {r[:200]}")
    check(f"forbidden name {bad!r}: no traceback", not ugly(r), r[:300])

bad = [r for r in RESULTS if not r[1]]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
for n, _, d in bad:
    print("  FAILED:", n, "|", str(d)[:400].replace("\n", " / "))
sys.exit(1 if bad else 0)
