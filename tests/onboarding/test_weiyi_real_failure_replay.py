from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from cross_embodiment.onboarding.capability import CapabilityMatcher, OnboardingScope
from cross_embodiment.onboarding.candidate_builder import DeterministicCandidateBuilder
from cross_embodiment.onboarding.catalog import load_capability_catalog
from cross_embodiment.onboarding.evidence import EvidenceMatrix
from cross_embodiment.onboarding.extractors.base import ScanContext
from cross_embodiment.onboarding.extractors.ros2 import Ros2Extractor
from cross_embodiment.onboarding.inventory import AssetInventory
from cross_embodiment.onboarding.models import CapabilityCandidate


ROOT = Path(__file__).resolve().parents[2]
RAW_VENDOR = Path("/home/robot/文档/for_robot_dpy/robot_launch")
REPLAY = Path(__file__).parent / "fixtures/deepseek_protocol/weiyi_failed_candidates.json"
JOINTS = tuple(f"arm.right.joint.{index}" for index in range(7))

RAW_FILES = (
    "examples/caiquan_demo.py",
    "examples/right_arm_return.py",
    "third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/action/ArmMove.action",
    "third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/msg/ArmState.msg",
    "third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/msg/ArmFault.msg",
    "third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/msg/ArmFaultType.msg",
    "third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/msg/ArmMotionError.msg",
    "third_party/wy_arm_sdk/install/arm_control_system/share/arm_control_system/config/dual_arm_system.yaml",
)


def _real_evidence(tmp_path: Path):
    if not RAW_VENDOR.is_dir():
        pytest.skip("original robot_launch asset root is unavailable")
    vendor = tmp_path / "robot_launch"
    for relative in RAW_FILES:
        source = RAW_VENDOR / relative
        assert source.is_file(), source
        target = vendor / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    records = Ros2Extractor().scan_files(
        ScanContext(vendor, "robot_launch", frozenset())
    )
    return EvidenceMatrix.build(AssetInventory((), (), ()), records)


def _saved_candidate(capability_id: str) -> dict:
    calls = json.loads(REPLAY.read_text())["submit_candidate_calls"]
    matches = [
        item["arguments"] for item in calls
        if item["arguments"]["capability_id"] == capability_id
    ]
    assert matches
    return matches[0]


def _records(matrix: EvidenceMatrix, claim_type: str, **claims):
    return tuple(
        item for item in matrix.records
        if item.claim_type == claim_type
        and all(item.claims.get(key) == value for key, value in claims.items())
    )


def _state_candidate(matrix: EvidenceMatrix, *, corrected_fault: bool = False):
    saved = _saved_candidate("joint_position_state")
    semantics = dict(saved["proposed_semantics"])
    if corrected_fault:
        semantics["fault_field"] = "arm_fault.fault_code"
    subscriptions = _records(
        matrix, "ros2_subscription_usage",
        endpoint="/wy_robot1/right_arm_state",
        interface_type="arm_control_interface/msg/ArmState",
    )
    state_type = next(
        item for item in matrix.records
        if item.claims.get("qualified_interface") == "arm_control_interface/msg/ArmState"
    )
    config = next(
        item for item in matrix.records
        if item.claim_type == "robot_joint_configuration"
        and item.claims.get("device") == "right_arm"
    )
    evidence_ids = tuple(item.evidence_id for item in (*subscriptions, state_type, config))
    return CapabilityCandidate("joint_position_state", evidence_ids, semantics)


def _move_candidate(matrix: EvidenceMatrix):
    saved = _saved_candidate("joint_position")
    semantics = dict(saved["proposed_semantics"])
    action = next(
        item for item in matrix.records
        if item.claim_type == "ros2_action_usage"
        and item.claims.get("endpoint") == "/wy_robot1/right_arm_move_action"
        and item.claims.get("target_field") == "joint_angles"
    )
    action_type = next(
        item for item in matrix.records
        if item.claims.get("qualified_interface") == "arm_control_interface/action/ArmMove"
    )
    config = next(
        item for item in matrix.records
        if item.claim_type == "robot_joint_configuration"
        and item.claims.get("device") == "right_arm"
    )
    arrival = next(
        item for item in matrix.records
        if item.claim_type == "joint_arrival_policy"
        and item.source_path.as_posix() == "examples/caiquan_demo.py"
    )
    evidence_ids = (action.evidence_id, action_type.evidence_id, config.evidence_id, arrival.evidence_id)
    return CapabilityCandidate("joint_position", evidence_ids, semantics)


def _assess(matrix: EvidenceMatrix, candidate: CapabilityCandidate):
    catalog = load_capability_catalog(ROOT / "catalogs/capabilities/v0.1.yaml")
    scope = OnboardingScope(
        "right_arm", (candidate.capability_id,), JOINTS, (candidate,),
    )
    return CapabilityMatcher().assess(catalog, matrix, scope)


def test_saved_state_candidate_replay_distinguishes_fault_type_from_fault_code(
    tmp_path: Path,
) -> None:
    matrix = _real_evidence(tmp_path)

    original = _assess(matrix, _state_candidate(matrix)).get("joint_position_state")
    corrected_coverage = _assess(
        matrix, _state_candidate(matrix, corrected_fault=True),
    )
    corrected = corrected_coverage.get("joint_position_state")

    assert {item.field for item in original.missing} == {"fault_field"}
    assert corrected.status == "native"
    assert corrected.candidate_valid
    assert corrected_coverage.candidates[0].proposed_semantics["binding_operation"] == (
        "joint_state"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("endpoint", "/invented/right_arm_state"),
        ("positions_field", "joint_position"),
        ("unit", "degree"),
        ("ordered_joints", tuple(reversed(JOINTS))),
    ),
)
def test_saved_state_replay_rejects_wrong_mapping_fields(
    tmp_path: Path, field: str, value,
) -> None:
    matrix = _real_evidence(tmp_path)
    candidate = _state_candidate(matrix, corrected_fault=True)
    semantics = dict(candidate.proposed_semantics)
    semantics[field] = value
    wrong = CapabilityCandidate(candidate.capability_id, candidate.evidence_ids, semantics)

    assessment = _assess(matrix, wrong).get("joint_position_state")

    assert assessment.status == "unknown"
    assert field in {item.field for item in assessment.missing}


def test_saved_action_candidate_replay_confirms_mapping_and_keeps_policy_gap(
    tmp_path: Path,
) -> None:
    matrix = _real_evidence(tmp_path)

    coverage = _assess(matrix, _move_candidate(matrix))
    assessment = coverage.get("joint_position")

    assert assessment.status == "unknown"
    assert assessment.candidate_valid
    assert assessment.mapping_complete
    assert not assessment.execution_policy_complete
    assert {item.field for item in assessment.missing} == {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }
    normalized = coverage.candidates[0].proposed_semantics
    assert normalized["binding_operation"] == "joint_position"
    assert normalized["state_binding"] == "right_arm_joint_state"


def test_deterministic_builder_derives_both_interface_candidates_from_raw_assets(
    tmp_path: Path,
) -> None:
    matrix = _real_evidence(tmp_path)
    catalog = load_capability_catalog(ROOT / "catalogs/capabilities/v0.1.yaml")

    candidates = DeterministicCandidateBuilder().build(
        catalog,
        matrix,
        device_id="right_arm",
        capability_ids=("joint_position_state", "joint_position"),
        ordered_joints=JOINTS,
    )
    coverage = CapabilityMatcher().assess(
        catalog,
        matrix,
        OnboardingScope(
            "right_arm",
            ("joint_position_state", "joint_position"),
            JOINTS,
            candidates,
        ),
    )

    state = coverage.get("joint_position_state")
    move = coverage.get("joint_position")
    assert state.status == "native"
    assert state.mapping_complete
    assert move.status == "unknown"
    assert move.mapping_complete
    assert not move.execution_policy_complete
    assert {item.field for item in move.missing} == {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }
    by_capability = {item.capability_id: item for item in coverage.candidates}
    assert by_capability["joint_position_state"].proposed_semantics["endpoint"] == (
        "/wy_robot1/right_arm_state"
    )
    assert by_capability["joint_position"].proposed_semantics["endpoint"] == (
        "/wy_robot1/right_arm_move_action"
    )
    assert "timeout_s" not in by_capability[
        "joint_position"
    ].proposed_semantics


def test_deterministic_builder_does_not_fall_back_to_another_device(
    tmp_path: Path,
) -> None:
    matrix = _real_evidence(tmp_path)
    catalog = load_capability_catalog(ROOT / "catalogs/capabilities/v0.1.yaml")
    records = tuple(
        replace(record, claims={**record.claims, "device": "missing_arm"})
        if record.claim_type == "robot_joint_configuration"
        and record.claims.get("device") == "right_arm"
        else record
        for record in matrix.records
    )
    mismatched = EvidenceMatrix.build(AssetInventory((), (), ()), records)

    with pytest.raises(ValueError, match="scoped ROS2 state, action"):
        DeterministicCandidateBuilder().build(
            catalog,
            mismatched,
            device_id="missing_arm",
            capability_ids=("joint_position_state", "joint_position"),
            ordered_joints=JOINTS,
        )
