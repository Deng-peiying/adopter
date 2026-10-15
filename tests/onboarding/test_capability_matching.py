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


def confirmed_policy(claims: dict) -> dict:
    return {
        **claims,
        "execution_policy_status": "confirmed",
        "execution_policy_origin": "validated_test_policy",
    }


def test_matches_native_state_and_position_without_promoting_stages() -> None:
    state = ev("state", "ros2_binding", **dict(state_candidate("state").proposed_semantics))
    move = ev(
        "move", "ros2_binding",
        **confirmed_policy(dict(move_candidate("move").proposed_semantics)),
    )
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
    move = ev(
        "move", "ros2_binding",
        **confirmed_policy(dict(move_candidate("move").proposed_semantics)),
    )
    extras = [
        ev("power", "ros2_interface_definition", interface="SetPower", interface_kind="srv"),
        ev("stop", "ros2_interface_definition", interface="StopMove", interface_kind="srv"),
        ev("rt", "ros2_interface_definition", interface="ArmRtCtrl", interface_kind="action"),
    ]
    scope = OnboardingScope("right_arm", ("joint_position_state", "joint_position"), JOINTS, (state_candidate("state"), move_candidate("move")))
    coverage = CapabilityMatcher().assess(CATALOG, matrix(state, move, *extras), scope)
    assert set(coverage.discovered_unmapped_evidence_ids) == {"power", "stop", "rt"}


def test_structural_interface_paths_support_nested_mapping_fields() -> None:
    state_usage = ev(
        "state-usage", "ros2_subscription_usage",
        binding_operation="joint_state", transport_kind="ros2_subscription",
        endpoint="/wy/right_arm_state", interface_type="demo/msg/ArmState",
        positions_field="joint_angles", mode_field="arm_mode", ready_values=[104],
        fault_code_field="arm_fault.fault_code",
        unit="radian", ordered_joints=JOINTS, joint_limits=LIMITS,
    )
    state_type = ev(
        "state-type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState",
        field_paths=["header.stamp", "joint_angles", "arm_mode", "arm_fault.fault_code"],
    )
    move_usage = ev(
        "move-usage", "ros2_action_usage",
        **confirmed_policy({
            key: value
            for key, value in dict(
                move_candidate("move-usage").proposed_semantics
            ).items()
            if key != "result_description_field"
        }),
    )
    move_type = ev(
        "move-type", "ros2_interface_definition",
        qualified_interface="demo/action/ArmMove",
        result_field_paths=["result.code", "result.description"],
    )
    joint_config = ev(
        "joint-config", "robot_joint_configuration",
        unit="radian", joint_limits=LIMITS,
    )
    candidate_state = state_candidate("state-usage", "state-type", "joint-config")
    candidate_move = move_candidate("move-usage", "move-type")
    scope = OnboardingScope(
        "right_arm", ("joint_position_state", "joint_position"), JOINTS,
        (candidate_state, candidate_move),
    )
    coverage = CapabilityMatcher().assess(
        CATALOG, matrix(state_usage, state_type, move_usage, move_type, joint_config), scope,
    )
    assert coverage.get("joint_position_state").status == "native"
    assert coverage.get("joint_position").status == "native"


def test_platform_contract_supports_operation_canonical_order_and_state_binding() -> None:
    state_semantics = dict(state_candidate("vendor-state").proposed_semantics)
    move_semantics = dict(move_candidate("vendor-move").proposed_semantics)
    platform_fields = {"binding_operation", "ordered_joints"}
    state_evidence = ev(
        "vendor-state", "vendor_binding",
        **{key: value for key, value in state_semantics.items() if key not in platform_fields},
    )
    move_evidence = ev(
        "vendor-move", "vendor_binding",
        **confirmed_policy({
            key: value for key, value in move_semantics.items()
            if key not in platform_fields | {"state_binding"}
        }),
    )
    scope = OnboardingScope(
        "right_arm", ("joint_position_state", "joint_position"), JOINTS,
        (state_candidate("vendor-state"), move_candidate("vendor-move")),
    )
    coverage = CapabilityMatcher().assess(CATALOG, matrix(state_evidence, move_evidence), scope)
    assert coverage.get("joint_position_state").status == "native"
    assert coverage.get("joint_position").status == "native"


def test_target_unit_can_be_supported_by_vendor_joint_unit_evidence() -> None:
    semantics = dict(move_candidate("move", "unit").proposed_semantics)
    move = ev(
        "move", "ros2_action_usage",
        **confirmed_policy({
            key: value for key, value in semantics.items()
            if key != "target_unit"
        }),
    )
    unit = ev("unit", "robot_joint_configuration", unit="radian")
    scope = OnboardingScope(
        "right_arm", ("joint_position",), JOINTS,
        (move_candidate("move", "unit"),),
    )
    assessment = CapabilityMatcher().assess(CATALOG, matrix(move, unit), scope).get("joint_position")
    assert assessment.status == "native"


def test_policy_values_without_affirmative_confirmation_remain_gaps() -> None:
    semantics = dict(move_candidate("move").proposed_semantics)
    move = ev("move", "ros2_action_usage", **semantics)
    scope = OnboardingScope(
        "right_arm", ("joint_position",), JOINTS,
        (move_candidate("move"),),
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(move), scope,
    ).get("joint_position")

    assert assessment.mapping_complete
    assert not assessment.execution_policy_complete
    assert {item.field for item in assessment.missing} == {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }


def test_structural_field_must_come_from_the_correct_interface_section() -> None:
    state_usage = ev(
        "state", "ros2_subscription_usage",
        binding_operation="joint_state", transport_kind="ros2_subscription",
        endpoint="/wy/right_arm_state", interface_type="demo/msg/ArmState",
        positions_field="joint_angles", mode_field="arm_mode", ready_values=[104],
        fault_code_field="arm_fault.fault_code",
    )
    wrong_section = ev(
        "type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState",
        result_field_paths=["header.stamp"],
    )
    config = ev(
        "config", "robot_joint_configuration",
        unit="radian", joint_limits=LIMITS,
    )
    candidate = state_candidate("state", "type", "config")
    scope = OnboardingScope(
        "right_arm", ("joint_position_state",), JOINTS, (candidate,),
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(state_usage, wrong_section, config), scope,
    ).get("joint_position_state")

    assert assessment.status == "unknown"
    assert {item.field for item in assessment.missing} == {"stamp_field"}


def test_unconfirmed_application_policy_is_not_vendor_execution_semantics() -> None:
    semantics = dict(move_candidate("move").proposed_semantics)
    move = ev(
        "move",
        "ros2_action_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {"arrival_tolerance_rad", "settle_window_s", "completion"}
        },
        execution_policy_status="unconfirmed",
        execution_policy_origin="python_function_default",
    )
    arrival = ev(
        "arrival",
        "joint_arrival_policy",
        arrival_tolerance_rad=0.015,
        settle_window_s=1.0,
        completion=["terminal_result", "measured_arrival"],
        execution_policy_status="unconfirmed",
        execution_policy_origin="application_helper_default",
    )
    candidate = move_candidate("move", "arrival")
    scope = OnboardingScope("right_arm", ("joint_position",), JOINTS, (candidate,))

    assessment = CapabilityMatcher().assess(CATALOG, matrix(move, arrival), scope).get("joint_position")

    assert assessment.status == "unknown"
    assert {item.field for item in assessment.missing} == {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }


def test_transport_operation_is_deterministically_normalized_to_sdk_operation() -> None:
    semantics = dict(state_candidate("state", "type", "unit").proposed_semantics)
    semantics["binding_operation"] = "subscribe"
    candidate = CapabilityCandidate(
        "joint_position_state", ("state", "type", "unit"), semantics,
    )
    state = ev(
        "state", "ros2_subscription_usage",
        transport_operation="subscribe", transport_kind="ros2_subscription",
        endpoint="/wy/right_arm_state", interface_type="demo/msg/ArmState",
        positions_field="joint_angles", mode_field="arm_mode", ready_values=[104],
        fault_code_field="arm_fault.fault_code",
    )
    state_type = ev(
        "type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState",
        field_paths=["header.stamp", "joint_angles", "arm_mode", "arm_fault.fault_code"],
    )
    unit = ev("unit", "robot_joint_configuration", unit="radian", joint_limits=LIMITS)
    scope = OnboardingScope(
        "right_arm", ("joint_position_state",), JOINTS, (candidate,),
    )

    coverage = CapabilityMatcher().assess(CATALOG, matrix(state, state_type, unit), scope)

    assert coverage.get("joint_position_state").status == "native"
    assert coverage.candidates[0].proposed_semantics["binding_operation"] == "joint_state"


def test_transport_operation_normalization_rejects_unobserved_operation() -> None:
    semantics = dict(state_candidate("state").proposed_semantics)
    semantics["binding_operation"] = "publish"
    candidate = CapabilityCandidate(
        "joint_position_state", ("state", "type", "config"), semantics,
    )
    evidence = ev(
        "state", "ros2_subscription_usage",
        **{
            key: value for key, value in semantics.items()
            if key != "binding_operation"
        },
        transport_operation="subscribe",
        fault_code_field="arm_fault.fault_code",
    )
    state_type = ev(
        "type", "ros2_interface_definition", field_paths=["header.stamp"],
        qualified_interface="demo/msg/ArmState",
    )
    config = ev(
        "config", "robot_joint_configuration",
        unit="radian", joint_limits=LIMITS,
    )
    scope = OnboardingScope(
        "right_arm", ("joint_position_state",), JOINTS, (candidate,),
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(evidence, state_type, config), scope,
    ).get(
        "joint_position_state"
    )

    assert assessment.status == "unknown"
    assert {item.field for item in assessment.missing} == {"binding_operation"}


def test_fault_field_requires_fault_code_usage_not_only_structural_path() -> None:
    semantics = dict(state_candidate("state", "type").proposed_semantics)
    semantics["fault_field"] = "arm_fault.fault_type.value"
    candidate = CapabilityCandidate(
        "joint_position_state", ("state", "type", "config"), semantics,
    )
    state = ev(
        "state", "ros2_subscription_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {"binding_operation", "fault_field", "stamp_field"}
        },
        transport_operation="subscribe",
        fault_code_field="arm_fault.fault_code",
    )
    state_type = ev(
        "type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState",
        field_paths=[
            "header.stamp", "arm_fault.fault_code", "arm_fault.fault_type.value",
        ],
    )
    config = ev(
        "config", "robot_joint_configuration",
        unit="radian", joint_limits=LIMITS,
    )
    scope = OnboardingScope(
        "right_arm", ("joint_position_state",), JOINTS, (candidate,),
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(state, state_type, config), scope,
    ).get(
        "joint_position_state"
    )

    assert assessment.status == "unknown"
    assert {item.field for item in assessment.missing} == {"fault_field"}


def test_action_transport_and_state_binding_aliases_normalize_but_policy_stays_gap() -> None:
    semantics = dict(move_candidate("move", "arrival").proposed_semantics)
    semantics["binding_operation"] = "send_action_goal"
    semantics["state_binding"] = "joint_position_state"
    candidate = CapabilityCandidate(
        "joint_position", ("move", "arrival"), semantics,
    )
    move = ev(
        "move", "ros2_action_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {
                "binding_operation", "state_binding", "arrival_tolerance_rad",
                "settle_window_s", "completion",
            }
        },
        transport_operation="send_action_goal",
        execution_policy_status="unconfirmed",
    )
    arrival = ev(
        "arrival", "joint_arrival_policy",
        arrival_tolerance_rad=semantics["arrival_tolerance_rad"],
        settle_window_s=semantics["settle_window_s"],
        completion=semantics["completion"],
        execution_policy_status="unconfirmed",
    )
    scope = OnboardingScope(
        "right_arm", ("joint_position",), JOINTS, (candidate,),
    )

    coverage = CapabilityMatcher().assess(CATALOG, matrix(move, arrival), scope)
    assessment = coverage.get("joint_position")

    assert assessment.status == "unknown"
    assert coverage.candidates[0].proposed_semantics["binding_operation"] == "joint_position"
    assert coverage.candidates[0].proposed_semantics["state_binding"] == "right_arm_joint_state"
    assert {item.field for item in assessment.missing} == {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }
    assert assessment.candidate_valid


def test_structural_field_from_another_interface_cannot_support_candidate() -> None:
    semantics = dict(state_candidate("state", "wrong-type", "config").proposed_semantics)
    state = ev(
        "state", "ros2_subscription_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {"binding_operation", "stamp_field", "unit", "joint_limits"}
        },
        transport_operation="subscribe",
        fault_code_field="arm_fault.fault_code",
    )
    wrong_type = ev(
        "wrong-type", "ros2_interface_definition",
        qualified_interface="other/msg/Telemetry",
        field_paths=["header.stamp"],
    )
    config = ev(
        "config", "robot_joint_configuration", device="right_arm",
        unit="radian", joint_limits=LIMITS,
    )
    candidate = CapabilityCandidate(
        "joint_position_state", ("state", "wrong-type", "config"), semantics,
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(state, wrong_type, config),
        OnboardingScope("right_arm", ("joint_position_state",), JOINTS, (candidate,)),
    ).get("joint_position_state")

    assert assessment.status == "unknown"
    assert {item.field for item in assessment.missing} == {"stamp_field"}


def test_transport_endpoint_associated_with_other_configured_device_is_rejected() -> None:
    semantics = dict(state_candidate("left", "type", "right-config").proposed_semantics)
    semantics["endpoint"] = "/wy/left_arm_state"
    left = ev(
        "left", "ros2_subscription_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {"binding_operation", "stamp_field", "unit", "joint_limits"}
        },
        transport_operation="subscribe",
        fault_code_field="arm_fault.fault_code",
    )
    interface = ev(
        "type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState", field_paths=["header.stamp"],
    )
    right_config = ev(
        "right-config", "robot_joint_configuration", device="right_arm",
        unit="radian", joint_limits=LIMITS,
    )
    left_config = ev(
        "left-config", "robot_joint_configuration", device="left_arm",
        unit="radian", joint_limits=LIMITS,
    )
    candidate = CapabilityCandidate(
        "joint_position_state", ("left", "type", "right-config"), semantics,
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(left, interface, right_config, left_config),
        OnboardingScope("right_arm", ("joint_position_state",), JOINTS, (candidate,)),
    ).get("joint_position_state")

    assert assessment.status == "unknown"
    endpoint_error = next(item for item in assessment.missing if item.field == "endpoint")
    assert "another configured device" in endpoint_error.reason


def test_transport_endpoint_without_target_device_association_is_rejected() -> None:
    semantics = dict(state_candidate("left", "type", "right-config").proposed_semantics)
    semantics["endpoint"] = "/wy/left_arm_state"
    left = ev(
        "left", "ros2_subscription_usage",
        **{
            key: value for key, value in semantics.items()
            if key not in {"binding_operation", "stamp_field", "unit", "joint_limits"}
        },
        transport_operation="subscribe",
        fault_code_field="arm_fault.fault_code",
    )
    interface = ev(
        "type", "ros2_interface_definition",
        qualified_interface="demo/msg/ArmState", field_paths=["header.stamp"],
    )
    right_config = ev(
        "right-config", "robot_joint_configuration", device="right_arm",
        unit="radian", joint_limits=LIMITS,
    )
    candidate = CapabilityCandidate(
        "joint_position_state", ("left", "type", "right-config"), semantics,
    )

    assessment = CapabilityMatcher().assess(
        CATALOG, matrix(left, interface, right_config),
        OnboardingScope("right_arm", ("joint_position_state",), JOINTS, (candidate,)),
    ).get("joint_position_state")

    endpoint_error = next(item for item in assessment.missing if item.field == "endpoint")
    assert "does not prove association" in endpoint_error.reason
