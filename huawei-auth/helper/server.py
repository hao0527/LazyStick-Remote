"""Loopback-only bridge for the independent authorization page.

SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
from contextlib import suppress
import ipaddress
import json
from pathlib import Path
import secrets
import time

from aiohttp import web
from auth_core import InputError, public_error

SITE_ORIGIN = "https://lazystick.icu"
CONTROLLER = web.AppKey("controller", object)
KEY = web.AppKey("key", str)
STOP = web.AppKey("stop", asyncio.Event)
LAST_USED = web.AppKey("last_used", dict)


def create_app(controller, key, port, static_dir, stop):
    allowed_origins = {SITE_ORIGIN, f"http://127.0.0.1:{port}"}

    @web.middleware
    async def guard(request, handler):
        origin = request.headers.get("Origin")
        try:
            local_peer = ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            local_peer = False
        if not local_peer or request.host != f"127.0.0.1:{port}" or (origin and origin not in allowed_origins):
            return web.json_response({"error": "只允许授权页面在本机访问。"}, status=403)
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                   "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                   "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}
        if origin:
            headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin"})
        if request.method == "OPTIONS":
            headers.update({"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                            "Access-Control-Allow-Headers": "Content-Type, X-LazyStick-Auth",
                            "Access-Control-Allow-Private-Network": "true", "Access-Control-Max-Age": "300"})
            return web.Response(status=204, headers=headers)
        if request.path.startswith("/api/") and not secrets.compare_digest(request.headers.get("X-LazyStick-Auth", ""), key):
            return web.json_response({"error": "连接已失效，请重新运行助手。"}, status=403, headers=headers)
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({"error": "请求格式不正确。"}, status=error.status)
        except Exception:
            response = web.json_response({"error": "操作未完成，请重试。"}, status=500)
        response.headers.update(headers)
        if request.path.startswith("/api/"):
            request.app[LAST_USED]["at"] = time.monotonic()
        return response

    app = web.Application(middlewares=[guard], client_max_size=16 * 1024)
    app[CONTROLLER], app[KEY], app[STOP], app[LAST_USED] = controller, key, stop, {"at": time.monotonic()}

    async def asset(request):
        name = request.match_info.get("name", "index.html")
        if name not in {"index.html", "app.js", "style.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(Path(static_dir) / name)

    async def state(request):
        return web.json_response(controller.snapshot())

    async def action(request):
        try:
            if request.content_type != "application/json":
                raise InputError("请求必须使用 JSON。")
            data = await request.json()
            if not isinstance(data, dict):
                raise InputError("请求格式不正确。")
            operation = request.match_info["action"]
            if operation == "stop":
                await controller.run("logout", {})
                asyncio.get_running_loop().call_later(0.5, stop.set)
                return web.json_response({"ok": True})
            result = await controller.run(operation, data)
            if operation == "export":
                return web.Response(text=json.dumps(result, ensure_ascii=False, indent=2),
                                    content_type="application/json",
                                    headers={"Content-Disposition": 'attachment; filename="lamp-esp32-session.json"'})
            return web.json_response(result)
        except json.JSONDecodeError:
            return web.json_response({"error": "请求格式不正确。"}, status=400)
        except Exception as error:
            return web.json_response({"error": public_error(error), "state": controller.snapshot()},
                                     status=400 if isinstance(error, InputError) else 502)

    async def expire(application):
        while not stop.is_set():
            await asyncio.sleep(15)
            # Do not clear a session while a cloud request is in progress.
            if not controller.lock.locked():
                controller.expire()
                if time.monotonic() - application[LAST_USED]["at"] > 60 * 60:
                    stop.set()

    async def lifetime(application):
        task = asyncio.create_task(expire(application))
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        controller.reset()

    app.router.add_get("/", asset)
    app.router.add_get("/{name:index.html|app.js|style.css}", asset)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/{action}", action)
    app.router.add_route("OPTIONS", "/api/{action}", state)
    app.cleanup_ctx.append(lifetime)
    return app
