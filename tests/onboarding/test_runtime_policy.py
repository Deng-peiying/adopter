from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from tests.onboarding.test_onboarding_agent import prepare_workflow


POLICY_VALUES = {
    "timeout_s": 90.0,
    "arrival_tolerance_rad": 0.015,
    "settle_window_s": 1.0,
}


def _unresolved_run(tmp_path: Path):
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    evidence_path = workflow.run_root / "interface-evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    move_record = next(
        item for item in evidence["evidence"]
        if item["evidence_id"] == "move-evidence"
    )
    move_record["claims"]["execution_policy_status"] = "unconfirmed"
    move_record["claims"]["execution_policy_origin"] = "application_helper_default"
    evidence_path.write_text(
        yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8",
    )
    move = dict(candidates[1].proposed_semantics)
    for field in POLICY_VALUES:
        move.pop(field)
    (workflow.run_root / "deterministic-candidates.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "capability-candidates/v0.1",
            "source": "deterministic_normalized_evidence",
            "candidates": [
                {
                    "capability_id": "joint_position_state",
                    "evidence_ids": ["state-evidence"],
                    "proposed_semantics": dict(candidates[0].proposed_semantics),
                },
                {
                    "capability_id": "joint_position",
                    "evidence_ids": ["move-evidence"],
                    "proposed_semantics": move,
                },
            ],
        }, sort_keys=False),
        encoding="utf-8",
    )
    scope_path = tmp_path / "scope.yaml"
    scope_path.write_text(yaml.safe_dump({
        "device_id": "right_arm",
        "capability_ids": ["joint_position_state", "joint_position"],
        "ordered_joints": [f"arm.right.joint.{index}" for index in range(7)],
    }), encoding="utf-8")
    return workflow, identity_path, scope_path


def test_confirmed_runtime_policy_promotes_candidate_to_auditable_runtime_package(
    tmp_path: Path,
) -> None:
    workflow, identity_path, scope_path = _unresolved_run(tmp_path)
    workflow.assess(scope_path, workflow.run_root / "deterministic-candidates.yaml")
    candidate = workflow.generate_candidate(identity_path)
    evidence_before = (workflow.run_root / "interface-evidence.yaml").read_bytes()
    decisions_path = workflow.run_root / "agent-capability-decisions.json"
    decisions_path.write_text('{"immutable": true}\n', encoding="utf-8")
    decisions_before = decisions_path.read_bytes()
    candidate_before = {
        path.relative_to(candidate.root): path.read_bytes()
        for path in candidate.root.rglob("*") if path.is_file()
    }

    result = workflow.confirm_runtime_policy(
        timeout_s=90.0,
        arrival_tolerance_rad=0.015,
        settle_window_s=1.0,
        source="previously_live_validated_runtime_policy",
        operator="robot",
        reference="2026-10-13 right-arm measured-arrival validation",
        confirmed_at="2026-10-15T23:30:00+08:00",
    )

    assert result.conformance_passed
    assert result.interface_mapped
    assert result.completion_policy_resolved
    assert result.runtime_package_generated
    assert result.runtime_package_loadable
    assert result.runtime_preflight_passed is False
    assert result.live_execution_ready is False
    assert result.motion_sent is False
    assert result.policy_source == "previously_live_validated_runtime_policy"
    assert result.package_root == workflow.run_root / "hardware-package-runtime"
    mapping = yaml.safe_load(
        (result.package_root / "config/right_arm_ros2_mapping.yaml")
        .read_text(encoding="utf-8")
    )
    move = mapping["bindings"]["right_arm_joint_position"]
    assert move["transport"]["timeout_s"] == 90.0
    assert move["completion"]["arrival_tolerance_rad"] == 0.015
    assert move["completion"]["settle_window_s"] == 1.0
    policy = yaml.safe_load(
        (result.package_root / "validation/runtime-completion-policy.yaml")
        .read_text(encoding="utf-8")
    )
    assert {field: policy[field] for field in POLICY_VALUES} == POLICY_VALUES
    assert policy["source"] == "previously_live_validated_runtime_policy"
    assert policy["operator"] == "robot"
    assert policy["candidate_package_digest"] == result.candidate_package_digest
    assert (workflow.run_root / "interface-evidence.yaml").read_bytes() == evidence_before
    assert decisions_path.read_bytes() == decisions_before
    assert {
        path.relative_to(candidate.root): path.read_bytes()
        for path in candidate.root.rglob("*") if path.is_file()
    } == candidate_before
    assert not (workflow.run_root / "interface-evidence.pre-policy.yaml").exists()
    assert result.policy_digest == sha256(
        (result.package_root / "validation/runtime-completion-policy.yaml").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"timeout_s": 0}, "positive"),
        ({"arrival_tolerance_rad": float("nan")}, "finite"),
        ({"source": "vendor_declared"}, "source"),
        ({"operator": ""}, "operator"),
    ],
)
def test_runtime_policy_rejects_invalid_or_unattributed_values(
    tmp_path: Path, overrides: dict, message: str,
) -> None:
    workflow, identity_path, scope_path = _unresolved_run(tmp_path)
    workflow.assess(scope_path, workflow.run_root / "deterministic-candidates.yaml")
    workflow.generate_candidate(identity_path)
    values = {
        **POLICY_VALUES,
        "source": "previously_live_validated_runtime_policy",
        "operator": "robot",
        "reference": "2026-10-13 right-arm measured-arrival validation",
        "confirmed_at": "2026-10-15T23:30:00+08:00",
        **overrides,
    }

    with pytest.raises(ValueError, match=message):
        workflow.confirm_runtime_policy(**values)

    assert not (workflow.run_root / "hardware-package-runtime").exists()
