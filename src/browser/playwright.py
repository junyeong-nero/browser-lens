import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, Optional, cast

import termcolor

if os.getenv("USE_PATCHRIGHT") == "1":
    try:
        import patchright.sync_api as playwright_sync_module  # type: ignore[import-not-found]
    except ImportError:
        import playwright.sync_api as playwright_sync_module
else:
    import playwright.sync_api as playwright_sync_module

playwright = type(sys)("playwright")  # placeholder so existing `playwright.sync_api.X` refs resolve
playwright.sync_api = playwright_sync_module  # type: ignore[attr-defined]
sync_playwright = playwright_sync_module.sync_playwright
PlaywrightError = playwright_sync_module.Error
PlaywrightTimeoutError = playwright_sync_module.TimeoutError

from .aria_snapshot import AriaSnapshot, NodeInfo, build_aria_snapshot
from .artifact_logger import ArtifactLogger
from .dom_interactive import (
    DOM_REF_ATTR,
    build_dom_node_infos,
    extract_dom_interactive,
    initial_occurrence_counter,
)
from .recording import BrowserRecordingHelper
from .state import BrowserState, EnvState, InteractionState, PageState, ViewportState
from .state_graph import browser_state_to_graph

FRAME_CAPTURE_FPS = 60
MOUSE_HIGHLIGHT_CAPTURE_DELAY_SECONDS = 0.28


PLAYWRIGHT_INSTALL_HINT = (
    "Playwright browser binaries are missing. Run "
    "`uv run playwright install chromium` and retry."
)

_STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'plugins', {
      get: () => [
        { name: 'Chrome PDF Plugin' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Native Client' },
      ],
    });
  } catch (e) {}
  try {
    window.chrome = window.chrome || { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
  } catch (e) {}
  try {
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
      window.navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : origQuery(params);
    }
  } catch (e) {}
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
      if (parameter === 37445) return 'Intel Inc.';
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.call(this, parameter);
    };
  } catch (e) {}
})();
"""

_REF_VISIBILITY_EVALUATE_ALL_SCRIPT = """
(elements, refsByNth) => {
  const result = {};
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  for (const [nthKey, ref] of Object.entries(refsByNth || {})) {
    const nth = Number(nthKey);
    const element = elements[nth];
    if (!element) continue;

    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const visible =
      style.visibility !== "hidden" &&
      style.display !== "none" &&
      !!(rect.width || rect.height || element.getClientRects().length);

    let inViewport = null;
    let distance = null;
    if (visible) {
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      inViewport =
        centerX >= 0 &&
        centerX <= viewportWidth &&
        centerY >= 0 &&
        centerY <= viewportHeight;
      distance = inViewport ? 0 : Math.min(Math.abs(centerY), Math.abs(centerY - viewportHeight));
    }

    result[String(ref)] = {
      visible,
      in_viewport: inViewport,
      viewport_distance: distance,
    };
  }
  return result;
}
"""


PLAYWRIGHT_KEY_MAP = {
    "backspace": "Backspace",
    "tab": "Tab",
    "return": "Enter",
    "enter": "Enter",
    "shift": "Shift",
    "control": "ControlOrMeta",
    "alt": "Alt",
    "escape": "Escape",
    "space": "Space",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "end": "End",
    "home": "Home",
    "left": "ArrowLeft",
    "up": "ArrowUp",
    "right": "ArrowRight",
    "down": "ArrowDown",
    "insert": "Insert",
    "delete": "Delete",
    "semicolon": ";",
    "equals": "=",
    "multiply": "Multiply",
    "add": "Add",
    "separator": "Separator",
    "subtract": "Subtract",
    "decimal": "Decimal",
    "divide": "Divide",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f11": "F11",
    "f12": "F12",
    "command": "Meta",
}


class PlaywrightBrowser:
    """Controls a local Chromium browser via Playwright."""

    def __init__(
        self,
        screen_size: tuple[int, int],
        initial_url: str = "https://www.duckduckgo.com",
        search_engine_url: str = "https://www.duckduckgo.com",
        highlight_mouse: bool = False,
        headless: bool = False,
        fit_window_to_screen: bool = False,
        artifact_logger: Optional[ArtifactLogger] = None,
        allowed_upload_roots: Optional[list[str | Path]] = None,
        channel: Optional[str] = None,
        user_agent: Optional[str] = None,
        locale: Optional[str] = None,
        timezone_id: Optional[str] = None,
        proxy: Optional[dict[str, str]] = None,
        storage_state_path: Optional[str | Path] = None,
        stealth: bool = False,
        extra_http_headers: Optional[dict[str, str]] = None,
    ):
        self._initial_url = initial_url
        self._screen_size = screen_size
        self._search_engine_url = search_engine_url
        self._highlight_mouse = highlight_mouse
        self._headless = headless
        self._fit_window_to_screen = fit_window_to_screen
        self._artifact_logger = artifact_logger if artifact_logger is not None else ArtifactLogger()
        self._allowed_upload_roots = self._normalize_upload_roots(allowed_upload_roots)
        self._channel = channel
        self._user_agent = user_agent
        self._locale = locale
        self._timezone_id = timezone_id
        self._proxy = proxy
        self._storage_state_path = Path(storage_state_path).expanduser() if storage_state_path else None
        self._stealth = stealth
        self._extra_http_headers = extra_http_headers
        self._recording = BrowserRecordingHelper(
            artifact_logger=self._artifact_logger,
            subprocess_module=subprocess,
            shutil_module=shutil,
        )
        self._aria_ref_map: dict[int, NodeInfo] | None = None
        self._aria_ref_target_map: dict[int, Any] | None = None
        self._history_aria_snapshot: AriaSnapshot | None = None
        self._previous_state: BrowserState | None = None
        self._pending_last_action: str | None = None

    def set_artifact_logger(self, artifact_logger: ArtifactLogger) -> None:
        """Swap the artifact logger (e.g. when starting a new session task).

        Installs the new logger without creating artifact directories until the
        task writes its first log artifact.
        """
        self._artifact_logger = artifact_logger
        self._recording.set_artifact_logger(artifact_logger)
        self._previous_state = None
        self._artifact_logger.prepare_log_dirs()

    def _normalize_upload_roots(
        self,
        allowed_upload_roots: Optional[list[str | Path]],
    ) -> list[Path]:
        roots = allowed_upload_roots
        if roots is None:
            roots = [Path.cwd(), Path(tempfile.gettempdir())]
        return [Path(root).expanduser().resolve() for root in roots]

    def _is_allowed_upload_path(self, path: Path) -> bool:
        for root in self._allowed_upload_roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    def reset_to_blank(self) -> None:
        """Recover from an aborted task: close popups, navigate to a blank page,
        and drop cached ARIA refs so the next task starts clean.
        """
        self._clear_aria_ref_cache()
        try:
            for page in list(self._context.pages):
                if page is not self._page:
                    try:
                        page.close()
                    except Exception:
                        pass
            self._page.goto("about:blank")
            self._page.wait_for_load_state()
        except Exception as exc:
            termcolor.cprint(
                f"Browser reset after task failure encountered an error: {exc}",
                color="yellow",
            )

    def _goto_or_blank(self, url: str, *, context: str) -> None:
        """Navigate to ``url`` and keep the browser usable if navigation fails."""
        try:
            self._page.goto(url)
        except playwright.sync_api.Error as exc:
            termcolor.cprint(
                f"{context} navigation failed for {url}: {exc}. "
                "Continuing from about:blank.",
                color="yellow",
            )
            try:
                self._page.goto("about:blank")
            except playwright.sync_api.Error as fallback_exc:
                termcolor.cprint(
                    "Fallback navigation to about:blank also failed; "
                    f"continuing with the current browser page: {fallback_exc}",
                    color="yellow",
                )

    def _handle_new_page(self, new_page: Any) -> None:
        self._page = new_page
        self._clear_aria_ref_cache()
        try:
            self._page.wait_for_load_state()
        except Exception as exc:
            termcolor.cprint(
                f"New page load-state wait failed: {exc}",
                color="yellow",
            )

    def __enter__(self):
        print("Creating session...")
        self._prepare_log_dirs()
        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--no-default-browser-check",
                "--no-first-run",
            ],
        }
        if self._fit_window_to_screen and not self._headless:
            launch_kwargs["args"].extend(
                [
                    f"--window-size={self._screen_size[0]},{self._screen_size[1]}",
                    "--window-position=0,0",
                ]
            )
        if self._channel:
            launch_kwargs["channel"] = self._channel
        if self._proxy:
            launch_kwargs["proxy"] = self._proxy
        try:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
        except playwright.sync_api.Error as exc:
            self._playwright.stop()
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(PLAYWRIGHT_INSTALL_HINT) from exc
            raise
        viewport_size: dict[str, int] = {
            "width": self._screen_size[0],
            "height": self._screen_size[1],
        }
        context_kwargs: dict[str, Any] = {"viewport": viewport_size}
        if self._user_agent:
            context_kwargs["user_agent"] = self._user_agent
        if self._locale:
            context_kwargs["locale"] = self._locale
        if self._timezone_id:
            context_kwargs["timezone_id"] = self._timezone_id
        if self._extra_http_headers:
            context_kwargs["extra_http_headers"] = self._extra_http_headers
        if self._storage_state_path and self._storage_state_path.is_file():
            context_kwargs["storage_state"] = str(self._storage_state_path)
        video_dir = self.video_dir()
        if video_dir:
            self._artifact_logger.prepare_video_dir()
            context_kwargs["record_video_dir"] = str(video_dir)
            context_kwargs["record_video_size"] = viewport_size
        self._context = self._browser.new_context(**context_kwargs)
        if self._stealth:
            self._context.add_init_script(_STEALTH_INIT_SCRIPT)
        self._page = self._context.new_page()
        self._goto_or_blank(self._initial_url, context="Initial page")
        self._context.on("page", self._handle_new_page)
        termcolor.cprint("Started local playwright.", color="green", attrs=["bold"])
        history_dir = self.history_dir()
        if history_dir:
            print(f"Logging Playwright history to {history_dir.parent}")
        self._start_frame_stream()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        close_error: BaseException | None = None
        try:
            self._stop_frame_stream()
            context = getattr(self, "_context", None)
            if context:
                if self._storage_state_path:
                    try:
                        self._storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(self._storage_state_path))
                    except Exception as exc:
                        termcolor.cprint(
                            f"Failed to persist storage_state to {self._storage_state_path}: {exc}",
                            color="yellow",
                        )
                try:
                    context.close()
                except Exception as exc:
                    close_error = exc
                    termcolor.cprint(f"Failed to close browser context: {exc}", color="yellow")
            browser = getattr(self, "_browser", None)
            if browser:
                try:
                    browser.close()
                except Exception as exc:
                    if "Browser.close: Connection closed while reading from the driver" not in str(exc):
                        close_error = close_error or exc
                        termcolor.cprint(f"Failed to close browser: {exc}", color="yellow")
        finally:
            playwright_runtime = getattr(self, "_playwright", None)
            if playwright_runtime:
                playwright_runtime.stop()
        if close_error is not None and exc_type is None:
            raise close_error

    def open_web_browser(self) -> EnvState:
        self._mark_last_action("open_web_browser")
        return self.current_state()

    def click_at(self, x: int, y: int) -> EnvState:
        self._mark_last_action("click_at")
        self.highlight_click_target(x, y, kind="click")
        self._page.mouse.click(x, y)
        return self._state_after_load()

    def hover_at(self, x: int, y: int) -> EnvState:
        self._mark_last_action("hover_at")
        self.highlight_mouse(x, y, kind="hover")
        self._page.mouse.move(x, y)
        return self._state_after_load()

    def type_text_at(
        self,
        x: int,
        y: int,
        text: str,
        press_enter: bool = False,
        clear_before_typing: bool = True,
    ) -> EnvState:
        self._mark_last_action("type_text_at")
        self.highlight_click_target(x, y, kind="type")
        self._page.mouse.click(x, y)
        self._page.wait_for_load_state()

        if clear_before_typing:
            if sys.platform == "darwin":
                self._press_key_combination(["Command", "A"])
            else:
                self._press_key_combination(["Control", "A"])
            self._press_key_combination(["Delete"])

        self._page.keyboard.type(text)
        self._page.wait_for_load_state()

        if press_enter:
            self._press_key_combination(["Enter"])
        self._page.wait_for_load_state()
        return self.current_state()

    def _horizontal_document_scroll(self, direction: Literal["left", "right"]) -> EnvState:
        self._mark_last_action("scroll_document")
        horizontal_scroll_amount = self.screen_size()[0] // 2
        sign = "" if direction == "right" else "-"
        self._page.evaluate(f"window.scrollBy({sign}{horizontal_scroll_amount}, 0); ")
        return self._state_after_load()

    def scroll_document(self, direction: Literal["up", "down", "left", "right"]) -> EnvState:
        self._mark_last_action("scroll_document")
        if direction == "down":
            return self.key_combination(["PageDown"])
        elif direction == "up":
            return self.key_combination(["PageUp"])
        elif direction in ("left", "right"):
            return self._horizontal_document_scroll(direction)
        else:
            raise ValueError("Unsupported direction: ", direction)

    def scroll_at(
        self,
        x: int,
        y: int,
        direction: Literal["up", "down", "left", "right"],
        magnitude: int = 800,
    ) -> EnvState:
        self._mark_last_action("scroll_at")
        self.highlight_mouse(x, y, kind=f"scroll-{direction}")
        self._page.mouse.move(x, y)
        self._page.wait_for_load_state()

        dx = 0
        dy = 0
        if direction == "up":
            dy = -magnitude
        elif direction == "down":
            dy = magnitude
        elif direction == "left":
            dx = -magnitude
        elif direction == "right":
            dx = magnitude
        else:
            raise ValueError("Unsupported direction: ", direction)

        self._page.mouse.wheel(dx, dy)
        return self._state_after_load()

    def wait_5_seconds(self) -> EnvState:
        self._mark_last_action("wait_5_seconds")
        time.sleep(5)
        return self.current_state()

    def go_back(self) -> EnvState:
        self._mark_last_action("go_back")
        self._clear_aria_ref_cache()
        self._page.go_back()
        return self._state_after_load()

    def go_forward(self) -> EnvState:
        self._mark_last_action("go_forward")
        self._clear_aria_ref_cache()
        self._page.go_forward()
        return self._state_after_load()

    def search(self) -> EnvState:
        self._mark_last_action("search")
        return self.navigate(self._search_engine_url)

    def navigate(self, url: str) -> EnvState:
        self._mark_last_action("navigate")
        self._clear_aria_ref_cache()
        normalized_url = url if url.startswith(("http://", "https://")) else "https://" + url
        self._goto_or_blank(normalized_url, context="Page")
        return self._state_after_load()

    def take_aria_snapshot(self) -> AriaSnapshot:
        """Take an ARIA snapshot, assign integer refs, and cache the ref map.

        Reuses the snapshot captured for the current state's history .a11y.yaml
        so each logged step captures the frame-aware snapshot once.
        """
        if self._history_aria_snapshot is not None:
            snapshot = self._history_aria_snapshot
            self._history_aria_snapshot = None
            self._aria_ref_map = snapshot.ref_map
            return snapshot
        try:
            snapshot, _source, _frame_count = self._capture_frame_aware_aria_snapshot()
        except Exception as exc:
            termcolor.cprint(
                f"ARIA snapshot capture failed: {exc}",
                color="yellow",
            )
            snapshot = AriaSnapshot(text="", ref_map={}, url=self._page.url)
            self._aria_ref_target_map = {}
        self._aria_ref_map = snapshot.ref_map
        return snapshot

    def resolve_ref(self, ref: int) -> Any:
        """Resolve an integer ref to a Playwright Locator using the cached ref map."""
        if self._aria_ref_map is None:
            raise ValueError("No ARIA snapshot cached. Call take_aria_snapshot() first.")
        node = self._aria_ref_map.get(ref)
        if node is None:
            raise ValueError(f"ref {ref} is stale, request a new snapshot")
        if node.nth < 0:
            raise ValueError(f"NodeInfo.nth must be >= 0, got {node.nth} for ref {ref}")
        # Skip name param if empty to avoid selector matching empty name attribute
        target = self._page
        if self._aria_ref_target_map is not None:
            target = self._aria_ref_target_map.get(ref, self._page)
        role_target = cast(Any, target)
        if node.dom_ref:
            return role_target.locator(f'[{DOM_REF_ATTR}="{node.dom_ref}"]').first
        if node.name:
            locator = role_target.get_by_role(node.role, name=node.name)
        else:
            locator = role_target.get_by_role(node.role)
        return locator.nth(node.nth)

    def measure_ref_visibility(self, refs: list[int]) -> dict[int, dict[str, bool | float | None]]:
        """Measure visibility metadata for ARIA refs with grouped browser API calls."""
        if self._aria_ref_map is None:
            raise ValueError("No ARIA snapshot cached. Call take_aria_snapshot() first.")

        target_by_id: dict[int, Any] = {}
        grouped_refs: dict[tuple[int, str, str, str], dict[str, int]] = {}
        for ref in refs:
            node = self._aria_ref_map.get(ref)
            if node is None or node.nth < 0:
                continue

            target = self._page
            if self._aria_ref_target_map is not None:
                target = self._aria_ref_target_map.get(ref, self._page)
            target_id = id(target)
            target_by_id[target_id] = target

            if node.dom_ref:
                selector = f'[{DOM_REF_ATTR}="{node.dom_ref}"]'
                key = (target_id, "selector", selector, "")
                nth = 0
            else:
                key = (target_id, "role", node.role, node.name)
                nth = node.nth
            grouped_refs.setdefault(key, {})[str(nth)] = ref

        visibility_by_ref: dict[int, dict[str, bool | float | None]] = {}
        for (target_id, kind, selector_or_role, name), refs_by_nth in grouped_refs.items():
            target = target_by_id[target_id]
            try:
                if kind == "selector":
                    locator = target.locator(selector_or_role)
                elif name:
                    locator = target.get_by_role(selector_or_role, name=name)
                else:
                    locator = target.get_by_role(selector_or_role)
                group_visibility = locator.evaluate_all(
                    _REF_VISIBILITY_EVALUATE_ALL_SCRIPT,
                    refs_by_nth,
                )
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(group_visibility, dict):
                continue
            for raw_ref, visibility in group_visibility.items():
                try:
                    ref = int(raw_ref)
                except (TypeError, ValueError):
                    continue
                if isinstance(visibility, dict):
                    visibility_by_ref[ref] = {
                        "visible": visibility.get("visible"),
                        "in_viewport": visibility.get("in_viewport"),
                        "viewport_distance": visibility.get("viewport_distance"),
                    }
        return visibility_by_ref

    def reload_page(self) -> EnvState:
        self._mark_last_action("reload_page")
        self._clear_aria_ref_cache()
        self._page.reload()
        return self._state_after_load()

    def list_tabs(self) -> dict[str, Any]:
        pages = list(self._context.pages)
        active_index = self._active_tab_index(pages)
        tabs = []
        for index, page in enumerate(pages):
            try:
                title = page.title()
            except Exception:  # noqa: BLE001
                title = ""
            tabs.append(
                {
                    "index": index,
                    "url": getattr(page, "url", ""),
                    "title": title,
                    "active": index == active_index,
                }
            )
        return {
            "active_tab_index": active_index,
            "tab_count": len(pages),
            "tabs": tabs,
        }

    def switch_to_next_tab(self) -> EnvState:
        self._mark_last_action("switch_to_next_tab")
        self._switch_tab(direction=1)
        return self._state_after_load()

    def switch_to_previous_tab(self) -> EnvState:
        self._mark_last_action("switch_to_previous_tab")
        self._switch_tab(direction=-1)
        return self._state_after_load()

    def switch_to_tab(self, index: int) -> EnvState:
        self._mark_last_action("switch_to_tab")
        pages = list(self._context.pages)
        if index < 0 or index >= len(pages):
            raise ValueError(f"Invalid tab index {index}; tab_count={len(pages)}")
        self._focus_tab(pages[index])
        return self._state_after_load()

    def close_current_tab(self) -> EnvState:
        self._mark_last_action("close_current_tab")
        pages = list(self._context.pages)
        if len(pages) <= 1:
            raise ValueError("Cannot close the only open tab")
        current_index = self._active_tab_index(pages)
        if current_index < 0:
            current_index = 0
        target_index = current_index - 1 if current_index > 0 else 1
        current_page = pages[current_index]
        target_page = pages[target_index]
        current_page.close()
        self._focus_tab(target_page)
        return self._state_after_load()

    def upload_file(self, x: int, y: int, path: str) -> EnvState:
        self._mark_last_action("upload_file")
        raw_path = Path(path).expanduser()
        if not raw_path.is_absolute():
            raise ValueError(f"upload_file requires an absolute path; got: {path}")
        if not raw_path.exists():
            raise FileNotFoundError(f"upload_file target does not exist: {path}")
        resolved_path = raw_path.resolve(strict=True)
        if not self._is_allowed_upload_path(resolved_path):
            roots = ", ".join(str(root) for root in self._allowed_upload_roots)
            raise PermissionError(
                f"upload_file target is outside allowed upload roots: {resolved_path}. "
                f"Allowed roots: {roots}"
            )

        with self._page.expect_file_chooser() as file_chooser_info:
            self.highlight_click_target(x, y, kind="upload")
            self._page.mouse.click(x, y)
        file_chooser_info.value.set_files(str(resolved_path))
        return self.current_state()

    def get_accessibility_tree(self) -> dict[str, Any]:
        try:
            snapshot, source, frame_count = self._capture_frame_aware_aria_snapshot()
        except Exception as exc:
            return {
                "tree": None,
                "url": self._page.url,
                "source": "body_locator_aria_snapshot",
                "status": "error",
                "error": str(exc),
                "frame_count": 0,
            }
        self._aria_ref_map = snapshot.ref_map
        return {
            "tree": snapshot.text,
            "url": self._page.url,
            "source": source,
            "status": "captured",
            "error": None,
            "frame_count": frame_count,
        }

    def _press_key_combination(self, keys: list[str]) -> None:
        keys = [PLAYWRIGHT_KEY_MAP.get(k.lower(), k) for k in keys]
        held_keys = keys[:-1]
        for key in held_keys:
            self._page.keyboard.down(key)
        try:
            self._page.keyboard.press(keys[-1])
        finally:
            for key in reversed(held_keys):
                self._page.keyboard.up(key)

    def key_combination(self, keys: list[str]) -> EnvState:
        self._mark_last_action("key_combination")
        self._press_key_combination(keys)
        return self.current_state()

    def drag_and_drop(
        self, x: int, y: int, destination_x: int, destination_y: int
    ) -> EnvState:
        self._mark_last_action("drag_and_drop")
        self.highlight_mouse(x, y, kind="drag-start")
        self._page.mouse.move(x, y)
        self._page.wait_for_load_state()
        self._page.mouse.down()
        self._page.wait_for_load_state()
        self.highlight_mouse(destination_x, destination_y, kind="drag-end")
        self._page.mouse.move(destination_x, destination_y)
        self._page.wait_for_load_state()
        self._page.mouse.up()
        return self.current_state()

    def _state_after_load(self) -> EnvState:
        self._page.wait_for_load_state()
        return self.current_state()

    def current_state(self) -> EnvState:
        self._page.wait_for_load_state()
        time.sleep(0.5)
        screenshot_bytes = self._page.screenshot(
            type="png",
            full_page=False,
            scale="css",
        )
        self._recording.update_frame_buffer(screenshot_bytes)
        viewport_width, viewport_height = self.screen_size()
        scroll_x, scroll_y = self._scroll_position()
        available_refs = sorted(self._aria_ref_map.keys()) if self._aria_ref_map else []
        last_action = self._pending_last_action
        self._pending_last_action = None
        state = EnvState(
            page=PageState(
                url=self._page.url,
                title=self._page.title(),
            ),
            viewport=ViewportState(
                screenshot=screenshot_bytes,
                width=viewport_width,
                height=viewport_height,
                scroll_x=scroll_x,
                scroll_y=scroll_y,
            ),
            interaction=InteractionState(
                focused_element=self._focused_element(),
                available_refs=available_refs,
                last_action=last_action,
            ),
        )
        previous_state = self._previous_state
        artifact_metadata = self._write_history_snapshot(state, previous_state)
        self._previous_state = state
        if artifact_metadata is None:
            return state
        return EnvState(
            page=state.page.model_copy(
                update={
                    "html_path": self._artifact_path(artifact_metadata, "html_path"),
                    "a11y_path": self._artifact_path(artifact_metadata, "a11y_path"),
                }
            ),
            viewport=state.viewport,
            interaction=state.interaction,
        )

    def _scroll_position(self) -> tuple[int, int]:
        position = self._page.evaluate(
            "() => ({ scrollX: window.scrollX, scrollY: window.scrollY })"
        )
        if not isinstance(position, dict):
            return 0, 0
        return int(position.get("scrollX", 0)), int(position.get("scrollY", 0))

    def _focused_element(self) -> str | None:
        focused = self._page.evaluate(
            """
            () => {
              const el = document.activeElement;
              if (!el || el === document.body) return null;
              const tag = el.tagName ? el.tagName.toLowerCase() : '';
              const id = el.id ? `#${el.id}` : '';
              const name = el.getAttribute && el.getAttribute('name')
                ? `[name=${el.getAttribute('name')}]`
                : '';
              return `${tag}${id}${name}` || null;
            }
            """
        )
        return focused if isinstance(focused, str) else None

    def _artifact_path(self, metadata: dict[str, Any] | None, key: str) -> str | None:
        if metadata is None:
            return None
        value = metadata.get(key)
        return value if isinstance(value, str) else None

    def _mark_last_action(self, action_name: str) -> None:
        self._history_aria_snapshot = None
        if self._pending_last_action is None:
            self._pending_last_action = action_name

    def clear_pending_action(self, action_name: str | None = None) -> None:
        if action_name is None or self._pending_last_action == action_name:
            self._pending_last_action = None

    def screen_size(self) -> tuple[int, int]:
        viewport_size = self._page.viewport_size
        if viewport_size:
            return viewport_size["width"], viewport_size["height"]
        inner_size = self._window_inner_size()
        if inner_size is not None:
            return inner_size
        return self._screen_size

    def _window_inner_size(self) -> tuple[int, int] | None:
        try:
            size = self._page.evaluate(
                """
                () => ({
                  width: window.innerWidth || document.documentElement.clientWidth || 0,
                  height: window.innerHeight || document.documentElement.clientHeight || 0,
                })
                """
            )
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(size, dict):
            return None
        try:
            width = int(size.get("width", 0))
            height = int(size.get("height", 0))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    def highlight_mouse(self, x: int, y: int, *, kind: str = "pointer") -> None:
        if not self._highlight_mouse:
            return
        self._page.evaluate(
            """
            ({ x, y, kind }) => {
                const styleId = "tiny-browser-agent-pointer-highlight-style";
                if (!document.getElementById(styleId)) {
                    const style = document.createElement("style");
                    style.id = styleId;
                    style.textContent = `
                        .tiny-browser-agent-pointer-highlight {
                            position: fixed;
                            left: 0;
                            top: 0;
                            width: 44px;
                            height: 44px;
                            --tba-highlight-color: #3182f6;
                            --tba-highlight-fill: rgba(49, 130, 246, .12);
                            --tba-highlight-border: rgba(49, 130, 246, .42);
                            border-radius: 999px;
                            box-sizing: border-box;
                            pointer-events: none;
                            z-index: 2147483647;
                            transform: translate(-50%, -50%) scale(.72);
                            animation: tba-pointer-fade 920ms cubic-bezier(.2, 0, .2, 1) forwards;
                        }
                        .tiny-browser-agent-pointer-highlight::before,
                        .tiny-browser-agent-pointer-highlight::after {
                            position: absolute;
                            pointer-events: none;
                        }
                        .tiny-browser-agent-pointer-highlight::before {
                            content: "";
                            inset: 0;
                            border: 2px solid var(--tba-highlight-border);
                            border-radius: 999px;
                            background: var(--tba-highlight-fill);
                            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .66);
                            animation: tba-pointer-ripple 920ms cubic-bezier(.2, 0, .2, 1) forwards;
                        }
                        .tiny-browser-agent-pointer-highlight::after {
                            content: "";
                            left: 50%;
                            top: 50%;
                            width: 8px;
                            height: 8px;
                            border-radius: 999px;
                            background: var(--tba-highlight-color);
                            box-shadow: 0 0 0 4px var(--tba-highlight-fill);
                            transform: translate(-50%, -50%);
                        }
                        .tiny-browser-agent-pointer-highlight[data-kind^="drag"] {
                            --tba-highlight-color: #0b57d0;
                            --tba-highlight-fill: rgba(11, 87, 208, .12);
                            --tba-highlight-border: rgba(11, 87, 208, .38);
                        }
                        .tiny-browser-agent-pointer-highlight[data-kind^="scroll"] {
                            --tba-highlight-color: #0b57d0;
                            --tba-highlight-fill: rgba(11, 87, 208, .12);
                            --tba-highlight-border: rgba(11, 87, 208, .38);
                        }
                        .tiny-browser-agent-pointer-highlight[data-kind="hover"] {
                            --tba-highlight-color: #4e5968;
                            --tba-highlight-fill: rgba(78, 89, 104, .12);
                            --tba-highlight-border: rgba(78, 89, 104, .34);
                        }
                        .tiny-browser-agent-pointer-highlight[data-kind="type"] {
                            --tba-highlight-color: #4e5968;
                            --tba-highlight-fill: rgba(78, 89, 104, .12);
                            --tba-highlight-border: rgba(78, 89, 104, .34);
                        }
                        .tiny-browser-agent-pointer-highlight[data-kind="upload"] {
                            --tba-highlight-color: #4e5968;
                            --tba-highlight-fill: rgba(78, 89, 104, .12);
                            --tba-highlight-border: rgba(78, 89, 104, .34);
                        }
                        @keyframes tba-pointer-fade {
                            0% { opacity: 0; transform: translate(-50%, -50%) scale(.72); }
                            10% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
                            62% { opacity: .92; transform: translate(-50%, -50%) scale(1); }
                            100% { opacity: 0; transform: translate(-50%, -50%) scale(1.02); }
                        }
                        @keyframes tba-pointer-ripple {
                            0% { opacity: 0; transform: scale(.72); }
                            14% { opacity: .42; transform: scale(.86); }
                            100% { opacity: 0; transform: scale(1.36); }
                        }
                    `;
                    document.head.appendChild(style);
                }

                const rawKind = String(kind || "pointer");
                const marker = document.createElement("div");
                marker.className = "tiny-browser-agent-pointer-highlight";
                marker.dataset.kind = rawKind;
                marker.style.left = `${Math.round(x)}px`;
                marker.style.top = `${Math.round(y)}px`;
                document.documentElement.appendChild(marker);
                setTimeout(() => marker.remove(), 980);
            }
            """,
            {"x": int(x), "y": int(y), "kind": kind},
        )
        time.sleep(MOUSE_HIGHLIGHT_CAPTURE_DELAY_SECONDS)

    def highlight_click_target(self, x: int, y: int, *, kind: str = "click") -> None:
        """Highlight the actionable element under a click point, falling back to a point marker."""
        if not self._highlight_mouse:
            return
        box = self._element_box_at_point(x, y)
        if box is not None and self._highlight_element_box(box, kind=kind):
            return
        self.highlight_mouse(x, y, kind=kind)

    def highlight_locator(self, locator: Any, *, kind: str = "click") -> None:
        """Highlight the bounds of a resolved locator when mouse highlighting is enabled."""
        if not self._highlight_mouse:
            return
        try:
            locator.scroll_into_view_if_needed(timeout=1_000)
        except TypeError:
            try:
                locator.scroll_into_view_if_needed()
            except Exception:
                pass
        except Exception:
            pass
        try:
            box = locator.bounding_box(timeout=1_000)
        except TypeError:
            box = locator.bounding_box()
        except Exception:
            return
        normalized_box = self._normalize_highlight_box(box)
        if normalized_box is None:
            return
        if self._highlight_element_box(normalized_box, kind=kind):
            return
        self.highlight_mouse(
            int(normalized_box["x"] + normalized_box["width"] / 2),
            int(normalized_box["y"] + normalized_box["height"] / 2),
            kind=kind,
        )

    def _element_box_at_point(self, x: int, y: int) -> dict[str, int] | None:
        try:
            box = self._page.evaluate(
                """
                ({ x, y }) => {
                    const pointX = Number(x);
                    const pointY = Number(y);
                    if (!Number.isFinite(pointX) || !Number.isFinite(pointY)) return null;

                    const leaf = document.elementFromPoint(pointX, pointY);
                    if (!leaf || !(leaf instanceof Element)) return null;

                    const actionableSelector = [
                        "button",
                        "a[href]",
                        "input",
                        "select",
                        "textarea",
                        "summary",
                        "label",
                        "[onclick]",
                        "[role='button']",
                        "[role='link']",
                        "[role='tab']",
                        "[role='checkbox']",
                        "[role='radio']",
                        "[role='menuitem']",
                        "[role='option']",
                        "[tabindex]:not([tabindex='-1'])"
                    ].join(",");
                    const target = leaf.closest(actionableSelector);
                    if (!target || target === document.body || target === document.documentElement) {
                        return null;
                    }

                    const style = window.getComputedStyle(target);
                    if (style.display === "none" || style.visibility === "hidden") return null;

                    const rect = target.getBoundingClientRect();
                    if (rect.width < 2 || rect.height < 2) return null;
                    return {
                        x: rect.left,
                        y: rect.top,
                        width: rect.width,
                        height: rect.height
                    };
                }
                """,
                {"x": int(x), "y": int(y)},
            )
        except Exception:
            return None
        return self._normalize_highlight_box(box)

    def _normalize_highlight_box(self, box: Any) -> dict[str, int] | None:
        if not isinstance(box, dict):
            return None
        try:
            x = float(box["x"])
            y = float(box["y"])
            width = float(box["width"])
            height = float(box["height"])
        except (KeyError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return {
            "x": int(round(x)),
            "y": int(round(y)),
            "width": max(1, int(round(width))),
            "height": max(1, int(round(height))),
        }

    def _highlight_element_box(self, box: dict[str, int], *, kind: str = "click") -> bool:
        if not self._highlight_mouse:
            return False
        try:
            highlighted = self._page.evaluate(
                """
                ({ x, y, width, height, kind }) => {
                    const rect = {
                        x: Number(x),
                        y: Number(y),
                        width: Number(width),
                        height: Number(height)
                    };
                    if (
                        !Number.isFinite(rect.x) ||
                        !Number.isFinite(rect.y) ||
                        !Number.isFinite(rect.width) ||
                        !Number.isFinite(rect.height) ||
                        rect.width <= 0 ||
                        rect.height <= 0
                    ) {
                        return false;
                    }

                    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
                    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
                    const pad = Math.max(
                        6,
                        Math.min(18, Math.round(Math.min(rect.width, rect.height) * .16))
                    );
                    const left = Math.max(0, Math.round(rect.x - pad));
                    const top = Math.max(0, Math.round(rect.y - pad));
                    const right = Math.min(viewportWidth, Math.round(rect.x + rect.width + pad));
                    const bottom = Math.min(viewportHeight, Math.round(rect.y + rect.height + pad));
                    if (right <= 0 || bottom <= 0 || left >= viewportWidth || top >= viewportHeight) {
                        return false;
                    }

                    const rawKind = String(kind || "target");
                    const palette = rawKind === "hover" || rawKind === "type" || rawKind === "upload"
                        ? {
                            border: "rgba(78, 89, 104, .42)",
                            fill: "rgba(78, 89, 104, .10)",
                            ripple: "rgba(78, 89, 104, .28)"
                        }
                        : {
                            border: "rgba(49, 130, 246, .50)",
                            fill: "rgba(49, 130, 246, .12)",
                            ripple: "rgba(49, 130, 246, .30)"
                        };
                    const overlayWidth = Math.max(24, right - left);
                    const overlayHeight = Math.max(24, bottom - top);
                    const marker = document.createElement("div");
                    marker.className = "tiny-browser-agent-element-highlight";
                    marker.dataset.kind = rawKind;
                    Object.assign(marker.style, {
                        position: "fixed",
                        left: `${left}px`,
                        top: `${top}px`,
                        width: `${overlayWidth}px`,
                        height: `${overlayHeight}px`,
                        minWidth: "24px",
                        minHeight: "24px",
                        border: `2px solid ${palette.border}`,
                        borderRadius: "12px",
                        background: palette.fill,
                        boxShadow: "inset 0 0 0 1px rgba(255, 255, 255, .70), 0 8px 22px rgba(25, 31, 40, .08)",
                        boxSizing: "border-box",
                        pointerEvents: "none",
                        zIndex: "2147483647",
                        opacity: "0",
                        transform: "scale(.99)"
                    });

                    const ripple = document.createElement("div");
                    Object.assign(ripple.style, {
                        position: "absolute",
                        inset: "-2px",
                        border: `2px solid ${palette.ripple}`,
                        borderRadius: "inherit",
                        opacity: "0",
                        transform: "scale(.96)",
                        pointerEvents: "none"
                    });

                    marker.appendChild(ripple);
                    document.documentElement.appendChild(marker);
                    if (typeof marker.animate === "function") {
                        marker.animate(
                            [
                                { opacity: 0, transform: "scale(.99)" },
                                { opacity: 1, transform: "scale(1)", offset: .12 },
                                { opacity: .92, transform: "scale(1)", offset: .64 },
                                { opacity: 0, transform: "scale(1.01)" }
                            ],
                            { duration: 920, easing: "cubic-bezier(.2, 0, .2, 1)", fill: "forwards" }
                        );
                        ripple.animate(
                            [
                                { opacity: 0, transform: "scale(.96)" },
                                { opacity: .38, transform: "scale(1)", offset: .14 },
                                { opacity: .12, transform: "scale(1.10)", offset: .58 },
                                { opacity: 0, transform: "scale(1.18)" }
                            ],
                            { duration: 920, easing: "cubic-bezier(.2, 0, .2, 1)", fill: "forwards" }
                        );
                    } else {
                        marker.style.transition = "opacity 920ms cubic-bezier(.2, 0, .2, 1), transform 920ms cubic-bezier(.2, 0, .2, 1)";
                        ripple.style.transition = "opacity 920ms cubic-bezier(.2, 0, .2, 1), transform 920ms cubic-bezier(.2, 0, .2, 1)";
                        requestAnimationFrame(() => {
                            marker.style.opacity = "1";
                            marker.style.transform = "scale(1)";
                            ripple.style.opacity = ".20";
                            ripple.style.transform = "scale(1.14)";
                        });
                    }
                    setTimeout(() => marker.remove(), 980);
                    return true;
                }
                """,
                {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                    "kind": kind,
                },
            )
        except Exception:
            return False
        if highlighted:
            time.sleep(MOUSE_HIGHLIGHT_CAPTURE_DELAY_SECONDS)
        return bool(highlighted)


    def _start_frame_stream(self) -> None:
        try:
            self._recording.start_frame_stream(fps=FRAME_CAPTURE_FPS)
        except Exception as exc:
            termcolor.cprint(f"Frame stream startup failed: {exc}", color="yellow")

    def _stop_frame_stream(self) -> None:
        self._recording.stop_frame_stream()

    def begin_action_capture(self) -> None:
        """Best-effort capture of frames emitted while a browser action runs."""
        self._recording.begin_action_capture(page=self._page, context=self._context)

    def end_action_capture(self, *, persist: bool = True) -> dict[str, Any] | None:
        return self._recording.end_action_capture(persist=persist)

    def _prepare_log_dirs(self):
        self._artifact_logger.prepare_log_dirs()

    def _active_tab_index(self, pages: list[Any] | None = None) -> int:
        pages = list(self._context.pages) if pages is None else pages
        try:
            return pages.index(self._page)
        except ValueError:
            return -1

    def _clear_aria_ref_cache(self) -> None:
        self._aria_ref_map = None
        self._aria_ref_target_map = None
        self._history_aria_snapshot = None

    def _focus_tab(self, page: Any) -> None:
        self._page = page
        self._page.bring_to_front()
        self._clear_aria_ref_cache()

    def _switch_tab(self, direction: int) -> None:
        pages = list(self._context.pages)
        if not pages:
            return
        current_index = self._active_tab_index(pages)
        if current_index < 0:
            current_index = 0
        next_index = (current_index + direction) % len(pages)
        self._focus_tab(pages[next_index])

    def latest_artifact_metadata(self) -> Optional[dict]:
        return self._artifact_logger.latest_artifact_metadata()

    def history_dir(self) -> Optional[Path]:
        return self._artifact_logger.history_dir()

    def video_dir(self) -> Optional[Path]:
        return self._artifact_logger.video_dir()

    def _aria_snapshot_targets(self) -> list[Any]:
        frames = getattr(self._page, "frames", None)
        if isinstance(frames, list) and frames:
            return frames
        return [self._page]

    def _capture_frame_aware_aria_snapshot(self) -> tuple[AriaSnapshot, str, int]:
        targets = self._aria_snapshot_targets()
        multi_frame = len(targets) > 1
        combined_lines: list[str] = []
        combined_ref_map: dict[int, NodeInfo] = {}
        target_map: dict[int, Any] = {}
        ref_offset = 0
        captured_frame_count = 0

        for index, target in enumerate(targets, start=1):
            target_url = getattr(target, "url", self._page.url)
            try:
                raw_yaml = target.locator("html > body").aria_snapshot()
            except Exception as exc:
                if multi_frame:
                    combined_lines.append(f"Frame {index}: {target_url}")
                    combined_lines.append(f"  [ARIA snapshot failed: {exc}]")
                    continue
                raise
            snapshot = build_aria_snapshot(raw_yaml, target_url, ref_offset=ref_offset)
            frame_ref_map: dict[int, NodeInfo] = dict(snapshot.ref_map)
            frame_lines = snapshot.text.splitlines() if snapshot.text else []

            dom_nodes = extract_dom_interactive(target)
            if dom_nodes:
                counter = initial_occurrence_counter(frame_ref_map)
                dom_entries, dom_lines, _ = build_dom_node_infos(
                    dom_nodes,
                    counter,
                    next_ref=ref_offset + len(frame_ref_map) + 1,
                )
                if dom_entries:
                    frame_ref_map.update(dom_entries)
                    frame_lines.append("# dom-augmented (aria-hidden / inert / shadow):")
                    frame_lines.extend(dom_lines)

            if multi_frame:
                combined_lines.append(f"Frame {index}: {target_url}")
                if frame_lines:
                    combined_lines.extend(
                        f"  {line}" if line else line
                        for line in frame_lines
                    )
            elif frame_lines:
                combined_lines.extend(frame_lines)
            combined_ref_map.update(frame_ref_map)
            target_map.update({ref: target for ref in frame_ref_map})
            ref_offset += len(frame_ref_map)
            captured_frame_count += 1

        self._aria_ref_target_map = target_map
        return (
            AriaSnapshot(
                text="\n".join(combined_lines),
                ref_map=combined_ref_map,
                url=self._page.url,
            ),
            "frame_locator_aria_snapshot" if multi_frame else "body_locator_aria_snapshot",
            captured_frame_count,
        )

    def _capture_a11y_snapshot(self, step_name: str) -> dict[str, Any]:
        history_dir = self.history_dir()
        if not history_dir:
            return {
                "a11y_path": None,
                "a11y_source": "body_locator_aria_snapshot",
                "a11y_capture_status": "disabled",
                "a11y_capture_error": None,
            }

        self._artifact_logger.prepare_history_dir()
        a11y_path = history_dir / f"{step_name}.a11y.yaml"
        try:
            snapshot, a11y_source, _frame_count = self._capture_frame_aware_aria_snapshot()
            a11y_path.write_text(snapshot.text, encoding="utf-8")
            self._history_aria_snapshot = snapshot
        except Exception as exc:
            return {
                "a11y_path": None,
                "a11y_source": "body_locator_aria_snapshot",
                "a11y_capture_status": "error",
                "a11y_capture_error": str(exc),
            }

        return {
            "a11y_path": a11y_path.name,
            "a11y_source": a11y_source,
            "a11y_capture_status": "captured",
            "a11y_capture_error": None,
        }

    def _write_history_snapshot(
        self,
        state: BrowserState,
        previous_state: BrowserState | None = None,
    ) -> dict[str, Any] | None:
        history_dir = self.history_dir()
        if not history_dir:
            return None

        self._artifact_logger.prepare_history_dir()
        next_step = 1
        latest_metadata = self.latest_artifact_metadata()
        if latest_metadata is not None:
            next_step = int(latest_metadata["step"]) + 1
        step_name = f"step-{next_step:04d}"
        a11y_metadata = self._capture_a11y_snapshot(step_name)
        state_for_metadata = state.model_copy(
            update={
                "page": state.page.model_copy(
                    update={
                        "html_path": f"{step_name}.html",
                        "a11y_path": a11y_metadata["a11y_path"],
                    }
                )
            }
        )
        return self._artifact_logger.write_snapshot(
            screenshot_bytes=state.viewport.screenshot,
            url=state.page.url,
            html=self._page.content(),
            a11y_path=a11y_metadata["a11y_path"],
            metadata_extra={
                "a11y_source": a11y_metadata["a11y_source"],
                "a11y_capture_status": a11y_metadata["a11y_capture_status"],
                "a11y_capture_error": a11y_metadata["a11y_capture_error"],
                "state_graph": browser_state_to_graph(state_for_metadata, previous_state),
            },
        )
