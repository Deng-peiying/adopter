from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import EvidenceRecord


EVIDENCE_CONTRACT_SCHEMA_VERSION = "evidence-contract/v0.1"


@dataclass(frozen=True)
class EvidenceFieldContract:
    """Shared Scanner/Evidence/Matcher contract for one candidate field."""

    field: str
    fact: str
    evidence_claims: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ()
    structural_claims: tuple[str, ...] = ()
    source: str = "vendor_evidence"
    normalization_rule: str | None = None
    reject_unconfirmed_policy: bool = False
    platform_value: Any = None
    normalization_inputs: tuple[str, ...] = ()


def _vendor(
    field: str,
    fact: str,
    *claims: str,
    types: tuple[str, ...] = (),
    structural_claims: tuple[str, ...] = (),
    reject_unconfirmed_policy: bool = False,
) -> EvidenceFieldContract:
    return EvidenceFieldContract(
        field=field,
        fact=fact,
        evidence_claims=claims or (field,),
        evidence_types=tuple(dict.fromkeys((
            *types,
            "reviewed_interface_binding",
            "ros2_binding",
            "vendor_binding",
        ))),
        structural_claims=structural_claims,
        reject_unconfirmed_policy=reject_unconfirmed_policy,
    )


_STATE_CONTRACT = {
    "binding_operation": EvidenceFieldContract(
        "binding_operation",
        "SDK joint-state semantics backed by an observed transport read operation",
        evidence_claims=("transport_operation",),
        evidence_types=("ros2_subscription_usage",),
        source="platform_catalog+vendor_evidence",
        normalization_rule=(
            "evidenced transport operation subscribe -> the capability catalog's "
            "single canonical binding operation"
        ),
    ),
    "transport_kind": _vendor(
        "transport_kind", "ROS2 subscription construction",
        types=("ros2_subscription_usage",),
    ),
    "endpoint": _vendor(
        "endpoint", "statically resolved subscription endpoint",
        types=("ros2_subscription_usage",),
    ),
    "interface_type": _vendor(
        "interface_type", "imported message type used by the subscription",
        types=("ros2_subscription_usage",),
    ),
    "positions_field": _vendor(
        "positions_field", "message field read as measured joint positions",
        types=("ros2_subscription_usage",),
    ),
    "stamp_field": _vendor(
        "stamp_field", "timestamp path declared by the message definition",
        types=("ros2_interface_definition",), structural_claims=("field_paths",),
    ),
    "mode_field": _vendor(
        "mode_field", "message field read as arm mode",
        types=("ros2_subscription_usage",),
    ),
    "ready_values": _vendor(
        "ready_values", "mode value used by vendor code as ready/idle",
        types=("ros2_subscription_usage",),
    ),
    "fault_field": _vendor(
        "fault_field", "message field used by vendor code as the numeric fault code",
        "fault_code_field", "fault_field", types=("ros2_subscription_usage",),
    ),
    "unit": _vendor(
        "unit", "joint unit declared by the vendor joint configuration",
        types=("robot_joint_configuration",),
    ),
    "ordered_joints": EvidenceFieldContract(
        "ordered_joints", "canonical joint order supplied by onboarding scope",
        source="onboarding_scope",
        platform_value="scope.ordered_joints",
    ),
    "joint_limits": _vendor(
        "joint_limits", "ordered soft limits from vendor joint configuration",
        types=("robot_joint_configuration",),
    ),
}


_MOVE_CONTRACT = {
    "binding_operation": EvidenceFieldContract(
        "binding_operation",
        "SDK joint-position semantics backed by an observed action goal operation",
        evidence_claims=("transport_operation",),
        evidence_types=("ros2_action_usage",),
        source="platform_catalog+vendor_evidence",
        normalization_rule=(
            "evidenced transport operation send_action_goal -> the capability "
            "catalog's single canonical binding operation"
        ),
    ),
    "transport_kind": _vendor(
        "transport_kind", "ROS2 ActionClient construction",
        types=("ros2_action_usage",),
    ),
    "endpoint": _vendor(
        "endpoint", "statically resolved ROS2 action endpoint",
        types=("ros2_action_usage",),
    ),
    "interface_type": _vendor(
        "interface_type", "imported action type used by ActionClient",
        types=("ros2_action_usage",),
    ),
    "timeout_s": _vendor(
        "timeout_s", "confirmed command lifecycle timeout policy",
        types=("ros2_action_usage",), reject_unconfirmed_policy=True,
    ),
    "target_field": _vendor(
        "target_field", "dynamic action goal field receiving the joint target",
        types=("ros2_action_usage",),
    ),
    "target_unit": _vendor(
        "target_unit", "unit of the ordered vendor joint target", "target_unit", "unit",
        types=("ros2_action_usage", "robot_joint_configuration"),
    ),
    "constants": _vendor(
        "constants", "constant action goal fields in vendor code",
        types=("ros2_action_usage",),
    ),
    "result_code_field": _vendor(
        "result_code_field", "action result field compared with a success code",
        types=("ros2_action_usage",),
    ),
    "result_description_field": _vendor(
        "result_description_field", "result description path declared by action type",
        types=("ros2_action_usage", "ros2_interface_definition"),
        structural_claims=("result_field_paths",),
    ),
    "success_code": _vendor(
        "success_code", "result code treated as success by vendor code",
        types=("ros2_action_usage",),
    ),
    "unit": _vendor(
        "unit", "joint unit declared by vendor joint configuration",
        types=("robot_joint_configuration", "ros2_action_usage"),
    ),
    "ordered_joints": EvidenceFieldContract(
        "ordered_joints", "canonical joint order supplied by onboarding scope",
        source="onboarding_scope",
        platform_value="scope.ordered_joints",
    ),
    "state_binding": EvidenceFieldContract(
        "state_binding", "generated state binding for measured-arrival verification",
        source="adapter_runtime",
        normalization_rule=(
            "capability reference joint_position_state -> generated device joint-state binding"
        ),
        platform_value="adapter_runtime.device_joint_state_binding",
        normalization_inputs=("joint_position_state",),
    ),
    "arrival_tolerance_rad": _vendor(
        "arrival_tolerance_rad", "confirmed measured-arrival tolerance policy",
        types=("joint_arrival_policy", "ros2_action_usage"),
        reject_unconfirmed_policy=True,
    ),
    "settle_window_s": _vendor(
        "settle_window_s", "confirmed measured-arrival settle policy",
        types=("joint_arrival_policy", "ros2_action_usage"),
        reject_unconfirmed_policy=True,
    ),
    "completion": EvidenceFieldContract(
        "completion",
        "SDK completion requires terminal action result and fresh measured arrival",
        source="adapter_runtime",
        platform_value=["terminal_result", "measured_arrival"],
    ),
}


_CONTRACTS = {
    "joint_position_state": _STATE_CONTRACT,
    "joint_position": _MOVE_CONTRACT,
}


def evidence_contract(capability_id: str) -> dict[str, EvidenceFieldContract]:
    return dict(_CONTRACTS.get(capability_id, {}))


def execution_policy_fields(capability_id: str) -> tuple[str, ...]:
    return tuple(
        field for field, rule in evidence_contract(capability_id).items()
        if rule.reject_unconfirmed_policy
    )


def evidence_contract_payload(capability_id: str) -> dict[str, dict[str, Any]]:
    def jsonable(value: Any) -> Any:
        if isinstance(value, tuple):
            return [jsonable(item) for item in value]
        if isinstance(value, dict):
            return {key: jsonable(item) for key, item in value.items()}
        return value

    return {
        field: jsonable(asdict(rule))
        for field, rule in evidence_contract(capability_id).items()
    }


def evidence_contract_document(capability_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_CONTRACT_SCHEMA_VERSION,
        "capabilities": {
            capability_id: evidence_contract_payload(capability_id)
            for capability_id in capability_ids
        },
    }


def resolve_platform_value(
    capability_id: str,
    field: str,
    *,
    binding_operations: tuple[str, ...],
    device_id: str,
    ordered_joints: tuple[str, ...],
) -> Any:
    rule = evidence_contract(capability_id).get(field)
    if rule is None:
        return None
    if field == "binding_operation" and len(binding_operations) == 1:
        return binding_operations[0]
    if rule.platform_value == "scope.ordered_joints":
        return list(ordered_joints)
    if rule.platform_value == "adapter_runtime.device_joint_state_binding":
        return f"{device_id}_joint_state"
    return rule.platform_value


def resolved_platform_fields(
    capability_id: str,
    *,
    binding_operations: tuple[str, ...],
    device_id: str,
    ordered_joints: tuple[str, ...],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for field, rule in evidence_contract(capability_id).items():
        if rule.source not in {
            "platform_catalog+vendor_evidence", "onboarding_scope", "adapter_runtime",
        }:
            continue
        value = resolve_platform_value(
            capability_id,
            field,
            binding_operations=binding_operations,
            device_id=device_id,
            ordered_joints=ordered_joints,
        )
        if value is not None:
            resolved[field] = value
    return resolved


def normalized(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [normalized(child) for child in value]
    if isinstance(value, dict):
        return {name: normalized(child) for name, child in value.items()}
    return value


def supporting_evidence(
    capability_id: str,
    field: str,
    value: Any,
    records: Iterable[EvidenceRecord],
    *,
    candidate_semantics: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    rule = evidence_contract(capability_id).get(field)
    if rule is None or rule.source not in {"vendor_evidence", "platform_catalog+vendor_evidence"}:
        return ()
    expected = normalized(value)
    candidate_interface = (
        candidate_semantics.get("interface_type")
        if candidate_semantics is not None else None
    )
    supported: list[str] = []
    for record in records:
        if rule.evidence_types and record.claim_type not in rule.evidence_types:
            continue
        if rule.reject_unconfirmed_policy:
            status = record.claims.get("execution_policy_status")
            origin = record.claims.get("execution_policy_origin")
            if status != "confirmed" or origin not in {
                "operator_configured",
                "platform_policy",
                "validated_test_policy",
                "vendor_declared",
            }:
                continue
        if any(
            claim in record.claims and normalized(record.claims[claim]) == expected
            for claim in rule.evidence_claims
        ):
            supported.append(record.evidence_id)
            continue
        if rule.structural_claims and candidate_interface is not None:
            if record.claims.get("qualified_interface") != candidate_interface:
                continue
        if any(
            isinstance(record.claims.get(claim), (tuple, list))
            and expected in normalized(record.claims[claim])
            for claim in rule.structural_claims
        ):
            supported.append(record.evidence_id)
    return tuple(supported)
