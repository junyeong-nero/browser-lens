"""
Descriptor functions for text/mixed grounding mode.

These are used ONLY for building LLM function declarations via
build_function_declaration(). Actual execution is handled by the
BrowserToolExecutor handler map.
"""
from typing import Literal


def observe_page() -> dict:
    """Observe the current browser state without changing it.

    Returns the current URL and ARIA snapshot with stable refs so you can
    re-orient when the page state is unclear. Does not navigate or reload; use
    navigate() to go to a URL.
    """
    ...


def open_web_browser(url: str = "") -> dict:
    """Open the browser and return the initial page state.

    Text/mixed grounding should use observe_page() to observe the current
    page or navigate() to change URL. This descriptor is kept so the vision
    tool set can still declare it.
    """
    ...


def navigate(url: str) -> dict:
    """Navigate the browser to a URL.

    Args:
        url: The full URL to navigate to (include https:// prefix when known).
    """
    ...


def go_back() -> dict:
    """Navigate back to the previous page in browser history."""
    ...


def go_forward() -> dict:
    """Navigate forward to the next page in browser history."""
    ...


def key_combination(keys: list[str]) -> dict:
    """Press a keyboard shortcut combination (e.g. Ctrl+C, Enter).

    Args:
        keys: List of key names to press together, e.g. ["Control", "A"].
    """
    ...


def wait_5_seconds() -> dict:
    """Wait 5 seconds for a page or animation to settle."""
    ...


def click_by_ref(ref: int) -> dict:
    """Click an element identified by its ARIA snapshot reference number.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot, e.g. [5].
    """
    ...


def select_option_by_ref(ref: int, option_label: str) -> dict:
    """Select an option in a native HTML select element by ARIA snapshot reference.

    Use this for standard HTML dropdowns where the select or combobox has a ref.
    Do not use it for custom dropdown widgets that are not backed by a native
    <select>; open those widgets and observe the page again before choosing.

    Args:
        ref: The integer ref for the native select/combobox shown in the ARIA snapshot.
        option_label: The visible option text or option value to select.
    """
    ...


def type_by_ref(ref: int, text: str, press_enter: bool = False) -> dict:
    """Type text into an element identified by its ARIA snapshot reference number.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot.
        text: The text to type into the element.
        press_enter: If True, press Enter after typing.
    """
    ...


def hover_by_ref(ref: int) -> dict:
    """Hover the mouse over an element by its ARIA snapshot reference number.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot.
    """
    ...


def scroll_by_ref(ref: int, direction: Literal["up", "down"] = "down") -> dict:
    """Scroll relative to an element by its ARIA snapshot reference number.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot.
        direction: Scroll direction — "up" or "down".
    """
    ...


def check_by_ref(ref: int) -> dict:
    """Return the current state of an element identified by its ARIA snapshot reference.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot.
    """
    ...


def wait_for_ref(
    ref: int,
    state: Literal["attached", "detached", "visible", "hidden"] = "visible",
    timeout_ms: int = 5000,
) -> dict:
    """Wait for an element identified by its ARIA snapshot reference to reach a state.

    Args:
        ref: The integer ref shown in brackets in the ARIA snapshot.
        state: Desired Playwright locator state.
        timeout_ms: Maximum time to wait in milliseconds.
    """
    ...


# Default descriptors exposed for text/mixed mode. Keep this set small so the
# model chooses among the browser actions that are actually used in logs.
TEXT_MODE_TOOL_DESCRIPTORS = [
    observe_page,
    navigate,
    go_back,
    key_combination,
    click_by_ref,
    select_option_by_ref,
    type_by_ref,
    scroll_by_ref,
    check_by_ref,
]
