"""Subgoal result helpers for planner-driven actor runs."""

from __future__ import annotations

import re
from typing import Literal

from core.types import Subgoal

SubgoalOutcome = tuple[Subgoal, Literal["done", "failed"], str]

_STEP_MARKER_RE = re.compile(
    r"^\s*(?:(?P<step>STEP)[\s_-]+(?P<step_status>DONE|FAILED)|"
    r"(?P<task>TASK)[\s_-]+(?P<task_status>COMPLETE))\s*:",
    re.IGNORECASE,
)
_STATUS_SUFFIX_RE = re.compile(r"\s*\(status:\s*(?:done|failed)\)\s*", re.IGNORECASE)
_INTERNAL_REF_RE = re.compile(
    r"\s*(?:\(\s*)?(?:[-–—]\s*)?\brefs?\s*"
    r"(?:\[[0-9]+\]|[0-9]+)(?:\s*,\s*(?:\[[0-9]+\]|[0-9]+))*\s*\)?",
    re.IGNORECASE,
)
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")


def step_marker_kind(final_text: str) -> Literal["STEP_DONE", "STEP_FAILED", "TASK_COMPLETE"] | None:
    match = _STEP_MARKER_RE.match(final_text)
    if not match:
        return None
    if match.group("step"):
        return (
            "STEP_DONE"
            if match.group("step_status").upper() == "DONE"
            else "STEP_FAILED"
        )
    return "TASK_COMPLETE"


def has_step_marker(final_text: str) -> bool:
    return step_marker_kind(final_text) is not None


def classify_step_final_text(
    *,
    step_id: int,
    final_text: str,
    steps: int,
) -> tuple[Literal["done", "failed"], str, str | None]:
    """Classify an Executor step result.

    Returns (result, reason, final_answer). final_answer is non-None only when
    the Executor declared the whole task complete via TASK_COMPLETE.
    """
    final_text = final_text.strip()
    if not final_text:
        return "failed", (
            f"Step {step_id} did not produce a final status message after "
            f"{steps} step(s)."
        ), None
    marker = step_marker_kind(final_text)
    if marker == "TASK_COMPLETE":
        return "done", final_text, clean_step_reason_for_answer(final_text)
    if marker == "STEP_FAILED":
        return "failed", final_text, None
    if marker == "STEP_DONE":
        return "done", final_text, None
    return "failed", (
        f"Step {step_id} ended without declaring a status. Final text: {final_text[:200]}"
    ), None


def build_subgoal_plan_summary(
    outcomes: list[SubgoalOutcome],
    *,
    overall_status: str | None = None,
) -> str:
    succeeded = sum(1 for _, result, _ in outcomes if result == "done")
    failed = sum(1 for _, result, _ in outcomes if result == "failed")
    if failed == 0:
        header = "All planner subgoals completed."
    elif overall_status == "complete":
        header = "Planner subgoals completed after replanning."
    else:
        header = "Planner subgoals completed with failures."
    lines = [header, f"Subgoal outcomes: {succeeded} succeeded, {failed} failed."]
    for subgoal, result, reason in outcomes:
        lines.append(f"[{subgoal.id}] {subgoal.description}: {reason} (status: {result})")
    if failed:
        failure_header = (
            "Recovered failure reasons:"
            if overall_status == "complete"
            else "Failure reasons:"
        )
        lines.append(failure_header)
        for subgoal, result, reason in outcomes:
            if result == "failed":
                lines.append(f"- [{subgoal.id}] {reason}")
    return "\n".join(lines)


def clean_step_reason_for_answer(reason: str) -> str:
    """Remove Executor-only markers from a step final message."""
    cleaned = _STEP_MARKER_RE.sub("", reason.strip(), count=1)
    cleaned = _STATUS_SUFFIX_RE.sub(" ", cleaned)
    cleaned = _INTERNAL_REF_RE.sub("", cleaned)
    cleaned = _EMPTY_PARENS_RE.sub("", cleaned)

    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = " ".join(raw_line.split())
        line = _STATUS_SUFFIX_RE.sub(" ", line)
        line = _INTERNAL_REF_RE.sub("", line)
        line = _EMPTY_PARENS_RE.sub("", line)
        line = re.sub(r"\s+([,.;:])", r"\1", line).strip()
        if line:
            lines.append(line)

    return "\n".join(lines).strip()


def build_subgoal_plan_final_answer(
    outcomes: list[SubgoalOutcome],
    *,
    overall_status: str | None = None,
) -> str:
    """Build the user-facing fallback answer for a planner-driven run.

    The aggregate planner summary is useful as an internal audit trail, but it
    exposes subgoal ids, status markers, and recovery details. For chat output,
    prefer the latest successful subgoal's own answer because the final subgoal
    usually contains the requested result.
    """
    done_answers = [
        clean_step_reason_for_answer(reason)
        for _, result, reason in outcomes
        if result == "done"
    ]
    latest_done_answer = next((answer for answer in reversed(done_answers) if answer), None)
    if latest_done_answer and overall_status == "complete":
        return latest_done_answer

    failed_answers = [
        clean_step_reason_for_answer(reason)
        for _, result, reason in outcomes
        if result == "failed"
    ]
    failed_answers = [answer for answer in failed_answers if answer]

    if latest_done_answer and failed_answers:
        return (
            f"{latest_done_answer}\n\n"
            f"Some parts could not be completed: {'; '.join(failed_answers)}"
        )
    if latest_done_answer:
        return latest_done_answer
    if failed_answers:
        return f"Could not complete the request: {'; '.join(failed_answers)}"
    return build_subgoal_plan_summary(outcomes, overall_status=overall_status)
