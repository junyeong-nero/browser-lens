"""Descriptor functions for screenshot/coordinate grounding via chat models.

These descriptors expose coordinate-based browser controls as regular function
declarations for OpenAI-compatible endpoints that can accept image inputs.
"""

from typing import Literal

from tools.text_mode_tools import (
    go_back,
    go_forward,
    key_combination,
    navigate,
    open_web_browser,
    wait_5_seconds,
)


def click_at(x: int, y: int) -> dict:
    """Click a point in the current browser screenshot.

    Args:
        x: Horizontal coordinate in viewport CSS pixels, matching the screenshot.
        y: Vertical coordinate in viewport CSS pixels, matching the screenshot.
    """
    ...


def hover_at(x: int, y: int) -> dict:
    """Move the mouse over a point in the current browser screenshot.

    Args:
        x: Horizontal coordinate in viewport CSS pixels, matching the screenshot.
        y: Vertical coordinate in viewport CSS pixels, matching the screenshot.
    """
    ...


def type_text_at(
    x: int,
    y: int,
    text: str,
    press_enter: bool = False,
    clear_before_typing: bool = True,
) -> dict:
    """Click a point and type text there.

    Args:
        x: Horizontal coordinate in viewport CSS pixels, matching the screenshot.
        y: Vertical coordinate in viewport CSS pixels, matching the screenshot.
        text: Text to type.
        press_enter: Whether to press Enter after typing.
        clear_before_typing: Whether to clear existing field contents first.
    """
    ...


def scroll_at(
    x: int,
    y: int,
    direction: Literal["up", "down", "left", "right"] = "down",
    magnitude: int = 800,
) -> dict:
    """Scroll at a point in the current browser screenshot.

    Args:
        x: Horizontal coordinate in viewport CSS pixels, matching the screenshot.
        y: Vertical coordinate in viewport CSS pixels, matching the screenshot.
        direction: Direction to scroll.
        magnitude: Scroll amount in viewport CSS pixels.
    """
    ...


VISION_MODE_TOOL_DESCRIPTORS = [
    open_web_browser,
    navigate,
    go_back,
    go_forward,
    key_combination,
    wait_5_seconds,
    click_at,
    hover_at,
    type_text_at,
    scroll_at,
]
