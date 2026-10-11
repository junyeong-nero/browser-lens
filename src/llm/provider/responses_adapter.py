"""Translate the Gemini-style `generate_content` interface used across the
codebase into the OpenAI Responses API (`/v1/responses`) request/response shape,
and back. Mirrors `chat_completion_adapter` but targets the `input`/`output`
item model rather than chat `messages`.
"""

import json
from typing import Any

from google.genai import types

from tools.types import TOOL_ARGUMENT_ERROR_KEY, build_tool_argument_parse_error

from .chat_completion_adapter import (
    _function_response_image_observation_text,
    _inline_data_to_image_content,
    content_to_text,
    declaration_to_openai_tool,
)
from .chat_completion_http import _build_response_format


def build_request_body(
    *,
    model: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    supports_temperature: bool,
) -> dict[str, Any]:
    input_items = contents_to_input(contents)
    if config.system_instruction:
        system_text = content_to_text(config.system_instruction)
        if system_text:
            input_items.insert(0, system_text_item(system_text))

    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "store": False,
    }

    if config.max_output_tokens is not None:
        body["max_output_tokens"] = config.max_output_tokens
    # Reasoning models (supports_temperature=False) reject all custom sampling
    # parameters, so gate both temperature and top_p on the same flag.
    if supports_temperature:
        if config.temperature is not None:
            body["temperature"] = config.temperature
        if config.top_p is not None:
            body["top_p"] = config.top_p

    tools = _build_tools(config)
    if tools:
        body["tools"] = tools

    text_format = _config_to_text_format(config)
    if text_format is not None:
        body["text"] = text_format

    return body


def user_text_item(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def system_text_item(text: str) -> dict[str, Any]:
    return {"role": "system", "content": [{"type": "input_text", "text": text}]}


def response_format_to_text(
    response_format: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Convert a Chat Completions `response_format` into the Responses API
    `text` payload. The Responses API nests the format spec under `text.format`
    and, for JSON-schema mode, flattens the `json_schema` wrapper so `name`,
    `schema`, and `strict` sit directly on the format object.
    """
    if response_format is None:
        return None
    if response_format.get("type") == "json_schema":
        schema_spec = response_format.get("json_schema") or {}
        return {"format": {"type": "json_schema", **schema_spec}}
    return {"format": response_format}


def contents_to_input(contents: list[types.Content]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for content in contents:
        if not content.parts:
            continue

        role = "assistant" if content.role == "model" else (content.role or "user")
        text_parts: list[str] = []
        media_parts: list[dict[str, Any]] = []
        function_calls: list[types.FunctionCall] = []
        function_responses: list[types.FunctionResponse] = []

        for part in content.parts:
            if getattr(part, "thought", False):
                continue
            if part.text:
                text_parts.append(part.text)
            elif part.inline_data:
                image = _inline_data_to_input_image(part.inline_data)
                if image is not None:
                    media_parts.append(image)
                else:
                    text_parts.append(f"[{part.inline_data.mime_type}]")
            elif part.function_call:
                function_calls.append(part.function_call)
            elif part.function_response:
                function_responses.append(part.function_response)

        message = _message_item(role, text_parts, media_parts)
        if message is not None:
            items.append(message)

        for function_call in function_calls:
            items.append(_function_call_item(function_call))

        for function_response in function_responses:
            items.append(_function_call_output_item(function_response))
            observation = _function_response_observation_item(function_response)
            if observation is not None:
                items.append(observation)

    return items


def payload_to_response(payload: dict[str, Any]) -> types.GenerateContentResponse:
    parts: list[types.Part] = []

    for item in payload.get("output") or []:
        item_type = item.get("type")
        if item_type == "reasoning":
            text = _reasoning_text(item)
            if text:
                parts.append(types.Part(text=text, thought=True))
        elif item_type == "message":
            text = _message_text(item)
            if text:
                parts.append(types.Part(text=text))
        elif item_type == "function_call":
            parts.append(_function_call_part(item))

    if not parts:
        return types.GenerateContentResponse(candidates=[])

    candidate = types.Candidate(
        content=types.Content(role="model", parts=parts),
        finish_reason=types.FinishReason.STOP,
    )
    return types.GenerateContentResponse(candidates=[candidate])


def extract_output_text(payload: dict[str, Any]) -> str:
    texts = [
        _message_text(item)
        for item in (payload.get("output") or [])
        if item.get("type") == "message"
    ]
    return "\n".join(text for text in texts if text).strip()


def _build_tools(config: types.GenerateContentConfig) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in config.tools or []:
        for decl in tool.function_declarations or []:
            tools.append({"type": "function", **declaration_to_openai_tool(decl)})
    return tools


def _config_to_text_format(
    config: types.GenerateContentConfig,
) -> dict[str, Any] | None:
    return response_format_to_text(_build_response_format(config))


def _message_item(
    role: str,
    text_parts: list[str],
    media_parts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    content: list[dict[str, Any]] = []
    text = "\n".join(part for part in text_parts if part).strip()
    if text:
        if role == "assistant":
            content.append({"type": "output_text", "text": text, "annotations": []})
        else:
            content.append({"type": "input_text", "text": text})
    content.extend(media_parts)
    if not content:
        return None
    if role == "assistant":
        return {
            "type": "message",
            "role": role,
            "status": "completed",
            "content": content,
        }
    return {"role": role, "content": content}


def _function_call_item(function_call: types.FunctionCall) -> dict[str, Any]:
    call_id = function_call.id or function_call.name or "call_0"
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": function_call.name or "",
        "arguments": json.dumps(function_call.args or {}, ensure_ascii=False),
        "status": "completed",
    }


def _function_call_output_item(
    function_response: types.FunctionResponse,
) -> dict[str, Any]:
    call_id = function_response.id or function_response.name or "call_0"
    output = json.dumps(function_response.response or {}, ensure_ascii=False)
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
        "status": "completed",
    }


def _function_response_observation_item(
    function_response: types.FunctionResponse,
) -> dict[str, Any] | None:
    media_parts = []
    for response_part in function_response.parts or []:
        inline_data = getattr(response_part, "inline_data", None)
        if inline_data is None:
            continue
        image = _inline_data_to_input_image(inline_data)
        if image is not None:
            media_parts.append(image)
    if not media_parts:
        return None
    name = function_response.name or "browser tool"
    text = _function_response_image_observation_text(function_response, name)
    return {
        "role": "user",
        "content": [{"type": "input_text", "text": text}, *media_parts],
    }


def _inline_data_to_input_image(inline_data: Any) -> dict[str, Any] | None:
    chat_image = _inline_data_to_image_content(inline_data)
    if chat_image is None:
        return None
    return {"type": "input_image", "image_url": chat_image["image_url"]["url"]}


def _reasoning_text(item: dict[str, Any]) -> str:
    segments = [
        segment.get("text", "")
        for segment in (item.get("summary") or [])
        if isinstance(segment, dict)
    ]
    return "\n".join(segment for segment in segments if segment).strip()


def _message_text(item: dict[str, Any]) -> str:
    segments = [
        segment.get("text", "")
        for segment in (item.get("content") or [])
        if isinstance(segment, dict) and segment.get("type") == "output_text"
    ]
    return "\n".join(segment for segment in segments if segment).strip()


def _function_call_part(item: dict[str, Any]) -> types.Part:
    name = item.get("name", "")
    args_str = item.get("arguments", "{}")
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError as exc:
        args = {
            TOOL_ARGUMENT_ERROR_KEY: build_tool_argument_parse_error(
                tool_name=name,
                raw_arguments=args_str,
                exc=exc,
            )
        }
    call_id = item.get("call_id") or item.get("id") or "call_0"
    return types.Part(
        function_call=types.FunctionCall(id=call_id, name=name, args=args)
    )
