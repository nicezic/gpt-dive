from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
from openai import AsyncOpenAI
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import create_async_http_client
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile, openai_model_profile
from pydantic_ai.providers import Provider

from .auth import OpenAICodexAuth, OpenAICodexCredentials, OpenAICodexCredentialSource

_BASE_URL = httpx.URL("https://chatgpt.com/backend-api/codex")
_RESPONSES_PATH = f"{_BASE_URL.path}/responses"


class _OpenAICodexHTTPAuth(httpx.Auth):
    """Attach subscription credentials only to the trusted ChatGPT Codex endpoint."""

    def __init__(self, credential_source: OpenAICodexCredentialSource) -> None:
        self._credential_source = credential_source

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._is_trusted_openai_codex_url(request.url):
            yield request
            return

        replayable = self._is_replayable_request(request)
        if replayable:
            try:
                _ = request.content
            except httpx.RequestNotRead:
                replayable = False

        credentials = await self._credential_source.get_credentials()
        self._apply(request, credentials)
        response = yield request

        if response.status_code == 401 and replayable:
            await response.aread()
            credentials = await self._credential_source.get_credentials(
                force_refresh=True, rejected_revision=credentials.revision
            )
            self._apply(request, credentials)
            yield request

    @staticmethod
    def _apply(request: httpx.Request, credentials: OpenAICodexCredentials) -> None:
        request.headers["Authorization"] = (
            f"Bearer {credentials.access_token.get_secret_value()}"
        )
        request.headers["ChatGPT-Account-ID"] = (
            credentials.account_id.get_secret_value()
        )
        request.headers["originator"] = "gpt-dive"
        if credentials.account_is_fedramp:
            request.headers["X-OpenAI-Fedramp"] = "true"
        else:
            request.headers.pop("X-OpenAI-Fedramp", None)

    @staticmethod
    def _is_trusted_openai_codex_url(url: httpx.URL) -> bool:
        raw_path = url.raw_path.partition(b"?")[0]
        path_segments = url.path.split("/")
        return (
            url.scheme == _BASE_URL.scheme
            and url.host == _BASE_URL.host
            and url.port is None
            and raw_path.startswith(_BASE_URL.raw_path.rstrip(b"/") + b"/")
            and b"%" not in raw_path
            and b"\\" not in raw_path
            and "." not in path_segments
            and ".." not in path_segments
        )

    @staticmethod
    def _is_replayable_request(request: httpx.Request) -> bool:
        return request.method == "POST" and request.url.path.rstrip("/") in (
            _RESPONSES_PATH,
            f"{_RESPONSES_PATH}/compact",
        )


class OpenAICodexProvider(Provider[AsyncOpenAI]):
    """GPT Dive-owned provider for ChatGPT subscription-backed Codex requests."""

    @property
    def name(self) -> str:
        return "openai-codex"

    @property
    def base_url(self) -> str:
        return str(self.client.base_url)

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    @staticmethod
    def model_profile(model_name: str) -> ModelProfile:
        return merge_profile(
            openai_model_profile(model_name),
            OpenAIModelProfile(
                openai_unsupported_model_settings=(
                    "max_tokens",
                    "temperature",
                    "top_p",
                ),
            ),
        )

    def __init__(
        self,
        *,
        credential_source: OpenAICodexCredentialSource | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if credential_source is None:
            credential_source = OpenAICodexAuth()
        self._credential_source = credential_source

        if http_client is None:
            http_client = create_async_http_client()
            self._own_http_client = http_client
            self._http_client_factory = create_async_http_client
        else:
            if http_client.auth is not None:
                raise UserError(
                    "`http_client` must not already have authentication configured."
                )
            if http_client.follow_redirects:
                raise UserError("`http_client` must have `follow_redirects=False`.")

        http_client.auth = _OpenAICodexHTTPAuth(credential_source)
        self._client = AsyncOpenAI(
            base_url=str(_BASE_URL),
            api_key="codex-subscription-auth",
            http_client=http_client,
        )

    def _set_http_client(self, http_client: httpx.AsyncClient) -> None:
        http_client.auth = _OpenAICodexHTTPAuth(self._credential_source)
        self._client._client = http_client  # pyright: ignore[reportPrivateUsage]
