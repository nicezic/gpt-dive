from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIResponsesModel

from gpt_dive.openai_codex import (
    OpenAICodexCredentials,
    OpenAICodexProvider,
    OpenAICodexResponsesModel,
)

pytestmark = pytest.mark.anyio


def _credentials(revision: str, token: str) -> OpenAICodexCredentials:
    return OpenAICodexCredentials(
        access_token=SecretStr(token),
        refresh_token=SecretStr(f"refresh-{revision}"),
        id_token=SecretStr(f"id-{revision}"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        account_id=SecretStr("acct-1"),
        revision=revision,
    )


class _CredentialSource:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str | None]] = []

    async def get_credentials(
        self, *, force_refresh: bool = False, rejected_revision: str | None = None
    ) -> OpenAICodexCredentials:
        self.calls.append((force_refresh, rejected_revision))
        if force_refresh:
            return _credentials("rev-2", "token-2")
        return _credentials("rev-1", "token-1")


async def test_provider_scopes_auth_and_replays_one_401() -> None:
    source = _CredentialSource()
    seen: list[dict[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "host": request.url.host,
                "authorization": request.headers.get("Authorization"),
                "account": request.headers.get("ChatGPT-Account-ID"),
                "originator": request.headers.get("originator"),
            }
        )
        if (
            request.url.host == "chatgpt.com"
            and len([item for item in seen if item["host"] == "chatgpt.com"]) == 1
        ):
            return httpx.Response(401, request=request)
        return httpx.Response(200, request=request, json={"ok": True})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    OpenAICodexProvider(credential_source=source, http_client=client)

    response = await client.post(
        "https://chatgpt.com/backend-api/codex/responses", content=b"{}"
    )
    assert response.status_code == 200
    assert seen[0]["authorization"] == "Bearer token-1"
    assert seen[1]["authorization"] == "Bearer token-2"
    assert seen[1]["account"] == "acct-1"
    assert seen[1]["originator"] == "gpt-dive"
    assert source.calls == [(False, None), (True, "rev-1")]

    await client.get("https://example.com/not-codex")
    assert seen[-1]["host"] == "example.com"
    assert seen[-1]["authorization"] is None
    assert seen[-1]["account"] is None
    await client.aclose()


class _FakeStreamedResponse:
    def __init__(self) -> None:
        self._response = ModelResponse(
            parts=[TextPart("ok")],
            model_name="gpt-5.6-sol",
            provider_name="openai-codex",
        )

    def __aiter__(self):
        async def iterator():
            if False:
                yield None

        return iterator()

    def get(self) -> ModelResponse:
        return self._response


async def test_model_request_aggregates_stream_and_forces_store_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_request_stream(
        self, messages, model_settings, model_request_parameters, run_context=None
    ):
        captured["settings"] = model_settings
        yield _FakeStreamedResponse()

    monkeypatch.setattr(OpenAIResponsesModel, "request_stream", fake_request_stream)
    source = _CredentialSource()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, request=request)
        )
    )
    model = OpenAICodexResponsesModel(
        "gpt-5.6-sol",
        provider=OpenAICodexProvider(credential_source=source, http_client=client),
    )

    response = await model.request([], {"temperature": 0.7}, ModelRequestParameters())
    assert response.parts == [TextPart("ok")]
    assert captured["settings"] == {"temperature": 0.7, "openai_store": False}

    with pytest.raises(UserError, match="Counting tokens ahead"):
        await model.count_tokens([], None, ModelRequestParameters())
    await client.aclose()
