"""Plan-and-Act step execution and control loop for BrowserAgent."""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any, Literal

from google.genai.types import Content, Part

from core.types import AgentRunResult, Subgoal
from .exceptions import AgentBudgetExceeded
from .safety import SAFETY_TERMINATION_REASON
from . import subgoals as step_helpers

StepOutcome = tuple[Subgoal, Literal["done", "failed"], str]


def _format_history(history: list[StepOutcome]) -> str:
    if not history:
        return "None yet."
    lines = []
    for step, result, reason in history:
        compact_reason = " ".join(reason.split())[:500]
        lines.append(f"- [{step.id}] {result}: {step.description} — {compact_reason}")
    return "\n".join(lines)


def _step_prompt(agent: Any, step: Subgoal, history: list[StepOutcome]) -> str:
    latest_url = agent.latest_url or "unknown"
    scope = getattr(agent, "_navigation_scope", None)
    scope_text = getattr(scope, "description", "No explicit navigation scope.")
    return (
        f"Overall task (reference only):\n{agent._query}\n\n"
        f"Task navigation scope:\n{scope_text}\n\n"
        f"Latest browser URL: {latest_url}\n\n"
        "Execution history so far (compact, not full trajectory):\n"
        f"{_format_history(history)}\n\n"
        "You are the Executor. Carry out ONLY the current plan step below using the "
        "browser tools. Do not work ahead to later steps.\n\n"
        f"[Step {step.id}] {step.description}\n"
        f"Rationale: {step.reasoning}\n\n"
        "When you have finished acting for this step, stop calling tools and respond "
        "with exactly one final message beginning with one of:\n"
        "- 'STEP_DONE:' if you completed this step's action,\n"
        "- 'STEP_FAILED:' if this step cannot be completed,\n"
        "- 'TASK_COMPLETE:' if the entire overall task is now satisfied; include the "
        "final answer to the user after the marker.\n"
    )


def _finalize_budget_exceeded(
    agent: Any,
    history: list[StepOutcome],
    step: Subgoal,
    exc: AgentBudgetExceeded,
) -> AgentRunResult:
    reason = str(exc)
    completed = dataclasses.replace(step, status="failed")
    history.append((completed, "failed", reason))
    agent._emit_event(
        "subgoal_failed",
        subgoal_id=completed.id,
        status="failed",
        reason=reason,
    )
    return agent._finalize_subgoal_plan(
        history,
        status="partial_failure",
        reason=reason,
    )


def _callback_accepts_remaining_plan(callback: Any) -> bool:
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    if "remaining_plan" in parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _call_replan_callback(
    callback: Any,
    *,
    history: list[StepOutcome],
    latest_url: str | None,
    remaining_plan: list[Subgoal],
) -> list[Subgoal]:
    kwargs: dict[str, Any] = {
        "history": history,
        "latest_url": latest_url,
    }
    if _callback_accepts_remaining_plan(callback):
        kwargs["remaining_plan"] = remaining_plan
    return callback(**kwargs)


def run_step_loop(
    agent: Any,
    step: Subgoal,
    history: list[StepOutcome] | None = None,
) -> tuple[Literal["done", "failed"], str, str | None]:
    """Run one high-level plan step. Returns (result, reason, final_answer)."""
    history = history or []
    agent.final_reasoning = None
    agent._last_final_response = None
    agent._current_subgoal_id = step.id
    agent._contents = [
        Content(role="user", parts=[Part(text=_step_prompt(agent, step, history))])
    ]
    try:
        status = "CONTINUE"
        steps = 0
        while status == "CONTINUE":
            agent._raise_if_interrupted()
            agent._raise_if_total_step_budget_exceeded()
            if steps >= agent._max_steps_per_subgoal:
                return "failed", (
                    f"Exceeded max steps ({agent._max_steps_per_subgoal}) for step {step.id}."
                ), None
            status = agent.run_one_iteration()
            steps += 1
            agent._total_steps_used += 1
            final_text = (
                getattr(agent, "_last_final_response", None)
                or agent.final_reasoning
                or ""
            ).strip()
            if status == "COMPLETE" and not step_helpers.has_step_marker(final_text):
                if steps >= agent._max_steps_per_subgoal:
                    break
                agent.append_user_message(
                    "The previous turn ended this step without the required "
                    "STEP_DONE:, STEP_FAILED:, or TASK_COMPLETE: marker. Inspect the "
                    "latest browser state and respond with exactly one final message "
                    "using the required marker. If the previous turn produced no text "
                    "because of a transient model error, retry the step decision now."
                )
                agent.final_reasoning = None
                agent._last_final_response = None
                status = "CONTINUE"
    finally:
        agent._current_subgoal_id = None

    return step_helpers.classify_step_final_text(
        step_id=step.id,
        final_text=(
            getattr(agent, "_last_final_response", None) or agent.final_reasoning or ""
        ),
        steps=steps,
    )


def run_plan_and_act(agent: Any) -> AgentRunResult:
    """Plan-and-Act control loop: execute steps, replanning only after failures."""
    plan = list(agent._subgoals)
    history: list[StepOutcome] = []
    iterations = 0
    replanned_after_failure = False
    while plan:
        agent._raise_if_interrupted()
        iterations += 1
        step = dataclasses.replace(plan[0], status="active")
        try:
            agent._raise_if_subgoal_budget_exceeded(iterations)
        except AgentBudgetExceeded as exc:
            return _finalize_budget_exceeded(agent, history, step, exc)
        agent._emit_event(
            "subgoal_started",
            subgoal_id=step.id,
            description=step.description,
            reasoning=step.reasoning,
        )
        try:
            result, reason, final_answer = agent._run_subgoal_loop(step, history)
        except AgentBudgetExceeded as exc:
            return _finalize_budget_exceeded(agent, history, step, exc)
        completed = dataclasses.replace(step, status=result)
        history.append((completed, result, reason))
        agent._emit_event(
            "subgoal_completed" if result == "done" else "subgoal_failed",
            subgoal_id=completed.id,
            status=result,
            reason=reason,
        )
        if getattr(agent, "_safety_terminated", False):
            return agent._finalize_subgoal_plan(
                history,
                status="interrupted",
                reason=SAFETY_TERMINATION_REASON,
            )
        if final_answer is not None:
            return agent._finalize_subgoal_plan(
                history, status="complete", reason=None, final_answer=final_answer
            )
        if result == "done":
            plan = plan[1:]
            if not plan and replanned_after_failure:
                return agent._finalize_subgoal_plan(
                    history,
                    status="complete",
                    reason=None,
                )
            continue
        if agent._replan_callback is None:
            plan = plan[1:]
            continue
        try:
            plan = list(
                _call_replan_callback(
                    agent._replan_callback,
                    history=history,
                    latest_url=agent.latest_url,
                    remaining_plan=plan[1:],
                )
            )
        except Exception as exc:  # noqa: BLE001
            agent._emit_event(
                "replan_error", subgoal_id=completed.id, error_message=str(exc)
            )
            return agent._finalize_subgoal_plan(
                history,
                status="blocked",
                reason=f"Replan failed after step {completed.id}: {exc}",
            )
        replanned_after_failure = True
    return agent._finalize_subgoal_plan(history, status=None, reason=None)
