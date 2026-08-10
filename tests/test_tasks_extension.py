from __future__ import annotations

from job_manager import JobManager
from tasks_extension import EXTENSION_ID, TasksExtension


def test_extension_identifier_and_methods(tmp_path):
    extension = TasksExtension(JobManager(tmp_path))
    assert extension.identifier == EXTENSION_ID
    assert {binding.method for binding in extension.methods()} == {"tasks/get", "tasks/update", "tasks/cancel"}


def test_task_shape_maps_running_job(tmp_path):
    extension = TasksExtension(JobManager(tmp_path))
    job = extension.jobs.start("sleep 1", timeout=3)
    try:
        task = extension._create_task(job)
        assert task["resultType"] == "task"
        assert task["status"] == "working"
        assert task["taskId"] == job["job_id"]
        assert task["ttlMs"] is None
        assert task["pollIntervalMs"] == 1000
    finally:
        extension.jobs.cancel(job["job_id"])


def test_tasks_intercepts_only_wsl2_async_start(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from mcp_types import CallToolRequestParams, ClientCapabilities

    extension = TasksExtension(JobManager(tmp_path))
    ctx = SimpleNamespace(
        protocol_version="2026-07-28",
        session=SimpleNamespace(
            client_capabilities=ClientCapabilities(extensions={EXTENSION_ID: {}})
        ),
    )
    fallback_calls = []

    async def call_next(_ctx):
        fallback_calls.append(True)
        return {"fallback": True}

    start = CallToolRequestParams(
        name="wsl2_async",
        arguments={"action": "start", "command": "printf TASK_OK", "timeout": 3},
    )
    task = asyncio.run(extension.intercept_tool_call(start, ctx, call_next))
    assert task["resultType"] == "task"
    extension.jobs.cancel(task["taskId"])

    status = CallToolRequestParams(
        name="wsl2_async",
        arguments={"action": "status", "job_id": task["taskId"]},
    )
    assert asyncio.run(extension.intercept_tool_call(status, ctx, call_next)) == {"fallback": True}
    assert fallback_calls == [True]
