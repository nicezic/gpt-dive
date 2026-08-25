from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from pydantic_ai import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.settings import ModelSettings

from .auth import OpenAICodexLoginRequiredError


def _find_login_required(error: BaseException) -> OpenAICodexLoginRequiredError | None:
    """Recover the one auth error the OpenAI SDK may wrap as a connection error."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OpenAICodexLoginRequiredError):
            return current
        current = current.__cause__ or current.__context__
    return None


class OpenAICodexResponsesModel(OpenAIResponsesModel):
    """Adapt official OpenAI Responses behavior to the stateless Codex subscription backend."""

    @staticmethod
    def _codex_settings(model_settings: ModelSettings | None) -> ModelSettings:
        settings = dict(model_settings or {})
        settings["openai_store"] = False
        return cast(ModelSettings, settings)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Preserve ordinary Agent.run() by streaming and aggregating locally."""
        async with self.request_stream(
            messages, model_settings, model_request_parameters
        ) as streamed_response:
            async for _ in streamed_response:
                pass
            aggregated = streamed_response.get()
            if aggregated.state == "incomplete":
                raise UnexpectedModelBehavior(
                    "OpenAI Codex streamed response ended before it was complete"
                )
            return aggregated

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        settings = self._codex_settings(model_settings)
        try:
            async with super().request_stream(
                messages, settings, model_request_parameters, run_context=run_context
            ) as streamed_response:
                yield streamed_response
        except ModelAPIError as error:
            if login_required := _find_login_required(error):
                raise login_required from error
            raise

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> Any:
        raise UserError(
            f"Counting tokens ahead of the request is not supported by model {self.model_name!r} "
            "on the OpenAI Codex subscription backend."
        )
