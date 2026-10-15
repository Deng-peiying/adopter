from __future__ import annotations

from pathlib import Path

from cross_embodiment.onboarding.capability import CapabilityMatcher, OnboardingScope
from cross_embodiment.onboarding.catalog import load_capability_catalog
from cross_embodiment.onboarding.evidence import EvidenceMatrix
from cross_embodiment.onboarding.inventory import AssetInventory
from cross_embodiment.onboarding.models import CapabilityCandidate, EvidenceLevel, EvidenceRecord


ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_capability_catalog(ROOT / "catalogs/capabilities/v0.1.yaml")
JOINTS = tuple(f"arm.right.joint.{i}" for i in range(7))
LIMITS = tuple((-2.0, 2.0) for _ in JOINTS)


def ev(identifier: str, claim_type: str, **claims) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=identifier,
        source_asset_ids=(),
        source_path=Path(f"evidence/{identifier}.json"),
        claim_type=claim_type,
        claims=claims,
        provenance={"extractor": "fixture"},
        confidence_boundary="fixture evidence",
        level=EvidenceLevel.DECLARED,
    )


def matrix(*evidence: EvidenceRecord) -> EvidenceMatrix:
    return EvidenceMatrix.build(AssetInventory((), (), ()), evidence)


def state_candidate(*evidence_ids: str, unit: str = "radian") -> CapabilityCandidate:
    return CapabilityCandidate("joint_position_state", evidence_ids, {
        "binding_operation": "joint_state", "transport_kind": "ros2_subscription",
        "endpoint": "/wy/right_arm_state",
        "interface_type": "demo/msg/ArmState",
        "positions_field": "joint_angles", "stamp_field": "header.stamp",
        "mode_field": "arm_mode", "ready_values": [104], "fault_field": "arm_fault.fault_code",
        "unit": unit, "ordered_joints": JOINTS, "joint_limits": LIMITS,
    })


def move_candidate(*evidence_ids: str) -> CapabilityCandidate:
    return CapabilityCandidate("joint_position", evidence_ids, {
        "binding_operation": "joint_position", "transport_kind": "ros2_action",
        "endpoint": "/wy/right_arm_move_action",
        "interface_type": "demo/action/ArmMove",
        "timeout_s": 90.0, "target_field": "goal.target", "target_unit": "radian",
        "constants": {"move_type": "MoveJ"},
        "result_code_field": "result.code",
        "result_description_field": "result.description",
        "success_code": 0, "unit": "radian", "ordered_joints": JOINTS,
        "state_binding": "right_arm_joint_state", "arrival_tolerance_rad": 0.015,
        "settle_window_s": 1.0,
        "completion": ["terminal_result", "measured_arrival"],
    })


def test_matches_native_state_and_position_without_promoting_stages() -> None:
    state = ev("state", "ros2_binding", **dict(state_candidate("state").proposed_semantics))
    move = ev("move", "ros2_binding", **dict(move_candidate("move").proposed_semantics))
    scope = OnboardingScope("right_arm", ("joint_position_state", "joint_position"), JOINTS, (state_candidate("state"), move_candidate("move")))
    coverage = CapabilityMatcher().assess(CATALOG, matrix(state, move), scope)

    assert coverage.get("joint_position_state").status == "native"
    assert coverage.get("joint_position").status == "native"
    assert coverage.get("joint_position").stages.discovered
    assert not coverage.get("joint_position").stages.mapped
    assert not coverage.get("joint_position").stages.offline_verified


def test_classifies_derived_unsupported_and_unknown_separately() -> None:
    derived = ev("derived", "derivation", capability_id="ee_pose_state", derivation="joint_state+urdf+fk")
    unsupported = ev("unsupported", "unsupported", capability_id="joint_torque", reason="vendor exposes no torque command")
    scope = OnboardingScope("right_arm", ("ee_pose_state", "joint_torque", "joint_velocity"), JOINTS, ())
    coverage = CapabilityMatcher().assess(CATALOG, matrix(derived, unsupported), scope)
    assert coverage.get("ee_pose_state").status == "derived"
    assert coverage.get("joint_torque").status == "unsupported"
    assert coverage.get("joint_velocity").status == "unknown"


def test_conflicting_units_block_candidate() -> None:
    first = ev("rad", "ros2_binding", **dict(state_candidate("rad").proposed_semantics))
    second = ev("deg", "documentation", unit="degree")
    scope = OnboardingScope("right_arm", ("joint_position_state",), JOINTS, (state_candidate("rad", "deg"),))
    result = CapabilityMatcher().assess(CATALOG, matrix(first, second), scope).get("joint_position_state")
    assert result.status == "unknown"
    assert result.conflicts == ("unit",)
    assert any(item.field == "unit" for item in result.missing)


def test_weiyi_shaped_extra_interfaces_remain_discovered_unmapped() -> None:
    state = ev("state", "ros2_binding", **dict(state_candidate("state").proposed_semantics))
    move = ev("move", "ros2_binding", **dict(move_candidate("move").proposed_semantics))
    extras = [
        ev("power", "ros2_interface_definition", interface="SetPower", interface_kind="srv"),
        ev("stop", "ros2_interface_definition", interface="StopMove", interface_kind="srv"),
        ev("rt", "ros2_interface_definition", interface="ArmRtCtrl", interface_kind="action"),
    ]
    scope = OnboardingScope("right_arm", ("joint_position_state", "joint_position"), JOINTS, (state_candidate("state"), move_candidate("move")))
    coverage = CapabilityMatcher().assess(CATALOG, matrix(state, move, *extras), scope)
    assert set(coverage.discovered_unmapped_evidence_ids) == {"power", "stop", "rt"}
