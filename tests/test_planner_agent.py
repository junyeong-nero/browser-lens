import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

import config as app_config
from agents.planner.agent import PlannerAgent, _SubgoalSchema
from core.types import Subgoal


def _mock_llm_client(subgoals_data: list[dict]) -> MagicMock:
    return _mock_llm_client_from_parts([_text_part(json.dumps(subgoals_data))])


def _text_part(text: str, *, thought: bool | None = None) -> MagicMock:
    part = MagicMock()
    part.text = text
    part.thought = thought
    return part


def _mock_llm_client_from_parts(parts: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    content = MagicMock()
    content.parts = parts
    candidate = MagicMock()
    candidate.content = content
    response = MagicMock()
    response.candidates = [candidate]
    client.generate_content.return_value = response
    return client


SAMPLE_PLAN = [
    {"description": "Open Google", "reasoning": "Need a search entry point"},
    {"description": "Search for Python", "reasoning": "The query asks about Python"},
]

SAMPLE_PLAN_WITH_IDS = [
    {"id": 99, "description": "Open Google", "reasoning": "Need a search entry point"},
    {"id": 100, "description": "Search for Python", "reasoning": "The query asks about Python"},
]


class TestPlannerAgentPlan:
    def test_returns_list_of_subgoals(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="search Python on Google", llm_client=client)

        subgoals = planner.plan()

        assert len(subgoals) == 2
        assert all(isinstance(sg, Subgoal) for sg in subgoals)

    def test_subgoal_ids_start_at_one(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert subgoals[0].id == 1
        assert subgoals[1].id == 2

    def test_subgoal_fields(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert subgoals[0].description == "Open Google"
        assert subgoals[0].reasoning == "Need a search entry point"
        assert subgoals[0].status == "pending"

    def test_calls_llm_once(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        planner.plan()
        assert client.generate_content.call_count == 1

    def test_uses_json_response_mime_type(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        planner.plan()
        call_kwargs = client.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
        assert config.response_mime_type == "application/json"

    def test_planner_temperature_can_be_overridden_by_config(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        model_config = app_config.EndpointModelConfig(
            endpoint_url="https://api.openai.com/v1",
            model="gpt-5.4-mini",
            temperature=0.8,
        )

        with patch(
            "agents.planner.agent.app_config.planner_config",
            return_value=model_config,
        ):
            planner = PlannerAgent(query="test", llm_client=client)
            planner.plan()

        call_kwargs = client.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
        assert config.temperature == 0.8

    def test_response_schema_does_not_require_model_supplied_ids(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        planner.plan()
        call_kwargs = client.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
        schema = config.response_schema
        schema_item = getattr(schema, "__args__", [None])[0]

        assert "id" not in _SubgoalSchema.model_fields
        assert "reasoning" in _SubgoalSchema.model_fields
        assert "success_criteria" not in _SubgoalSchema.model_fields
        assert schema_item is _SubgoalSchema

    def test_uses_system_instruction_for_planning_prompt(self):
        client = _mock_llm_client(SAMPLE_PLAN)
        planner = PlannerAgent(query="test", llm_client=client)
        planner.plan()

        call_kwargs = client.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]

        system_text = "\n".join(
            part.text or "" for part in config.system_instruction.parts or []
        )
        user_text = "\n".join(part.text or "" for part in contents[0].parts or [])

        assert "Plan-and-Act web browser automation system" in system_text
        assert "Respond ONLY with JSON" in system_text
        assert "Do not name a search provider" in system_text
        assert "browser's default search entry point" in system_text
        assert "search tool" not in system_text
        assert user_text == "User query:\ntest"

    def test_invalid_json_no_array_returns_empty_list(self):
        client = MagicMock()
        part = MagicMock()
        part.text = "not valid json at all"
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        response = MagicMock()
        response.candidates = [candidate]
        client.generate_content.return_value = response

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert subgoals == []

    def test_accepts_object_wrapped_array(self):
        client = MagicMock()
        part = MagicMock()
        part.text = json.dumps({"subgoals": SAMPLE_PLAN})
        part.thought = None
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        response = MagicMock()
        response.candidates = [candidate]
        client.generate_content.return_value = response

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert len(subgoals) == 2
        assert subgoals[0].description == "Open Google"

    def test_accepts_markdown_fenced_json(self):
        client = MagicMock()
        part = MagicMock()
        part.text = "```json\n" + json.dumps(SAMPLE_PLAN) + "\n```"
        part.thought = None
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        response = MagicMock()
        response.candidates = [candidate]
        client.generate_content.return_value = response

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert len(subgoals) == 2

    def test_skips_reasoning_thought_part(self):
        client = _mock_llm_client_from_parts(
            [
                _text_part(
                    "Let me think... I should plan this carefully.",
                    thought=True,
                ),
                _text_part(json.dumps(SAMPLE_PLAN)),
            ]
        )

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert len(subgoals) == 2

    def test_accepts_multi_part_json_text_response(self):
        raw_plan = json.dumps(SAMPLE_PLAN)
        split_at = raw_plan.index("reasoning")
        client = _mock_llm_client_from_parts(
            [
                _text_part(raw_plan[:split_at]),
                _text_part(raw_plan[split_at:]),
            ]
        )

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()

        assert len(subgoals) == 2
        assert subgoals[0].description == "Open Google"

    def test_accepts_thought_plus_multi_part_json_text_response(self):
        raw_plan = json.dumps(SAMPLE_PLAN)
        split_at = raw_plan.index("Search for Python")
        client = _mock_llm_client_from_parts(
            [
                _text_part("internal chain of thought", thought=True),
                _text_part(raw_plan[:split_at]),
                _text_part(raw_plan[split_at:]),
            ]
        )

        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()

        assert len(subgoals) == 2
        assert subgoals[1].description == "Search for Python"

    def test_ignores_model_supplied_ids_and_assigns_runtime_ids(self):
        client = _mock_llm_client(SAMPLE_PLAN_WITH_IDS)
        planner = PlannerAgent(query="test", llm_client=client)

        subgoals = planner.plan()

        assert [subgoal.id for subgoal in subgoals] == [1, 2]

    def test_empty_plan(self):
        client = _mock_llm_client([])
        planner = PlannerAgent(query="test", llm_client=client)
        subgoals = planner.plan()
        assert subgoals == []


class TestPlannerAgentReplan:
    def test_replan_returns_subgoals(self):
        new_plan = [
            {
                "description": "Try the site's fallback path",
                "reasoning": "Direct path was blocked",
            },
        ]
        client = _mock_llm_client(new_plan)
        planner = PlannerAgent(query="search Python", llm_client=client)

        history = [
            (
                Subgoal(id=1, description="Open site", reasoning="entry"),
                "done",
                "STEP_DONE: opened",
            ),
            (
                Subgoal(id=2, description="Search on Google", reasoning="find"),
                "failed",
                "STEP_FAILED: Page not responding",
            ),
        ]

        subgoals = planner.replan(history=history, latest_url="https://example.com")

        assert len(subgoals) == 1
        assert subgoals[0].id == 3
        assert subgoals[0].description == "Try the site's fallback path"
        assert subgoals[0].reasoning == "Direct path was blocked"

    def test_replan_invalid_json_raises_parse_error(self):
        events = []
        client = _mock_llm_client_from_parts([_text_part("not valid json at all")])
        planner = PlannerAgent(
            query="search Python",
            llm_client=client,
            event_sink=events.append,
        )
        history = [
            (
                Subgoal(id=1, description="Open site", reasoning="entry"),
                "done",
                "STEP_DONE: opened",
            ),
        ]

        with pytest.raises(RuntimeError, match="response is not valid JSON"):
            planner.replan(history=history, latest_url="https://example.com")

        event_types = [event["type"] for event in events]
        assert "planner_parse_error" in event_types
        assert "planner_replanned" not in event_types

    def test_replan_accepts_empty_object_as_empty_plan(self):
        events = []
        client = _mock_llm_client_from_parts([_text_part("{}")])
        planner = PlannerAgent(
            query="search Python",
            llm_client=client,
            event_sink=events.append,
        )
        history = [
            (
                Subgoal(id=1, description="Open site", reasoning="entry"),
                "done",
                "STEP_DONE: opened",
            ),
        ]

        subgoals = planner.replan(history=history, latest_url="https://example.com")

        assert subgoals == []
        event_types = [event["type"] for event in events]
        assert "planner_parse_error" not in event_types
        assert "planner_replanned" in event_types

    def test_replan_start_id_after_history(self):
        new_plan = [
            {"description": "Fallback step", "reasoning": "Need another path"},
        ]
        client = _mock_llm_client(new_plan)
        planner = PlannerAgent(query="test", llm_client=client)

        history = [
            (
                Subgoal(id=5, description="Finished step", reasoning="done"),
                "done",
                "STEP_DONE: ok",
            )
        ]
        subgoals = planner.replan(history=history)
        assert subgoals[0].id == 6

    def test_replan_completed_event_includes_last_step_id(self):
        events = []
        client = _mock_llm_client(
            [{"description": "Fallback step", "reasoning": "Need another path"}]
        )
        planner = PlannerAgent(query="test", llm_client=client, event_sink=events.append)

        history = [
            (
                Subgoal(id=5, description="Failed step", reasoning="blocked"),
                "failed",
                "Timeout",
            )
        ]
        planner.replan(history=history)

        replanned = next(event for event in events if event["type"] == "planner_replanned")
        assert replanned["last_step_id"] == 5


    def test_replan_prompt_includes_history_and_latest_url(self):
        client = _mock_llm_client(
            [{"description": "Fallback step", "reasoning": "Need another path"}]
        )
        planner = PlannerAgent(query="original query", llm_client=client)
        done = Subgoal(id=1, description="Done step", reasoning="entry")
        failed = Subgoal(id=2, description="Failed step", reasoning="blocked")
        remaining = Subgoal(
            id=3,
            description="Summarize the result",
            reasoning="The user needs the final answer.",
        )

        planner.replan(
            history=[
                (done, "done", "STEP_DONE: ok"),
                (failed, "failed", "STEP_FAILED: Timeout"),
            ],
            latest_url="https://example.com/current",
            remaining_plan=[remaining],
        )

        call_kwargs = client.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]
        user_text = "\n".join(part.text or "" for part in contents[0].parts or [])
        assert "Original query:\noriginal query" in user_text
        assert "Latest browser URL: https://example.com/current" in user_text
        assert "Execution history so far" in user_text
        assert "STEP_DONE: ok" in user_text
        assert "STEP_FAILED: Timeout" in user_text
        assert "Prior remaining plan before replanning" in user_text
        assert "[3] Summarize the result" in user_text

    def test_replan_uses_replan_system_instruction(self):
        client = _mock_llm_client(
            [{"description": "Fallback step", "reasoning": "Need another path"}]
        )
        planner = PlannerAgent(query="test", llm_client=client)

        planner.replan(
            history=[
                (
                    Subgoal(id=5, description="Failed step", reasoning="blocked"),
                    "failed",
                    "Timeout",
                )
            ]
        )

        call_kwargs = client.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
        system_text = "\n".join(
            part.text or "" for part in config.system_instruction.parts or []
        )

        assert "Executor just finished a step" in system_text
        assert "avoid repeating the failed path" in system_text
        assert "current browser URL" in system_text
        assert "current browser state" not in system_text
        assert "Do not name a search provider" in system_text
        assert "browser's default search entry point" in system_text
        assert "search tool" not in system_text
