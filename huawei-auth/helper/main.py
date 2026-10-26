"""Launch the Huawei JSON export assistant. SPDX-License-Identifier: GPL-3.0-only"""
import argparse
import asyncio
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import webbrowser

from aiohttp import web
from auth_core import AuthController, IdentityStore
from server import create_app, SITE_ORIGIN


async def main(args):
    data_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share") / "LazyStickHuaweiAuth"
    controller = AuthController(IdentityStore(data_dir / "identities.json"))
    stop = asyncio.Event()
    key = secrets.token_hex(32)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", args.port))
    listener.setblocking(False)
    port = listener.getsockname()[1]
    static_dir = Path(sys._MEIPASS) / "ui" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    app = create_app(controller, key, port, static_dir, stop)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=25)
    await runner.setup()
    site = web.SockSite(runner, listener)
    await site.start()
    base = f"http://127.0.0.1:{port}/" if args.local else SITE_ORIGIN + "/huawei-auth/"
    if not args.no_browser:
        webbrowser.open(f"{base}#port={port}&key={key}")
    print("LazyStick Huawei Auth is running on this computer.", flush=True)
    print("Use the opened browser page. Close this window or press Ctrl+C to quit.", flush=True)
    print(f"Page: {base}#port={port}&key={key}", flush=True)
    print(f"Local fallback: http://127.0.0.1:{port}/#port={port}&key={key}", flush=True)
    print("No passwords or session tokens are saved. Idle shutdown: 60 minutes.", flush=True)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LazyStick Huawei authorization helper")
    parser.add_argument("--local", action="store_true", help="Use bundled local page if the public site is unavailable")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    parser.add_argument("--port", type=int, default=0, help="Loopback port (default: automatically selected)")
    options = parser.parse_args()
    logging.disable(logging.CRITICAL)  # Do not write authentication response details to logs.
    try:
        asyncio.run(main(options))
    except KeyboardInterrupt:
        pass
    except Exception:
        print("Unable to start the helper. Close other copies and try again.", file=sys.stderr)
        sys.exit(1)
