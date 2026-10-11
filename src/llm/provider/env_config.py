import os

DEFAULT_ACTION_SUMMARY_TIMEOUT_SECONDS = 10.0
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_TIMEOUT_SECONDS = DEFAULT_ACTION_SUMMARY_TIMEOUT_SECONDS


def require_env(name: str, missing_message: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(missing_message)
    return value


def optional_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    stripped = value.strip()
    if stripped or default is None:
        return stripped
    return default


def _parse_positive_timeout_seconds(env_name: str, default_seconds: float) -> float:
    timeout_value = os.environ.get(env_name, str(default_seconds))
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a number.") from exc
    if timeout_seconds <= 0:
        raise ValueError(f"{env_name} must be greater than 0.")
    return timeout_seconds


def parse_action_summary_timeout_seconds() -> float:
    return _parse_positive_timeout_seconds(
        "ACTION_SUMMARY_TIMEOUT_SECONDS",
        DEFAULT_ACTION_SUMMARY_TIMEOUT_SECONDS,
    )


def parse_llm_timeout_seconds() -> float:
    return _parse_positive_timeout_seconds(
        "LLM_TIMEOUT_SECONDS",
        DEFAULT_LLM_TIMEOUT_SECONDS,
    )


def parse_timeout_seconds() -> float:
    return parse_action_summary_timeout_seconds()
