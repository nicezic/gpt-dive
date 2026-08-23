from __future__ import annotations

import contextlib
import importlib.machinery
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "voyage-free-guard"
mod = importlib.machinery.SourceFileLoader("voyage_free_guard", str(SCRIPT)).load_module()


class FakeHeaders:
    def __init__(self, cookies: list[str] | None = None):
        self.cookies = cookies or []

    def get_all(self, name: str, default=None):
        return self.cookies if name.lower() == "set-cookie" else (default or [])


class FakeResponse:
    def __init__(self, status: int, body: object = b"", *, url: str, cookies: list[str] | None = None):
        self.status = status
        self._body = json.dumps(body).encode() if isinstance(body, (dict, list, str)) else body
        self._url = url
        self.headers = FakeHeaders(cookies)

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.snapshot = root / "snapshot.json"
        self.ledger = root / "usage.jsonl"
        self.state_dir_patch = patch.object(mod, "STATE_DIR", root)
        self.snapshot_patch = patch.object(mod, "SNAPSHOT_PATH", self.snapshot)
        self.ledger_patch = patch.object(mod, "LEDGER_PATH", self.ledger)
        self.state_dir_patch.start()
        self.snapshot_patch.start()
        self.ledger_patch.start()

    def tearDown(self):
        self.ledger_patch.stop()
        self.snapshot_patch.stop()
        self.state_dir_patch.stop()
        self.tmp.cleanup()

    def valid_opener(self, *, remaining: int = 150_000_000):
        def opener(req, timeout=None):
            if req.full_url == mod.DASHBOARD_USAGE_URL:
                self.assertEqual(req.get_header("Cookie"), "__session=old-session")
                return FakeResponse(
                    200,
                    url=mod.DASHBOARD_USAGE_URL,
                    cookies=["__session=rotated-session; Path=/; Max-Age=86400; Secure; HttpOnly; SameSite=Lax"],
                )
            if req.full_url == mod.ACCESS_TOKEN_URL:
                self.assertEqual(req.get_header("Cookie"), "__session=rotated-session")
                return FakeResponse(200, {"token": "access-secret"}, url=mod.ACCESS_TOKEN_URL)
            if req.full_url.startswith(mod.QUOTA_ORIGIN):
                self.assertEqual(req.get_header("Authorization"), "Bearer access-secret")
                return FakeResponse(
                    200,
                    {"code": 200, "successCode": "OK", "data": [{
                        "modelName": mod.MODEL,
                        "totalFreeToken": 200_000_000,
                        "remainingToken": remaining,
                    }]},
                    url=req.full_url,
                )
            raise AssertionError(req.full_url)
        return opener

    def test_fresh_quota_still_uses_dashboard_only_for_explicit_refresh(self):
        persisted: list[str] = []
        with patch.dict(os.environ, {mod.SESSION_ENV: "old-session"}, clear=False):
            result = mod.fresh_quota(self.valid_opener(), persisted.append)
        self.assertEqual(persisted, ["rotated-session"])
        self.assertEqual(result["remainingToken"], 150_000_000)
        self.assertNotIn("access-secret", repr(result))

    def test_local_status_warns_at_80_percent_but_passes(self):
        now = datetime(2026, 8, 15, tzinfo=UTC)
        snapshot = mod.make_snapshot(total=200_000_000, used=160_000_000, source="dashboard", verified=True, now=now)
        mod.write_snapshot(snapshot)
        status = mod.status_payload(snapshot, now=now + timedelta(days=1))
        self.assertTrue(status["warning"])
        self.assertFalse(status["reauthRequired"])
        self.assertEqual(status["guard"], "PASS")

    def test_ledger_adds_only_events_after_baseline(self):
        now = datetime(2026, 8, 15, tzinfo=UTC)
        snapshot = mod.make_snapshot(total=200_000_000, used=10_000_000, source="dashboard", verified=True, now=now)
        mod.write_snapshot(snapshot)
        self.ledger.write_text(
            json.dumps({"ts": "2026-08-14T00:00:00Z", "model": mod.MODEL, "estimatedTokens": 99}) + "\n" +
            json.dumps({"ts": "2026-08-16T00:00:00Z", "model": mod.MODEL, "estimatedTokens": 1234}) + "\n",
            encoding="utf-8",
        )
        status = mod.status_payload(snapshot, now=now + timedelta(days=2))
        self.assertEqual(status["localEstimatedToken"], 1234)
        self.assertEqual(status["usedToken"], 10_001_234)

    def test_snapshot_requires_reauth_at_30_days(self):
        now = datetime(2026, 8, 15, tzinfo=UTC)
        snapshot = mod.make_snapshot(total=200_000_000, used=1, source="dashboard", verified=True, now=now)
        status = mod.status_payload(snapshot, now=now + timedelta(days=30))
        self.assertTrue(status["reauthRequired"])
        self.assertEqual(status["guard"], "BLOCK")

    def test_refresh_main_resets_to_authoritative_server_usage(self):
        quota = {"modelName": mod.MODEL, "totalFreeToken": 200_000_000, "remainingToken": 123_000_000}
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", [str(SCRIPT), "--refresh", "--json"]),
            patch.object(mod, "fresh_quota", return_value=quota),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            mod.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["source"], "dashboard")
        self.assertEqual(payload["usedTokenAtBaseline"], 77_000_000)
        self.assertEqual(payload["localEstimatedToken"], 0)
        self.assertIsNotNone(payload["verifiedAt"])
        self.assertEqual(payload["guard"], "PASS")

    def test_bootstrap_main_sets_local_baseline_and_30_day_deadline(self):
        out = io.StringIO()
        with (
            patch.object(sys, "argv", [str(SCRIPT), "--bootstrap-used-tokens", "12345", "--json"]),
            contextlib.redirect_stdout(out),
        ):
            mod.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["source"], "local-bootstrap")
        self.assertEqual(payload["usedTokenAtBaseline"], 12345)
        self.assertIsNone(payload["verifiedAt"])
        self.assertFalse(payload["reauthRequired"])

    def test_expired_default_guard_exits_70(self):
        old = datetime.now(UTC) - timedelta(days=31)
        mod.write_snapshot(mod.make_snapshot(total=200_000_000, used=1, source="dashboard", verified=True, now=old))
        with (
            patch.object(sys, "argv", [str(SCRIPT), "--json"]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as caught,
        ):
            mod.main()
        self.assertEqual(caught.exception.code, 70)

    def test_invalid_session_redirect_fails_closed_without_secret_output(self):
        def opener(req, timeout=None):
            return FakeResponse(200, url="https://voyageai.us.auth0.com/login")

        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {mod.SESSION_ENV: "super-secret-session"}, clear=False),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as caught,
        ):
            mod.fresh_quota(opener, lambda _: None)
        self.assertEqual(caught.exception.code, 70)
        self.assertNotIn("super-secret-session", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
