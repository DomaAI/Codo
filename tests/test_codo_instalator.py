"""Instalatory Codo (install.sh, install.ps1): bez sieci, w tymczasowym katalogu domowym.

Lokalny serwer HTTP udaje bymadd.pl albo stronę wydań. CODO_NO_DEPS=1 w każdym
przebiegu: test nie może niczego doinstalować na maszynie, na której biegnie.
"""
import functools
import hashlib
import http.server
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

CLI = Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")
INSTALL_SH = CLI.parent / "install.sh"
INSTALL_PS1 = CLI.parent / "install.ps1"
BASH = shutil.which("bash")


class _Cichy(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class InstalatorPlikiTests(unittest.TestCase):
    def test_ps1_czyste_ascii(self):
        # Windows PowerShell 5.1 czyta skrypt bez BOM jako ANSI: bajty „—” i polskich liter
        # z UTF-8 zamieniają się w cudzysłowy, które psują składnię.
        zle = [(n, line) for n, line in enumerate(INSTALL_PS1.read_bytes().splitlines(), 1)
               if any(b > 127 for b in line)]
        self.assertEqual(zle, [])

    def test_ps1_instaluje_pythona_i_odswieza_path(self):
        ps1 = INSTALL_PS1.read_text(encoding="ascii")
        self.assertIn("Python.Python.3.13", ps1)
        self.assertIn("Get-AuthenticodeSignature", ps1)
        self.assertIn("CODO_PATH_REFRESH", ps1)       # rozsyła WM_SETTINGCHANGE po zmianie PATH
        self.assertNotIn("exit 1", ps1)               # exit pod `irm | iex` zamyka okno

    @unittest.skipUnless(BASH, "brak bash")
    def test_sh_skladnia(self):
        self.assertEqual(subprocess.run([BASH, "-n", str(INSTALL_SH)]).returncode, 0)

    def test_sh_nie_pyta_o_haslo_i_nie_czyta_stdin(self):
        sh = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn("sudo -n true", sh)             # sudo tylko bez hasła
        # Każde wywołanie menedżera pakietów ma wejście z /dev/null: przy `curl | bash`
        # program czytający stdin zjadłby resztę skryptu.
        for line in sh.splitlines():
            if ">>\"$LOG\" 2>&1" in line and "fetch " not in line:
                self.assertIn("</dev/null", line, line)


@unittest.skipUnless(BASH and os.name != "nt", "instalator powłoki: tylko Linux i macOS")
class InstalatorShTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="codo-inst-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.srv_dir = self.tmp / "srv"
        (self.srv_dir / "cli").mkdir(parents=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        data = CLI.read_bytes()
        self.sha = hashlib.sha256(data).hexdigest()
        (self.srv_dir / "cli" / "doma").write_bytes(data)
        (self.srv_dir / "cli" / "doma.sha256").write_text(self.sha + "\n", encoding="utf-8")
        (self.srv_dir / "codo").write_bytes(data)
        (self.srv_dir / "SHA256SUMS").write_text(f"{self.sha}  codo\n", encoding="utf-8")
        handler = functools.partial(_Cichy, directory=str(self.srv_dir))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.bin = self.home / ".local" / "bin"

    def install(self, path=None, **env):
        full = {"HOME": str(self.home), "SHELL": "/bin/zsh", "PATH": path or os.environ["PATH"],
                "LANG": "pl_PL.UTF-8", "TERM": "dumb", "CODO_NO_DEPS": "1", "DOMA_API_URL": self.url,
                "CODO_SOURCE": "bymadd",   # kopia eksportowana ma domyślnie źródło „wydanie”
                "DOMA_CONFIG_DIR": str(self.home / ".config" / "doma")}
        full.update(env)
        return subprocess.run([BASH, str(INSTALL_SH)], env=full, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120, encoding="utf-8")

    def codo(self, *args, path=None):
        env = {"HOME": str(self.home), "PATH": path or os.environ["PATH"], "CODO_LANG": "pl",
               "DOMA_CONFIG_DIR": str(self.home / ".config" / "doma")}
        return subprocess.run([str(self.bin / "codo"), *args], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60, encoding="utf-8")

    def test_swieza_instalacja(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Suma kontrolna zgodna", r.stdout)
        self.assertIn("Zainstalowano Codo", r.stdout)
        self.assertEqual(self.codo("version").returncode, 0)
        for old in ("domaai", "doma", "domaai-code"):
            self.assertTrue((self.bin / old).is_symlink(), old)
        # Świeży macOS nie ma ~/.zshrc: instalator go tworzy, inaczej `codo` nie ma w PATH.
        rc = (self.home / ".zshrc").read_text(encoding="utf-8")
        self.assertIn(f'export PATH="{self.bin}:$PATH"', rc)
        # Druga instalacja niczego nie dubluje.
        r2 = self.install()
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("Przeinstalowano", r2.stdout)
        self.assertEqual((self.home / ".zshrc").read_text(encoding="utf-8").count("export PATH="), 1)

    def test_komunikaty_po_angielsku(self):
        r = self.install(LANG="en_US.UTF-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Installed Codo", r.stdout)
        self.assertIn("Get started", r.stdout)

    def test_powloki_bash_i_fish(self):
        (self.home / ".bashrc").write_text("# moje\n", encoding="utf-8")
        self.assertEqual(self.install(SHELL="/bin/bash").returncode, 0)
        self.assertIn(str(self.bin), (self.home / ".bashrc").read_text(encoding="utf-8"))
        shutil.rmtree(self.bin)
        self.assertEqual(self.install(SHELL="/usr/bin/fish").returncode, 0)
        self.assertIn(f'fish_add_path -g "{self.bin}"', (self.home / ".config/fish/config.fish").read_text(encoding="utf-8"))

    def test_zla_suma_przerywa(self):
        (self.srv_dir / "cli" / "doma.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Suma kontrolna się nie zgadza", r.stderr)
        self.assertFalse((self.bin / "codo").exists())

    def test_obciete_pobranie_przerywa(self):
        data = CLI.read_bytes()[:20_000]
        (self.srv_dir / "cli" / "doma").write_bytes(data)
        (self.srv_dir / "cli" / "doma.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n", encoding="utf-8")
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Nic nie zmieniono", r.stderr)
        self.assertFalse((self.bin / "codo").exists())

    def test_instalatory_nie_wymieniaja_hostingu_kodu(self):
        # 21.11.2026: pliki serwowane publicznie nie mogą zdradzać, gdzie leży kod ani jak nazywa się repo.
        katalog = Path(INSTALL_SH).parent
        if 'DEFAULT_SOURCE="wydanie"' in INSTALL_SH.read_text(encoding="utf-8"):
            self.skipTest("kopia eksportowana ma adres wydań wpisany celowo")
        for nazwa in ("install.sh", "install.ps1"):
            tekst = (katalog / nazwa).read_text(encoding="utf-8").lower()
            for slowo in ("github", "beepmadd"):
                self.assertNotIn(slowo, tekst, f"{nazwa} wymienia {slowo}")

    def test_zrodlo_wydanie_wymaga_adresu(self):
        if 'CODO_RELEASES_URL:-}' not in INSTALL_SH.read_text(encoding="utf-8"):
            self.skipTest("kopia eksportowana ma adres wydań wpisany celowo (instalacja poszłaby do sieci)")
        r = self.install(CODO_SOURCE="wydanie")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CODO_RELEASES_URL", r.stderr)
        self.assertFalse((self.bin / "codo").exists())

    def test_zrodlo_wydanie(self):
        # dawna wartość CODO_SOURCE (inna niż bymadd) dalej znaczy „wydanie”
        r = self.install(CODO_SOURCE="github", CODO_BASE_URL=self.url, LANG="en_US.UTF-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Checksum verified", r.stdout)
        self.assertEqual(self.codo("version").returncode, 0)
        self.assertFalse((self.bin / "domaai").exists())     # dawne nazwy tylko tam, gdzie już były
        shutil.rmtree(self.bin)
        (self.srv_dir / "SHA256SUMS").write_text(f"{self.sha}  inny-plik\n", encoding="utf-8")
        r = self.install(CODO_SOURCE="wydanie", CODO_BASE_URL=self.url, LANG="en_US.UTF-8")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no entry for codo", r.stderr)

    def _path_ze_starym_pythonem(self):
        """PATH, w którym `python3` się nie nadaje, a dobry interpreter ma inną nazwę."""
        fake = self.tmp / "fakebin"
        fake.mkdir()
        (fake / "python3").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (fake / "python3").chmod(0o755)
        real = os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)
        os.symlink(real, fake / "python3.12")
        return f"{fake}{os.pathsep}/usr/bin{os.pathsep}/bin"

    def test_python3_z_path_za_stary_interpreter_w_pierwszej_linii(self):
        path = self._path_ze_starym_pythonem()
        r = self.install(path=path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = (self.bin / "codo").read_bytes().split(b"\n", 1)[0]
        self.assertTrue(first.startswith(b"#!/") and b"/env " not in first, first)
        # Działa mimo złego `python3` w PATH.
        v = self.codo("version", path=path)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        # `codo update` zachowuje tę linię, inaczej nowa wersja wróciłaby do `env python3`.
        loader = importlib.machinery.SourceFileLoader("codo_inst_runtime", str(CLI))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        fresh = CLI.read_bytes()
        kept = mod._keep_shebang(self.bin / "codo", fresh)
        self.assertEqual(kept.split(b"\n", 1)[0], first)
        self.assertEqual(kept.split(b"\n", 1)[1], fresh.split(b"\n", 1)[1])
        # Zwykła instalacja (env python3) zostaje bez zmian.
        plain = self.tmp / "plain"
        plain.write_bytes(fresh)
        self.assertEqual(mod._keep_shebang(plain, fresh), fresh)

    def test_brak_prawa_zapisu_czytelny_blad(self):
        ro = self.tmp / "ro"
        ro.mkdir()
        ro.chmod(0o555)
        self.addCleanup(ro.chmod, 0o755)
        if os.access(ro, os.W_OK):
            self.skipTest("root zapisuje wszędzie")
        r = self.install(CODO_BIN_DIR=str(ro))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CODO_BIN_DIR", r.stderr)


if __name__ == "__main__":
    unittest.main()
