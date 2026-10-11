from __future__ import annotations

from core.types import GroundingMode


def validate_grounding_provider(
    grounding: GroundingMode,
    provider_label: str,
    *,
    supports_image_inputs: bool,
) -> None:
    if grounding in ("vision", "mixed") and not supports_image_inputs:
        raise ValueError(
            f"grounding='{grounding}' requires a provider that supports image inputs, "
            f"but llm_client uses '{provider_label}'."
        )
