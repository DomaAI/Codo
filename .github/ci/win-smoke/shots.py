"""Windows smoke: screenshots of the Codo window in Microsoft Edge (Playwright, channel msedge).
1. first start without any account (license / sign-in screen)
2. a conversation with a local fake model (OpenAI-compatible /v1 on 127.0.0.1, no real provider)

usage: python shots.py <out dir>      (CODO_FILE = path to the codo script)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake as T  # noqa: E402  (fake model, env and start helpers)
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "shots").resolve()
out.mkdir(parents=True, exist_ok=True)
channel = os.environ.get("SHOT_CHANNEL", "msedge")
root = Path(tempfile.mkdtemp(prefix="codo shots ąę "))
proj = root / "mój projekt"
proj.mkdir()
(proj / "app.py").write_text("def main():\n    print('hej')\n", encoding="utf-8")
(proj / "README.md").write_text("# Projekt\n\nZażółć gęślą jaźń.\n", encoding="utf-8")
srv, model_url = T.start_fake_model()
problems = []


def post(url_base, tok, path, body):
    r = urllib.request.Request(url_base + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json", "X-Codo-Token": tok})
    return urllib.request.urlopen(r, timeout=20).read()


def shoot(page, name):
    p = out / f"{name}.png"
    page.screenshot(path=str(p), full_page=False)
    print("shot", p, flush=True)


def console_hook(page, tag):
    page.on("console", lambda m: print(f"[{tag} console {m.type}] {m.text}"[:400]) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: (problems.append(f"{tag}: {e}"), print(f"[{tag} pageerror] {e}"[:600])))


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel=channel, headless=True)
    for lang in ("pl", "en"):
        # ── 1. first start: no account at all ──
        env = T.make_env(root / f"first-{lang}", model_url, lang)
        cfg = Path(env["DOMA_CONFIG_DIR"])
        (cfg / "konta.json").unlink()
        (cfg / "settings.json").write_text(json.dumps({"lang": lang}))
        p, url, port, tok = T.start_ui(proj, env)
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="pl-PL" if lang == "pl" else "en-US")
            page = ctx.new_page()
            console_hook(page, f"first-{lang}")
            page.goto(url)
            page.wait_for_timeout(3500)
            shoot(page, f"1-first-start-{lang}")
            post(f"http://127.0.0.1:{port}", tok, "/api/license", {"use": "personal"})
            page.reload()
            page.wait_for_timeout(3500)
            shoot(page, f"2-sign-in-{lang}")
            ctx.close()
        finally:
            try:
                post(f"http://127.0.0.1:{port}", tok, "/api/quit", {})
            except Exception:
                pass
            try:
                p.wait(20)
            except Exception:
                p.kill()

        # ── 2. a conversation with the fake model ──
        env = T.make_env(root / f"chat-{lang}", model_url, lang)
        p, url, port, tok = T.start_ui(proj, env)
        try:
            post(f"http://127.0.0.1:{port}", tok, "/api/license", {"use": "personal"})
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="pl-PL" if lang == "pl" else "en-US")
            page = ctx.new_page()
            console_hook(page, f"chat-{lang}")
            page.goto(url + "&gate=0")     # past the sign-in gate, like the Mac screenshots (CODO_*)
            page.wait_for_timeout(3000)
            shoot(page, f"3-agent-creator-{lang}")
            import re as _re
            later = page.get_by_role("button", name=_re.compile("Nie teraz|Not now"))
            if later.count():
                later.first.click()
                page.wait_for_timeout(1500)
            shoot(page, f"3-home-{lang}")
            box = page.locator("#input")
            try:
                box.wait_for(state="visible", timeout=15000)
                box.click()
                box.fill("Opisz strukturę projektu" if lang == "pl" else "Describe the project structure")
                page.keyboard.press("Enter")
                try:
                    page.get_by_role("heading", name="Struktura projektu").first.wait_for(timeout=40000)
                except Exception as e:
                    problems.append(f"chat-{lang}: answer not shown: {e}"[:300])
                page.wait_for_timeout(2500)
                shoot(page, f"4-conversation-{lang}")
                box.fill("zapisz notatkę" if lang == "pl" else "zapisz a note")
                page.keyboard.press("Enter")
                page.wait_for_timeout(8000)
                shoot(page, f"5-tools-{lang}")
                yes = page.get_by_role("button", name=_re.compile("^(Tak|Yes)$"))
                if yes.count():
                    yes.first.click()
                    try:
                        page.locator("p", has_text="Komenda zwróciła").first.wait_for(timeout=40000)
                    except Exception as e:
                        problems.append(f"chat-{lang}: command not finished: {e}"[:300])
                    page.wait_for_timeout(1500)
                    shoot(page, f"5b-command-done-{lang}")
                else:
                    problems.append(f"chat-{lang}: no Yes button for the command")
                ctx.set_default_timeout(5000)
                page.set_viewport_size({"width": 420, "height": 860})
                page.wait_for_timeout(1500)
                shoot(page, f"6-narrow-{lang}")
            except Exception as e:
                problems.append(f"chat-{lang}: {e}"[:400])
                shoot(page, f"4-conversation-{lang}-error")
            ctx.close()
        finally:
            try:
                post(f"http://127.0.0.1:{port}", tok, "/api/quit", {})
            except Exception:
                pass
            try:
                p.wait(20)
            except Exception:
                p.kill()
    browser.close()

srv.shutdown()
shutil.rmtree(root, ignore_errors=True)
print("problems:", json.dumps(problems, ensure_ascii=False, indent=1))
sys.exit(1 if problems else 0)
