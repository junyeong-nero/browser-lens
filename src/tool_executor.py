from collections.abc import Callable
from functools import partial
import inspect
from pathlib import Path
from typing import Any

from google.genai import types

from browser import PlaywrightBrowser
from core.navigation_scope import NavigationScope
from core.types import GroundingMode
from tools.click_at import handle_click_at
from tools.click_by_ref import handle_click_by_ref
from tools.drag_and_drop import handle_drag_and_drop
from tools.go_back import handle_go_back
from tools.go_forward import handle_go_forward
from tools.hover_at import handle_hover_at
from tools.hover_by_ref import handle_hover_by_ref
from tools.key_combination import handle_key_combination
from tools.navigate import handle_navigate
from tools.open_web_browser import handle_observe_page, handle_open_web_browser
from tools.scroll_at import handle_scroll_at
from tools.scroll_by_ref import handle_scroll_by_ref
from tools.scroll_document import handle_scroll_document
from tools.search import handle_search
from tools.check_by_ref import handle_check_by_ref
from tools.select_option_by_ref import handle_select_option_by_ref
from tools.text_mode_tools import TEXT_MODE_TOOL_DESCRIPTORS
from tools.type_text_at import handle_type_text_at
from tools.type_by_ref import handle_type_by_ref
from tools.types import (
    CustomFunction,
    ExecutedCall,
    ToolBatchResult,
    ToolResult,
    is_env_state_result,
)
from tools.wait_5_seconds import handle_wait_5_seconds
from tools.wait_for_ref import handle_wait_for_ref
from tools.vision_mode_tools import VISION_MODE_TOOL_DESCRIPTORS


MAX_ARIA_SNAPSHOT_CHARS = 120_000
COORDINATE_FUNCTION_NAMES = {
    "click_at",
    "hover_at",
    "scroll_at",
    "type_text_at",
}

TOOL_HANDLERS = {
    "open_web_browser": handle_open_web_browser,
    "observe_page": handle_observe_page,
    "click_at": handle_click_at,
    "hover_at": handle_hover_at,
    "type_text_at": handle_type_text_at,
    "scroll_document": handle_scroll_document,
    "scroll_at": handle_scroll_at,
    "wait_5_seconds": handle_wait_5_seconds,
    "go_back": handle_go_back,
    "go_forward": handle_go_forward,
    "search": handle_search,
    "navigate": handle_navigate,
    "key_combination": handle_key_combination,
    "drag_and_drop": handle_drag_and_drop,
    "click_by_ref": handle_click_by_ref,
    "select_option_by_ref": handle_select_option_by_ref,
    "type_by_ref": handle_type_by_ref,
    "hover_by_ref": handle_hover_by_ref,
    "scroll_by_ref": handle_scroll_by_ref,
    "check_by_ref": handle_check_by_ref,
    "wait_for_ref": handle_wait_for_ref,
}


BROWSER_STATE_CHANGING_FUNCTIONS = {
    "open_web_browser",
    "click_at",
    "click_by_ref",
    "select_option_by_ref",
    "close_current_tab",
    "drag_and_drop",
    "go_back",
    "go_forward",
    "hover_at",
    "hover_by_ref",
    "key_combination",
    "navigate",
    "reload_page",
    "scroll_at",
    "scroll_by_ref",
    "scroll_document",
    "search",
    "switch_to_next_tab",
    "switch_to_previous_tab",
    "switch_to_tab",
    "type_by_ref",
    "type_text_at",
    "upload_file",
    "wait_5_seconds",
    "wait_for_ref",
}
SCREENSHOT_RESPONSE_FUNCTIONS = set(TOOL_HANDLERS) | BROWSER_STATE_CHANGING_FUNCTIONS


class BrowserToolExecutor:
    def __init__(
        self,
        browser_computer: PlaywrightBrowser,
        custom_functions: list[CustomFunction] | None = None,
        grounding: GroundingMode = "vision",
        navigation_scope: NavigationScope | None = None,
    ) -> None:
        self._browser_computer = browser_computer
        self._grounding = grounding
        self._navigation_scope = navigation_scope
        self._custom_functions = {
            custom_function.__name__: custom_function
            for custom_function in (custom_functions or [])
        }
        self._handlers: dict[str, Callable[[dict], ToolResult]] = {
            name: partial(handler, browser_computer)
            for name, handler in TOOL_HANDLERS.items()
        }
        self._cached_raw_aria_snapshot_text: str | None = None
        self._cached_raw_aria_metadata: dict[str, Any] | None = None
        self._allowed_function_names: set[str] | None = None
        self._last_call_produced_env_state = False

    def build_tools(
        self,
        build_function_declaration: Callable[[Callable[..., object]], types.FunctionDeclaration],
        excluded_predefined_functions: list[str] | None = None,
    ) -> list[types.Tool]:
        custom_declarations = [
            build_function_declaration(fn) for fn in self._custom_functions.values()
        ]

        excluded_names = set(excluded_predefined_functions or [])
        excluded_names.update(self._scope_excluded_predefined_names())

        if self._grounding == "vision":
            vision_declarations = self._build_unique_declarations(
                build_function_declaration,
                VISION_MODE_TOOL_DESCRIPTORS,
                excluded_names=excluded_names,
            )
            self._annotate_coordinate_declarations(vision_declarations)
            declarations = [*vision_declarations, *custom_declarations]
            self._allowed_function_names = self._declaration_names(declarations)
            return [types.Tool(function_declarations=declarations)]

        if self._grounding == "text":
            text_declarations = self._build_unique_declarations(
                build_function_declaration,
                TEXT_MODE_TOOL_DESCRIPTORS,
                excluded_names=excluded_names,
            )
            declarations = [*text_declarations, *custom_declarations]
            self._allowed_function_names = self._declaration_names(declarations)
            return [types.Tool(function_declarations=declarations)]

        vision_declarations = self._build_unique_declarations(
            build_function_declaration,
            [*VISION_MODE_TOOL_DESCRIPTORS, *TEXT_MODE_TOOL_DESCRIPTORS],
            excluded_names=excluded_names,
        )
        self._annotate_coordinate_declarations(vision_declarations)
        declarations = [*vision_declarations, *custom_declarations]
        self._allowed_function_names = self._declaration_names(declarations)
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _build_unique_declarations(
        build_function_declaration: Callable[[Callable[..., object]], types.FunctionDeclaration],
        descriptors: list[Callable[..., object]],
        *,
        excluded_names: set[str],
    ) -> list[types.FunctionDeclaration]:
        declarations: list[types.FunctionDeclaration] = []
        seen = set()
        for descriptor in descriptors:
            name = descriptor.__name__
            if name in excluded_names or name in seen:
                continue
            seen.add(name)
            declarations.append(build_function_declaration(descriptor))
        return declarations

    def _annotate_coordinate_declarations(
        self,
        declarations: list[types.FunctionDeclaration],
    ) -> None:
        try:
            width, height = self._browser_computer.screen_size()
        except Exception:  # noqa: BLE001
            return
        if width <= 0 or height <= 0:
            return

        for declaration in declarations:
            if declaration.name not in COORDINATE_FUNCTION_NAMES:
                continue
            schema = declaration.parameters_json_schema
            if not isinstance(schema, dict):
                continue
            properties = schema.setdefault("properties", {})
            if not isinstance(properties, dict):
                continue
            self._annotate_coordinate_property(properties, "x", width)
            self._annotate_coordinate_property(properties, "y", height)

    @staticmethod
    def _annotate_coordinate_property(
        properties: dict[str, Any],
        axis: str,
        limit: int,
    ) -> None:
        property_schema = properties.get(axis)
        if not isinstance(property_schema, dict):
            property_schema = {"type": "integer"}
            properties[axis] = property_schema
        property_schema["type"] = "integer"
        property_schema["minimum"] = 0
        property_schema["maximum"] = limit - 1
        property_schema["description"] = (
            f"{axis}-coordinate in current screenshot pixels, "
            f"from 0 to {limit - 1}."
        )

    @staticmethod
    def _declaration_names(
        declarations: list[types.FunctionDeclaration],
    ) -> set[str]:
        return {
            declaration.name
            for declaration in declarations
            if declaration.name
        }

    def execute_call(self, action: types.FunctionCall) -> ExecutedCall:
        captures_actions = hasattr(type(self._browser_computer), "begin_action_capture")
        if captures_actions:
            self._browser_computer.begin_action_capture()
        result: ToolResult | None = None
        capture_updates = None
        persist_capture = False
        try:
            self._last_call_produced_env_state = False
            result = self.execute(action)
            persist_capture = is_env_state_result(result)
        finally:
            if captures_actions:
                capture_updates = self._end_action_capture(persist=persist_capture)
            if not persist_capture:
                self._clear_pending_action()
        self._clear_aria_caches()
        base_artifacts = (
            self._latest_artifact_metadata()
            if is_env_state_result(result) or self._last_call_produced_env_state
            else None
        )
        artifacts: dict[str, Any] | None = None
        if is_env_state_result(result):
            artifacts = dict(base_artifacts) if base_artifacts else {}
            if isinstance(capture_updates, dict):
                artifacts.update(capture_updates)
            if self._grounding in {"text", "mixed"}:
                aria_text, aria_metadata = self._capture_and_cache_aria_snapshot()
                if aria_text:
                    artifacts["aria_snapshot"] = aria_text
                    artifacts.update(aria_metadata)
            if not artifacts:
                artifacts = None
        elif self._last_call_produced_env_state:
            artifacts = dict(base_artifacts) if base_artifacts else None
        else:
            artifacts = self.capture_post_action_artifacts()
        return ExecutedCall(function_call=action, result=result, artifacts=artifacts)

    def capture_post_action_artifacts(self) -> dict[str, Any] | None:
        """Best-effort snapshot for tool calls whose primary result is not EnvState."""
        if not self._history_logging_active():
            return None
        current_state = getattr(self._browser_computer, "current_state", None)
        if not callable(current_state):
            return None
        try:
            current_state()
        except Exception:  # noqa: BLE001
            return None
        latest_artifacts = self._latest_artifact_metadata()
        return dict(latest_artifacts) if latest_artifacts else None

    def _history_logging_active(self) -> bool:
        history_dir = getattr(self._browser_computer, "history_dir", None)
        if not callable(history_dir):
            return False
        try:
            value = history_dir()
        except Exception:  # noqa: BLE001
            return False
        return isinstance(value, (str, Path)) and bool(value)

    def _capture_and_cache_aria_snapshot(self) -> tuple[str, dict[str, Any]]:
        try:
            snapshot = self._browser_computer.take_aria_snapshot()
        except Exception:  # noqa: BLE001
            self._cached_raw_aria_snapshot_text = ""
            self._cached_raw_aria_metadata = {}
            return "", {}

        raw_text, raw_metadata = compact_aria_snapshot_text(snapshot.text)
        self._cached_raw_aria_snapshot_text = raw_text
        self._cached_raw_aria_metadata = raw_metadata
        return raw_text, raw_metadata

    def _end_action_capture(self, *, persist: bool) -> dict[str, Any] | None:
        end_capture = getattr(self._browser_computer, "end_action_capture", None)
        if not callable(end_capture):
            return None

        try:
            parameters = inspect.signature(end_capture).parameters
        except (TypeError, ValueError):
            parameters = {}

        if "persist" in parameters:
            capture_updates = end_capture(persist=persist)
            return capture_updates if isinstance(capture_updates, dict) else None

        # Backward-compatible fallback for browser doubles or older facades that
        # cannot discard captures explicitly. We still stop the capture; callers
        # should only rely on updates when persistence was requested.
        capture_updates = end_capture()
        if persist and isinstance(capture_updates, dict):
            return capture_updates
        return None

    def _clear_pending_action(self) -> None:
        clear_pending_action = getattr(
            self._browser_computer,
            "clear_pending_action",
            None,
        )
        if callable(clear_pending_action):
            clear_pending_action()

    def _clear_aria_caches(self) -> None:
        self._cached_raw_aria_snapshot_text = None
        self._cached_raw_aria_metadata = None

    def supports_function(self, name: str | None) -> bool:
        """Return whether `name` can be executed by this executor."""
        if name is None:
            return False
        if self._allowed_function_names is not None:
            return name in self._allowed_function_names
        return name in self._handlers or name in self._custom_functions

    def may_change_browser_state(self, name: str | None) -> bool:
        if name is None:
            return False
        return name in BROWSER_STATE_CHANGING_FUNCTIONS

    def serialize_function_response(
        self,
        executed_call: ExecutedCall,
        extra_response_fields: dict[str, Any] | None = None,
    ) -> types.FunctionResponse:
        if not is_env_state_result(executed_call.result):
            dict_result = executed_call.result
            if not isinstance(dict_result, dict):
                raise TypeError("Expected dict result for non-browser tool response")
            return types.FunctionResponse(
                name=executed_call.function_call.name,
                id=executed_call.function_call.id,
                response=dict_result,
            )

        env_state = executed_call.result
        response = self._build_env_state_response(env_state, extra_response_fields)
        parts = self._build_env_state_response_parts(env_state.screenshot)

        return types.FunctionResponse(
            name=executed_call.function_call.name,
            id=executed_call.function_call.id,
            response=response,
            parts=parts,
        )

    def _build_env_state_response(
        self,
        env_state: Any,
        extra_response_fields: dict[str, Any] | None,
    ) -> dict[str, Any]:
        response_fields = dict(extra_response_fields or {})
        response: dict[str, Any] = {"url": env_state.url}
        tab_metadata = self._compact_tab_metadata()
        if tab_metadata:
            response.update(tab_metadata)
        if self._grounding in {"vision", "mixed"}:
            response.update(self._coordinate_system_metadata(env_state))
        if self._grounding in {"text", "mixed"}:
            if self._cached_raw_aria_snapshot_text is None:
                self._capture_and_cache_aria_snapshot()
            aria_snapshot = self._cached_raw_aria_snapshot_text or ""
            aria_metadata = self._cached_raw_aria_metadata or {}
            response.update(
                {
                    "aria_snapshot": aria_snapshot,
                    **aria_metadata,
                }
            )
        response.update(response_fields)
        return response

    def _coordinate_system_metadata(self, env_state: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "coordinate_system": "viewport_css_pixels",
            "coordinate_instruction": (
                "For coordinate tools, use viewport CSS pixel coordinates "
                "matching the current screenshot."
            ),
        }
        viewport = getattr(env_state, "viewport", None)
        width = getattr(viewport, "width", 0)
        height = getattr(viewport, "height", 0)
        if isinstance(width, int) and width > 0:
            metadata["viewport_width"] = width
        if isinstance(height, int) and height > 0:
            metadata["viewport_height"] = height
        if (
            isinstance(width, int)
            and width > 0
            and isinstance(height, int)
            and height > 0
        ):
            metadata["coordinate_instruction"] = (
                "For coordinate tools, use viewport CSS pixel coordinates "
                "matching the current screenshot; "
                f"x must be 0-{width - 1} and y must be 0-{height - 1}. "
                "Do not use normalized 0-1000 coordinates."
            )
        return metadata

    def _compact_tab_metadata(self) -> dict[str, Any]:
        list_tabs = getattr(self._browser_computer, "list_tabs", None)
        if not callable(list_tabs):
            return {}
        try:
            tabs_payload = list_tabs()
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(tabs_payload, dict):
            return {}
        metadata: dict[str, Any] = {}
        for key in ("active_tab_index", "tab_count"):
            value = tabs_payload.get(key)
            if isinstance(value, int):
                metadata[key] = value
        return metadata

    def _build_env_state_response_parts(
        self,
        screenshot: bytes,
    ) -> list[types.FunctionResponsePart] | None:
        if self._grounding not in {"vision", "mixed"}:
            return None
        return [
            types.FunctionResponsePart(
                inline_data=types.FunctionResponseBlob(
                    mime_type="image/png",
                    data=screenshot,
                )
            )
        ]

    def execute(self, action: types.FunctionCall) -> ToolResult:
        name = action.name
        if name is None:
            raise ValueError(f"Unsupported function: {action}")
        if (
            self._allowed_function_names is not None
            and name not in self._allowed_function_names
        ):
            raise ValueError(f"Unsupported function: {action}")

        args = action.args or {}
        scope_violation = self._preflight_scope_violation(name, args)
        if scope_violation is not None:
            return scope_violation

        handler = self._handlers.get(name)
        if handler is not None:
            return self._record_tool_result(handler(args))

        custom_function = self._custom_functions.get(name)
        if custom_function is not None:
            filtered_args = self._filter_args(args, custom_function)
            return self._record_tool_result(custom_function(**filtered_args))

        raise ValueError(f"Unsupported function: {action}")

    def _preflight_scope_violation(
        self,
        name: str,
        args: dict[str, Any],
    ) -> dict[str, Any] | None:
        scope = self._navigation_scope
        if scope is None:
            return None

        url = args.get("url")
        if name in {"navigate", "open_web_browser"} and isinstance(url, str):
            if scope.blocks_search_url(url) or not scope.allows_url(url):
                return self._scope_error_payload(name, url)

        if name == "search":
            return self._scope_error_payload(name, "browser search page")

        return None

    def _scope_excluded_predefined_names(self) -> set[str]:
        if self._navigation_scope is None:
            return set()
        return {"search"}

    def _record_tool_result(self, result: ToolResult) -> ToolResult:
        if not is_env_state_result(result):
            return result
        self._last_call_produced_env_state = True
        return result

    def _scope_error_payload(self, name: str, url: str) -> dict[str, Any]:
        scope = self._navigation_scope
        message = (
            scope.violation_message(url)
            if scope is not None
            else f"Navigation blocked by task scope: {url}"
        )
        return {
            "status": "error",
            "tool_name": name,
            "error_type": "TaskScopeViolation",
            "error": message,
            "blocked_url": url,
        }

    def _filter_args(
        self, args: dict[str, Any], func: Callable[..., object]
    ) -> dict[str, Any]:
        sig = inspect.signature(func)
        valid_keys = {
            p.name for p in sig.parameters.values()
            if p.name != "self" and p.kind != inspect.Parameter.VAR_KEYWORD
        }
        return {k: v for k, v in args.items() if k in valid_keys}

    def _latest_artifact_metadata(self) -> dict[str, Any] | None:
        latest_artifacts_getter = getattr(
            self._browser_computer,
            "latest_artifact_metadata",
            None,
        )
        if callable(latest_artifacts_getter):
            latest_artifacts = latest_artifacts_getter()
            if isinstance(latest_artifacts, dict):
                return latest_artifacts
        return None


def compact_aria_snapshot_text(
    text: str,
    max_chars: int = MAX_ARIA_SNAPSHOT_CHARS,
) -> tuple[str, dict[str, Any]]:
    """Bound large ARIA snapshots before they enter model context."""
    if len(text) <= max_chars:
        return text, {}

    omitted_chars = len(text) - max_chars
    marker = (
        "\n... [ARIA snapshot truncated to stay within model context; "
        f"omitted {omitted_chars} characters. Use scroll/search/ref checks "
        "to inspect more of the page.]"
    )
    budget = max(max_chars - len(marker), 0)
    truncated = text[:budget].rstrip()
    newline_index = truncated.rfind("\n")
    if newline_index > max_chars // 2:
        truncated = truncated[:newline_index].rstrip()
    return (
        f"{truncated}{marker}",
        {
            "aria_snapshot_truncated": True,
            "aria_snapshot_original_chars": len(text),
        },
    )


def prune_old_screenshot_parts(
    contents: list[types.Content],
    max_recent_turns_with_screenshots: int,
) -> None:
    turn_with_screenshots_found = 0
    for content in reversed(contents):
        if content.role != "user" or not content.parts:
            continue

        has_screenshot = any(
            _is_screenshot_function_response(part)
            for part in content.parts
        )

        if not has_screenshot:
            continue

        turn_with_screenshots_found += 1
        if turn_with_screenshots_found <= max_recent_turns_with_screenshots:
            continue

        for part in content.parts:
            if _is_screenshot_function_response(part):
                part.function_response.parts = None


def _is_screenshot_function_response(part: types.Part) -> bool:
    return bool(
        part.function_response
        and part.function_response.parts
        and part.function_response.name in SCREENSHOT_RESPONSE_FUNCTIONS
    )


def prune_old_aria_parts(
    contents: list[types.Content],
    max_recent_turns_with_aria: int,
) -> None:
    """Remove aria_snapshot from old function responses to limit context size."""
    turns_found = 0
    for content in reversed(contents):
        if content.role != "user" or not content.parts:
            continue

        has_aria = any(
            part.function_response
            and isinstance(part.function_response.response, dict)
            and "aria_snapshot" in part.function_response.response
            for part in content.parts
        )
        if not has_aria:
            continue

        turns_found += 1
        if turns_found <= max_recent_turns_with_aria:
            continue

        for part in content.parts:
            if (
                part.function_response
                and isinstance(part.function_response.response, dict)
                and "aria_snapshot" in part.function_response.response
            ):
                part.function_response.response = {
                    k: v
                    for k, v in part.function_response.response.items()
                    if k != "aria_snapshot"
                }
