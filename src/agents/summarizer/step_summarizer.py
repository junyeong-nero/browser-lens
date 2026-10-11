from __future__ import annotations

import json
import os
import re

from google.genai import types

import config as app_config
from llm.provider.chat_completion_http import ChatCompletionsProvider
from llm.provider.env_config import parse_action_summary_timeout_seconds, require_env

from .types import ActionStepSummary, ActionSummaryTextProvider


_LEAK_PATTERN = re.compile(
    r"\b(?:ARIA|snapshot|frame\s*\d*|nodes?|ref|diff)\b"
    r"|트리\s*구조"
    r"|ARIA\s*트리"
    r"|\{[^}]*\}"
    r"|^\s*[+\-]\s+\S",
    re.IGNORECASE | re.MULTILINE,
)


def _clean_summary_field(text: str, replacement: str) -> str:
    normalized = " ".join(text.split())
    return replacement if _LEAK_PATTERN.search(normalized) else normalized


class ActionStepSummarizer:
    def __init__(
        self,
        provider: ActionSummaryTextProvider,
        model: str,
        summary_source: str,
    ):
        self._provider = provider
        self._model = model
        self._summary_source = summary_source

    @classmethod
    def from_env(cls) -> "ActionStepSummarizer | None":
        summary_config = app_config.summary_config()
        model = os.environ.get("ACTION_SUMMARY_MODEL", summary_config.model).strip()
        if not model:
            raise ValueError("ACTION_SUMMARY_MODEL must not be empty when summarization is enabled.")
        endpoint_override = os.environ.get("ACTION_SUMMARY_ENDPOINT_URL")
        endpoint_url = (
            endpoint_override
            if endpoint_override is not None
            else summary_config.endpoint_url
        ).strip()
        if not endpoint_url:
            raise ValueError("ACTION_SUMMARY_ENDPOINT_URL must not be empty when summarization is enabled.")
        effective_updates = {
            "model": model,
            "endpoint_url": endpoint_url,
        }
        if endpoint_override is not None and endpoint_url != summary_config.endpoint_url:
            effective_updates.update({"api_key_env": None})
        effective_config = summary_config.model_copy(update=effective_updates)

        configured_api_key_env = os.environ.get("ACTION_SUMMARY_API_KEY_ENV")
        api_key_env = (
            configured_api_key_env
            if configured_api_key_env is not None
            else app_config.api_key_env(effective_config)
        ).strip()
        if not api_key_env:
            raise ValueError("ACTION_SUMMARY_API_KEY_ENV must not be empty when summarization is enabled.")
        if not cls._api_key_env_has_credentials(api_key_env):
            return None

        effective_config = effective_config.model_copy(update={"api_key_env": api_key_env})
        extra_body = dict(effective_config.extra_body)
        reasoning_effort = app_config.reasoning_effort(effective_config)
        if reasoning_effort is not None:
            extra_body["reasoning_effort"] = reasoning_effort
        provider = ChatCompletionsProvider(
            api_key=require_env(
                api_key_env,
                f"{api_key_env} must be set for endpoint {effective_config.endpoint_url}.",
            ),
            endpoint_url=effective_config.endpoint_url,
            name=app_config.endpoint_label(effective_config),
            timeout_seconds=parse_action_summary_timeout_seconds(),
            headers=effective_config.headers,
            extra_body=extra_body,
            token_limit_field=effective_config.token_limit_field,
            supports_image_inputs=effective_config.supports_image_inputs,
            supports_temperature=app_config.supports_temperature(effective_config),
        )

        return cls(
            provider=provider,
            model=model,
            summary_source=app_config.endpoint_label(effective_config),
        )

    @staticmethod
    def _api_key_env_has_credentials(api_key_env: str) -> bool:
        return bool(os.environ.get(api_key_env, "").strip())

    def summarize_action(
        self,
        *,
        query: str,
        function_call: types.FunctionCall,
        reasoning: str | None,
        current_url: str | None,
        previous_url: str | None = None,
        aria_diff: str | None = None,
    ) -> ActionStepSummary | None:
        prompt_payload = {
            "user_request": query,
            "action": {
                "name": function_call.name,
                "args": dict(function_call.args or {}),
            },
            "model_reasoning": reasoning,
            "previous_url": previous_url,
            "current_url": current_url,
            "aria_diff": aria_diff,
        }

        try:
            raw_response = self._provider.generate_text(
                model=self._model,
                system_prompt=(
                    "You summarize browser automation action steps for end users. "
                    "Return strict JSON only. "
                    "Never invent unseen page details. "
                    "Match the user's language; use Korean for Korean requests. "
                    "Write concise text."
                ),
                prompt=(
                    "Summarize the executed browser action as three short fields.\n"
                    "Return JSON with keys what, why, outcome.\n"
                    "- what: a short label (≤ 24 chars) describing the executed action.\n"
                    "- why: one concise sentence explaining why this step was needed, grounded in the user request.\n"
                    "- outcome: one concise sentence describing the concrete result observed. "
                    "Use `aria_diff` and URL change only as internal evidence. "
                    "If the outcome cannot be inferred, return '—'.\n"
                    "Never invent page details that are not present in the inputs.\n"
                    "Describe the result the way a non-technical end user would see it "
                    "(e.g. 'Search results list is shown', 'Login form appeared', 'Moved to the driver download page'). "
                    "Never use the words 'ARIA', 'snapshot', 'frame', 'node', 'ref', 'diff', '트리', '구조', "
                    "and never quote raw diff syntax ('+', '-' line markers) or brace-wrapped tokens like '{Frame 1}'.\n\n"
                    f"{json.dumps(prompt_payload, ensure_ascii=False)}"
                ),
                max_tokens=220,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "action_step_summary",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "what": {"type": "string"},
                                "why": {"type": "string"},
                                "outcome": {"type": "string"},
                            },
                            "required": ["what", "why", "outcome"],
                            "additionalProperties": False,
                        },
                    },
                },
            )
        except Exception:
            return None

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            return None

        what = parsed.get("what")
        why = parsed.get("why")
        outcome = parsed.get("outcome")
        if not isinstance(what, str) or not what.strip():
            return None
        if not isinstance(why, str) or not why.strip():
            return None
        if not isinstance(outcome, str) or not outcome.strip():
            return None

        return ActionStepSummary(
            what=_clean_summary_field(what, "Action performed"),
            why=_clean_summary_field(why, "—"),
            outcome=_clean_summary_field(outcome, "—"),
            summary_source=self._summary_source,
        )

    def summarize_final_result(
        self,
        *,
        query: str,
        final_response: str | None,
        current_url: str | None,
    ) -> str | None:
        prompt_payload = {
            "user_request": query,
            "model_final_response": final_response,
            "current_url": current_url,
        }

        try:
            raw_response = self._provider.generate_text(
                model=self._model,
                system_prompt=(
                    "You rewrite the browser agent's final outcome for end users. "
                    "Return strict JSON only. "
                    "Never mention internal deliberation, screenshots, waiting, or that you are an agent unless the user explicitly asked for that. "
                    "Match the user's language; use Korean for Korean requests. "
                    "Answer the user's request directly and concisely."
                ),
                prompt=(
                    "Rewrite the final browser task outcome as the answer shown in chat.\n"
                    "Return JSON with key final_result_summary.\n"
                    "- final_result_summary: one concise answer for the user's request.\n"
                    "Do not narrate the browser process.\n"
                    "Use user_request to choose language and relevance. Do not infer details that "
                    "are not present in the inputs; factual claims should come only from "
                    "model_final_response and current_url. If the model response is vague, preserve "
                    "the uncertainty or blocker instead of inventing a result.\n\n"
                    f"{json.dumps(prompt_payload, ensure_ascii=False)}"
                ),
                max_tokens=120,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "final_result_summary",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "final_result_summary": {"type": "string"},
                            },
                            "required": ["final_result_summary"],
                            "additionalProperties": False,
                        },
                    },
                },
            )
        except Exception:
            return None

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            return None

        final_result_summary = parsed.get("final_result_summary")
        if not isinstance(final_result_summary, str) or not final_result_summary.strip():
            return None

        return " ".join(final_result_summary.split())
