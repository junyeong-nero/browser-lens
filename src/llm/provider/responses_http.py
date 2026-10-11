import json
from typing import Any
from urllib import error, request

from google.genai import types

from . import responses_adapter
from .chat_completion_http import ChatCompletionsProvider


def _responses_url(endpoint_url: str) -> str:
    normalized = endpoint_url.rstrip("/")
    if normalized.endswith("/responses"):
        return normalized
    return f"{normalized}/responses"


class ResponsesProvider(ChatCompletionsProvider):
    """OpenAI Responses API (`/v1/responses`) provider.

    Reuses the header/SSL/extra-body plumbing of `ChatCompletionsProvider`, but
    targets the `input`/`output` item model instead of chat `messages`. Reasoning
    effort is sent as a structured `reasoning.effort` field rather than via
    `extra_body`.
    """

    def __init__(
        self,
        *,
        api_key: str,
        endpoint_url: str | None = None,
        base_url: str | None = None,
        name: str | None = None,
        error_prefix: str | None = None,
        timeout_seconds: float = 15.0,
        headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        supports_image_inputs: bool = True,
        supports_temperature: bool = True,
        reasoning_effort: str | None = None,
    ):
        super().__init__(
            api_key=api_key,
            endpoint_url=endpoint_url,
            base_url=base_url,
            name=name,
            error_prefix=error_prefix,
            timeout_seconds=timeout_seconds,
            headers=headers,
            extra_body=extra_body,
            token_limit_field="max_output_tokens",
            supports_image_inputs=supports_image_inputs,
            supports_temperature=supports_temperature,
        )
        self.supports_reasoning_summaries = True
        endpoint = (endpoint_url or base_url or "").strip()
        self._responses_url = _responses_url(endpoint)
        self._reasoning_effort = reasoning_effort

    def generate_text(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 160,
        temperature: float = 0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        input_items = []
        if system_prompt:
            input_items.append(responses_adapter.system_text_item(system_prompt))
        input_items.append(responses_adapter.user_text_item(prompt))

        body: dict[str, Any] = {
            "model": model,
            "input": input_items,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if self._supports_temperature:
            body["temperature"] = temperature
        text_format = responses_adapter.response_format_to_text(response_format)
        if text_format is not None:
            body["text"] = text_format
        self._apply_reasoning(body)

        payload = self._post_json(self._with_extra_body(body))
        text = responses_adapter.extract_output_text(payload)
        if not text:
            raise RuntimeError(
                f"{self._error_prefix} response did not contain text content."
            )
        return text

    def generate_content(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        body = responses_adapter.build_request_body(
            model=model,
            contents=contents,
            config=config,
            supports_temperature=self._supports_temperature,
        )
        thinking = config.thinking_config
        include_thoughts = bool(thinking and thinking.include_thoughts)
        self._apply_reasoning(body, include_thoughts=include_thoughts)
        payload = self._post_json(self._with_extra_body(body))
        return responses_adapter.payload_to_response(payload)

    def _apply_reasoning(
        self,
        body: dict[str, Any],
        *,
        include_thoughts: bool = False,
    ) -> None:
        if self._reasoning_effort is None or "reasoning" in body:
            return
        reasoning: dict[str, Any] = {"effort": self._reasoning_effort}
        if include_thoughts:
            reasoning["summary"] = "auto"
        body["reasoning"] = reasoning

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        http_request = request.Request(
            self._responses_url,
            data=json.dumps(body, default=str).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self._timeout_seconds,
                context=self._build_ssl_context(),
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self._error_prefix} request failed with HTTP {exc.code}: {error_body}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"{self._error_prefix} request failed: {exc.reason}"
            ) from exc
