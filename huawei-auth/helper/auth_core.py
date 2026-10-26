"""Login and export only; no lamp commands, MQTT, or saved credentials.

SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import uuid

from vendor.huawei_smarthome.api.client import SmartHomeDiscoveryApi
from vendor.huawei_smarthome.api.errors import AuthExpiredError
from vendor.huawei_smarthome.auth.huawei import HuaweiSmartHomeAuthProvider
from vendor.huawei_smarthome.auth.session import SessionManager
from vendor.huawei_smarthome.errors import AuthenticationError, ReauthenticationRequired
from vendor.huawei_smarthome.storage.credentials import auth_session_to_storage
from vendor.huawei_smarthome.storage.identity import identity_fingerprint


class InputError(ValueError):
    """Only this exception's deliberately written message may reach the UI."""


def public_error(error):
    if isinstance(error, InputError):
        return str(error)
    if isinstance(error, (AuthenticationError, ReauthenticationRequired, AuthExpiredError)):
        return "登录或验证未通过，请检查账号、密码和验证码后重试。"
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "华为服务响应超时，请稍后重试。"
    return "操作未完成，请检查网络后重试；必要时重新登录。"


class IdentityStore:
    """Keep stable client IDs, indexed by account hash; no password or token."""
    def __init__(self, path):
        self.path = Path(path)

    async def get(self, account):
        def read_write():
            key = hashlib.sha256(account.strip().casefold().encode()).hexdigest()
            records = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            identity = records.get(key)
            if identity:
                if (not isinstance(identity, dict) or not identity.get("device_id") or
                        not isinstance(identity.get("pushtmid"), str) or len(identity["pushtmid"]) != 64 or
                        identity.get("identity_fingerprint") != identity_fingerprint(identity)):
                    raise InputError("本机客户端记录损坏，请检查助手的数据目录。")
                return identity
            identity = {"device_id": str(uuid.uuid4()).upper(), "device_name": "huawei-smarthome",
                        "pushtmid": secrets.token_hex(32)}
            identity["identity_fingerprint"] = identity_fingerprint(identity)
            records[key] = identity
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix("." + secrets.token_hex(8) + ".tmp")
            try:
                with temporary.open("x", encoding="utf-8") as stream:
                    json.dump(records, stream)
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return identity
        return await asyncio.to_thread(read_write)


class MemoryCredentials:
    async def async_save(self, session):
        # SessionManager retains the refreshed session. Never persist tokens here.
        pass


class AuthController:
    SESSION_IDLE_SECONDS = 15 * 60

    def __init__(self, identities, *, api=None, provider_factory=None):
        self.identities = identities
        self.api = api or SmartHomeDiscoveryApi(timeout=20)
        self.provider_factory = provider_factory or HuaweiSmartHomeAuthProvider
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic()
        self.reset()

    def reset(self):
        self.provider = self.challenge = self.manager = None
        self.channel_selected = False
        self.devices = []
        self.homes = {}

    def expire(self):
        if time.monotonic() - self.last_used > self.SESSION_IDLE_SECONDS:
            self.reset()

    def snapshot(self):
        self.expire()
        return {"version": 1, "authenticated": self.manager is not None,
                "challenge": self.challenge is not None, "channel_selected": self.channel_selected,
                "channels": [{"key": c.key, "name": c.name, "kind": c.kind, "sent": c.sent}
                             for c in self.challenge.channels] if self.challenge else [],
                "devices": [{"dev_id": d.dev_id, "home_id": d.home_id,
                             "name": d.name or "欧普智能台灯 2S", "home": self.homes.get(d.home_id, "")}
                            for d in self.devices if str(d.prod_id).upper() == "2BNN"]}

    def provider_for(self, session):
        return self.provider_factory(device_id=session.device_id, device_name=session.device_name,
                                     pushtmid=session.pushtmid, identity_fingerprint=session.identity_fingerprint)

    async def adopt(self, session):
        self.manager = SessionManager(session, MemoryCredentials(), self.provider_for)
        self.provider = self.challenge = None
        self.channel_selected = False
        await self.discover()

    async def http(self, method, *args):
        if not self.manager:
            raise InputError("请先登录华为账号。")
        session = await self.manager.async_ensure_hms_valid()
        try:
            return await method(session, *args)
        except AuthExpiredError:
            session = await self.manager.async_refresh_hms_lite(force=True)
            return await method(session, *args)

    async def discover(self):
        snapshot = await self.http(self.api.async_get_snapshot)
        missing = [d.dev_id for d in snapshot.devices if not d.prod_id]
        details = await self.http(self.api.async_get_device_details, missing) if missing else ()
        by_id = {d.dev_id: d for d in details}
        self.devices = [replace(by_id[d.dev_id], home_id=d.home_id)
                        if d.dev_id in by_id else d for d in snapshot.devices]
        self.homes = {h.home_id: h.name for h in snapshot.homes}

    async def run(self, action, data):
        if self.lock.locked():
            raise InputError("上一项操作尚未完成，请稍候。")
        async with self.lock:
            self.expire()
            self.last_used = time.monotonic()
            try:
                if action == "login":
                    account, password = data.get("account"), data.get("password")
                    if (not isinstance(account, str) or not account.strip() or len(account) > 256 or
                            not isinstance(password, str) or not password or len(password) > 1024):
                        raise InputError("请输入华为账号和密码。")
                    self.reset()
                    identity = await self.identities.get(account)
                    self.provider = self.provider_factory(**identity)
                    result = await self.provider.async_begin_login(account.strip(), password)
                    if result.session:
                        await self.adopt(result.session)
                    elif result.challenge:
                        self.challenge = result.challenge
                    else:
                        raise InputError("未收到登录结果，请重新登录。")
                elif action == "channel":
                    if not self.challenge or not self.provider:
                        raise InputError("验证已过期，请重新登录。")
                    channel = next((c for c in self.challenge.channels if c.key == data.get("key")), None)
                    if channel is None:
                        raise InputError("请选择验证方式。")
                    self.challenge = await self.provider.async_select_challenge_channel(channel)
                    self.channel_selected = True
                elif action == "verify":
                    code = data.get("code")
                    if not self.channel_selected or not self.provider:
                        raise InputError("请先获取验证码。")
                    if not isinstance(code, str) or not code.strip() or len(code) > 32:
                        raise InputError("请输入有效验证码。")
                    await self.adopt(await self.provider.async_complete_challenge(code.strip()))
                elif action == "discover":
                    await self.discover()
                elif action == "logout":
                    self.reset()
                elif action == "export":
                    if not self.manager:
                        raise InputError("请先登录华为账号。")
                    # Refresh membership before export; a caller cannot supply arbitrary device IDs.
                    await self.discover()
                    target = next((d for d in self.devices if d.dev_id == data.get("dev_id") and
                                   d.home_id == data.get("home_id") and str(d.prod_id).upper() == "2BNN"), None)
                    if target is None:
                        raise InputError("请选择当前账号下的欧普智能台灯 2S。")
                    await self.manager.async_ensure_oauth_valid()
                    await self.manager.async_ensure_hms_valid()
                    session = auth_session_to_storage(self.manager.session)
                    # Export only fields the firmware consumes; omit account name and optional metadata.
                    fields = ("user_id", "service_token", "hms_access_token", "hms_refresh_token", "hms_expires_at",
                              "oauth_access_token", "oauth_expires_at", "device_id", "device_name", "pushtmid",
                              "identity_fingerprint", "app_id", "base_url")
                    result = {"schema_version": 1,
                              "target": {"devId": target.dev_id, "homeId": target.home_id, "prodId": "2BNN"},
                              "session": {k: session[k] for k in fields}}
                    if len(json.dumps(result, ensure_ascii=False, indent=2).encode()) > 8192:
                        raise InputError("授权文件超过设备支持的 8 KB，请重新登录后重试。")
                    return result
                else:
                    raise InputError("不支持此操作。")
                return self.snapshot()
            finally:
                self.last_used = time.monotonic()
