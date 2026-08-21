from __future__ import annotations

import os
from enum import StrEnum
from typing import Any

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

_MODEL_OUTPUT_TOKENS_LIMITS: dict[str, int] = {
    "claude-opus-5": 128_000,
    "claude-sonnet-5": 128_000,
    "claude-haiku-4-5-20251001": 64_000,
}


class ModelAlias(StrEnum):
    """Single source of truth for model aliases and provider/model routing."""

    provider: str
    model_name: str
    transport: str
    credential_env: str | None
    base_url: str | None
    bare: bool
    subagent: bool
    output_tokens_limit: int | None

    def __new__(
        cls,
        alias: str,
        provider: str,
        model_name: str,
        transport: str,
        credential_env: str | None = None,
        base_url: str | None = None,
        bare: bool = True,
        subagent: bool = True,
    ):
        obj = str.__new__(cls, alias)
        obj._value_ = alias
        obj.provider = provider
        obj.model_name = model_name
        obj.transport = transport
        obj.credential_env = credential_env
        obj.base_url = base_url
        obj.bare = bare
        obj.subagent = subagent
        obj.output_tokens_limit = _MODEL_OUTPUT_TOKENS_LIMITS.get(model_name)
        return obj

    OPUS5 = (
        "opus5",
        "aiapiflow",
        "claude-opus-5",
        "anthropic-compatible",
        "AIAPIFLOW_CLAUDE_KEY",
        "https://aiapiflow.com",
    )
    KUNAVO_OPUS5 = (
        "kunavo-opus5",
        "kunavo",
        "claude-opus-5",
        "anthropic-compatible",
        "KUNAVO_API_KEY",
        "https://api.kunavo.com",
        True,
        False,
    )
    M3 = (
        "m3",
        "minimax",
        "MiniMax-M3",
        "anthropic-compatible",
        "MINIMAX_API_KEY",
        "https://api.minimax.io/anthropic",
    )
    SOL = ("sol", "openai-codex", "gpt-5.6-sol", "codex-subscription")
    TERRA = ("terra", "openai-codex", "gpt-5.6-terra", "codex-subscription")
    LUNA = ("luna", "openai-codex", "gpt-5.6-luna", "codex-subscription")

    def public_spec(self) -> dict[str, str | bool | int | None]:
        return {
            "provider": self.provider,
            "model": self.model_name,
            "transport": self.transport,
            "bare": self.bare,
            "subagent": self.subagent,
            "output_tokens_limit": self.output_tokens_limit,
        }


def model_catalog() -> dict[str, dict[str, str | bool | int | None]]:
    """Return the sanitized public model catalog derived from ModelAlias."""
    return {alias.value: alias.public_spec() for alias in ModelAlias}


def resolve_model(value: str | ModelAlias, *, lane: str | None = None) -> ModelAlias:
    """Resolve one alias and optionally enforce lane availability."""
    try:
        alias = value if isinstance(value, ModelAlias) else ModelAlias(value.strip().lower())
    except ValueError as exc:
        choices = ", ".join(member.value for member in ModelAlias)
        raise ValueError(f"unknown model alias {value!r}; choose one of: {choices}") from exc

    if lane is not None:
        if lane not in {"bare", "subagent"}:
            raise ValueError(f"unknown model lane: {lane!r}")
        if not bool(getattr(alias, lane)):
            raise ValueError(f"model {alias.value!r} is not enabled for {lane}")
    return alias


def build_model(value: str | ModelAlias) -> Any:
    """Build the Pydantic AI model from the central registry metadata."""
    alias = resolve_model(value)
    if alias.transport == "anthropic-compatible":
        if not alias.credential_env or not alias.base_url:
            raise RuntimeError(f"incomplete provider routing for model {alias.value!r}")
        provider = AnthropicProvider(
            api_key=os.environ[alias.credential_env],
            base_url=alias.base_url,
        )
        return AnthropicModel(alias.model_name, provider=provider)

    if alias.transport == "codex-subscription":
        from .openai_codex import OpenAICodexProvider, OpenAICodexResponsesModel

        return OpenAICodexResponsesModel(alias.model_name, provider=OpenAICodexProvider())

    raise RuntimeError(f"unsupported transport {alias.transport!r} for {alias.value!r}")


def build_provider_model(provider: str, model_name: str) -> Any:
    """Build an exact model name on a registered Anthropic-compatible provider route."""
    route = next(
        (
            alias
            for alias in ModelAlias
            if alias.provider == provider and alias.transport == "anthropic-compatible"
        ),
        None,
    )
    if route is None or not route.credential_env or not route.base_url:
        raise ValueError(f"unknown peer provider {provider!r}")
    return AnthropicModel(
        model_name,
        provider=AnthropicProvider(
            api_key=os.environ[route.credential_env],
            base_url=route.base_url,
        ),
    )


def model_output_tokens_limit(model_name: str) -> int | None:
    return _MODEL_OUTPUT_TOKENS_LIMITS.get(model_name)
