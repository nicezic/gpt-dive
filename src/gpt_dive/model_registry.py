from __future__ import annotations

import asyncio
import os
from enum import StrEnum
from typing import Any, NamedTuple

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

_MODEL_OUTPUT_TOKENS_LIMITS: dict[str, int] = {
    "claude-opus-5": 128_000,
    "claude-sonnet-5": 128_000,
    "claude-haiku-4-5-20251001": 64_000,
    "deepseek-v4-pro-0813": 64_000,
    "deepseek-v4-pro": 64_000,
    "kimi-k3": 64_000,
    "glm-5.3": 64_000,
    "grok-4.6": 64_000,
}


class ProviderRoute(NamedTuple):
    """Connection route, model interface, and default model for one provider."""

    credential_env: str
    base_url: str
    default_model: str
    transport: str = "anthropic-compatible"


# Single source of truth for exact-model provider routing (peer review and any
# future direct-model caller). Adding a provider is one entry here plus its
# environment key; see docs/pydantic/providers.md for the recipe.
PROVIDER_ROUTES: dict[str, ProviderRoute] = {
    "micu": ProviderRoute(
        "MICU_OPUS_API_KEY", "https://www.micuapi.ai", "claude-opus-5"
    ),
    "micu-opus": ProviderRoute(
        "MICU_OPUS_API_KEY", "https://www.micuapi.ai", "claude-opus-5"
    ),
    "micu-ds": ProviderRoute(
        "MICU_DS_API_KEY", "https://www.micuapi.ai", "deepseek-v4-pro-0813"
    ),
    "micu-kimi": ProviderRoute(
        "MICU_KIMI_API_KEY", "https://www.micuapi.ai", "kimi-k3"
    ),
    "micu-glm": ProviderRoute("MICU_GLM_API_KEY", "https://www.micuapi.ai", "glm-5.3"),
    "micu-grok": ProviderRoute(
        "MICU_GROK_API_KEY", "https://www.micuapi.ai", "grok-4.6"
    ),
    "micu-vip4": ProviderRoute(
        "MICU_VIP4_API_KEY", "https://www.micuapi.ai", "deepseek-v4-pro-0813"
    ),
    "minimax": ProviderRoute(
        "MINIMAX_API_KEY", "https://api.minimax.io/anthropic", "MiniMax-M3"
    ),
    "opencode-go": ProviderRoute(
        "OPENCODE_GO_API_KEY",
        "https://opencode.ai/zen/go/v1",
        "glm-5.3-flash",
        "openai-chat-compatible",
    ),
    "opencode-zen": ProviderRoute(
        "OPENCODE_GO_API_KEY",
        "https://opencode.ai/zen/v1",
        "muse-spark-1.3-contributor-free",
        "openai-responses-compatible",
    ),
}


class ModelAlias(StrEnum):
    """Single source of truth for model aliases and provider/model routing."""

    provider: str
    model_name: str
    peer_review: bool
    subagent: bool
    output_tokens_limit: int | None

    def __new__(
        cls,
        alias: str,
        provider: str,
        model_name: str,
        peer_review: bool = True,
        subagent: bool = True,
    ):
        obj = str.__new__(cls, alias)
        obj._value_ = alias
        obj.provider = provider
        obj.model_name = model_name
        obj.peer_review = peer_review
        obj.subagent = subagent
        obj.output_tokens_limit = _MODEL_OUTPUT_TOKENS_LIMITS.get(model_name)
        return obj

    OPUS5 = ("opus5", "micu", "claude-opus-5")
    MICU_OPUS5 = ("micu-opus5", "micu", "claude-opus-5")
    DEEPSEEK = ("ds", "micu-ds", "deepseek-v4-pro-0813")
    KIMI = ("kimi", "micu-kimi", "kimi-k3")
    GLM = ("glm", "micu-glm", "glm-5.3")
    GROK = ("grok", "micu-grok", "grok-4.6")
    VIP4 = ("vip4", "micu-vip4", "deepseek-v4-pro-0813")
    M3 = ("m3", "minimax", "MiniMax-M3")
    GLM_FLASH = ("glm-5.3-flash", "opencode-go", "glm-5.3-flash")
    MUSE_FREE = ("muse-free", "opencode-zen", "muse-spark-1.3-contributor-free")
    SOL = ("sol", "openai-codex", "gpt-5.6-sol")
    TERRA = ("terra", "openai-codex", "gpt-5.6-terra")
    LUNA = ("luna", "openai-codex", "gpt-5.6-luna")
    GPT6 = ("gpt6", "openai-codex", "gpt-6-astra")

    @property
    def transport(self) -> str:
        if self.provider == "openai-codex":
            return "codex-subscription"
        route = PROVIDER_ROUTES.get(self.provider)
        if route is None:
            raise RuntimeError(f"missing provider route for model {self.value!r}")
        return route.transport

    def public_spec(self) -> dict[str, str | bool | int | None]:
        return {
            "provider": self.provider,
            "model": self.model_name,
            "transport": self.transport,
            "peer_review": self.peer_review,
            "subagent": self.subagent,
            "output_tokens_limit": self.output_tokens_limit,
        }


def model_catalog() -> dict[str, dict[str, str | bool | int | None]]:
    """Return the sanitized public model catalog derived from ModelAlias."""
    return {alias.value: alias.public_spec() for alias in ModelAlias}


def resolve_model(value: str | ModelAlias, *, lane: str | None = None) -> ModelAlias:
    """Resolve one alias and optionally enforce lane availability."""
    try:
        alias = (
            value
            if isinstance(value, ModelAlias)
            else ModelAlias(value.strip().lower())
        )
    except ValueError as exc:
        choices = ", ".join(member.value for member in ModelAlias)
        raise ValueError(
            f"unknown model alias {value!r}; choose one of: {choices}"
        ) from exc

    if lane is not None:
        if lane not in {"peer_review", "subagent"}:
            raise ValueError(f"unknown model lane: {lane!r}")
        if not bool(getattr(alias, lane)):
            raise ValueError(f"model {alias.value!r} is not enabled for {lane}")
    return alias


def _build_routed_model(route: ProviderRoute, model_name: str) -> Any:
    api_key = os.environ[route.credential_env]
    if route.transport == "anthropic-compatible":
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(api_key=api_key, base_url=route.base_url),
        )

    if route.transport in {"openai-chat-compatible", "openai-responses-compatible"}:
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=api_key, base_url=route.base_url)
        if route.transport == "openai-chat-compatible":
            return OpenAIChatModel(model_name, provider=provider)
        return OpenAIResponsesModel(model_name, provider=provider)

    raise RuntimeError(f"unsupported provider transport {route.transport!r}")


def build_model(value: str | ModelAlias) -> Any:
    """Build the Pydantic AI model from the central registry metadata."""
    alias = resolve_model(value)
    if alias.provider == "openai-codex":
        from pydantic_ai.models.openai_codex import OpenAICodexModel

        return OpenAICodexModel(alias.model_name)

    route = PROVIDER_ROUTES.get(alias.provider)
    if route is None:
        raise RuntimeError(f"incomplete provider routing for model {alias.value!r}")
    return _build_routed_model(route, alias.model_name)


def build_provider_model(provider: str, model_name: str) -> Any:
    """Build an exact model name on a registered peer-review provider."""
    if provider == "openai-codex":
        from pydantic_ai.models.openai_codex import OpenAICodexModel

        return OpenAICodexModel(model_name)

    route = PROVIDER_ROUTES.get(provider)
    if route is None:
        known = ", ".join(sorted(PROVIDER_ROUTES))
        raise ValueError(
            f"unknown peer provider {provider!r}; registered providers: {known}"
        )
    return _build_routed_model(route, model_name)


def _async_client_for_route(route: ProviderRoute) -> Any:
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(
        api_key=os.environ[route.credential_env],
        base_url=route.base_url,
        default_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )


async def verify_provider_model(
    provider: str, model_name: str, *, timeout: float = 10.0
) -> dict[str, Any]:
    """Soft-verify one exact model name against the provider's models list.

    Returns ``{checked, exists, available}``. ``checked=False`` means the
    models endpoint could not be consulted (unsupported, unauthorized, slow);
    callers must then proceed as before. ``available`` carries the provider's
    model ids whenever the listing succeeded.
    """
    route = PROVIDER_ROUTES.get(provider)
    if route is None or route.transport != "anthropic-compatible":
        return {"checked": False, "exists": False, "available": []}
    try:
        client = _async_client_for_route(route)

        async def _list_ids() -> list[str]:
            return [model.id async for model in client.models.list()]

        available = await asyncio.wait_for(_list_ids(), timeout=timeout)
    except Exception:
        return {"checked": False, "exists": False, "available": []}
    return {"checked": True, "exists": model_name in available, "available": available}


def model_output_tokens_limit(model_name: str) -> int | None:
    return _MODEL_OUTPUT_TOKENS_LIMITS.get(model_name)
