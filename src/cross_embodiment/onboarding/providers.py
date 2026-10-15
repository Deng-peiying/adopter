from __future__ import annotations

import json
import os
from typing import Any, Protocol


class OnboardingModelProvider(Protocol):
    def next_turn(self, context: list[dict[str, Any]]) -> dict[str, Any]: ...


class DeepSeekProvider:
    """OpenAI-compatible DeepSeek provider loaded only when explicitly used."""

    def __init__(
        self,
        *,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        api_key_env: str = "DEEPSEEK_API_KEY",
    ) -> None:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"{api_key_env} is required")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "DeepSeek orchestration requires the onboarding-agent optional dependency"
            ) from exc
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def next_turn(self, context: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Hardware Onboarding reasoning agent. Return exactly one JSON "
                        "object: either {tool, arguments} using an allowed typed tool or {final}. "
                        "Every semantic claim must cite evidence IDs. Never request shell access, "
                        "arbitrary file writes, or verification promotion."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("DeepSeek returned an empty onboarding turn")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("DeepSeek onboarding turn must be a JSON object")
        return value
