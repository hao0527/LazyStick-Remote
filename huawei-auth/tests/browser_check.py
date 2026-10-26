"""Real browser + real loopback HTTP, with mocked Huawei login/discovery only."""
import asyncio
import json
import mimetypes
from pathlib import Path
import secrets
import socket
import tempfile
import threading
from urllib.parse import urlsplit

from aiohttp import web
from playwright.sync_api import sync_playwright, expect
from test_auth_core import AuthController, IdentityStore, FakeApi, FakeProvider
from server import create_app, SITE_ORIGIN

PAGE = Path(__file__).resolve().parents[1]
OUTPUT = PAGE.parent / ".auth-build/browser"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        core = AuthController(IdentityStore(Path(temporary) / "identity.json"), api=FakeApi(), provider_factory=FakeProvider)
        key = secrets.token_hex(32)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        port = listener.getsockname()[1]
        ready = threading.Event()
        loop = asyncio.new_event_loop()
        stop = asyncio.Event()

        async def serve():
            runner = web.AppRunner(create_app(core, key, port, PAGE, stop), access_log=None)
            await runner.setup()
            await web.SockSite(runner, listener).start()
            ready.set()
            try:
                await stop.wait()
                await asyncio.sleep(1)
            finally:
                await runner.cleanup()

        thread = threading.Thread(target=lambda: loop.run_until_complete(serve()), daemon=True)
        thread.start()
        assert ready.wait(10)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                context = browser.new_context(viewport={"width": 1080, "height": 1000}, accept_downloads=True)
                context.grant_permissions(["local-network-access"], origin=SITE_ORIGIN)
                page = context.new_page()
                errors, remote_requests = [], []
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(request):
                    url = request.request.url
                    if url.startswith(f"http://127.0.0.1:{port}/"):
                        return request.continue_()
                    remote_requests.append((url, request.request.method))
                    parsed = urlsplit(url)
                    name = "index.html" if parsed.path == "/huawei-auth/" else parsed.path.rsplit("/", 1)[-1]
                    if parsed.netloc == "lazystick.icu" and name in {"index.html", "app.js", "style.css"}:
                        return request.fulfill(body=(PAGE / name).read_bytes(), content_type=mimetypes.guess_type(name)[0])
                    return request.abort()

                page.route("**/*", route)
                base = SITE_ORIGIN + "/huawei-auth/"
                page.goto(base)
                expect(page.locator("#login")).to_be_disabled()
                page.screenshot(path=str(OUTPUT / "landing-desktop.png"), full_page=True)
                page.goto(f"{base}#port={port}&key={key}")
                # A fragment-only navigation does not reload JS; reload to emulate a new launch.
                page.reload()
                expect(page.locator("#connection-badge")).to_have_text("已连接", timeout=15000)
                assert page.url == base
                page.locator("#account").fill("mock@example.test")
                page.locator("#password").fill("bad")
                page.locator("#login").click()
                expect(page.locator("#status")).to_contain_text("未完成")
                expect(page.locator("#password")).to_have_value("")
                page.locator("#password").fill("challenge")
                page.locator("#login").click()
                expect(page.locator("#challenge-panel")).to_be_visible()
                page.locator("#send-code").click()
                expect(page.locator("#verify-form")).to_be_visible()
                page.locator("#code").fill("bad-code")
                page.locator('#verify-form button').click()
                expect(page.locator("#status")).to_contain_text("验证码错误")
                page.locator("#code").fill("123456")
                page.locator('#verify-form button').click()
                expect(page.locator("#signed-in")).to_be_visible()
                expect(page.locator("#device option")).to_have_count(1)
                with page.expect_download() as download:
                    page.locator("#download").click()
                file = download.value
                assert file.suggested_filename == "lamp-esp32-session.json"
                file.save_as(OUTPUT / "mock-download.json")
                exported = json.loads((OUTPUT / "mock-download.json").read_text())
                assert exported["schema_version"] == 1 and exported["target"]["prodId"] == "2BNN"
                assert "account" not in exported["session"]
                assert page.evaluate("JSON.stringify(localStorage)") == "{}"
                page.set_viewport_size({"width": 375, "height": 850})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(OUTPUT / "connected-mobile-dark.png"), full_page=True)
                page.locator("#theme-toggle").click()
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.screenshot(path=str(OUTPUT / "connected-mobile-light.png"), full_page=True)
                storage = page.evaluate("Object.keys(localStorage)")
                assert storage == ["lazystick.huaweiAuth.theme"]
                page.locator("#logout").click()
                expect(page.locator("#login-form")).to_be_visible()
                expect(page.locator("#download")).to_be_disabled()
                expect(page.locator("#account")).to_have_value("")
                page.locator("#disconnect").click()
                expect(page.locator("#status")).to_contain_text("助手已退出")
                assert all(method == "GET" and key not in url for url, method in remote_requests)
                assert not errors, errors
                browser.close()
                print("PASS browser: HTTPS-to-loopback, SMS challenge, errors, device filtering, JSON download, mobile/themes, no credential storage or remote POST")
        finally:
            loop.call_soon_threadsafe(stop.set)
            thread.join(5)
            loop.close()


if __name__ == "__main__":
    main()
