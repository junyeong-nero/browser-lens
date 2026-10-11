from typing import Any

from browser import PlaywrightBrowser, EnvState

from tools.helpers import current_state_after_page_ready, mark_and_resolve_ref_locator


def _select_native_option(locator, option_label: str) -> dict[str, Any]:
    """Select an option from a native HTML select element."""
    return locator.evaluate(
        """
        (element, requestedLabel) => {
            const findSelect = (node) => {
                if (node instanceof HTMLSelectElement) return node;
                if (node instanceof HTMLOptionElement) return node.closest('select');
                if (node instanceof Element) {
                    const childSelect = node.querySelector('select');
                    if (childSelect instanceof HTMLSelectElement) return childSelect;
                    const parentSelect = node.closest('select');
                    if (parentSelect instanceof HTMLSelectElement) return parentSelect;
                }
                return null;
            };

            const normalize = (value) => String(value || '').trim();
            const select = findSelect(element);
            if (!(select instanceof HTMLSelectElement)) {
                return {
                    ok: false,
                    error_type: 'NotNativeSelect',
                    error: 'Resolved ref is not a native HTML <select> or <option>.',
                };
            }

            const wanted = normalize(requestedLabel);
            const wantedLower = wanted.toLowerCase();
            const options = Array.from(select.options);
            const option = options.find((candidate) => {
                const labels = [
                    candidate.label,
                    candidate.textContent,
                    candidate.value,
                ].map(normalize);
                return labels.some((label) => label === wanted)
                    || labels.some((label) => label.toLowerCase() === wantedLower);
            });

            if (!option) {
                return {
                    ok: false,
                    error_type: 'OptionNotFound',
                    error: `No native select option matched "${wanted}".`,
                    available_options: options.slice(0, 50).map((candidate) => ({
                        label: normalize(candidate.label || candidate.textContent),
                        value: candidate.value,
                    })),
                };
            }

            select.value = option.value;
            option.selected = true;
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return {
                ok: true,
                selected_label: normalize(option.label || option.textContent),
                selected_value: option.value,
                selected_index: option.index,
            };
        }
        """,
        option_label,
    )


def handle_select_option_by_ref(
    computer: PlaywrightBrowser,
    args: dict,
) -> EnvState | dict[str, Any]:
    locator = mark_and_resolve_ref_locator(computer, args, "select_option_by_ref")
    option_label = str(args["option_label"])

    computer.highlight_locator(locator, kind="select")
    result = _select_native_option(locator, option_label)
    if not isinstance(result, dict):
        result = {
            "ok": False,
            "error_type": "UnexpectedSelectResult",
            "error": "Native select evaluation did not return a result payload.",
        }
    if not result.get("ok"):
        return {
            "status": "not_selectable",
            "tool_name": "select_option_by_ref",
            "ref": int(args["ref"]),
            "option_label": option_label,
            **result,
        }

    return current_state_after_page_ready(computer)
