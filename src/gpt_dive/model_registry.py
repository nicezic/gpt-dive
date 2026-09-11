from __future__ import annotations

import asyncio
import os
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
    """Connection route for one provider."""

    credential_env: str | None
    base_url: str | None
    transport: str = "anthropic-compatible"
    default_model: str = ""


PROVIDER_ROUTES: dict[str, ProviderRoute] = {
    "micu": ProviderRoute(
        "MICU_OPUS_API_KEY",
        "https://www.micuapi.ai",
        default_model="claude-opus-5",
    ),
    "micu-opus": ProviderRoute(
        "MICU_OPUS_API_KEY",
        "https://www.micuapi.ai",
        default_model="claude-opus-5",
    ),
    "micu-ds": ProviderRoute(
        "MICU_DS_API_KEY",
        "https://www.micuapi.ai",
        default_model="deepseek-v4-pro-0813",
    ),
    "micu-kimi": ProviderRoute(
        "MICU_KIMI_API_KEY",
        "https://www.micuapi.ai",
        default_model="kimi-k3",
    ),
    "micu-glm": ProviderRoute(
        "MICU_GLM_API_KEY",
        "https://www.micuapi.ai",
        default_model="glm-5.3",
    ),
    "micu-grok": ProviderRoute(
        "MICU_GROK_API_KEY",
        "https://www.micuapi.ai",
        default_model="grok-4.6",
    ),
    "micu-vip4": ProviderRoute(
        "MICU_VIP4_API_KEY",
        "https://www.micuapi.ai",
        default_model="deepseek-v4-pro-0813",
    ),
    "minimax": ProviderRoute(
        "MINIMAX_API_KEY",
        "https://api.minimax.io/anthropic",
        default_model="MiniMax-M3",
    ),
    "opencode-go": ProviderRoute(
        "OPENCODE_GO_API_KEY",
        "https://opencode.ai/zen/go/v1",
        transport="openai-chat-compatible",
        default_model="glm-5.3-flash",
    ),
    "opencode-zen": ProviderRoute(
        "OPENCODE_GO_API_KEY",
        "https://opencode.ai/zen/v1",
        transport="openai-responses-compatible",
        default_model="muse-spark-1.3-contributor-free",
    ),
    "openai-codex": ProviderRoute(
        None,
        None,
        transport="codex-subscription",
        default_model="gpt-5.6-terra",
    ),
}

MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "astra": ("openai-codex", "gpt-6-astra"),
    "gpt6": ("openai-codex", "gpt-6-astra"),
    "terra": ("openai-codex", "gpt-5.6-terra"),
    "sol": ("openai-codex", "gpt-5.6-sol"),
    "luna": ("openai-codex", "gpt-5.6-luna"),
    "opus": ("micu", "claude-opus-5"),
    "opus5": ("micu", "claude-opus-5"),
    "micu-opus5": ("micu", "claude-opus-5"),
    "ds": ("micu-ds", "deepseek-v4-pro-0813"),
    "kimi": ("micu-kimi", "kimi-k3"),
    "glm": ("micu-glm", "glm-5.3"),
    "grok": ("micu-grok", "grok-4.6"),
    "vip4": ("micu-vip4", "deepseek-v4-pro-0813"),
    "m3": ("minimax", "MiniMax-M3"),
    "glm-5.3-flash": ("opencode-go", "glm-5.3-flash"),
    "glm-flash": ("opencode-go", "glm-5.3-flash"),
    "muse-free": ("opencode-zen", "muse-spark-1.3-contributor-free"),
}


def resolve_model(
    model_alias: str, *, provider: str | None = None, lane: str | None = None
) -> tuple[str, str]:
    """Resolve model_alias to (provider, exact_model_name)."""
    if not isinstance(model_alias, str) or not model_alias.strip():
        raise ValueError("model alias must not be empty")

    key = model_alias.strip().lower()
    if key in MODEL_ALIASES:
        return MODEL_ALIASES[key]

    if ":" in model_alias:
        prov, exact = model_alias.split(":", 1)
        return prov.strip().lower(), exact.strip()

    if "/" in model_alias:
        prov, exact = model_alias.split("/", 1)
        return prov.strip().lower(), exact.strip()

    if provider is not None:
        prov = provider.strip().lower()
        return prov, model_alias.strip()

    choices = ", ".join(sorted(MODEL_ALIASES))
    raise ValueError(
        f"unknown model alias {model_alias!r}; choose one of: {choices} or use 'provider:model_name' or 'provider/model_name'"
    )


def _build_exact_model(route: ProviderRoute, model_name: str) -> Any:
    if route.transport == "codex-subscription":
        from pydantic_ai.models.openai_codex import OpenAICodexModel

        return OpenAICodexModel(model_name)

    if not route.credential_env or not route.base_url:
        raise RuntimeError("provider route is missing credential or base URL")
    api_key = os.environ[route.credential_env]
    if route.transport == "anthropic-compatible":
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(api_key=api_key, base_url=route.base_url),
        )

    if route.transport in {"openai-chat-compatible", "openai-responses-compatible"}:
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        openai_provider = OpenAIProvider(api_key=api_key, base_url=route.base_url)
        if route.transport == "openai-chat-compatible":
            return OpenAIChatModel(model_name, provider=openai_provider)
        return OpenAIResponsesModel(model_name, provider=openai_provider)

    raise RuntimeError(f"unsupported provider transport {route.transport!r}")


def get_model(model_alias: str, provider: str | None = None) -> Any:
    """Build Pydantic AI model instance from model_alias."""
    prov, model_name = resolve_model(model_alias, provider=provider)
    route = PROVIDER_ROUTES.get(prov)
    if route is None:
        choices = ", ".join(sorted(PROVIDER_ROUTES))
        raise ValueError(f"unknown provider {prov!r}; registered providers: {choices}")
    return _build_exact_model(route, model_name)


build_model = get_model


def build_provider_model(provider: str, model: str) -> Any:
    return get_model(model, provider=provider)


def model_catalog() -> dict[str, dict[str, Any]]:
    """Return public model catalog derived from MODEL_ALIASES."""
    return {
        alias: {
            "provider": prov,
            "model": model,
            "transport": (
                "codex-subscription"
                if prov == "openai-codex"
                else (
                    PROVIDER_ROUTES[prov].transport if prov in PROVIDER_ROUTES else ""
                )
            ),
            "output_tokens_limit": model_output_tokens_limit(model),
        }
        for alias, (prov, model) in MODEL_ALIASES.items()
    }


def _async_client_for_route(route: ProviderRoute) -> Any:
    from anthropic import AsyncAnthropic

    if not route.credential_env or not route.base_url:
        raise RuntimeError("provider route is missing credential or base URL")
    return AsyncAnthropic(
        api_key=os.environ[route.credential_env],
        base_url=route.base_url,
        default_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )


async def verify_provider_model(
    provider: str, model_name: str, *, timeout: float = 10.0
) -> dict[str, Any]:
    """Soft-verify one exact model id against an Anthropic-compatible catalog."""
    route = PROVIDER_ROUTES.get(provider.strip().lower())
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
