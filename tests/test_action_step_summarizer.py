import json
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from google.genai import types

from config import EndpointModelConfig
from agents.summarizer import ActionReviewService, ActionStepSummary, ActionStepSummarizer
from llm.provider.chat_completion_http import ChatCompletionsProvider
from tools.text_mode_tools import key_combination


class TestChatCompletionsTextProvider(unittest.TestCase):
    @patch("llm.provider.chat_completion_http.request.urlopen")
    def test_generate_text_builds_chat_completion_request(self, mock_urlopen):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"action_summary":"검색창 클릭","reason":"검색어를 입력하려고 했습니다."}',
                    }
                }
            ]
        }
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_payload
        ).encode("utf-8")

        provider = ChatCompletionsProvider(
            api_key="test-key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
        )
        text = provider.generate_text(
            model="gpt-4o-mini",
            system_prompt="system",
            prompt="prompt",
            max_tokens=64,
            temperature=0,
            response_format={"type": "json_object"},
        )

        self.assertEqual(
            text,
            '{"action_summary":"검색창 클릭","reason":"검색어를 입력하려고 했습니다."}',
        )
        http_request = mock_urlopen.call_args.args[0]
        request_body = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-4o-mini")
        self.assertEqual(request_body["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(request_body["messages"][1], {"role": "user", "content": "prompt"})
        self.assertEqual(request_body["response_format"], {"type": "json_object"})

    @patch("llm.provider.chat_completion_http.request.urlopen")
    def test_generate_content_uses_chat_completion_tool_protocol(self, mock_urlopen):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-2",
                                "type": "function",
                                "function": {
                                    "name": "key_combination",
                                    "arguments": '{"keys":["Enter"]}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_payload
        ).encode("utf-8")

        provider = ChatCompletionsProvider(
            api_key="test-key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
        )
        declaration = provider.build_function_declaration(key_combination)
        response = provider.generate_content(
            model="test-model",
            contents=[
                types.Content(role="user", parts=[types.Part(text="press enter")]),
                types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id="call-1",
                                name="key_combination",
                                args={"keys": ["Tab"]},
                            )
                        )
                    ],
                ),
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id="call-1",
                                name="key_combination",
                                response={"url": "https://example.com"},
                            )
                        )
                    ],
                ),
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=[declaration])]
            ),
        )

        request_body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["messages"][1]["role"], "assistant")
        self.assertEqual(request_body["messages"][1]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(
            json.loads(request_body["messages"][1]["tool_calls"][0]["function"]["arguments"]),
            {"keys": ["Tab"]},
        )
        self.assertEqual(request_body["messages"][2]["role"], "tool")
        self.assertEqual(request_body["messages"][2]["tool_call_id"], "call-1")
        self.assertEqual(
            json.loads(request_body["messages"][2]["content"]),
            {"url": "https://example.com"},
        )
        parameters = request_body["tools"][0]["function"]["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(parameters["properties"]["keys"]["type"], "array")
        self.assertEqual(parameters["properties"]["keys"]["items"]["type"], "string")
        returned_call = response.candidates[0].content.parts[0].function_call
        self.assertEqual(returned_call.id, "call-2")
        self.assertEqual(returned_call.args, {"keys": ["Enter"]})

    @patch("llm.provider.chat_completion_http.request.urlopen")
    def test_generate_text_preserves_response_format(self, mock_urlopen):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"action_summary":"검색창 클릭","reason":"검색어를 입력하려고 했습니다."}',
                    }
                }
            ]
        }
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_payload
        ).encode("utf-8")

        provider = ChatCompletionsProvider(
            api_key="test-key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
        )
        text = provider.generate_text(
            model="gpt-4o-mini",
            system_prompt="system",
            prompt="prompt",
            max_tokens=64,
            temperature=0,
            response_format={"type": "json_schema", "json_schema": {"name": "summary", "schema": {}}},
        )

        self.assertEqual(
            text,
            '{"action_summary":"검색창 클릭","reason":"검색어를 입력하려고 했습니다."}',
        )
        http_request = mock_urlopen.call_args.args[0]
        request_body = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-4o-mini")
        self.assertEqual(request_body["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(request_body["messages"][1], {"role": "user", "content": "prompt"})
        self.assertEqual(
            request_body["response_format"],
            {"type": "json_schema", "json_schema": {"name": "summary", "schema": {}}},
        )

    @patch("llm.provider.chat_completion_http.request.urlopen")
    def test_generate_content_uses_chat_completion_tool_protocol(self, mock_urlopen):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-2",
                                "type": "function",
                                "function": {
                                    "name": "key_combination",
                                    "arguments": '{"keys":["Enter"]}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_payload
        ).encode("utf-8")

        provider = ChatCompletionsProvider(
            api_key="test-key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
        )
        declaration = provider.build_function_declaration(key_combination)
        response = provider.generate_content(
            model="test-model",
            contents=[
                types.Content(role="user", parts=[types.Part(text="press enter")]),
                types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id="call-1",
                                name="key_combination",
                                args={"keys": ["Tab"]},
                            )
                        )
                    ],
                ),
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id="call-1",
                                name="key_combination",
                                response={"url": "https://example.com"},
                            )
                        )
                    ],
                ),
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=[declaration])]
            ),
        )

        request_body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["messages"][1]["role"], "assistant")
        self.assertEqual(request_body["messages"][1]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(
            json.loads(request_body["messages"][1]["tool_calls"][0]["function"]["arguments"]),
            {"keys": ["Tab"]},
        )
        self.assertEqual(request_body["messages"][2]["role"], "tool")
        self.assertEqual(request_body["messages"][2]["tool_call_id"], "call-1")
        self.assertEqual(
            json.loads(request_body["messages"][2]["content"]),
            {"url": "https://example.com"},
        )
        parameters = request_body["tools"][0]["function"]["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(parameters["properties"]["keys"]["type"], "array")
        self.assertEqual(parameters["properties"]["keys"]["items"]["type"], "string")
        returned_call = response.candidates[0].content.parts[0].function_call
        self.assertEqual(returned_call.id, "call-2")
        self.assertEqual(returned_call.args, {"keys": ["Enter"]})


class _FakeStepSummarizer:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.final_result_calls: list[dict[str, object]] = []

    def summarize_action(self, **kwargs) -> ActionStepSummary | None:
        self.calls.append(kwargs)
        return ActionStepSummary(
            what="예시 페이지 열기",
            why="요청한 페이지로 이동하기 위한 단계였습니다.",
            outcome="example.com으로 이동 완료.",
            summary_source="openrouter",
        )

    def summarize_final_result(self, **kwargs) -> str | None:
        self.final_result_calls.append(kwargs)
        return "예시 페이지를 찾았습니다."


class _FailingStepSummarizer:
    def summarize_action(self, **kwargs) -> ActionStepSummary | None:
        del kwargs
        return None

    def summarize_final_result(self, **kwargs) -> str | None:
        del kwargs
        return None


class _BlockingStepSummarizer:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[dict[str, object]] = []

    def summarize_action(self, **kwargs) -> ActionStepSummary | None:
        self.started.set()
        self.release.wait(timeout=2)
        self.calls.append(kwargs)
        return ActionStepSummary(
            what="비동기 예시 열기",
            why="요청한 페이지로 이동하기 위한 비동기 요약입니다.",
            outcome="비동기 요약 완료.",
            summary_source="openrouter",
        )

    def summarize_final_result(self, **kwargs) -> str | None:
        del kwargs
        return "예시 페이지를 찾았습니다."


class TestActionReviewServiceSummarizer(unittest.TestCase):
    def test_build_review_and_persisted_metadata_use_step_summarizer_once(self):
        summarizer = _FakeStepSummarizer()
        review_service = ActionReviewService(
            query="예시 페이지로 이동해줘",
            step_summarizer=summarizer,
        )
        function_call = types.FunctionCall(
            name="navigate",
            args={"url": "https://example.com"},
        )

        review_metadata = review_service.build_review_metadata_for_action(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning="Open the example page first.",
            artifacts={"url": "https://example.com"},
        )
        persisted_metadata = review_service.build_persisted_action_metadata(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning="Open the example page first.",
            artifacts={"url": "https://example.com"},
        )

        self.assertEqual(review_metadata["user_visible_label"], "예시 페이지 열기")
        self.assertEqual(persisted_metadata["action_summary"], "예시 페이지 열기")
        self.assertEqual(
            persisted_metadata["reason"],
            "요청한 페이지로 이동하기 위한 단계였습니다.",
        )
        self.assertEqual(persisted_metadata["summary_source"], "openrouter")
        self.assertEqual(len(summarizer.calls), 1)

    def test_aria_snapshot_diff_is_forwarded_to_summarizer(self):
        summarizer = _FakeStepSummarizer()
        review_service = ActionReviewService(
            query="검색 버튼을 눌러줘",
            step_summarizer=summarizer,
        )

        review_service.build_review_metadata_for_action(
            step_id=1,
            function_call_index=1,
            function_call=types.FunctionCall(name="navigate", args={"url": "https://example.com"}),
            reasoning=None,
            artifacts={
                "url": "https://example.com",
                "aria_snapshot": '- button "Search"\n- link "Home"\n',
            },
        )
        review_service.build_review_metadata_for_action(
            step_id=2,
            function_call_index=1,
            function_call=types.FunctionCall(name="click_at", args={"x": 10, "y": 20}),
            reasoning=None,
            artifacts={
                "url": "https://example.com/results",
                "aria_snapshot": '- button "Search"\n- heading "Results"\n',
            },
        )

        self.assertEqual(len(summarizer.calls), 2)
        first_diff = summarizer.calls[0]["aria_diff"]
        second_diff = summarizer.calls[1]["aria_diff"]
        self.assertIsNotNone(first_diff)
        assert isinstance(first_diff, str)
        self.assertIn("initial", first_diff.lower())
        self.assertIsNotNone(second_diff)
        assert isinstance(second_diff, str)
        self.assertIn('+ - heading "Results"', second_diff)
        self.assertIn('- - link "Home"', second_diff)

    def test_build_final_result_summary_uses_step_summarizer(self):
        summarizer = _FakeStepSummarizer()
        review_service = ActionReviewService(
            query="예시 페이지를 찾아줘",
            step_summarizer=summarizer,
        )

        final_result_summary = review_service.build_final_result_summary(
            final_response=(
                "I have found the page for EXAONE 4.5 on Hugging Face."
            ),
            current_url="https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B",
        )

        self.assertEqual(final_result_summary, "예시 페이지를 찾았습니다.")
        self.assertEqual(len(summarizer.final_result_calls), 1)

    def test_build_persisted_metadata_falls_back_when_summarizer_is_unavailable(self):
        review_service = ActionReviewService(
            query="예시 페이지로 이동해줘",
            step_summarizer=_FailingStepSummarizer(),
        )
        function_call = types.FunctionCall(
            name="navigate",
            args={"url": "https://example.com"},
        )

        persisted_metadata = review_service.build_persisted_action_metadata(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning=None,
            artifacts={"url": "https://example.com"},
        )

        self.assertEqual(
            persisted_metadata["action_summary"],
            "Navigated to https://example.com",
        )
        self.assertEqual(
            persisted_metadata["reason"],
            "Needed to open https://example.com.",
        )
        self.assertEqual(persisted_metadata["summary_source"], "app_derived")

    def test_build_final_result_summary_falls_back_when_summarizer_is_unavailable(self):
        review_service = ActionReviewService(
            query="예시 페이지를 찾아줘",
            step_summarizer=_FailingStepSummarizer(),
        )

        final_result_summary = review_service.build_final_result_summary(
            final_response="예시 페이지를 찾았습니다.",
            current_url="https://example.com",
        )

        self.assertEqual(final_result_summary, "예시 페이지를 찾았습니다.")

    def test_background_action_summary_returns_fallback_before_summarizer_finishes(self):
        summarizer = _BlockingStepSummarizer()
        review_service = ActionReviewService(
            query="예시 페이지로 이동해줘",
            step_summarizer=summarizer,
            background_action_summaries=True,
        )
        updated_metadata: list[dict[str, object]] = []
        function_call = types.FunctionCall(
            name="navigate",
            args={"url": "https://example.com"},
        )

        review_metadata = review_service.build_review_metadata_for_action(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning="Open the example page first.",
            artifacts={"url": "https://example.com"},
            on_review_metadata_ready=updated_metadata.append,
        )
        persisted_metadata_before_summary = review_service.build_persisted_action_metadata(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning="Open the example page first.",
            artifacts={"url": "https://example.com"},
        )

        self.assertEqual(review_metadata["summary_source"], "app_derived")
        self.assertEqual(
            review_metadata["action_summary"],
            "Navigated to https://example.com",
        )
        self.assertEqual(persisted_metadata_before_summary["summary_source"], "app_derived")
        self.assertEqual(updated_metadata, [])
        self.assertTrue(summarizer.started.wait(timeout=1))

        summarizer.release.set()
        self.assertTrue(review_service.wait_for_pending_action_summaries(timeout=1))

        self.assertEqual(len(summarizer.calls), 1)
        self.assertEqual(len(updated_metadata), 1)
        self.assertEqual(updated_metadata[0]["summary_source"], "openrouter")
        self.assertEqual(updated_metadata[0]["action_summary"], "비동기 예시 열기")

        persisted_metadata_after_summary = review_service.build_persisted_action_metadata(
            step_id=1,
            function_call_index=1,
            function_call=function_call,
            reasoning="Open the example page first.",
            artifacts={"url": "https://example.com"},
        )
        self.assertEqual(persisted_metadata_after_summary["summary_source"], "openrouter")
        self.assertEqual(
            persisted_metadata_after_summary["action_summary"],
            "비동기 예시 열기",
        )

    def test_merge_step_review_metadata_replaces_app_derived_summary_with_llm_summary(self):
        review_service = ActionReviewService(query="예시 페이지로 이동해줘")

        merged_metadata = review_service.merge_step_review_metadata(
            existing_metadata={
                "phase_id": "phase-navigation",
                "phase_label": "Navigation",
                "phase_summary": "Open the example page.",
                "what": "Navigated to https://example.com",
                "why": "Open the example page.",
                "outcome": "Navigated to example.com",
                "action_summary": "Navigated to https://example.com",
                "reason": "Open the example page.",
                "summary_source": "app_derived",
                "user_visible_label": "Navigated to https://example.com",
                "ambiguity_flag": False,
                "review_evidence": [],
                "verification_items": [],
            },
            review_metadata={
                "what": "예시 페이지 열기",
                "why": "요청한 페이지로 이동하기 위한 단계였습니다.",
                "outcome": "example.com으로 이동 완료.",
                "action_summary": "예시 페이지 열기",
                "reason": "요청한 페이지로 이동하기 위한 단계였습니다.",
                "summary_source": "openrouter",
                "user_visible_label": "예시 페이지 열기",
                "ambiguity_flag": False,
                "review_evidence": [],
                "verification_items": [],
            },
        )

        self.assertEqual(merged_metadata["summary_source"], "openrouter")
        self.assertEqual(merged_metadata["action_summary"], "예시 페이지 열기")
        self.assertEqual(merged_metadata["user_visible_label"], "예시 페이지 열기")

    def test_merge_step_review_metadata_deduplicates_verification_items(self):
        review_service = ActionReviewService(query="예시 페이지로 이동해줘")

        merged_metadata = review_service.merge_step_review_metadata(
            existing_metadata={
                "summary_source": "app_derived",
                "ambiguity_flag": True,
                "review_evidence": ["typed_text_not_in_query"],
                "verification_items": [{"id": "v1", "message": "확인 필요"}],
            },
            review_metadata={
                "summary_source": "openrouter",
                "ambiguity_flag": True,
                "review_evidence": ["typed_text_not_in_query"],
                "verification_items": [{"id": "v1", "message": "확인 필요"}],
            },
        )

        self.assertEqual(
            merged_metadata["verification_items"],
            [{"id": "v1", "message": "확인 필요"}],
        )


class TestActionStepSummarizer(unittest.TestCase):
    def test_from_env_returns_none_when_configured_key_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            summarizer = ActionStepSummarizer.from_env()

        self.assertIsNone(summarizer)

    def test_from_env_uses_summary_endpoint_config(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "ACTION_SUMMARY_TIMEOUT_SECONDS": "6",
            },
            clear=True,
        ):
            summarizer = ActionStepSummarizer.from_env()

        if summarizer is None:
            self.fail("Expected ActionStepSummarizer.from_env() to return a summarizer")
        self.assertEqual(summarizer._model, "gpt-4o-mini")
        self.assertEqual(summarizer._summary_source, "openai")
        provider = summarizer._provider
        self.assertEqual(provider._chat_completions_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(provider._timeout_seconds, 6.0)

    @patch("agents.summarizer.step_summarizer.app_config.summary_config")
    def test_from_env_uses_endpoint_overrides(
        self,
        mock_summary_config,
    ):
        mock_summary_config.return_value = EndpointModelConfig(
            endpoint_url="https://default.test/v1",
            api_key_env="DEFAULT_API_KEY",
            model="default-model",
            token_limit_field="max_completion_tokens",
            reasoning={"effort": "low"},
        )

        with patch.dict(
            os.environ,
            {
                "ACTION_SUMMARY_MODEL": "override-model",
                "ACTION_SUMMARY_ENDPOINT_URL": "https://override.test/v1",
                "ACTION_SUMMARY_API_KEY_ENV": "OVERRIDE_API_KEY",
                "OVERRIDE_API_KEY": "test-key",
            },
            clear=True,
        ):
            summarizer = ActionStepSummarizer.from_env()

        if summarizer is None:
            self.fail("Expected ActionStepSummarizer.from_env() to use configured endpoint")
        self.assertEqual(summarizer._model, "override-model")
        self.assertEqual(summarizer._summary_source, "https://override.test/v1")
        provider = summarizer._provider
        self.assertEqual(provider._chat_completions_url, "https://override.test/v1/chat/completions")
        self.assertEqual(provider._extra_body, {"reasoning_effort": "low"})

    @patch("agents.summarizer.step_summarizer.app_config.summary_config")
    def test_from_env_infers_key_env_from_endpoint_override(
        self,
        mock_summary_config,
    ):
        mock_summary_config.return_value = EndpointModelConfig(
            endpoint_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            model="default-model",
        )

        with patch.dict(
            os.environ,
            {
                "ACTION_SUMMARY_ENDPOINT_URL": "https://openrouter.ai/api/v1",
                "OPENROUTER_API_KEY": "router-key",
            },
            clear=True,
        ):
            summarizer = ActionStepSummarizer.from_env()

        if summarizer is None:
            self.fail("Expected ActionStepSummarizer.from_env() to infer override credentials")
        self.assertEqual(summarizer._summary_source, "openrouter")
        provider = summarizer._provider
        self.assertEqual(provider._chat_completions_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(provider._api_key, "router-key")

    @patch("agents.summarizer.step_summarizer.app_config.summary_config")
    def test_from_env_uses_llm_api_key_for_custom_endpoint_override(
        self,
        mock_summary_config,
    ):
        mock_summary_config.return_value = EndpointModelConfig(
            endpoint_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            model="default-model",
        )

        with patch.dict(
            os.environ,
            {
                "ACTION_SUMMARY_ENDPOINT_URL": "https://summary-gateway.test/v1",
                "LLM_API_KEY": "gateway-key",
            },
            clear=True,
        ):
            summarizer = ActionStepSummarizer.from_env()

        if summarizer is None:
            self.fail("Expected ActionStepSummarizer.from_env() to use custom endpoint credentials")
        self.assertEqual(summarizer._summary_source, "https://summary-gateway.test/v1")
        provider = summarizer._provider
        self.assertEqual(provider._chat_completions_url, "https://summary-gateway.test/v1/chat/completions")
        self.assertEqual(provider._api_key, "gateway-key")

    @patch("agents.summarizer.step_summarizer.app_config.summary_config")
    def test_from_env_uses_configured_key_env_instead_of_other_available_credentials(
        self,
        mock_summary_config,
    ):
        mock_summary_config.return_value = EndpointModelConfig(
            endpoint_url="https://summary.test/v1",
            api_key_env="SUMMARY_API_KEY",
            model="summary-model",
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
            },
            clear=True,
        ):
            summarizer = ActionStepSummarizer.from_env()

        self.assertIsNone(summarizer)

    def test_summarize_final_result_parses_provider_response(self):
        provider = MagicMock()
        provider.generate_text.return_value = json.dumps(
            {"final_result_summary": "EXAONE 4.5 Hugging Face 페이지를 찾았습니다."},
            ensure_ascii=False,
        )
        summarizer = ActionStepSummarizer(
            provider=provider,
            model="gpt-4o-mini",
            summary_source="openai",
        )

        summary = summarizer.summarize_final_result(
            query="exaone 4.5 huggingface 찾아줘",
            final_response=(
                "I have evaluated the screenshot. "
                "I found the page for EXAONE 4.5 on Hugging Face."
            ),
            current_url="https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B",
        )

        self.assertEqual(summary, "EXAONE 4.5 Hugging Face 페이지를 찾았습니다.")

    def test_summarize_action_prompt_matches_user_language(self):
        provider = MagicMock()
        provider.generate_text.return_value = json.dumps(
            {
                "what": "Open example page",
                "why": "This checks the requested page.",
                "outcome": "The example page is open.",
            }
        )
        summarizer = ActionStepSummarizer(
            provider=provider,
            model="gpt-4o-mini",
            summary_source="openai",
        )

        summarizer.summarize_action(
            query="Open example.com",
            function_call=types.FunctionCall(
                name="navigate",
                args={"url": "https://example.com"},
            ),
            reasoning="Need to open the requested page.",
            current_url="https://example.com",
        )

        call_kwargs = provider.generate_text.call_args.kwargs
        prompt_text = call_kwargs["system_prompt"] + "\n" + call_kwargs["prompt"]
        self.assertIn("Match the user's language", prompt_text)
        self.assertNotIn("Write concise Korean text", prompt_text)
        self.assertNotIn("short Korean fields", prompt_text)

    def test_summarize_final_result_prompt_avoids_unsupported_visible_result_inference(self):
        provider = MagicMock()
        provider.generate_text.return_value = json.dumps(
            {"final_result_summary": "I could not confirm the requested result."}
        )
        summarizer = ActionStepSummarizer(
            provider=provider,
            model="gpt-4o-mini",
            summary_source="openai",
        )

        summarizer.summarize_final_result(
            query="Find the requested result",
            final_response="I am done.",
            current_url="https://example.com/results",
        )

        call_kwargs = provider.generate_text.call_args.kwargs
        prompt_text = call_kwargs["system_prompt"] + "\n" + call_kwargs["prompt"]
        self.assertIn("Match the user's language", prompt_text)
        self.assertIn("Do not infer details that are not present", prompt_text)
        self.assertIn("only from model_final_response and current_url", prompt_text)
        self.assertNotIn("visible result only", prompt_text)
