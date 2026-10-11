from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
TokenLimitField = Literal["max_tokens", "max_completion_tokens"]
ApiKind = Literal["chat", "responses"]

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
_OPENAI_TEMPERATURE_UNSUPPORTED_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class ReasoningConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    effort: ReasoningEffort


class EndpointModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    endpoint_url: str
    api: ApiKind = "responses"
    api_key_env: str | None = None
    token_limit_field: TokenLimitField = "max_completion_tokens"
    headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    reasoning: ReasoningConfig | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    supports_image_inputs: bool = False

    @field_validator("model", "endpoint_url")
    @classmethod
    def _validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("api_key_env")
    @classmethod
    def _validate_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor: EndpointModelConfig
    planner: EndpointModelConfig
    summary: EndpointModelConfig


class ExecutionConstraintsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_steps_per_subgoal: int = 15
    max_total_steps: int = 100
    max_subgoals: int = 10

    @field_validator("max_steps_per_subgoal", "max_total_steps", "max_subgoals")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be greater than or equal to 1")
        return value


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    models: ModelsConfig
    constraints: ExecutionConstraintsConfig = Field(default_factory=ExecutionConstraintsConfig)


def _load() -> AppConfig:
    with open(_CONFIG_PATH) as f:
        loaded = yaml.safe_load(f) or {}
    return AppConfig.model_validate(loaded)


_config: AppConfig | None = None


def _get() -> AppConfig:
    global _config
    if _config is None:
        _config = _load()
    return _config


def actor_config() -> EndpointModelConfig:
    return _get().models.actor


def planner_config() -> EndpointModelConfig:
    return _get().models.planner


def summary_config() -> EndpointModelConfig:
    return _get().models.summary


def reasoning_effort(model_config: EndpointModelConfig) -> ReasoningEffort | None:
    if model_config.reasoning is None:
        return None
    return model_config.reasoning.effort


def _known_endpoint_label(endpoint_url: str) -> str | None:
    normalized = endpoint_url.strip().lower()
    if "openrouter.ai" in normalized:
        return "openrouter"
    if "api.openai.com" in normalized:
        return "openai"
    if "integrate.api.nvidia.com" in normalized:
        return "nvidia"
    return None


def endpoint_label(model_config: EndpointModelConfig) -> str:
    return _known_endpoint_label(model_config.endpoint_url) or model_config.endpoint_url


def supports_temperature(model_config: EndpointModelConfig) -> bool:
    if _known_endpoint_label(model_config.endpoint_url) != "openai":
        return True
    model = model_config.model.strip().lower()
    return not model.startswith(_OPENAI_TEMPERATURE_UNSUPPORTED_MODEL_PREFIXES)


def generation_temperature(
    model_config: EndpointModelConfig,
    default: float,
) -> float:
    if model_config.temperature is None:
        return default
    return model_config.temperature


def api_key_env(model_config: EndpointModelConfig) -> str:
    if model_config.api_key_env:
        return model_config.api_key_env

    label = _known_endpoint_label(model_config.endpoint_url)
    if label == "openrouter":
        return "OPENROUTER_API_KEY"
    if label == "openai":
        return "OPENAI_API_KEY"
    if label == "nvidia":
        return "NVIDIA_API_KEY"
    return "LLM_API_KEY"


def execution_constraints() -> ExecutionConstraintsConfig:
    return _get().constraints


def actor_model() -> str:
    return actor_config().model


def max_steps_per_subgoal() -> int:
    return execution_constraints().max_steps_per_subgoal


def max_total_steps() -> int:
    return execution_constraints().max_total_steps


def max_subgoals() -> int:
    return execution_constraints().max_subgoals
