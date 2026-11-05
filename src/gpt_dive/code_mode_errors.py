from __future__ import annotations

from typing import Literal

# One vocabulary from the Monty worker through the public MCP result.
RecoveryAction = Literal["correct_input", "inspect_first", "no_retry", "ask_user"]

WORKER_ERROR_MESSAGES = {
    "execution_error": "Code Mode Execution failed.",
    "non_json_result": "Code Mode result is not strict JSON.",
}

_NEXT_STEPS = {
    "invalid_request": "Correct the request fields; no new Execution was accepted.",
    "MontyTypingError": "Correct the reported Monty diagnostics; the supplied code did not execute. A `CoroutineType` diagnostic means a capability call is missing `await`; run_command returns a dict, so read result[\"stdout\"], not result.stdout.",
    "execution_error": "Inspect error.detail and the submitted code/capability result; check prior side effects before a corrected call.",
    "non_json_result": "Return a JSON-safe final expression (string, number, list, or dict); the program may already have had side effects.",
    "worker_protocol_error": "Inspect retained worker stderr/outcome for this execution_id; do not infer that user code did not run.",
    "launch_unobserved": "Verify live input and Execution evidence; acceptance was not confirmed. Do not blindly repeat side-effectful work.",
    "launch_interrupted": "Inspect the Execution record and launch diagnostics before deciding whether a new request is safe.",
    "response_deadline_exceeded": "The response deadline is not a work deadline. Check task(list) and existing Execution evidence before any retry.",
    "task_publication_failed": "Inspect the original Execution and Task publication state; do not start a duplicate Execution.",
    "result_retrieval_failed": "Inspect the retained result and store diagnostics for this execution_id before retrying the original work.",
    "response_protocol_error": "Inspect error.detail and the live output schema; avoid rerunning the original side-effectful code.",
    "deadline_exceeded": "Inspect the recorded work deadline and retained partial output; verify side effects before a new execution.",
    "cancelled": "Confirm explicit cancellation and retained artifacts; do not assume child side effects were rolled back.",
    "lost": "The outcome is not observable. Inspect retained evidence; do not infer success or rerun side-effectful work.",
}


# Category describes the failure domain; code keeps the specific, stable cause.
_CATEGORY_BY_CODE = {
    "invalid_request": "request",
    "execution_error": "execution",
    "non_json_result": "execution",
    "worker_protocol_error": "runtime",
    "launch_unobserved": "runtime",
    "launch_interrupted": "runtime",
    "deadline_exceeded": "runtime",
    "cancelled": "runtime",
    "lost": "runtime",
    "response_deadline_exceeded": "delivery",
    "response_protocol_error": "delivery",
    "task_publication_failed": "delivery",
    "result_retrieval_failed": "delivery",
    "TASK.NOT_AVAILABLE": "task",
    "TASK.NOT_TERMINAL": "task",
    "POLICY.USER_AUTH_REQUIRED": "policy",
    "MCP.SERVER.UNHANDLED": "mcp_server",
}


def category_for(code: str) -> str:
    return _CATEGORY_BY_CODE.get(code, "unknown")


def recovery_for(code: str) -> RecoveryAction:
    if code == "POLICY.USER_AUTH_REQUIRED":
        return "ask_user"
    if code == "invalid_request":
        return "correct_input"
    if code in {"cancelled", "TASK.NOT_TERMINAL"}:
        return "no_retry"
    return "inspect_first"


def guidance_for(code: str) -> str:
    next_step = _NEXT_STEPS.get(
        code,
        "Inspect error.detail, the live contract, and retained Execution evidence before a corrected call.",
    )
    return (
        f"Next: {next_step} "
        "Preserve error.category/code/message/detail and any execution_id in the user report. "
        "Never treat a top-level transport error as proof of execution failure."
    )
