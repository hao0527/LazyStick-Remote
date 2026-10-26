"""Start the distributed EXE, inspect its UI, then stop it without cloud writes."""
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler
import zipfile

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        with zipfile.ZipFile(ROOT / "huawei-auth/downloads/LazyStick-Huawei-Auth-windows-x64.zip") as archive:
            for name in archive.namelist():
                assert (directory / name).resolve().is_relative_to(directory.resolve())
            archive.extractall(directory)
        process = subprocess.Popen([str(directory / "LazyStick-Huawei-Auth.exe"), "--no-browser", "--local"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        lines = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True).start()
        try:
            url = None
            for _ in range(6):
                line = lines.get(timeout=30)
                if line.startswith("Page: "):
                    url = line[6:].strip()
                    break
            assert url, "Helper did not start"
            parsed = urlsplit(url)
            key = parse_qs(parsed.fragment)["key"][0]
            opener = build_opener(ProxyHandler({}))
            state = json.load(opener.open(Request(f"http://{parsed.netloc}/api/state", headers={"X-LazyStick-Auth": key})))
            assert not state["authenticated"]
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 375, "height": 850})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url)
                expect(page.locator("#connection-badge")).to_have_text("已连接")
                expect(page.locator("#login")).to_be_enabled()
                assert not urlsplit(page.url).fragment
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.locator("#disconnect").click()
                expect(page.locator("#status")).to_contain_text("助手已退出")
                assert not errors, errors
                browser.close()
            assert process.wait(timeout=15) == 0
            print("PASS distributed Windows EXE: starts without Python, serves bundled UI, connects, exits and clears session")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
