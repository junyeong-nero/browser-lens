import os
import unittest
from unittest.mock import MagicMock, patch

from config import EndpointModelConfig
from llm.client import EmptyResponseError, LLMClient, LLMInterrupted
from llm.provider.chat_completion_http import ChatCompletionsProvider


class TestLLMClient(unittest.TestCase):
    @patch("llm.client.time.sleep")
    def test_generate_content_retries_on_empty_response(self, mock_sleep):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        empty_response = MagicMock(candidates=[])
        success_response = MagicMock(candidates=[MagicMock()])
        provider.generate_content.side_effect = [empty_response, success_response]
        client = LLMClient(provider=provider, max_retries=3, base_delay_s=1)

        response = client.generate_content(
            model="test-model",
            contents=[],
            config=MagicMock(),
        )

        self.assertIs(response, success_response)
        self.assertEqual(provider.generate_content.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("llm.client.time.sleep")
    def test_generate_content_raises_after_persistent_empty_responses(self, mock_sleep):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        provider.generate_content.return_value = MagicMock(candidates=[])
        client = LLMClient(provider=provider, max_retries=3, base_delay_s=1)

        with self.assertRaises(EmptyResponseError):
            client.generate_content(
                model="test-model",
                contents=[],
                config=MagicMock(),
            )

        self.assertEqual(provider.generate_content.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("llm.client.time.sleep")
    def test_generate_content_retries_transport_errors(self, mock_sleep):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        success_response = MagicMock(candidates=[MagicMock()])
        provider.generate_content.side_effect = [RuntimeError("boom"), success_response]
        client = LLMClient(provider=provider, max_retries=3, base_delay_s=1)

        response = client.generate_content(
            model="test-model",
            contents=[],
            config=MagicMock(),
        )

        self.assertIs(response, success_response)
        self.assertEqual(provider.generate_content.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("llm.client.time.sleep")
    def test_generate_content_does_not_retry_nonretryable_http_status(self, mock_sleep):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        error = RuntimeError("endpoint request failed with HTTP 401: invalid api key")
        provider.generate_content.side_effect = error
        client = LLMClient(provider=provider, max_retries=3, base_delay_s=1)

        with self.assertRaises(RuntimeError) as raised:
            client.generate_content(
                model="test-model",
                contents=[],
                config=MagicMock(),
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(provider.generate_content.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("llm.client.time.sleep")
    def test_generate_content_retries_retryable_http_status(self, mock_sleep):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        success_response = MagicMock(candidates=[MagicMock()])
        provider.generate_content.side_effect = [
            RuntimeError("endpoint request failed with HTTP 429: rate limit exceeded"),
            success_response,
        ]
        client = LLMClient(provider=provider, max_retries=3, base_delay_s=1)

        response = client.generate_content(
            model="test-model",
            contents=[],
            config=MagicMock(),
        )

        self.assertIs(response, success_response)
        self.assertEqual(provider.generate_content.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("llm.client.time.monotonic", side_effect=[0.0, 0.0])
    @patch("llm.client.time.sleep")
    def test_generate_content_interrupts_retry_backoff(
        self,
        mock_sleep,
        _mock_monotonic,
    ):
        provider = MagicMock()
        provider.name = "endpoint"
        provider.supports_image_inputs = True
        provider.generate_content.side_effect = RuntimeError("temporarily unavailable")
        interrupt_checker = MagicMock(side_effect=[False, False, True])
        client = LLMClient(
            provider=provider,
            max_retries=3,
            base_delay_s=1,
            interrupt_checker=interrupt_checker,
        )

        with self.assertRaises(LLMInterrupted):
            client.generate_content(
                model="test-model",
                contents=[],
                config=MagicMock(),
            )

        self.assertEqual(provider.generate_content.call_count, 1)
        interrupt_checker.assert_called()
        mock_sleep.assert_called_once_with(0.2)

    def test_from_model_config_builds_endpoint_provider(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://example.test/v1",
            api="chat",
            api_key_env="TEST_API_KEY",
            model="test-model",
            token_limit_field="max_tokens",
            headers={"X-Test": "yes"},
            extra_body={"custom": {"flag": True}},
            reasoning={"effort": "low"},
            supports_image_inputs=False,
        )

        with patch.dict(
            os.environ,
            {"TEST_API_KEY": "test-key", "LLM_TIMEOUT_SECONDS": "7.5"},
            clear=True,
        ):
            client = LLMClient.from_model_config(model_config)

        provider = client._provider
        self.assertEqual(client.provider_name, "https://example.test/v1")
        self.assertFalse(client.supports_image_inputs)
        self.assertFalse(client.supports_reasoning_summaries)
        self.assertEqual(provider._chat_completions_url, "https://example.test/v1/chat/completions")
        self.assertEqual(provider._timeout_seconds, 7.5)
        self.assertEqual(provider._token_limit_field, "max_tokens")
        self.assertEqual(provider._extra_headers, {"X-Test": "yes"})
        self.assertEqual(
            provider._extra_body,
            {"custom": {"flag": True}, "reasoning_effort": "low"},
        )

    def test_from_model_config_requires_configured_api_key_env(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://example.test/v1",
            api_key_env="MISSING_API_KEY",
            model="test-model",
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MISSING_API_KEY"):
                LLMClient.from_model_config(model_config)

    def test_from_model_config_uses_default_timeout(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            client = LLMClient.from_model_config(model_config)

        self.assertEqual(client._provider._timeout_seconds, 120.0)
        self.assertTrue(client.supports_reasoning_summaries)

    def test_from_model_config_preserves_openai_gpt5_temperature_guard(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://api.openai.com/v1",
            model="gpt-5.4-mini",
            temperature=0.2,
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            client = LLMClient.from_model_config(model_config)

        self.assertFalse(client._provider._supports_temperature)

    def test_from_model_config_sends_explicit_temperature_for_openrouter(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.4-mini",
            temperature=0.2,
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            client = LLMClient.from_model_config(model_config)

        self.assertTrue(client._provider._supports_temperature)

    def test_from_model_config_ignores_action_summary_timeout(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://example.test/v1",
            api_key_env="TEST_API_KEY",
            model="test-model",
        )

        with patch.dict(
            os.environ,
            {
                "TEST_API_KEY": "test-key",
                "ACTION_SUMMARY_TIMEOUT_SECONDS": "7.5",
            },
            clear=True,
        ):
            client = LLMClient.from_model_config(model_config)

        self.assertEqual(client._provider._timeout_seconds, 120.0)

    def test_from_model_config_rejects_invalid_timeout(self):
        model_config = EndpointModelConfig(
            endpoint_url="https://example.test/v1",
            api_key_env="TEST_API_KEY",
            model="test-model",
        )

        with patch.dict(
            os.environ,
            {
                "TEST_API_KEY": "test-key",
                "LLM_TIMEOUT_SECONDS": "not-a-number",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "LLM_TIMEOUT_SECONDS"):
                LLMClient.from_model_config(model_config)


class _FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class TestChatCompletionsProvider(unittest.TestCase):
    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_text_posts_chat_completion_payload(self, _mock_ssl, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":"  hello  "}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
            token_limit_field="max_completion_tokens",
        )

        text = provider.generate_text(
            model="model-a",
            prompt="user prompt",
            system_prompt="system prompt",
            max_tokens=42,
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        self.assertEqual(text, "hello")
        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertEqual(http_request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(http_request.headers["Authorization"], "Bearer key")
        self.assertEqual(body["model"], "model-a")
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        )
        self.assertEqual(body["max_completion_tokens"], 42)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["temperature"], 0.5)
        self.assertEqual(body["response_format"], {"type": "json_object"})

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_content_uses_configured_token_limit_field(self, _mock_ssl, mock_urlopen):
        from google.genai import types

        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":"answer"}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
            token_limit_field="max_tokens",
        )

        provider.generate_content(
            model="router-model",
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])],
            config=types.GenerateContentConfig(max_output_tokens=123),
        )

        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 123)
        self.assertNotIn("max_completion_tokens", body)

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_content_translates_supported_config_fields(
        self,
        _mock_ssl,
        mock_urlopen,
    ):
        from google.genai import types

        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":"answer"}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="key",
            endpoint_url="https://example.test/v1",
            timeout_seconds=3,
        )

        provider.generate_content(
            model="gpt-5-mini",
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])],
            config=types.GenerateContentConfig(
                temperature=0.25,
                top_p=0.9,
                top_k=40,
                max_output_tokens=123,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(include_thoughts=True),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertEqual(body["temperature"], 0.25)
        self.assertEqual(body["top_p"], 0.9)
        self.assertEqual(body["max_completion_tokens"], 123)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("top_k", body)
        self.assertNotIn("thinking_config", body)
        self.assertNotIn("automatic_function_calling", body)

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_text_includes_configured_headers(self, _mock_ssl, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":[{"type":"text","text":"part one"},{"type":"text","text":"part two"}]}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="router-key",
            endpoint_url="https://router.test/api/v1/",
            headers={
                "HTTP-Referer": "https://app.test",
                "X-Title": "Tiny Browser Agent",
            },
        )

        text = provider.generate_text(model="router-model", prompt="hello")

        self.assertEqual(text, "part one\npart two")
        http_request = mock_urlopen.call_args.args[0]
        self.assertEqual(http_request.full_url, "https://router.test/api/v1/chat/completions")
        self.assertEqual(http_request.headers["Authorization"], "Bearer router-key")
        self.assertEqual(http_request.headers["Http-referer"], "https://app.test")
        self.assertEqual(http_request.headers["X-title"], "Tiny Browser Agent")

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_content_sends_function_response_screenshot_as_image(
        self,
        _mock_ssl,
        mock_urlopen,
    ):
        from google.genai import types

        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":"next"}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="router-key",
            endpoint_url="https://router.test/api/v1/",
        )

        provider.generate_content(
            model="vision-model",
            contents=[
                types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id="call-1",
                                name="open_web_browser",
                                args={},
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
                                name="open_web_browser",
                                response={
                                    "url": "https://example.com",
                                    "coordinate_system": "viewport_css_pixels",
                                    "coordinate_instruction": (
                                        "For coordinate tools, use viewport CSS pixel coordinates "
                                        "matching the current screenshot."
                                    ),
                                    "viewport_width": 1470,
                                    "viewport_height": 836,
                                },
                                parts=[
                                    types.FunctionResponsePart(
                                        inline_data=types.FunctionResponseBlob(
                                            mime_type="image/png",
                                            data=b"png",
                                        )
                                    )
                                ],
                            )
                        )
                    ],
                ),
            ],
            config=types.GenerateContentConfig(),
        )

        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertEqual(body["messages"][1]["role"], "tool")
        self.assertEqual(body["messages"][1]["tool_call_id"], "call-1")
        observation = body["messages"][2]
        self.assertEqual(observation["role"], "user")
        self.assertEqual(observation["content"][0]["type"], "text")
        self.assertIn(
            "viewport_css_pixels",
            observation["content"][0]["text"],
        )
        self.assertIn(
            "viewport size is 1470x836 CSS pixels",
            observation["content"][0]["text"],
        )
        self.assertIn(
            "Use x from 0 to 1469 and y from 0 to 835",
            observation["content"][0]["text"],
        )
        self.assertEqual(observation["content"][1]["type"], "image_url")
        self.assertEqual(
            observation["content"][1]["image_url"]["url"],
            "data:image/png;base64,cG5n",
        )

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_content_includes_extra_body(self, _mock_ssl, mock_urlopen):
        from google.genai import types

        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"reasoning_content":"think","content":"answer"}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="endpoint-key",
            endpoint_url="https://integrate.test/v1",
            extra_body={
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": "high",
                }
            },
            token_limit_field="max_tokens",
            timeout_seconds=3,
        )

        response = provider.generate_content(
            model="deepseek-ai/deepseek-v4-flash",
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])],
            config=types.GenerateContentConfig(
                temperature=1,
                top_p=0.95,
                max_output_tokens=16384,
            ),
        )

        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertEqual(http_request.full_url, "https://integrate.test/v1/chat/completions")
        self.assertEqual(http_request.headers["Authorization"], "Bearer endpoint-key")
        self.assertEqual(body["model"], "deepseek-ai/deepseek-v4-flash")
        self.assertEqual(body["temperature"], 1)
        self.assertEqual(body["top_p"], 0.95)
        self.assertEqual(body["max_tokens"], 16384)
        self.assertEqual(
            body["chat_template_kwargs"],
            {"thinking": True, "reasoning_effort": "high"},
        )

        parts = response.candidates[0].content.parts
        self.assertEqual(parts[0].text, "think")
        self.assertTrue(parts[0].thought)
        self.assertEqual(parts[1].text, "answer")

    @patch("llm.provider.chat_completion_http.request.urlopen")
    @patch("llm.provider.chat_completion_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
    def test_generate_content_omits_temperature_when_unsupported(self, _mock_ssl, mock_urlopen):
        from google.genai import types

        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"choices":[{"message":{"content":"answer"}}]}'
        )
        provider = ChatCompletionsProvider(
            api_key="endpoint-key",
            endpoint_url="https://api.openai.com/v1",
            supports_temperature=False,
            timeout_seconds=3,
        )

        provider.generate_content(
            model="gpt-5.4-mini",
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])],
            config=types.GenerateContentConfig(temperature=0.3),
        )

        http_request = mock_urlopen.call_args.args[0]
        body = __import__("json").loads(http_request.data.decode("utf-8"))
        self.assertNotIn("temperature", body)


if __name__ == "__main__":
    unittest.main()
