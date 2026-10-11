import base64
import json
import unittest
from unittest.mock import patch

from google.genai import types

from llm.provider.responses_http import ResponsesProvider


class _FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def _provider(**kwargs) -> ResponsesProvider:
    defaults = dict(
        api_key="endpoint-key",
        endpoint_url="https://api.openai.com/v1",
        timeout_seconds=3,
    )
    defaults.update(kwargs)
    return ResponsesProvider(**defaults)


@patch("llm.provider.responses_http.ChatCompletionsProvider._build_ssl_context", return_value=None)
@patch("llm.provider.responses_http.request.urlopen")
class TestResponsesProvider(unittest.TestCase):
    def _sent_body(self, mock_urlopen) -> dict:
        http_request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            http_request.full_url, "https://api.openai.com/v1/responses"
        )
        return json.loads(http_request.data.decode("utf-8"))

    def test_generate_content_builds_responses_request(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"output":[{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"hi"}]}]}'
        )

        def get_horoscope(sign: str) -> str:
            """Get today's horoscope for an astrological sign."""
            return sign

        provider = _provider()
        decl = provider.build_function_declaration(get_horoscope)

        provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])],
            config=types.GenerateContentConfig(
                system_instruction=types.Content(
                    role="system", parts=[types.Part(text="be brief")]
                ),
                max_output_tokens=256,
                tools=[types.Tool(function_declarations=[decl])],
            ),
        )

        body = self._sent_body(mock_urlopen)
        self.assertEqual(body["model"], "gpt-5.5")
        self.assertNotIn("messages", body)
        self.assertNotIn("instructions", body)
        self.assertEqual(body["max_output_tokens"], 256)
        self.assertEqual(
            body["input"],
            [
                {"role": "system", "content": [{"type": "input_text", "text": "be brief"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
            ],
        )
        self.assertEqual(
            body["tools"],
            [
                {
                    "type": "function",
                    "name": "get_horoscope",
                    "description": "Get today's horoscope for an astrological sign.",
                    "parameters": {
                        "type": "object",
                        "properties": {"sign": {"type": "string"}},
                        "required": ["sign"],
                    },
                }
            ],
        )

    def test_function_call_history_maps_to_input_items(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider()

        contents = [
            types.Content(role="user", parts=[types.Part(text="weather?")]),
            types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            id="call_1", name="get_weather", args={"city": "Seoul"}
                        )
                    )
                ],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="call_1", name="get_weather", response={"temp": 20}
                        )
                    )
                ],
            ),
        ]

        provider.generate_content(
            model="gpt-5.5",
            contents=contents,
            config=types.GenerateContentConfig(),
        )

        body = self._sent_body(mock_urlopen)
        call_item = body["input"][1]
        self.assertEqual(call_item["type"], "function_call")
        self.assertEqual(call_item["call_id"], "call_1")
        self.assertEqual(call_item["name"], "get_weather")
        self.assertEqual(json.loads(call_item["arguments"]), {"city": "Seoul"})

        output_item = body["input"][2]
        self.assertEqual(output_item["type"], "function_call_output")
        self.assertEqual(output_item["call_id"], "call_1")
        self.assertEqual(json.loads(output_item["output"]), {"temp": 20})

    def test_assistant_text_with_tool_call_history_uses_output_item_shape(
        self,
        mock_urlopen,
        _ssl,
    ):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider()

        contents = [
            types.Content(role="user", parts=[types.Part(text="open filters")]),
            types.Content(
                role="model",
                parts=[
                    types.Part(text="I will click the filters button."),
                    types.Part(
                        function_call=types.FunctionCall(
                            id="call_2", name="click_by_ref", args={"ref": 10}
                        )
                    ),
                ],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="call_2",
                            name="click_by_ref",
                            response={"url": "https://example.test/filters"},
                        )
                    )
                ],
            ),
        ]

        provider.generate_content(
            model="gpt-5.5",
            contents=contents,
            config=types.GenerateContentConfig(),
        )

        body = self._sent_body(mock_urlopen)
        assistant_message = body["input"][1]
        self.assertEqual(assistant_message["type"], "message")
        self.assertEqual(assistant_message["role"], "assistant")
        self.assertEqual(assistant_message["status"], "completed")
        self.assertNotIn("id", assistant_message)
        self.assertEqual(
            assistant_message["content"],
            [
                {
                    "type": "output_text",
                    "text": "I will click the filters button.",
                    "annotations": [],
                }
            ],
        )

        call_item = body["input"][2]
        self.assertEqual(call_item["type"], "function_call")
        self.assertEqual(call_item["call_id"], "call_2")
        self.assertEqual(call_item["status"], "completed")
        self.assertEqual(call_item["name"], "click_by_ref")
        self.assertEqual(json.loads(call_item["arguments"]), {"ref": 10})
        self.assertNotIn("id", call_item)

        output_item = body["input"][3]
        self.assertEqual(output_item["type"], "function_call_output")
        self.assertEqual(output_item["call_id"], "call_2")
        self.assertEqual(output_item["status"], "completed")
        self.assertEqual(
            json.loads(output_item["output"]),
            {"url": "https://example.test/filters"},
        )
        self.assertNotIn("id", output_item)
        for item in body["input"]:
            self.assertFalse(item.get("id", "").startswith("call_"))

    def test_generate_content_parses_output(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse(
            json.dumps(
                {
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [
                                {"type": "summary_text", "text": "thinking"}
                            ],
                        },
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "answer"}],
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_9",
                            "name": "do_thing",
                            "arguments": '{"x": 1}',
                        },
                    ]
                }
            )
        )
        provider = _provider()

        response = provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(),
        )

        parts = response.candidates[0].content.parts
        self.assertEqual(parts[0].text, "thinking")
        self.assertTrue(parts[0].thought)
        self.assertEqual(parts[1].text, "answer")
        self.assertEqual(parts[2].function_call.name, "do_thing")
        self.assertEqual(parts[2].function_call.id, "call_9")
        self.assertEqual(parts[2].function_call.args, {"x": 1})

    def test_omits_temperature_when_unsupported(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider(supports_temperature=False)

        provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(temperature=0.3),
        )

        body = self._sent_body(mock_urlopen)
        self.assertNotIn("temperature", body)

    def test_omits_top_p_when_temperature_unsupported(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider(supports_temperature=False)

        provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(temperature=1, top_p=0.95),
        )

        body = self._sent_body(mock_urlopen)
        self.assertNotIn("top_p", body)

    def test_includes_top_p_when_temperature_supported(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider(supports_temperature=True)

        provider.generate_content(
            model="gpt-4o-mini",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(top_p=0.95),
        )

        body = self._sent_body(mock_urlopen)
        self.assertEqual(body["top_p"], 0.95)

    def test_reasoning_effort_in_body(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider(reasoning_effort="medium")

        provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(),
        )

        body = self._sent_body(mock_urlopen)
        self.assertEqual(body["reasoning"], {"effort": "medium"})

    def test_reasoning_summary_requested_when_thoughts_enabled(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider(reasoning_effort="medium")

        provider.generate_content(
            model="gpt-5.5",
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=True),
            ),
        )

        body = self._sent_body(mock_urlopen)
        self.assertEqual(body["reasoning"], {"effort": "medium", "summary": "auto"})

    def test_image_input_maps_to_input_image(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse('{"output":[]}')
        provider = _provider()
        png = base64.b64encode(b"png").decode("ascii")

        provider.generate_content(
            model="gpt-5.5",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text="look"),
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/png", data=b"png"
                            )
                        ),
                    ],
                )
            ],
            config=types.GenerateContentConfig(),
        )

        body = self._sent_body(mock_urlopen)
        content = body["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "look"})
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["image_url"], f"data:image/png;base64,{png}")

    def test_generate_text_flattens_json_schema_format(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"output":[{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"{}"}]}]}'
        )
        provider = _provider()

        provider.generate_text(
            model="gpt-4o-mini",
            prompt="summarize",
            max_tokens=64,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "summary",
                    "strict": True,
                    "schema": {"type": "object", "properties": {}},
                },
            },
        )

        body = self._sent_body(mock_urlopen)
        self.assertEqual(
            body["text"]["format"],
            {
                "type": "json_schema",
                "name": "summary",
                "strict": True,
                "schema": {"type": "object", "properties": {}},
            },
        )

    def test_generate_text_returns_output_text(self, mock_urlopen, _ssl):
        mock_urlopen.return_value = _FakeHTTPResponse(
            '{"output":[{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"summary text"}]}]}'
        )
        provider = _provider()

        result = provider.generate_text(
            model="gpt-4o-mini",
            prompt="summarize",
            system_prompt="be terse",
            max_tokens=64,
        )

        self.assertEqual(result, "summary text")
        body = self._sent_body(mock_urlopen)
        self.assertNotIn("instructions", body)
        self.assertEqual(
            body["input"],
            [
                {"role": "system", "content": [{"type": "input_text", "text": "be terse"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "summarize"}]},
            ],
        )


class TestResponsesProviderSelection(unittest.TestCase):
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_client_uses_responses_provider_by_default(self):
        from config import EndpointModelConfig, ReasoningConfig
        from llm.client import LLMClient

        model_config = EndpointModelConfig(
            model="gpt-5.5",
            endpoint_url="https://api.openai.com/v1",
            reasoning=ReasoningConfig(effort="medium"),
        )

        client = LLMClient.from_model_config(model_config)

        self.assertIsInstance(client._provider, ResponsesProvider)
        self.assertEqual(client._provider._reasoning_effort, "medium")
        self.assertFalse(client._provider._supports_temperature)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_client_uses_chat_provider_when_configured(self):
        from config import EndpointModelConfig
        from llm.client import LLMClient
        from llm.provider.chat_completion_http import ChatCompletionsProvider

        model_config = EndpointModelConfig(
            model="gpt-4o-mini",
            endpoint_url="https://api.openai.com/v1",
            api="chat",
        )

        client = LLMClient.from_model_config(model_config)

        self.assertIsInstance(client._provider, ChatCompletionsProvider)
        self.assertNotIsInstance(client._provider, ResponsesProvider)


if __name__ == "__main__":
    unittest.main()
