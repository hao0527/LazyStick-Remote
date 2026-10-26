import asyncio
from pathlib import Path
import secrets
import socket
import tempfile
import unittest

import aiohttp
from aiohttp import web
from test_auth_core import AuthController, IdentityStore, FakeApi, FakeProvider
from server import create_app, SITE_ORIGIN


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = AuthController(IdentityStore(Path(self.temp.name) / "identity.json"),
                                         api=FakeApi(), provider_factory=FakeProvider)
        self.key = secrets.token_hex(32)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        self.port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.stop = asyncio.Event()
        app = create_app(self.controller, self.key, self.port, Path(__file__).resolve().parents[1], self.stop)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.SockSite(self.runner, listener).start()
        self.client = aiohttp.ClientSession()
        self.headers = {"X-LazyStick-Auth": self.key, "Origin": SITE_ORIGIN}

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()
        self.temp.cleanup()

    async def test_origin_host_and_capability(self):
        for headers in [{}, {"X-LazyStick-Auth": "bad"}, {**self.headers, "Origin": "https://untrusted.invalid"},
                        {**self.headers, "Host": "untrusted.invalid"}]:
            async with self.client.get(self.base + "/api/state", headers=headers) as r:
                self.assertEqual(r.status, 403)
        async with self.client.options(self.base + "/api/login", headers={"Origin": SITE_ORIGIN}) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], SITE_ORIGIN)
            self.assertEqual(r.headers["Access-Control-Allow-Private-Network"], "true")
        async with self.client.get(self.base + "/api/state", headers=self.headers) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertNotIn("fake-service", await r.text())
        async with self.client.get(self.base + "/helper/auth_core.py") as r:
            self.assertEqual(r.status, 404)

    async def test_login_export_stop_and_errors(self):
        async with self.client.post(self.base + "/api/login", headers=self.headers,
                                    json={"account": "mock", "password": "bad"}) as r:
            self.assertEqual(r.status, 502)
            self.assertNotIn("PRIVATE", await r.text())
        async with self.client.post(self.base + "/api/login", headers=self.headers,
                                    json={"account": "mock", "password": "direct"}) as r:
            self.assertTrue((await r.json())["authenticated"])
        async with self.client.post(self.base + "/api/export", headers=self.headers,
                                    json={"dev_id": "lamp-test-123", "home_id": "home"}) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("lamp-esp32-session.json", r.headers["Content-Disposition"])
            self.assertEqual((await r.json())["target"]["prodId"], "2BNN")
        async with self.client.post(self.base + "/api/login", headers=self.headers, json=[]) as r:
            self.assertEqual(r.status, 400)
        async with self.client.post(self.base + "/api/login", headers=self.headers,
                                    json={"account": "x" * 20000}) as r:
            self.assertNotEqual(r.status, 200)
        async with self.client.post(self.base + "/api/stop", headers=self.headers, json={}) as r:
            self.assertEqual(r.status, 200)
        await asyncio.wait_for(self.stop.wait(), 2)
        self.assertFalse(self.controller.snapshot()["authenticated"])


if __name__ == "__main__":
    unittest.main()
