from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from cross_embodiment.onboarding.agent import OnboardingAgent, OnboardingGoal
from cross_embodiment.onboarding.workflow import OnboardingWorkflow
from tests.onboarding.test_package_generator import inputs


ROOT = Path(__file__).resolve().parents[2]
VENDOR = Path(__file__).parent / "fixtures" / "ros2_vendor"


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.contexts = []

    def next_turn(self, context):
        self.contexts.append(context)
        return self.actions.pop(0)


def prepare_workflow(tmp_path: Path):
    run_root = tmp_path / "run"
    workflow = OnboardingWorkflow(run_root, ROOT)
    workflow.inspect((VENDOR,))
    coverage, _, _, identity = inputs()
    evidence_path = run_root / "interface-evidence.yaml"
    data = yaml.safe_load(evidence_path.read_text())
    for candidate, identifier in zip(coverage.candidates, ("state-evidence", "move-evidence")):
        data["evidence"].append({
            "evidence_id": identifier,
            "source_asset_ids": [],
            "source_path": f"raw/{identifier}.yaml",
            "claim_type": "reviewed_interface_binding",
            "claims": dict(candidate.proposed_semantics),
            "provenance": {"extractor": "fixture-reviewed-evidence"},
            "confidence_boundary": "test evidence",
            "level": "declared",
            "conflict_group": None,
        })
    evidence_path.write_text(yaml.safe_dump(data, sort_keys=False))
    identity_path = tmp_path / "identity.yaml"
    identity_path.write_text(yaml.safe_dump(identity.__dict__, sort_keys=False))
    return workflow, coverage.candidates, identity_path


def test_agent_rejects_escape_promotion_and_invention_then_retries(tmp_path: Path, monkeypatch) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    invalid = dict(candidates[0].proposed_semantics)
    invalid["endpoint"] = "/invented/right_arm_state"
    actions = [
        {"tool": "read_file", "arguments": {"path": "/etc/passwd"}},
        {"tool": "submit_candidate", "arguments": {"capability_id": "joint_position_state", "evidence_ids": ["state-evidence"], "proposed_semantics": invalid}},
        {"tool": "promote_verification", "arguments": {"capability_id": "joint_position", "stage": "hardware_motion_verified"}},
        {"tool": "submit_candidate", "arguments": {"capability_id": "joint_position_state", "evidence_ids": ["state-evidence"], "proposed_semantics": dict(candidates[0].proposed_semantics)}},
        {"tool": "submit_candidate", "arguments": {"capability_id": "joint_position", "evidence_ids": ["move-evidence"], "proposed_semantics": dict(candidates[1].proposed_semantics)}},
        {"tool": "assess", "arguments": {}},
        {"tool": "backend_fit", "arguments": {}},
        {"tool": "generate", "arguments": {}},
        {"tool": "validate", "arguments": {}},
        {"final": "L2 package generated and validated"},
    ]
    provider = ScriptedProvider(actions)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-must-never-enter-context")
    goal = OnboardingGoal(
        device_id="right_arm",
        capability_ids=("joint_position_state", "joint_position"),
        ordered_joints=tuple(f"arm.right.joint.{i}" for i in range(7)),
        identity_path=identity_path,
    )
    result = OnboardingAgent(provider).run(goal, workflow)

    assert result.completed
    assert result.conformance_passed
    assert result.package_root == workflow.run_root / "hardware-package"
    assert {item.reason for item in result.rejections} >= {
        "tool_not_allowed",
        "candidate_not_supported_by_evidence",
    }
    assert sum(1 for item in result.tool_trace if item.tool == "generate" and item.ok) == 1
    assert all("secret-must-never-enter-context" not in json.dumps(context) for context in provider.contexts)
    assert not any(path.name in {"passwd"} for path in workflow.run_root.rglob("*"))


def test_provider_module_imports_without_optional_openai_dependency() -> None:
    from cross_embodiment.onboarding.providers import DeepSeekProvider

    assert DeepSeekProvider.__name__ == "DeepSeekProvider"
