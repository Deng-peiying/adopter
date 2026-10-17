"""Deterministic candidate assembly from normalized interface evidence.

This module selects values only when the Scanner has produced one unambiguous
fact for the scoped device. It does not resolve semantic conflicts and it never
invents Runtime Completion Policy.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .evidence import EvidenceMatrix
from .models import CapabilityCandidate, CapabilityCatalog, EvidenceRecord


def _normalized(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_normalized(item) for item in value]
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    return value


def _unique(values: Iterable[Any], label: str) -> Any:
    by_value: dict[str, Any] = {}
    for value in values:
        by_value.setdefault(
            json.dumps(_normalized(value), sort_keys=True), value,
        )
    if len(by_value) != 1:
        raise ValueError(
            f"{label} requires one unambiguous evidence value; found "
            f"{len(by_value)}"
        )
    return next(iter(by_value.values()))


def _claim(records: Iterable[EvidenceRecord], name: str, label: str) -> Any:
    return _unique(
        (record.claims[name] for record in records if name in record.claims),
        label,
    )


def _device_records(
    records: Iterable[EvidenceRecord], claim_type: str, device_id: str,
) -> tuple[EvidenceRecord, ...]:
    available = tuple(record for record in records if record.claim_type == claim_type)
    scoped = tuple(
        record for record in available
        if record.claims.get("device") == device_id
        or device_id in str(record.claims.get("endpoint", ""))
    )
    return scoped


def _interface_definition(
    records: Iterable[EvidenceRecord], qualified_interface: str,
) -> EvidenceRecord:
    matching = tuple(
        record for record in records
        if record.claim_type == "ros2_interface_definition"
        and record.claims.get("qualified_interface") == qualified_interface
    )
    if len(matching) != 1:
        raise ValueError(
            f"interface {qualified_interface} requires one type definition; "
            f"found {len(matching)}"
        )
    return matching[0]


def _structural_path(
    record: EvidenceRecord, claim: str, predicate, label: str,
) -> str:
    matches = [
        str(path) for path in record.claims.get(claim, ())
        if predicate(str(path))
    ]
    if matches:
        minimum_depth = min(path.count(".") for path in matches)
        matches = [path for path in matches if path.count(".") == minimum_depth]
    return str(_unique(matches, label))


class DeterministicCandidateBuilder:
    """Build the two first-version mappings without using an LLM."""

    def build(
        self,
        catalog: CapabilityCatalog,
        matrix: EvidenceMatrix,
        *,
        device_id: str,
        capability_ids: tuple[str, ...],
        ordered_joints: tuple[str, ...],
    ) -> tuple[CapabilityCandidate, ...]:
        expected = {"joint_position_state", "joint_position"}
        if set(capability_ids) != expected or len(capability_ids) != len(expected):
            raise ValueError(
                "first-version deterministic assembly requires joint_position_state "
                "and joint_position"
            )
        records = matrix.records
        state_usage = _device_records(
            records, "ros2_subscription_usage", device_id,
        )
        action_usage = _device_records(records, "ros2_action_usage", device_id)
        state_usage = tuple(
            record for record in state_usage
            if "positions_field" in record.claims
        )
        action_usage = tuple(
            record for record in action_usage
            if "target_field" in record.claims
        )
        config = tuple(
            record for record in records
            if record.claim_type == "robot_joint_configuration"
            and record.claims.get("device") == device_id
            and len(record.claims.get("vendor_joint_order", ()))
            == len(ordered_joints)
        )
        if not state_usage or not action_usage or not config:
            raise ValueError(
                "scoped ROS2 state, action, and joint configuration evidence are required"
            )

        state_interface = str(_claim(
            state_usage, "interface_type", "state interface type",
        ))
        action_interface = str(_claim(
            action_usage, "interface_type", "action interface type",
        ))
        state_type = _interface_definition(records, state_interface)
        action_type = _interface_definition(records, action_interface)
        state_definition = catalog.get("joint_position_state")
        action_definition = catalog.get("joint_position")
        if (
            len(state_definition.binding_operations) != 1
            or len(action_definition.binding_operations) != 1
        ):
            raise ValueError("deterministic assembly requires one canonical operation")

        state_semantics = {
            "binding_operation": state_definition.binding_operations[0],
            "transport_kind": _claim(
                state_usage, "transport_kind", "state transport kind",
            ),
            "endpoint": _claim(state_usage, "endpoint", "state endpoint"),
            "interface_type": state_interface,
            "positions_field": _claim(
                state_usage, "positions_field", "state positions field",
            ),
            "stamp_field": _structural_path(
                state_type,
                "field_paths",
                lambda path: path.endswith(".stamp") or path == "stamp",
                "state timestamp path",
            ),
            "mode_field": _claim(state_usage, "mode_field", "state mode field"),
            "ready_values": _claim(
                state_usage, "ready_values", "ready mode values",
            ),
            "fault_field": _claim(
                state_usage, "fault_code_field", "numeric fault code field",
            ),
            "unit": _claim(config, "unit", "joint state unit"),
            "ordered_joints": ordered_joints,
            "joint_limits": _claim(config, "joint_limits", "joint limits"),
        }
        move_semantics = {
            "binding_operation": action_definition.binding_operations[0],
            "transport_kind": _claim(
                action_usage, "transport_kind", "action transport kind",
            ),
            "endpoint": _claim(action_usage, "endpoint", "action endpoint"),
            "interface_type": action_interface,
            "target_field": _claim(
                action_usage, "target_field", "joint target field",
            ),
            "target_unit": _claim(config, "unit", "joint target unit"),
            "constants": _claim(
                action_usage, "constants", "action goal constants",
            ),
            "result_code_field": _claim(
                action_usage, "result_code_field", "result code field",
            ),
            "result_description_field": _structural_path(
                action_type,
                "result_field_paths",
                lambda path: path.endswith("description"),
                "result description field",
            ),
            "success_code": _claim(
                action_usage, "success_code", "action success code",
            ),
            "unit": _claim(config, "unit", "canonical joint unit"),
            "ordered_joints": ordered_joints,
            "state_binding": f"{device_id}_joint_state",
            "completion": ["terminal_result", "measured_arrival"],
        }
        state_ids = tuple(sorted({
            *(record.evidence_id for record in state_usage),
            state_type.evidence_id,
            *(record.evidence_id for record in config),
        }))
        move_ids = tuple(sorted({
            *(record.evidence_id for record in action_usage),
            action_type.evidence_id,
            *(record.evidence_id for record in config),
        }))
        return (
            CapabilityCandidate(
                "joint_position_state", state_ids, state_semantics,
            ),
            CapabilityCandidate("joint_position", move_ids, move_semantics),
        )
