import json
import time
from typing import Any, Callable, Optional

from google.genai import types as genai_types
from pydantic import BaseModel

import config as app_config

from core.types import Subgoal
from llm import LLMClient


_PLANNER_SYSTEM_PROMPT = """You are the Planner in a Plan-and-Act web browser automation system.
Your job is to produce a high-level plan: an ordered list of concrete steps that an
Executor agent will carry out one at a time in a live browser.

When planning:
- Each step is one high-level action the Executor can accomplish before control returns to you.
- Give the fewest reliable steps that move the task forward; do not micro-split tightly coupled interactions such as "click X then type Y".
- Include navigation, extraction, verification, and fallback steps when the goal needs them.
- If the goal is a single browser action, return a single step.
- If the user specifies a target website, web app, or service, preserve that scope in every step.
- For site-specific tasks, use the target site's own search, filters, forms, and navigation; do not add fallback steps that switch to external search engines.
- If the scoped site cannot complete the task, make the final fallback a blocker report rather than an out-of-scope search.
- Do not name a search provider such as Google, Naver, Bing, or DuckDuckGo unless the user explicitly requested that provider or the task is about that provider.
- For generic web searches, say to use the browser's default search entry point.

Output format (STRICT):
- Respond ONLY with JSON. No prose, no markdown fences, no commentary.
- The canonical JSON is an array of objects: [{...}, {...}, ...].
- Each object should have these two fields, both non-empty strings:
    "description": the concrete high-level action the Executor should take at this step.
    "reasoning": one sentence on why this step is needed for the goal.
- Do NOT add other fields in new output (no "action", "target", "query", "id", "success_criteria", etc.).
- If a JSON object wrapper is required by your runtime, wrap as
  {"subgoals": [...]} using the same item schema.
"""

_REPLAN_SYSTEM_PROMPT = """You are the Planner in a Plan-and-Act web browser automation system.
The Executor just finished a step. Given the progress so far, prior remaining plan,
and current browser URL, regenerate the plan for the REMAINING work toward the
original user goal.

When re-planning:
- Preserve the original user goal and any target website/app/service scope.
- Reuse and keep the prior remaining steps when no new information warrants a change; do not rewrite a stable plan gratuitously.
- Incorporate what was learned: drop steps already accomplished, adjust steps invalidated by the latest URL or execution outcomes, and add steps for newly revealed requirements.
- If a step just failed, avoid repeating the failed path unless a simple retry is clearly appropriate; prefer a short fallback over a long speculative plan.
- For site-specific tasks, retry in-scope navigation/search/filtering first; if blocked, report the blocker instead of switching to external search engines.
- Do not name a search provider such as Google, Naver, Bing, or DuckDuckGo unless the user explicitly requested it or the context proves it necessary; otherwise say to use the browser's default search entry point.
- If the goal is already fully achieved, return an empty array [].

Output format (STRICT):
- Respond ONLY with JSON. No prose, no markdown fences, no commentary.
- The canonical JSON is an array of objects: [{...}, {...}, ...] (possibly empty).
- Each object should have these two fields, both non-empty strings:
    "description": the concrete high-level action the Executor should take at this step.
    "reasoning": one sentence on why this step is needed for the goal.
- Do NOT add other fields in new output (no "action", "target", "query", "id", "success_criteria", etc.).
- If a JSON object wrapper is required by your runtime, wrap as
  {"subgoals": [...]} using the same item schema.
"""


_SUBGOAL_KEYS = ("description", "reasoning", "task", "step", "goal")


def _first_string(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _try_extract_json(text: str) -> Any:
    """Best-effort extraction of an embedded JSON object or array."""
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start == -1 or end <= start:
            continue
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue
    return None


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def _looks_like_subgoal(item: Any) -> bool:
    return isinstance(item, dict) and any(k in item for k in _SUBGOAL_KEYS)


def _coerce_to_subgoal_list(value: Any) -> list[dict[str, Any]] | None:
    """Find a list of subgoal dicts inside the model's JSON output.

    Tolerates: bare list, single subgoal dict, `{"subgoals": [...]}`,
    arbitrarily-named wrapper keys, nested wrappers (e.g. `{"plan": {"steps": [...]}}`).
    """
    if isinstance(value, list):
        if any(_looks_like_subgoal(item) for item in value):
            return value
        return value if not value else None
    if isinstance(value, dict):
        if not value:
            return []
        if _looks_like_subgoal(value):
            return [value]
        for child in value.values():
            found = _coerce_to_subgoal_list(child)
            if found is not None:
                return found
    return None


def _format_remaining_plan(remaining_plan: list[Subgoal] | None) -> str:
    if not remaining_plan:
        return "None."
    lines = []
    for step in remaining_plan:
        compact_reasoning = " ".join(step.reasoning.split())[:500]
        lines.append(f"- [{step.id}] {step.description} — {compact_reasoning}")
    return "\n".join(lines)


def _extract_answer_text(response: Any) -> str:
    """Return all non-thought text parts from a model response.

    OpenAI/OpenRouter-style providers may surface reasoning as a leading
    `thought=True` part; reading `parts[0]` blindly would give the chain of
    thought instead of the JSON answer. Some providers also split JSON answers
    across multiple text parts, so preserve every non-thought text part in
    response order.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = []
    for part in parts:
        if getattr(part, "thought", None) is True:
            continue
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            text_parts.append(text)
    return "".join(text_parts).strip()


class _SubgoalSchema(BaseModel):
    description: str
    reasoning: str


class PlannerParseError(RuntimeError):
    """Raised when a replanning response cannot be parsed as a valid plan."""


class PlannerAgent:
    def __init__(
        self,
        query: str,
        llm_client: Optional[LLMClient] = None,
        model_name: str | None = None,
        event_sink: Optional[Callable[[dict[str, Any]], None]] = None,
        interrupt_checker: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._query = query
        planner_config = app_config.planner_config()
        self._llm_client = llm_client or LLMClient.from_model_config(
            planner_config,
            interrupt_checker=interrupt_checker,
        )
        self._model_name = model_name or planner_config.model
        self._temperature = app_config.generation_temperature(planner_config, 0.3)
        self._event_sink = event_sink

    def _emit_event(self, event_type: str, **payload: Any) -> None:
        if not self._event_sink:
            return
        self._event_sink({"type": event_type, "timestamp": time.time(), **payload})

    def plan(self) -> list[Subgoal]:
        """Decompose the query into a list of subgoals."""
        self._emit_event("planner_started", query=self._query)
        prompt = f"User query:\n{self._query}"
        subgoals = self._call_planner(
            prompt,
            start_id=1,
            system_prompt=_PLANNER_SYSTEM_PROMPT,
        )
        self._emit_event(
            "planner_completed",
            subgoals=[
                {"id": sg.id, "description": sg.description, "reasoning": sg.reasoning}
                for sg in subgoals
            ],
        )
        return subgoals

    def replan(
        self,
        *,
        history: list[tuple[Subgoal, str, str]],
        latest_url: str | None = None,
        remaining_plan: list[Subgoal] | None = None,
    ) -> list[Subgoal]:
        """Regenerate the remaining plan from history, latest URL, and prior plan."""
        last_id = max((step.id for step, _, _ in history), default=0)
        self._emit_event(
            "planner_replanning",
            last_step_id=last_id,
            failed_subgoal_id=last_id,
        )
        history_lines = []
        for step, status, reason in history:
            compact_reason = " ".join(str(reason).split())[:500]
            history_lines.append(
                f"- [{step.id}] {status}: {step.description} — {compact_reason}"
            )
        history_text = "\n".join(history_lines) or "None yet."
        prompt = (
            f"Original query:\n{self._query}\n\n"
            f"Latest browser URL: {latest_url or 'unknown'}\n\n"
            "Execution history so far (executed steps and outcomes):\n"
            f"{history_text}\n\n"
            "Prior remaining plan before replanning:\n"
            f"{_format_remaining_plan(remaining_plan)}\n\n"
            "Regenerate the remaining plan to complete the original query. "
            "Return an empty array if the goal is already achieved, or a single "
            "final step that reports the blocker if no in-scope path remains."
        )
        subgoals = self._call_planner(
            prompt,
            start_id=last_id + 1,
            system_prompt=_REPLAN_SYSTEM_PROMPT,
            raise_on_parse_error=True,
        )
        self._emit_event(
            "planner_replanned",
            last_step_id=last_id,
            failed_subgoal_id=last_id,
            subgoals=[
                {"id": sg.id, "description": sg.description, "reasoning": sg.reasoning}
                for sg in subgoals
            ],
        )
        return subgoals

    def _parse_subgoal_json(
        self,
        raw_text: str,
        *,
        raise_on_parse_error: bool = False,
    ) -> list[dict[str, Any]]:
        """Parse the planner response into a list of dicts, emitting an error
        event if the payload is not valid JSON.
        """
        def fail(error_message: str) -> list[dict[str, Any]]:
            self._emit_event(
                "planner_parse_error",
                error_message=error_message,
                raw_text=raw_text[:500],
            )
            if raise_on_parse_error:
                raise PlannerParseError(error_message)
            return []

        raw_text = _strip_code_fences(raw_text)
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = _try_extract_json(raw_text)
            if parsed is None:
                return fail("response is not valid JSON")
        unwrapped = _coerce_to_subgoal_list(parsed)
        if unwrapped is None:
            return fail(f"could not find a subgoal list in {type(parsed).__name__}")
        return unwrapped

    def _call_planner(
        self,
        prompt: str,
        start_id: int,
        system_prompt: str,
        *,
        raise_on_parse_error: bool = False,
    ) -> list[Subgoal]:
        contents = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            )
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=genai_types.Content(
                role="system",
                parts=[genai_types.Part(text=system_prompt)],
            ),
            temperature=self._temperature,
            response_mime_type="application/json",
            response_schema=list[_SubgoalSchema],
        )
        response = self._llm_client.generate_content(
            model=self._model_name,
            contents=contents,
            config=config,
        )
        raw_text = _extract_answer_text(response)
        if not raw_text:
            self._emit_event(
                "planner_parse_error",
                error_message="response did not contain JSON text",
                raw_text="",
            )
            if raise_on_parse_error:
                raise PlannerParseError("response did not contain JSON text")
            raw_text = "[]"
        self._emit_event("planner_raw_response", raw_text=raw_text[:2000])
        data = self._parse_subgoal_json(
            raw_text,
            raise_on_parse_error=raise_on_parse_error,
        )

        subgoals = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                error_message = f"expected dict, got {type(item).__name__}"
                self._emit_event(
                    "planner_parse_error",
                    error_message=error_message,
                    raw_text=str(item)[:500],
                )
                if raise_on_parse_error:
                    raise PlannerParseError(error_message)
                continue
            description = _first_string(item, ("description", "task", "step", "goal"))
            reasoning = _first_string(item, ("reasoning", "rationale", "why"))
            if not description:
                error_message = "subgoal missing description"
                self._emit_event(
                    "planner_parse_error",
                    error_message=error_message,
                    raw_text=str(item)[:500],
                )
                if raise_on_parse_error:
                    raise PlannerParseError(error_message)
                continue
            subgoals.append(
                Subgoal(
                    id=start_id + idx,
                    description=description,
                    reasoning=reasoning,
                )
            )
        return subgoals
