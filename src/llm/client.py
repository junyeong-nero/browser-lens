import re
import time
from collections.abc import Callable
from typing import Protocol

import termcolor
from google.genai import types

import config as app_config

from .provider.chat_completion_http import ChatCompletionsProvider
from .provider.env_config import parse_llm_timeout_seconds, require_env
from .provider.responses_http import ResponsesProvider


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRYABLE_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "temporarily_unavailable",
    "service unavailable",
    "unavailable",
    "internal error",
    "deadline exceeded",
    "rate limit",
    "resource_exhausted",
    "resource exhausted",
    "connection reset",
    "connection aborted",
    "connection error",
    "broken pipe",
)
HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)
INTERRUPT_POLL_INTERVAL_SECONDS = 0.2


def _describe_empty_response(response: types.GenerateContentResponse) -> str:
    parts: list[str] = []
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None:
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason is not None:
            parts.append(f"prompt_block_reason={block_reason}")
        block_message = getattr(feedback, "block_reason_message", None)
        if block_message:
            parts.append(f"prompt_block_message={block_message!r}")
        safety = getattr(feedback, "safety_ratings", None)
        if safety:
            parts.append(f"prompt_safety_ratings={safety}")

    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        total_tokens = getattr(usage, "total_token_count", None)
        thoughts_tokens = getattr(usage, "thoughts_token_count", None)
        parts.append(
            f"usage(prompt={prompt_tokens}, total={total_tokens}, thoughts={thoughts_tokens})"
        )

    return "; ".join(parts) if parts else "no prompt_feedback or usage metadata available"


class LLMError(Exception):
    pass


class EmptyResponseError(LLMError):
    pass


class LLMInterrupted(LLMError):
    pass


def _coerce_status_code(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _explicit_status_code(error: Exception) -> int | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        for attr in ("status_code", "code", "status"):
            status_code = _coerce_status_code(getattr(current, attr, None))
            if status_code is not None:
                return status_code
        current = current.__cause__ or current.__context__

    match = HTTP_STATUS_RE.search(str(error))
    if not match:
        return None
    return int(match.group(1))


def _should_retry_generation_error(error: Exception) -> bool:
    """Return whether a provider failure is likely transient."""
    if isinstance(error, LLMInterrupted):
        return False
    if isinstance(error, EmptyResponseError):
        return True

    status_code = _explicit_status_code(error)
    if status_code is not None:
        return status_code in RETRYABLE_STATUS_CODES

    message = str(error).lower()
    if any(marker in message for marker in RETRYABLE_ERROR_MARKERS):
        return True

    # Preserve the previous transport-error behavior for exceptions that carry
    # no HTTP status. Provider adapters include status codes for API rejections.
    return True


class ProviderProtocol(Protocol):
    name: str
    supports_image_inputs: bool
    supports_reasoning_summaries: bool

    @property
    def sdk_client(self): ...

    def build_function_declaration(
        self, callable_: Callable[..., object]
    ) -> types.FunctionDeclaration: ...

    def generate_content(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse: ...


class LLMClient:
    def __init__(
        self,
        provider: ProviderProtocol,
        max_retries: int = 5,
        base_delay_s: int = 1,
        interrupt_checker: Callable[[], bool] | None = None,
    ):
        self._provider = provider
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._interrupt_checker = interrupt_checker

    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls.from_model_config(app_config.actor_config())

    @classmethod
    def from_model_config(
        cls,
        model_config: app_config.EndpointModelConfig,
        *,
        max_retries: int = 5,
        base_delay_s: int = 1,
        interrupt_checker: Callable[[], bool] | None = None,
    ) -> "LLMClient":
        api_key_env = app_config.api_key_env(model_config)
        api_key = require_env(
            api_key_env,
            f"{api_key_env} must be set for endpoint {model_config.endpoint_url}.",
        )
        reasoning_effort = app_config.reasoning_effort(model_config)
        provider_name = app_config.endpoint_label(model_config)
        timeout_seconds = parse_llm_timeout_seconds()
        supports_temperature = app_config.supports_temperature(model_config)
        if model_config.api == "responses":
            provider = ResponsesProvider(
                api_key=api_key,
                endpoint_url=model_config.endpoint_url,
                name=provider_name,
                timeout_seconds=timeout_seconds,
                headers=model_config.headers,
                extra_body=dict(model_config.extra_body),
                supports_image_inputs=model_config.supports_image_inputs,
                supports_temperature=supports_temperature,
                reasoning_effort=reasoning_effort,
            )
        else:
            extra_body = dict(model_config.extra_body)
            if reasoning_effort is not None:
                extra_body["reasoning_effort"] = reasoning_effort
            provider = ChatCompletionsProvider(
                api_key=api_key,
                endpoint_url=model_config.endpoint_url,
                name=provider_name,
                timeout_seconds=timeout_seconds,
                headers=model_config.headers,
                extra_body=extra_body,
                token_limit_field=model_config.token_limit_field,
                supports_image_inputs=model_config.supports_image_inputs,
                supports_temperature=supports_temperature,
            )
        return cls(
            provider=provider,
            max_retries=max_retries,
            base_delay_s=base_delay_s,
            interrupt_checker=interrupt_checker,
        )

    @classmethod
    def for_text(cls) -> "LLMClient":
        return cls.from_model_config(app_config.actor_config())

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def supports_image_inputs(self) -> bool:
        return self._provider.supports_image_inputs

    @property
    def supports_reasoning_summaries(self) -> bool:
        return self._provider.supports_reasoning_summaries

    @property
    def sdk_client(self):
        return self._provider.sdk_client

    def build_function_declaration(
        self, callable_: Callable[..., object]
    ) -> types.FunctionDeclaration:
        return self._provider.build_function_declaration(callable_)

    def _raise_if_interrupted(self) -> None:
        if self._interrupt_checker is not None and self._interrupt_checker():
            raise LLMInterrupted("Task interrupted by user.")

    def _sleep_before_retry(self, delay_seconds: float) -> None:
        if self._interrupt_checker is None:
            time.sleep(delay_seconds)
            return

        deadline = time.monotonic() + delay_seconds
        while True:
            self._raise_if_interrupted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(INTERRUPT_POLL_INTERVAL_SECONDS, remaining))

    def generate_content(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            self._raise_if_interrupted()
            try:
                response = self._provider.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                last_error = exc
                if not _should_retry_generation_error(exc):
                    raise
            else:
                if response.candidates:
                    return response
                diagnostics = _describe_empty_response(response)
                termcolor.cprint(
                    f"Empty response diagnostics: {diagnostics}\n",
                    color="yellow",
                )
                last_error = EmptyResponseError(
                    "Model returned no candidates after a successful request. "
                    f"{diagnostics}"
                )

            if attempt < self._max_retries - 1:
                delay = self._base_delay_s * (2**attempt)
                termcolor.cprint(
                    (
                        f"Generating content failed on attempt {attempt + 1}. "
                        f"Retrying in {delay} seconds...\n"
                    ),
                    color="yellow",
                )
                self._sleep_before_retry(delay)

        termcolor.cprint(
            f"Generating content failed after {self._max_retries} attempts.\n",
            color="red",
        )
        if last_error is None:
            raise LLMError("Generating content failed for an unknown reason.")
        raise last_error
