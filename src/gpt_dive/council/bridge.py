from __future__ import annotations

import asyncio
import json
import os
import re
from types import TracebackType
from typing import Any, Self

_EDGE_EXECUTABLE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
_COMPOSER_SELECTOR = "#prompt-textarea"
_STOP_SELECTOR = '[data-testid="stop-button"]'

_COMPOSER_STATE_EXPRESSION = r"""
(() => {
  const visible = (element) => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const composer = document.querySelector("#prompt-textarea");
  const stop = document.querySelector('[data-testid="stop-button"]');
  const composerVisible = visible(composer);
  const stopVisible = visible(stop);
  const editable = !!composer && composer.getAttribute("contenteditable") === "true" && composer.getAttribute("aria-disabled") !== "true";
  const text = composer ? (composer.innerText || composer.textContent || "") : "";
  const empty = text.trim().length === 0;

  if (!composerVisible) return {state: "MISSING", reason: "composer-missing", empty};
  if (stopVisible) return {state: "BUSY", reason: "generating", empty};
  if (!editable) return {state: "BUSY", reason: "composer-disabled", empty};
  if (!empty) return {state: "BUSY", reason: "draft-present", empty};
  return {state: "READY", reason: "ready", empty: true};
})()
""".strip()


def _redact_cli_output(text: str) -> str:
    text = re.sub(r"(?i)(token=)[^&\s]+", r"\1[REDACTED]", text)
    return re.sub(r"(?i)(PLAYWRIGHT_MCP_EXTENSION_TOKEN=)[^\s]+", r"\1[REDACTED]", text)


def _session_is_open(output: str, session: str) -> bool:
    marker = f"- {session}:"
    if marker not in output:
        return False
    block = output.split(marker, 1)[1].split("\n- ", 1)[0]
    return "- status: open" in block


def _extension_prelude(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(
        {**payload, "stateExpr": _COMPOSER_STATE_EXPRESSION}, ensure_ascii=True
    )
    return f"""async (page) => {{
  const ext = page.context().pages().find(p => p.url().startsWith("chrome-extension://"));
  if (!ext) throw new Error("Playwright Extension page is not available");
  const input = {payload_json};
  return await ext.evaluate(async (args) => {{
    const matches = (await chrome.tabs.query({{}})).filter(t => t.url === args.url);
    if (matches.length !== 1) throw new Error(`expected exactly one target ChatGPT tab, found ${{matches.length}}`);
    const tabId = matches[0].id;
    if (!Number.isInteger(tabId)) throw new Error("target ChatGPT tab has no tab id");
    const target = {{tabId}};
    let attachedHere = false;
    try {{
      try {{
        await chrome.debugger.attach(target, "1.3");
        attachedHere = true;
      }} catch (error) {{
        if (!String(error).toLowerCase().includes("already attached")) throw error;
      }}

      const inspectState = async () => {{
        const result = await chrome.debugger.sendCommand(target, "Runtime.evaluate", {{
          expression: args.stateExpr,
          returnByValue: true,
        }});
        if (result && result.exceptionDetails) throw new Error("composer state evaluation failed");
        return result && result.result ? result.result.value : null;
      }};
"""


def _probe_script(url: str) -> str:
    return (
        _extension_prelude({"url": url})
        + """
      const observed = await inspectState();
      return {ok: true, tabId, ...observed};
    } finally {
      if (attachedHere) await chrome.debugger.detach(target).catch(() => {});
    }
  }, input);
}"""
    )


def _send_script(url: str, message: str, *, ready_timeout: float, ack_timeout: float) -> str:
    return (
        _extension_prelude(
            {
                "url": url,
                "message": message,
                "readyTimeoutMs": max(1, int(ready_timeout * 1000)),
                "ackTimeoutMs": max(1, int(ack_timeout * 1000)),
            }
        )
        + """
      const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
      const readyDeadline = Date.now() + args.readyTimeoutMs;
      let before = await inspectState();
      while (!before || before.state !== "READY") {
        if (Date.now() >= readyDeadline) {
          const state = before && before.state ? before.state : "UNKNOWN";
          const reason = before && before.reason ? before.reason : "unknown";
          throw new Error(`SOL composer not READY before timeout: ${state}/${reason}`);
        }
        await sleep(100);
        before = await inspectState();
      }

      const documentResult = await chrome.debugger.sendCommand(target, "DOM.getDocument", {depth: 1});
      const rootId = documentResult && documentResult.root ? documentResult.root.nodeId : 0;
      if (!rootId) throw new Error("could not read target DOM root");
      const queryResult = await chrome.debugger.sendCommand(target, "DOM.querySelector", {
        nodeId: rootId,
        selector: "#prompt-textarea",
      });
      if (!queryResult || !queryResult.nodeId) throw new Error("SOL composer disappeared before input");

      await chrome.debugger.sendCommand(target, "DOM.focus", {nodeId: queryResult.nodeId});
      await chrome.debugger.sendCommand(target, "Input.insertText", {text: args.message});

      const textResult = await chrome.debugger.sendCommand(target, "Runtime.evaluate", {
        expression: "(() => { const e=document.querySelector('#prompt-textarea'); return e ? (e.innerText || e.textContent || '') : null; })()",
        returnByValue: true,
      });
      const insertedText = textResult && textResult.result ? textResult.result.value : null;
      if (insertedText !== args.message) throw new Error("SOL composer text did not match the requested message");

      await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13,
      });
      await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13,
      });

      const ackDeadline = Date.now() + args.ackTimeoutMs;
      let after = await inspectState();
      while (!after || !after.empty) {
        if (Date.now() >= ackDeadline) {
          const state = after && after.state ? after.state : "UNKNOWN";
          const reason = after && after.reason ? after.reason : "unknown";
          throw new Error(`SOL composer did not accept the message: ${state}/${reason}`);
        }
        await sleep(50);
        after = await inspectState();
      }
      return {ok: true, accepted: true, preState: before.state, postState: after.state, postReason: after.reason, tabId};
    } finally {
      if (attachedHere) await chrome.debugger.detach(target).catch(() => {});
    }
  }, input);
}"""
    )


class SolBridge:
    """Input-only adapter to the user's existing logged-in Edge ChatGPT tab."""

    def __init__(
        self,
        *,
        session: str = "msedge",
        ready_timeout: float = 600.0,
        ack_timeout: float = 5.0,
    ) -> None:
        self._session = session
        self._ready_timeout = ready_timeout
        self._ack_timeout = ack_timeout
        self._started = False
        self._owns_session = False

    @property
    def started(self) -> bool:
        return self._started

    async def _run_cli(
        self,
        *args: str,
        with_creds: bool = False,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> str:
        command = ["playwright-cli", *args]
        if with_creds:
            command = ["creds", "run", "ai", "--", *command]
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Playwright CLI timed out after {timeout} seconds") from exc
        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")
        if proc.returncode != 0:
            detail = _redact_cli_output((stderr or stdout).strip())
            raise RuntimeError(f"Playwright CLI failed: {detail or f'exit {proc.returncode}'}")
        return stdout

    async def start(self) -> None:
        if self.started:
            return
        inventory = await self._run_cli("list", "--all", timeout=20.0)
        if _session_is_open(inventory, self._session):
            self._started = True
            self._owns_session = False
            return

        await self._run_cli(
            "attach",
            "--extension=chrome",
            f"--session={self._session}",
            with_creds=True,
            env={"PLAYWRIGHT_MCP_EXECUTABLE_PATH": _EDGE_EXECUTABLE},
            timeout=30.0,
        )
        inventory = await self._run_cli("list", "--all", timeout=20.0)
        if not _session_is_open(inventory, self._session):
            raise RuntimeError(f"Playwright session {self._session!r} did not become open after attach")
        self._started = True
        self._owns_session = True

    async def close(self) -> None:
        owns_session = self._owns_session
        self._started = False
        self._owns_session = False
        if not owns_session:
            return
        try:
            await self._run_cli(f"-s={self._session}", "detach", timeout=20.0)
        except RuntimeError:
            # The external Edge session may already have disappeared during shutdown.
            return

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _run_code(self, code: str, *, timeout: float) -> Any:
        if not self.started:
            raise RuntimeError("SOL bridge is not started")
        raw = await self._run_cli(
            f"-s={self._session}",
            "--raw",
            "run-code",
            code,
            timeout=timeout,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            detail = _redact_cli_output(raw.strip())
            raise RuntimeError(f"invalid Playwright CLI result: {detail[:500]}") from exc

    async def probe(self, *, url: str) -> dict[str, Any]:
        result = await self._run_code(_probe_script(url), timeout=15.0)
        if not isinstance(result, dict) or result.get("state") not in {"READY", "BUSY", "MISSING"}:
            raise RuntimeError("invalid SOL composer state result")
        return result

    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        if not message:
            raise ValueError("message must not be empty")
        result = await self._run_code(
            _send_script(
                url,
                message,
                ready_timeout=self._ready_timeout,
                ack_timeout=self._ack_timeout,
            ),
            timeout=self._ready_timeout + self._ack_timeout + 15.0,
        )
        if not isinstance(result, dict) or not result.get("accepted"):
            raise RuntimeError("SOL browser input was not accepted")
        return result
