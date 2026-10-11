from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlparse

from google.genai import types

from .ambiguity import (
    ActionReviewContext,
    AmbiguityCandidate,
    detect_ambiguity_candidate,
)
from .aria_diff import compute_aria_diff
from .formatters import (
    DEFAULT_PHASE,
    NAVIGATION_ACTION_NAMES,
    PHASE_GROUPS,
    build_action_summary,
    build_fallback_reason,
)
from .types import ActionStepSummarizerProtocol, ActionStepSummary

ReviewMetadataReadyCallback = Callable[[dict[str, Any]], None]
StepSummaryReadyCallback = Callable[[ActionStepSummary], None]


def _ambiguity_fields(
    ambiguity_candidate: AmbiguityCandidate | None,
) -> dict[str, Any]:
    return {
        "ambiguity_flag": ambiguity_candidate is not None,
        "ambiguity_type": ambiguity_candidate.ambiguity_type if ambiguity_candidate else None,
        "ambiguity_message": ambiguity_candidate.message if ambiguity_candidate else None,
        "review_evidence": ambiguity_candidate.review_evidence if ambiguity_candidate else [],
    }


def _action_summary_fields(action_step_summary: ActionStepSummary) -> dict[str, Any]:
    return {
        "what": action_step_summary.what,
        "why": action_step_summary.why,
        "outcome": action_step_summary.outcome,
        "action_summary": action_step_summary.action_summary,
        "reason": action_step_summary.reason,
        "summary_source": action_step_summary.summary_source,
    }


def _a11y_path_from_artifacts(artifacts: Optional[dict[str, Any]]) -> Any:
    return artifacts.get("a11y_path") if artifacts else None


def _verification_item_for_ambiguity(
    *,
    step_id: int,
    function_call_index: int,
    ambiguity_candidate: AmbiguityCandidate,
    artifacts: Optional[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": f"ambiguity-step-{step_id}-{function_call_index}",
        "message": ambiguity_candidate.message,
        "detail": f"Review evidence: {', '.join(ambiguity_candidate.review_evidence)}",
        "source_step_id": step_id,
        "status": "needs_review",
        "a11y_path": _a11y_path_from_artifacts(artifacts),
        **_ambiguity_fields(ambiguity_candidate),
    }


def _merge_verification_items(
    existing_items: list[Any],
    new_items: list[Any],
) -> list[Any]:
    merged_items: list[Any] = []
    seen_keys: set[str] = set()
    for item in [*existing_items, *new_items]:
        key = item.get("id") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key:
            key = repr(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged_items.append(item)
    return merged_items


class ActionReviewService:
    def __init__(
        self,
        query: str,
        step_summarizer: ActionStepSummarizerProtocol | None = None,
        background_action_summaries: bool = False,
    ):
        self._query = query
        self._action_review_history: list[ActionReviewContext] = []
        self._step_summarizer = step_summarizer
        self._background_action_summaries = background_action_summaries
        self._step_summary_cache: dict[tuple[int, int], ActionStepSummary] = {}
        self._step_summary_lock = threading.RLock()
        self._pending_step_summary_threads: dict[tuple[int, int], threading.Thread] = {}
        self._pending_step_summary_callbacks: dict[
            tuple[int, int],
            list[StepSummaryReadyCallback],
        ] = {}

    def build_final_result_summary(
        self,
        *,
        final_response: str | None,
        current_url: str | None,
        fallback_summary: str | None = None,
    ) -> str | None:
        fallback_summary = (
            fallback_summary
            if fallback_summary is not None
            else self.clean_reasoning_text(final_response)
        )
        if self._step_summarizer is None:
            return fallback_summary

        summarized = self._step_summarizer.summarize_final_result(
            query=self._query,
            final_response=final_response,
            current_url=current_url,
        )
        return summarized or fallback_summary

    def build_action_summary(self, function_call: types.FunctionCall) -> str:
        return build_action_summary(function_call)

    def build_fallback_reason(self, function_call: types.FunctionCall) -> str:
        return build_fallback_reason(function_call)

    def clean_reasoning_text(self, reasoning: Optional[str]) -> Optional[str]:
        if not reasoning:
            return None
        cleaned_reasoning = " ".join(reasoning.split())
        return cleaned_reasoning or None

    def build_phase_metadata(
        self,
        function_call: types.FunctionCall | None,
        reasoning: Optional[str],
        step_id: int,
        *,
        final_result_summary: Optional[str] = None,
    ) -> dict[str, Any]:
        if final_result_summary is not None or function_call is None:
            return {
                "phase_id": "phase-complete",
                "phase_label": "Complete",
                "phase_summary": reasoning,
                "user_visible_label": "Final summary",
            }

        action_name = function_call.name or "action"
        phase_id, phase_label = PHASE_GROUPS.get(action_name, DEFAULT_PHASE)

        return {
            "phase_id": phase_id,
            "phase_label": phase_label,
            "phase_summary": reasoning,
            "user_visible_label": self.build_action_summary(function_call)
            if function_call.name
            else f"Step {step_id}",
        }

    def _build_fallback_outcome(
        self,
        function_call: types.FunctionCall,
        current_url: str | None,
        previous_url: str | None,
    ) -> str:
        if current_url and previous_url and current_url != previous_url:
            try:
                host = urlparse(current_url).hostname or current_url
            except Exception:  # noqa: BLE001
                host = current_url
            return f"Navigated to {host}"
        action_name = function_call.name or ""
        if action_name in NAVIGATION_ACTION_NAMES:
            return "Navigation requested"
        return "—"

    def _build_fallback_action_step_summary(
        self,
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        current_url: str | None,
        previous_url: str | None = None,
    ) -> ActionStepSummary:
        return ActionStepSummary(
            what=self.build_action_summary(function_call),
            why=self.clean_reasoning_text(reasoning)
            or self.build_fallback_reason(function_call),
            outcome=self._build_fallback_outcome(function_call, current_url, previous_url),
            summary_source="app_derived",
        )

    def _summarize_action_step(
        self,
        *,
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        current_url: str | None,
        previous_url: str | None = None,
        previous_aria: str | None = None,
        current_aria: str | None = None,
    ) -> ActionStepSummary | None:
        if self._step_summarizer is None:
            return None
        aria_diff = compute_aria_diff(previous_aria, current_aria)
        try:
            return self._step_summarizer.summarize_action(
                query=self._query,
                function_call=function_call,
                reasoning=reasoning,
                current_url=current_url,
                previous_url=previous_url,
                aria_diff=aria_diff,
            )
        except Exception:  # noqa: BLE001
            return None

    def _get_cached_step_summary(
        self,
        cache_key: tuple[int, int],
    ) -> ActionStepSummary | None:
        with self._step_summary_lock:
            return self._step_summary_cache.get(cache_key)

    def _set_cached_step_summary(
        self,
        cache_key: tuple[int, int],
        action_step_summary: ActionStepSummary,
    ) -> None:
        with self._step_summary_lock:
            self._step_summary_cache[cache_key] = action_step_summary

    def _get_action_step_summary(
        self,
        *,
        step_id: int,
        function_call_index: int,
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        current_url: str | None,
        previous_url: str | None = None,
        previous_aria: str | None = None,
        current_aria: str | None = None,
    ) -> ActionStepSummary:
        cache_key = (step_id, function_call_index)
        cached_summary = self._get_cached_step_summary(cache_key)
        if cached_summary is not None:
            return cached_summary

        fallback_summary = self._build_fallback_action_step_summary(
            function_call=function_call,
            reasoning=reasoning,
            current_url=current_url,
            previous_url=previous_url,
        )
        self._set_cached_step_summary(cache_key, fallback_summary)

        if self._step_summarizer is None or self._background_action_summaries:
            return fallback_summary

        summarized = self._summarize_action_step(
            function_call=function_call,
            reasoning=reasoning,
            current_url=current_url,
            previous_url=previous_url,
            previous_aria=previous_aria,
            current_aria=current_aria,
        )
        resolved_summary = summarized or fallback_summary
        self._set_cached_step_summary(cache_key, resolved_summary)
        return resolved_summary

    def _run_action_step_summary_worker(
        self,
        *,
        cache_key: tuple[int, int],
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        current_url: str | None,
        previous_url: str | None = None,
        previous_aria: str | None = None,
        current_aria: str | None = None,
    ) -> None:
        callbacks: list[StepSummaryReadyCallback] = []
        summarized: ActionStepSummary | None = None
        try:
            summarized = self._summarize_action_step(
                function_call=function_call,
                reasoning=reasoning,
                current_url=current_url,
                previous_url=previous_url,
                previous_aria=previous_aria,
                current_aria=current_aria,
            )
            if summarized is None:
                return
            with self._step_summary_lock:
                self._step_summary_cache[cache_key] = summarized
                callbacks = list(
                    self._pending_step_summary_callbacks.get(cache_key, [])
                )

            for callback in callbacks:
                try:
                    callback(summarized)
                except Exception:  # noqa: BLE001
                    continue
        finally:
            with self._step_summary_lock:
                self._pending_step_summary_threads.pop(cache_key, None)
                self._pending_step_summary_callbacks.pop(cache_key, None)

    def _schedule_action_step_summary(
        self,
        *,
        cache_key: tuple[int, int],
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        current_url: str | None,
        previous_url: str | None = None,
        previous_aria: str | None = None,
        current_aria: str | None = None,
        on_summary_ready: StepSummaryReadyCallback | None = None,
    ) -> None:
        if self._step_summarizer is None or not self._background_action_summaries:
            return

        callback_to_call_now: StepSummaryReadyCallback | None = None
        summary_to_send_now: ActionStepSummary | None = None
        thread_to_start: threading.Thread | None = None
        with self._step_summary_lock:
            cached_summary = self._step_summary_cache.get(cache_key)
            if cached_summary is not None and cached_summary.summary_source != "app_derived":
                callback_to_call_now = on_summary_ready
                summary_to_send_now = cached_summary
            else:
                if on_summary_ready is not None:
                    self._pending_step_summary_callbacks.setdefault(
                        cache_key,
                        [],
                    ).append(on_summary_ready)
                if cache_key not in self._pending_step_summary_threads:
                    thread_to_start = threading.Thread(
                        target=self._run_action_step_summary_worker,
                        kwargs={
                            "cache_key": cache_key,
                            "function_call": function_call,
                            "reasoning": reasoning,
                            "current_url": current_url,
                            "previous_url": previous_url,
                            "previous_aria": previous_aria,
                            "current_aria": current_aria,
                        },
                        name=f"action-step-summary-{cache_key[0]}-{cache_key[1]}",
                        daemon=True,
                    )
                    self._pending_step_summary_threads[cache_key] = thread_to_start

        if callback_to_call_now is not None and summary_to_send_now is not None:
            try:
                callback_to_call_now(summary_to_send_now)
            except Exception:  # noqa: BLE001
                pass
        if thread_to_start is not None:
            thread_to_start.start()

    def wait_for_pending_action_summaries(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._step_summary_lock:
                threads = list(self._pending_step_summary_threads.values())
            live_threads = [thread for thread in threads if thread.is_alive()]
            if not live_threads:
                return True
            for thread in live_threads:
                if deadline is None:
                    thread.join()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                thread.join(timeout=remaining)

    def with_action_step_summary(
        self,
        review_metadata: dict[str, Any],
        action_step_summary: ActionStepSummary,
    ) -> dict[str, Any]:
        return {
            **review_metadata,
            **_action_summary_fields(action_step_summary),
            "user_visible_label": action_step_summary.action_summary,
        }

    def build_review_metadata_for_action(
        self,
        step_id: int,
        function_call_index: int,
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        artifacts: Optional[dict[str, Any]],
        subgoal_id: int | None = None,
        on_review_metadata_ready: ReviewMetadataReadyCallback | None = None,
    ) -> dict[str, Any]:
        current_url = artifacts.get("url") if artifacts else None
        current_aria = artifacts.get("aria_snapshot") if artifacts else None
        previous_context_for_url = (
            self._action_review_history[-1] if self._action_review_history else None
        )
        previous_url = previous_context_for_url.current_url if previous_context_for_url else None
        previous_aria = (
            previous_context_for_url.aria_snapshot if previous_context_for_url else None
        )
        action_step_summary = self._get_action_step_summary(
            step_id=step_id,
            function_call_index=function_call_index,
            function_call=function_call,
            reasoning=reasoning,
            current_url=current_url,
            previous_url=previous_url,
            previous_aria=previous_aria,
            current_aria=current_aria,
        )
        current_context = ActionReviewContext(
            action_name=function_call.name or "action",
            action_args=dict(function_call.args or {}),
            current_url=current_url,
            aria_snapshot=current_aria,
        )
        previous_context = self._action_review_history[-1] if self._action_review_history else None
        ambiguity_candidate = detect_ambiguity_candidate(
            query=self._query,
            current_action=current_context,
            previous_action=previous_context,
        )
        self._action_review_history.append(current_context)

        review_metadata = {
            **self.build_phase_metadata(
                function_call=function_call,
                reasoning=reasoning,
                step_id=step_id,
            ),
            **_action_summary_fields(action_step_summary),
            "subgoal_id": subgoal_id,
            "user_visible_label": action_step_summary.action_summary,
            **_ambiguity_fields(ambiguity_candidate),
            "a11y_path": _a11y_path_from_artifacts(artifacts),
            "verification_items": [],
        }

        if ambiguity_candidate is not None:
            review_metadata["verification_items"] = [
                _verification_item_for_ambiguity(
                    step_id=step_id,
                    function_call_index=function_call_index,
                    ambiguity_candidate=ambiguity_candidate,
                    artifacts=artifacts,
                )
            ]

        if action_step_summary.summary_source == "app_derived":
            self._schedule_action_step_summary(
                cache_key=(step_id, function_call_index),
                function_call=function_call,
                reasoning=reasoning,
                current_url=current_url,
                previous_url=previous_url,
                previous_aria=previous_aria,
                current_aria=current_aria,
                on_summary_ready=(
                    None
                    if on_review_metadata_ready is None
                    else lambda action_step_summary: on_review_metadata_ready(
                        self.with_action_step_summary(
                            review_metadata,
                            action_step_summary,
                        )
                    )
                ),
            )
        return review_metadata

    def build_persisted_action_metadata(
        self,
        step_id: int,
        function_call_index: int,
        function_call: types.FunctionCall,
        reasoning: Optional[str],
        ambiguity_candidate: AmbiguityCandidate | None = None,
        artifacts: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        cleaned_reasoning = self.clean_reasoning_text(reasoning)
        action_step_summary = self._get_action_step_summary(
            step_id=step_id,
            function_call_index=function_call_index,
            function_call=function_call,
            reasoning=reasoning,
            current_url=artifacts.get("url") if artifacts else None,
        )
        return {
            "action": {
                "name": function_call.name,
                "args": dict(function_call.args or {}),
            },
            **_action_summary_fields(action_step_summary),
            "reasoning_text": cleaned_reasoning,
            "model_step_id": step_id,
            "function_call_index_within_step": function_call_index,
            **_ambiguity_fields(ambiguity_candidate),
            "a11y_path": _a11y_path_from_artifacts(artifacts),
        }

    def merge_step_review_metadata(
        self,
        existing_metadata: dict[str, Any],
        review_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        verification_items = _merge_verification_items(
            list(existing_metadata.get("verification_items", [])),
            list(review_metadata.get("verification_items", [])),
        )

        existing_evidence = list(existing_metadata.get("review_evidence", []))
        merged_evidence = existing_evidence + [
            evidence
            for evidence in review_metadata.get("review_evidence", [])
            if evidence not in existing_evidence
        ]

        ambiguity_flag = bool(existing_metadata.get("ambiguity_flag")) or bool(
            review_metadata.get("ambiguity_flag")
        )
        ambiguity_type = existing_metadata.get("ambiguity_type")
        ambiguity_message = existing_metadata.get("ambiguity_message")
        if review_metadata.get("ambiguity_flag"):
            ambiguity_type = review_metadata.get("ambiguity_type") or ambiguity_type
            ambiguity_message = review_metadata.get("ambiguity_message") or ambiguity_message

        prefer_review_summary = (
            existing_metadata.get("summary_source") == "app_derived"
            and review_metadata.get("summary_source")
            and review_metadata.get("summary_source") != "app_derived"
        )

        return {
            "phase_id": existing_metadata.get("phase_id") or review_metadata.get("phase_id"),
            "phase_label": existing_metadata.get("phase_label") or review_metadata.get("phase_label"),
            "phase_summary": existing_metadata.get("phase_summary") or review_metadata.get("phase_summary"),
            "what": review_metadata.get("what")
            if prefer_review_summary
            else existing_metadata.get("what") or review_metadata.get("what"),
            "why": review_metadata.get("why")
            if prefer_review_summary
            else existing_metadata.get("why") or review_metadata.get("why"),
            "outcome": review_metadata.get("outcome")
            if prefer_review_summary
            else existing_metadata.get("outcome") or review_metadata.get("outcome"),
            "action_summary": review_metadata.get("action_summary")
            if prefer_review_summary
            else existing_metadata.get("action_summary")
            or review_metadata.get("action_summary"),
            "reason": review_metadata.get("reason")
            if prefer_review_summary
            else existing_metadata.get("reason") or review_metadata.get("reason"),
            "summary_source": review_metadata.get("summary_source")
            if prefer_review_summary
            else existing_metadata.get("summary_source")
            or review_metadata.get("summary_source"),
            "subgoal_id": existing_metadata.get("subgoal_id")
            if existing_metadata.get("subgoal_id") is not None
            else review_metadata.get("subgoal_id"),
            "user_visible_label": review_metadata.get("user_visible_label")
            if prefer_review_summary
            else existing_metadata.get("user_visible_label")
            or review_metadata.get("user_visible_label"),
            "ambiguity_flag": ambiguity_flag,
            "ambiguity_type": ambiguity_type,
            "ambiguity_message": ambiguity_message,
            "review_evidence": merged_evidence,
            "a11y_path": review_metadata.get("a11y_path")
            or existing_metadata.get("a11y_path"),
            "verification_items": verification_items,
        }
