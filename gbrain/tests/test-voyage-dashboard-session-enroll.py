from __future__ import annotations

import importlib.machinery
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "voyage-dashboard-session-enroll"
mod = importlib.machinery.SourceFileLoader("voyage_enroll", str(SCRIPT)).load_module()


class VoyageDashboardSessionEnrollTests(unittest.TestCase):
    def test_read_dashboard_session_parses_raw_json_string(self):
        cp = subprocess.CompletedProcess(
            ["playwright-cli"],
            0,
            stdout=json.dumps("session-secret") + "\n",
            stderr="",
        )
        with patch.object(mod, "run", return_value=cp):
            self.assertEqual(mod.read_dashboard_session("msedge"), "session-secret")

    def test_store_session_adds_new_credential_via_stdin(self):
        calls = []

        def fake_run(args, *, input_text=None, env=None):
            calls.append((args, input_text, env))
            if args[:2] == ["creds", "info"]:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing")
            return subprocess.CompletedProcess(args, 0, stdout="added\n", stderr="")

        with patch.object(mod, "run", side_effect=fake_run):
            mod.store_session("session-secret")
        self.assertEqual(
            calls[-1][0],
            [
                "creds",
                "add",
                mod.CREDS_ID,
                "--label",
                mod.CREDS_LABEL,
                "--binding",
                mod.CREDS_BINDING,
            ],
        )
        self.assertEqual(calls[-1][1], "session-secret\n")

    def test_store_session_updates_existing_credential_via_stdin(self):
        calls = []

        def fake_run(args, *, input_text=None, env=None):
            calls.append((args, input_text, env))
            return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

        with patch.object(mod, "run", side_effect=fake_run):
            mod.store_session("rotated-secret")
        self.assertEqual(calls[-1][0], ["creds", "set", mod.CREDS_ID])
        self.assertEqual(calls[-1][1], "rotated-secret\n")

    def test_session_is_open_matches_exact_session_name(self):
        cp = subprocess.CompletedProcess(
            ["playwright-cli"],
            0,
            stdout="### Browsers\nabc:\n- msedge:\n  - status: open\n",
            stderr="",
        )
        with (
            patch.object(mod, "resolve_playwright_cli", return_value="/abs/playwright-cli"),
            patch.object(mod, "run", return_value=cp),
        ):
            self.assertTrue(mod.session_is_open("msedge"))
            self.assertFalse(mod.session_is_open("msedge-other"))

    def test_attach_extension_uses_creds_and_edge_executable_env(self):
        cp = subprocess.CompletedProcess(["creds"], 0, stdout="", stderr="")
        with (
            patch.object(mod, "resolve_playwright_cli", return_value="/abs/playwright-cli"),
            patch.object(mod, "run", return_value=cp) as run_mock,
        ):
            mod.attach_extension("msedge")
        args, kwargs = run_mock.call_args
        self.assertEqual(
            args[0],
            [
                "creds",
                "run",
                "ai",
                "--",
                "/abs/playwright-cli",
                "attach",
                "--extension=chrome",
                "--session=msedge",
            ],
        )
        self.assertEqual(kwargs["env"]["PLAYWRIGHT_MCP_EXECUTABLE_PATH"], mod.EDGE_EXECUTABLE)

    def test_refresh_usage_snapshot_runs_guard_through_creds(self):
        payload = {"source": "dashboard", "guard": "PASS", "usedPercent": 12.3}
        cp = subprocess.CompletedProcess(["creds"], 0, stdout=json.dumps(payload) + "\n", stderr="")
        with (
            patch.dict(mod.os.environ, {"VOYAGE_GUARD_BIN": "/tmp/voyage-free-guard"}, clear=False),
            patch.object(mod, "run", return_value=cp) as run_mock,
        ):
            result = mod.refresh_usage_snapshot()
        self.assertEqual(result, payload)
        self.assertEqual(
            run_mock.call_args.args[0],
            ["creds", "run", "ai", "--", "/tmp/voyage-free-guard", "--refresh", "--json"],
        )

    def test_main_attaches_and_detaches_when_session_absent(self):
        with (
            patch.object(sys, "argv", [str(SCRIPT)]),
            patch.object(mod, "session_is_open", return_value=False),
            patch.object(mod, "attach_extension") as attach,
            patch.object(mod, "read_dashboard_session", return_value="session-secret") as read,
            patch.object(mod, "store_session") as store,
            patch.object(mod, "refresh_usage_snapshot", return_value={"source": "dashboard", "guard": "PASS"}) as refresh,
            patch.object(mod, "detach_session") as detach,
        ):
            mod.main()
        attach.assert_called_once_with("msedge")
        read.assert_called_once_with("msedge")
        store.assert_called_once_with("session-secret")
        refresh.assert_called_once_with()
        detach.assert_called_once_with("msedge")

    def test_main_reuses_existing_session_without_detach(self):
        with (
            patch.object(sys, "argv", [str(SCRIPT)]),
            patch.object(mod, "session_is_open", return_value=True),
            patch.object(mod, "attach_extension") as attach,
            patch.object(mod, "read_dashboard_session", return_value="session-secret"),
            patch.object(mod, "store_session"),
            patch.object(mod, "refresh_usage_snapshot", return_value={"source": "dashboard", "guard": "PASS"}) as refresh,
            patch.object(mod, "detach_session") as detach,
        ):
            mod.main()
        attach.assert_not_called()
        refresh.assert_called_once_with()
        detach.assert_not_called()


if __name__ == "__main__":
    unittest.main()
