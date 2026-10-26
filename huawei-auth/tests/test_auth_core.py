"""Offline login/export checks; no real account, SMS, or lamp writes."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper"))
from auth_core import AuthController, IdentityStore, InputError, public_error
from vendor.huawei_smarthome.auth.interface import ChallengeChannel, LoginChallenge, LoginStart
from vendor.huawei_smarthome.domain.models import AuthSession, RemoteDeviceDescriptor, RemoteDiscoverySnapshot, RemoteHome


class FakeProvider:
    def __init__(self, **identity):
        self.identity = identity
        self.channel = ChallengeChannel("138****0000", "2", "sms", False)
        self.challenge = LoginChallenge("verify", "test", "2", (self.channel,))

    def session(self):
        return AuthSession(account="mock@example.test", user_id="test-user", service_token="fake-service-token",
                           oauth_access_token="fake-oauth", hms_access_token="fake-hms",
                           oauth_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                           hms_expires_at=datetime.now(timezone.utc) + timedelta(hours=1), **self.identity)

    async def async_begin_login(self, account, password):
        if password == "bad":
            raise ValueError("PRIVATE CLOUD BODY SHOULD NOT BE RETURNED")
        if password == "direct":
            return LoginStart(session=self.session())
        return LoginStart(challenge=self.challenge)

    async def async_select_challenge_channel(self, channel):
        assert channel.key == self.channel.key
        return self.challenge

    async def async_complete_challenge(self, code):
        if code != "123456":
            raise InputError("验证码错误，请重试。")
        return self.session()

    async def async_refresh_oauth(self, session):
        return replace(session, oauth_access_token="refreshed-oauth",
                       oauth_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    async def async_refresh_hms_lite(self, session):
        return replace(session, hms_access_token="refreshed-hms",
                       hms_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))


class FakeApi:
    def __init__(self):
        self.devices = (RemoteDeviceDescriptor("home", "lamp-test-123", "书桌台灯", prod_id=None),
                        RemoteDeviceDescriptor("home", "unsupported", "其他设备", prod_id="OTHER"))

    async def async_get_snapshot(self, session):
        return RemoteDiscoverySnapshot((RemoteHome("home", "测试家庭"),), self.devices, datetime.now(timezone.utc))

    async def async_get_device_details(self, session, missing):
        return (replace(self.devices[0], prod_id="2BNN"),)


class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "identities.json"
        self.api = FakeApi()
        self.core = AuthController(IdentityStore(self.path), api=self.api, provider_factory=FakeProvider)

    def tearDown(self):
        self.temp.cleanup()

    async def test_sms_export_and_no_credentials_on_disk(self):
        state = await self.core.run("login", {"account": "mock@example.test", "password": "challenge"})
        self.assertTrue(state["challenge"])
        self.assertNotIn("service_token", json.dumps(state))
        with self.assertRaises(InputError):
            await self.core.run("verify", {"code": "123456"})
        await self.core.run("channel", {"key": state["channels"][0]["key"]})
        with self.assertRaises(InputError):
            await self.core.run("verify", {"code": "bad-code"})
        state = await self.core.run("verify", {"code": "123456"})
        self.assertEqual(len(state["devices"]), 1)
        exported = await self.core.run("export", {"dev_id": "lamp-test-123", "home_id": "home"})
        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(exported["target"]["prodId"], "2BNN")
        self.assertNotIn("account", exported["session"])
        self.assertLessEqual(len(json.dumps(exported).encode()), 8192)
        disk = self.path.read_text()
        for secret in ["mock@example.test", "fake-service-token", "fake-oauth", "fake-hms", "123456"]:
            self.assertNotIn(secret, disk)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)
        # Keep only a mock export for firmware-schema compatibility checks.
        target = Path(__file__).resolve().parents[2] / ".auth-build/mock-export.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(exported), encoding="utf-8")

    async def test_reject_arbitrary_or_removed_device(self):
        await self.core.run("login", {"account": "a", "password": "direct"})
        for dev, home in [("unsupported", "home"), ("lamp-test-123", "wrong-home")]:
            with self.assertRaises(InputError):
                await self.core.run("export", {"dev_id": dev, "home_id": home})
        self.api.devices = ()
        with self.assertRaises(InputError):
            await self.core.run("export", {"dev_id": "lamp-test-123", "home_id": "home"})

    async def test_idle_expiry_logout_and_identity_reuse(self):
        await self.core.run("login", {"account": "a", "password": "direct"})
        identity = self.core.manager.session.device_id
        self.core.last_used -= 901
        self.assertFalse(self.core.snapshot()["authenticated"])
        with self.assertRaises(InputError):
            await self.core.run("export", {"dev_id": "lamp-test-123", "home_id": "home"})
        await self.core.run("login", {"account": "a", "password": "direct"})
        self.assertEqual(identity, self.core.manager.session.device_id)
        await self.core.run("logout", {})
        self.assertFalse(self.core.snapshot()["authenticated"])

    async def test_refresh_before_export_and_busy_rejection(self):
        await self.core.run("login", {"account": "a", "password": "direct"})
        self.core.manager._session = replace(self.core.manager.session, oauth_expires_at=datetime.now(timezone.utc))
        exported = await self.core.run("export", {"dev_id": "lamp-test-123", "home_id": "home"})
        self.assertEqual(exported["session"]["oauth_access_token"], "refreshed-oauth")
        async with self.core.lock:
            with self.assertRaises(InputError):
                await self.core.run("logout", {})

    def test_error_redaction(self):
        self.assertNotIn("PRIVATE", public_error(ValueError("PRIVATE")))


if __name__ == "__main__":
    unittest.main()
