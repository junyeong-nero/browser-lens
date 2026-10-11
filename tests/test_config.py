import pytest

from config import AppConfig


def _minimal_config(**constraints):
    def model_config(model: str):
        return {
            "endpoint_url": "https://example.test/v1",
            "model": model,
        }

    data = {
        "models": {
            "actor": model_config("actor-model"),
            "planner": model_config("planner-model"),
            "summary": model_config("summary-model"),
        }
    }
    if constraints:
        data["constraints"] = constraints
    return data


def test_execution_constraints_have_agent_defaults_when_omitted():
    config = AppConfig.model_validate(_minimal_config())

    assert config.constraints.max_steps_per_subgoal == 15
    assert config.constraints.max_total_steps == 100
    assert config.constraints.max_subgoals == 10


def test_execution_constraints_can_be_configured():
    config = AppConfig.model_validate(
        _minimal_config(
            max_steps_per_subgoal=4,
            max_total_steps=12,
            max_subgoals=3,
        )
    )

    assert config.constraints.max_steps_per_subgoal == 4
    assert config.constraints.max_total_steps == 12
    assert config.constraints.max_subgoals == 3


def test_execution_constraints_reject_non_positive_values():
    with pytest.raises(ValueError):
        AppConfig.model_validate(_minimal_config(max_steps_per_subgoal=0))


def test_endpoint_model_config_supports_reasoning_effort_and_token_field():
    data = _minimal_config()
    data["models"]["actor"]["token_limit_field"] = "max_tokens"
    data["models"]["actor"]["reasoning"] = {"effort": "low"}
    data["models"]["actor"]["supports_image_inputs"] = True
    data["models"]["actor"]["temperature"] = 0.2

    config = AppConfig.model_validate(data)

    assert config.models.actor.token_limit_field == "max_tokens"
    assert config.models.actor.reasoning is not None
    assert config.models.actor.reasoning.effort == "low"
    assert config.models.actor.supports_image_inputs is True
    assert config.models.actor.temperature == 0.2


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_endpoint_model_config_rejects_temperature_outside_openai_range(temperature):
    data = _minimal_config()
    data["models"]["actor"]["temperature"] = temperature

    with pytest.raises(ValueError):
        AppConfig.model_validate(data)


def test_endpoint_model_config_defaults_to_text_only():
    config = AppConfig.model_validate(_minimal_config())

    assert config.models.actor.supports_image_inputs is False


def test_endpoint_model_config_defaults_to_responses_api():
    config = AppConfig.model_validate(_minimal_config())

    assert config.models.actor.api == "responses"


def test_endpoint_model_config_rejects_empty_endpoint_fields():
    data = _minimal_config()
    data["models"]["actor"]["endpoint_url"] = " "

    with pytest.raises(ValueError):
        AppConfig.model_validate(data)


def test_endpoint_label_and_api_key_env_are_inferred_from_known_endpoint_url():
    from config import api_key_env, endpoint_label

    data = _minimal_config()
    data["models"]["actor"]["endpoint_url"] = "https://openrouter.ai/api/v1"
    data["models"]["summary"]["endpoint_url"] = "https://api.openai.com/v1"

    config = AppConfig.model_validate(data)

    assert endpoint_label(config.models.actor) == "openrouter"
    assert endpoint_label(config.models.summary) == "openai"
    assert api_key_env(config.models.actor) == "OPENROUTER_API_KEY"
    assert api_key_env(config.models.summary) == "OPENAI_API_KEY"


def test_api_key_env_defaults_to_llm_api_key_for_custom_endpoint():
    from config import api_key_env

    config = AppConfig.model_validate(_minimal_config())

    assert api_key_env(config.models.actor) == "LLM_API_KEY"


def test_supports_temperature_defaults_from_endpoint_and_model():
    from config import supports_temperature

    data = _minimal_config()
    data["models"]["actor"]["endpoint_url"] = "https://api.openai.com/v1"
    data["models"]["actor"]["model"] = "gpt-5.4-mini"
    data["models"]["summary"]["endpoint_url"] = "https://api.openai.com/v1"
    data["models"]["summary"]["model"] = "gpt-4o-mini"

    config = AppConfig.model_validate(data)

    assert supports_temperature(config.models.actor) is False
    assert supports_temperature(config.models.summary) is True


def test_explicit_temperature_does_not_override_openai_reasoning_model_guard():
    from config import supports_temperature

    data = _minimal_config()
    data["models"]["actor"]["endpoint_url"] = "https://api.openai.com/v1"
    data["models"]["actor"]["model"] = "gpt-5.4-mini"
    data["models"]["actor"]["temperature"] = 0.2

    config = AppConfig.model_validate(data)

    assert supports_temperature(config.models.actor) is False


def test_explicit_temperature_is_supported_for_openrouter_model():
    from config import supports_temperature

    data = _minimal_config()
    data["models"]["actor"]["endpoint_url"] = "https://openrouter.ai/api/v1"
    data["models"]["actor"]["model"] = "openai/gpt-5.4-mini"
    data["models"]["actor"]["temperature"] = 0.2

    config = AppConfig.model_validate(data)

    assert supports_temperature(config.models.actor) is True
