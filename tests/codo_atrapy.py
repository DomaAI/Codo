"""Wspólne pomoce testów silnika Codo, przenośne między Linuksem, macOS i Windows.

Atrapy programów (agent claude/codex, gh, python3) to skrypty Pythona. Na Linuksie i macOS
plik wykonywalny z pierwszą linią #!sys.executable; na Windows (brak shebangów) obok skryptu
leży NAZWA.cmd, który woła ten sam interpreter, tak jak npm instaluje claude.cmd i codex.cmd.
"""
import contextlib
import os
import sys
from pathlib import Path

IS_WIN = os.name == "nt"


def _launcher_exe():
    """Windows: launcher pip/distlib (ten sam, z którego powstają pip.exe i inne programy z konsoli)."""
    try:
        import pip._vendor.distlib as d
    except ImportError:
        return None
    f = Path(d.__file__).parent / ("t64.exe" if sys.maxsize > 2 ** 32 else "t32.exe")
    return f if f.is_file() else None


def atrapa(folder, name: str, code: str, exe: bool = False) -> Path:
    """Program `name` w `folder` wykonujący kod Pythona `code`. Zwraca ścieżkę do uruchamiania.
    Windows: domyślnie NAZWA.cmd jak shim npm (claude.cmd, codex.cmd); exe=True daje prawdziwy NAZWA.exe
    (launcher distlib, jak gh.exe), który dostaje argumenty bez pośrednictwa cmd.exe."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if IS_WIN and exe and _launcher_exe():
        import io as _io
        import zipfile
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("__main__.py", code)
        out = folder / f"{name}.exe"
        out.write_bytes(_launcher_exe().read_bytes() + f'#!"{sys.executable}"\r\n'.encode("utf-8") + buf.getvalue())
        return out
    if IS_WIN:
        script = folder / f"{name}.py"
        script.write_text(code, encoding="utf-8")
        cmd = folder / f"{name}.cmd"
        cmd.write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\r\n', encoding="utf-8")
        return cmd
    exe = folder / name
    exe.write_text(f"#!{sys.executable}\n" + code, encoding="utf-8")
    exe.chmod(0o755)
    return exe


def zamknij_stdin(p) -> None:
    """Zamknięcie wejścia procesu, który mógł się już zakończyć (Windows: OSError EINVAL przy flush)."""
    with contextlib.suppress(OSError, ValueError):
        p.stdin.close()


def dom_env(home) -> dict:
    """Zmienne katalogu domowego dla procesu potomnego: HOME i USERPROFILE (Windows czyta USERPROFILE)."""
    return {"HOME": str(home), "USERPROFILE": str(home)}


# ── testy w stylu pytest uruchamiane też przez `python -m unittest` (bez pytest) ──────────────────
# Moduł pisze `from codo_atrapy import pytest` i na końcu `load_tests = jako_unittest(globals())`.
# Pod pytest wszystko idzie do prawdziwego pytest (fixture, raises, fail); unittest dostaje klasę
# z tymi samymi funkcjami test_*, a fixture tmp_path, monkeypatch, capsys i własne moduły rozwiązuje sam.
import importlib  # noqa: E402
import inspect  # noqa: E402
import io  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

try:
    import pytest as _pytest
except ImportError:
    _pytest = None

_FIXTURES = {}   # id(obiekt fixture w module) -> zwykła funkcja


class _Atrapa:
    """Podzbiór pytest używany przez te testy."""

    def fixture(self, fn=None, **kw):
        def wrap(f):
            obj = _pytest.fixture(**kw)(f) if _pytest else f
            _FIXTURES[id(obj)] = f
            return obj
        return wrap(fn) if fn is not None else wrap

    def fail(self, msg=""):
        if _pytest:
            _pytest.fail(msg)
        raise AssertionError(msg)

    def raises(self, exc):
        if _pytest:
            return _pytest.raises(exc)
        return _Raises(exc)

    def __getattr__(self, name):
        if _pytest is None:
            raise AttributeError(name)
        return getattr(_pytest, name)


class _Raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None

    def __enter__(self):
        return self

    def __exit__(self, typ, val, tb):
        if typ is None:
            raise AssertionError(f"DID NOT RAISE {self.exc}")
        if not issubclass(typ, self.exc):
            return False
        self.value = val
        return True


pytest = _Atrapa()


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value=None, raising=True):
        if isinstance(target, str):
            value = name
            mod, _, name = target.rpartition(".")
            target = importlib.import_module(mod)
        old = getattr(target, name, _MISSING)
        if old is _MISSING and raising:
            raise AttributeError(name)
        self._undo.append(lambda: delattr(target, name) if old is _MISSING else setattr(target, name, old))
        setattr(target, name, value)

    def setenv(self, name, value):
        old = os.environ.get(name)
        self._undo.append(lambda: os.environ.pop(name, None) if old is None else os.environ.__setitem__(name, old))
        os.environ[name] = str(value)

    def delenv(self, name, raising=True):
        if name not in os.environ:
            if raising:
                raise KeyError(name)
            return
        old = os.environ.pop(name)
        self._undo.append(lambda: os.environ.__setitem__(name, old))

    def undo(self):
        while self._undo:
            self._undo.pop()()


_MISSING = object()


class _Capsys:
    def __init__(self, case):
        self.out, self.err = io.StringIO(), io.StringIO()
        for stream, buf in (("stdout", self.out), ("stderr", self.err)):
            old = getattr(sys, stream)
            case.addCleanup(setattr, sys, stream, old)
            setattr(sys, stream, buf)

    def readouterr(self):
        o, e = self.out.getvalue(), self.err.getvalue()
        self.out.seek(0), self.out.truncate(), self.err.seek(0), self.err.truncate()
        return type("CaptureResult", (), {"out": o, "err": e})()


def jako_unittest(module_globals):
    """Hak load_tests: funkcje test_* modułu jako metody jednej klasy unittest."""
    def resolve(case, name, cache):
        if name in cache:
            return cache[name]
        if name == "tmp_path":
            d = tempfile.mkdtemp(prefix="codo-test-")
            case.addCleanup(shutil.rmtree, d, True)
            val = Path(d)
        elif name == "monkeypatch":
            val = MonkeyPatch()
            case.addCleanup(val.undo)
        elif name == "capsys":
            val = _Capsys(case)
        else:
            fn = _FIXTURES.get(id(module_globals.get(name)))
            if fn is None:
                raise LookupError(f"fixture {name}")
            val = fn(*[resolve(case, a, cache) for a in inspect.signature(fn).parameters])
            if inspect.isgenerator(val):
                gen = val
                val = next(gen)
                case.addCleanup(lambda: next(gen, None))
        cache[name] = val
        return val

    def make(fn):
        def test(self):
            cache = {}
            args = [resolve(self, a, cache) for a in inspect.signature(fn).parameters]
            fn(*args)
        test.__name__, test.__doc__ = fn.__name__, fn.__doc__
        return test

    tests = {n: make(f) for n, f in module_globals.items()
             if n.startswith("test_") and inspect.isfunction(f) and f.__module__ == module_globals["__name__"]}
    case = type("PytestowyModul", (unittest.TestCase,), tests)
    case.__module__ = module_globals["__name__"]

    def load_tests(loader, standard_tests, pattern):
        standard_tests.addTests(loader.loadTestsFromTestCase(case))
        return standard_tests
    return load_tests


def sprzataj(tmp, sekundy: float = 15.0) -> None:
    """TemporaryDirectory.cleanup() z ponowieniem na Windows: katalog bywa jeszcze zajęty przez proces potomny,
    który właśnie się kończy (WinError 32). Proces, który nie zniknie w tym czasie, wywraca test jak wcześniej."""
    import time
    end = time.monotonic() + (sekundy if IS_WIN else 0)
    while True:
        try:
            tmp.cleanup()
            return
        except PermissionError:
            if time.monotonic() > end:
                raise
            time.sleep(0.5)
