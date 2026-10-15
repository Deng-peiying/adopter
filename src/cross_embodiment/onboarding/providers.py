from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] | None
    raw_arguments: str
    argument_error: str | None = None


@dataclass(frozen=True)
class ProviderToolResult:
    call_id: str
    name: str
    ok: bool
    payload: Any


@dataclass(frozen=True)
class ProviderTurn:
    content: str | None
    reasoning_content: str | None
    tool_calls: tuple[ProviderToolCall, ...]


class OnboardingModelProvider(Protocol):
    def start(self, context: Mapping[str, Any]) -> None: ...

    def record_tool_results(
        self,
        tool_results: tuple[ProviderToolResult, ...],
    ) -> None: ...

    def next_turn(
        self,
        tool_results: tuple[ProviderToolResult, ...] = (),
        feedback: str | None = None,
    ) -> ProviderTurn: ...


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


DEEPSEEK_TOOLS = (
    _tool("list_evidence", "List evidence IDs, optionally filtered by exact claim type.", {
        "claim_type": {"type": "string"},
    }),
    _tool("get_evidence", "Read one structured evidence record.", {
        "evidence_id": {"type": "string"},
    }, ["evidence_id"]),
    _tool("submit_candidate", "Submit one complete evidence-linked capability mapping candidate.", {
        "capability_id": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "proposed_semantics": {"type": "object", "additionalProperties": True},
    }, ["capability_id", "evidence_ids", "proposed_semantics"]),
    _tool(
        "accept_deterministic_candidate",
        (
            "Accept one Scanner-derived candidate after checking its linked evidence. "
            "Do not retype deterministic mapping fields."
        ),
        {
            "capability_id": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        ["capability_id", "evidence_ids", "reason"],
    ),
    _tool("record_conclusion", "Record a terminal evidence-linked gap, unsupported, or unknown conclusion.", {
        "capability_id": {"type": "string"},
        "status": {"type": "string", "enum": ["gap", "unsupported", "unknown"]},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    }, ["capability_id", "status", "evidence_ids", "missing_fields", "reason"]),
    _tool("assess", "Read the current deterministic assessment of accepted candidates.", {}),
)


def _message_value(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def _read_local_api_key(path: Path) -> str | None:
    """Read one literal key assignment without executing the Python file."""
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets if isinstance(statement, ast.Assign)
            else (statement.target,)
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "DEEPSEEK_API_KEY"
            for target in targets
        ):
            continue
        value = ast.literal_eval(statement.value)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"invalid DEEPSEEK_API_KEY in {path}")
        return value.strip()
    raise ValueError(f"DEEPSEEK_API_KEY assignment is missing in {path}")


class DeepSeekProvider:
    """Stateful DeepSeek Chat Completions provider with native tool-call history."""

    def __init__(
        self,
        *,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        api_key_env: str = "DEEPSEEK_API_KEY",
        credential_path: Path | None = None,
        client: Any | None = None,
        thinking: bool = False,
    ) -> None:
        api_key = os.environ.get(api_key_env)
        if client is None and not api_key:
            configured_path = credential_path or Path(
                os.environ.get(
                    "CROSS_EMBODIMENT_DEEPSEEK_CREDENTIAL_FILE",
                    Path(__file__).resolve().parents[3]
                    / ".deepseek_credentials.py",
                )
            )
            api_key = _read_local_api_key(configured_path)
        if client is None and not api_key:
            raise ValueError(
                f"{api_key_env} or a local .deepseek_credentials.py is required"
            )
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "DeepSeek orchestration requires the onboarding-agent optional dependency"
                ) from exc
            client = OpenAI(api_key=api_key, base_url=base_url)
        self._client = client
        self.model = model
        self.thinking = thinking
        self._messages: list[dict[str, Any]] = []
        self._started = False

    @property
    def messages(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._messages)

    def start(self, context: Mapping[str, Any]) -> None:
        if self._started:
            raise RuntimeError("DeepSeek provider session has already started")
        self._messages = [
            {
                "role": "system",
                "content": (
                    "You are a Hardware Onboarding reasoning agent. Use the supplied typed tools "
                    "to inspect evidence and decide every scoped capability. Submit supported "
                    "Scanner-derived mappings with accept_deterministic_candidate after reviewing "
                    "their evidence; use submit_candidate only when deterministic assembly is "
                    "unavailable or ambiguous. Record unresolved evidence or execution-policy "
                    "gaps with record_conclusion. Never invent endpoints, fields, units, policy "
                    "values, verification, or motion evidence."
                ),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        self._started = True

    def next_turn(
        self,
        tool_results: tuple[ProviderToolResult, ...] = (),
        feedback: str | None = None,
    ) -> ProviderTurn:
        if not self._started:
            raise RuntimeError("DeepSeek provider session has not started")
        self.record_tool_results(tool_results)
        if feedback:
            self._messages.append({"role": "user", "content": feedback})

        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages,
            "tools": list(DEEPSEEK_TOOLS),
            "tool_choice": "auto",
        }
        if self.thinking:
            request["extra_body"] = {"thinking": {"type": "enabled"}}
        response = self._client.chat.completions.create(**request)
        message = response.choices[0].message
        content = _message_value(message, "content")
        reasoning_content = _message_value(message, "reasoning_content")
        raw_tool_calls = tuple(_message_value(message, "tool_calls", ()) or ())

        assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
        if reasoning_content is not None:
            assistant_message["reasoning_content"] = reasoning_content
        serialized_calls: list[dict[str, Any]] = []
        calls: list[ProviderToolCall] = []
        for raw_call in raw_tool_calls:
            call_id = str(_message_value(raw_call, "id", ""))
            function = _message_value(raw_call, "function")
            name = str(_message_value(function, "name", ""))
            raw_arguments = str(_message_value(function, "arguments", "{}"))
            error: str | None = None
            arguments: Mapping[str, Any] | None
            try:
                parsed = json.loads(raw_arguments)
                if not isinstance(parsed, dict):
                    raise ValueError("tool arguments must be a JSON object")
                arguments = parsed
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = None
                error = str(exc)
            calls.append(ProviderToolCall(call_id, name, arguments, raw_arguments, error))
            serialized_calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": raw_arguments},
            })
        if serialized_calls:
            assistant_message["tool_calls"] = serialized_calls
        self._messages.append(assistant_message)
        return ProviderTurn(content, reasoning_content, tuple(calls))

    def record_tool_results(
        self,
        tool_results: tuple[ProviderToolResult, ...],
    ) -> None:
        if not self._started:
            raise RuntimeError("DeepSeek provider session has not started")
        for result in tool_results:
            self._messages.append({
                "role": "tool",
                "tool_call_id": result.call_id,
                "name": result.name,
                "content": json.dumps({"ok": result.ok, "result": result.payload}, ensure_ascii=False),
            })
