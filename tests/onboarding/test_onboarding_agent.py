from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from cross_embodiment.onboarding.agent import OnboardingAgent, OnboardingGoal
from cross_embodiment.onboarding.providers import ProviderToolCall, ProviderTurn
from cross_embodiment.onboarding.workflow import OnboardingWorkflow
from tests.onboarding.test_package_generator import inputs


ROOT = Path(__file__).resolve().parents[2]
VENDOR = Path(__file__).parent / "fixtures" / "ros2_vendor"


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.context = None
        self.received = []
        self.recorded_results = []

    def start(self, context):
        self.context = context

    def next_turn(self, tool_results=(), feedback=None):
        self.received.append((tool_results, feedback))
        return self.turns.pop(0)

    def record_tool_results(self, tool_results):
        self.recorded_results.append(tuple(tool_results))


def call(call_id: str, name: str, arguments=None, *, error=None):
    raw = json.dumps(arguments) if arguments is not None else "{bad-json"
    return ProviderToolCall(call_id, name, arguments, raw, error)


def prepare_workflow(tmp_path: Path):
    run_root = tmp_path / "run"
    workflow = OnboardingWorkflow(run_root, ROOT)
    workflow.inspect((VENDOR,))
    coverage, _, _, identity = inputs()
    evidence_path = run_root / "interface-evidence.yaml"
    data = yaml.safe_load(evidence_path.read_text())
    for candidate, identifier in zip(coverage.candidates, ("state-evidence", "move-evidence")):
        claims = dict(candidate.proposed_semantics)
        if candidate.capability_id == "joint_position":
            claims.update({
                "execution_policy_status": "confirmed",
                "execution_policy_origin": "validated_test_policy",
            })
        data["evidence"].append({
            "evidence_id": identifier,
            "source_asset_ids": [],
            "source_path": f"raw/{identifier}.yaml",
            "claim_type": "reviewed_interface_binding",
            "claims": claims,
            "provenance": {"extractor": "fixture-reviewed-evidence"},
            "confidence_boundary": "test evidence",
            "level": "declared",
            "conflict_group": None,
        })
    evidence_path.write_text(yaml.safe_dump(data, sort_keys=False))
    identity_path = tmp_path / "identity.yaml"
    identity_path.write_text(yaml.safe_dump(identity.__dict__, sort_keys=False))
    return workflow, coverage.candidates, identity_path


def test_agent_handles_multi_calls_errors_and_completes_mapped_package(
    tmp_path: Path, monkeypatch,
) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    invalid = dict(candidates[0].proposed_semantics)
    invalid["endpoint"] = "/invented/right_arm_state"
    turns = [
        ProviderTurn(None, None, (
            call("escape", "read_file", {"path": "/etc/passwd"}),
            call("promote", "promote_verification", {
                "capability_id": "joint_position",
                "stage": "hardware_motion_verified",
            }),
            call("invented", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": invalid,
            }),
        )),
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move", "submit_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "proposed_semantics": dict(candidates[1].proposed_semantics),
            }),
        )),
    ]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-must-never-enter-context")
    provider = ScriptedProvider(turns)
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
    assert next(
        item for item in result.rejections if item.call_id == "promote"
    ).reason == "tool_not_allowed"
    invented_rejection = next(
        item for item in result.tool_trace if item.call_id == "invented"
    )
    missing_requirement = invented_rejection.result["missing_requirements"]
    assert [item["field"] for item in missing_requirement] == ["endpoint"]
    assert "subscription endpoint" in missing_requirement[0]["reason"]
    assert "no linked evidence supports proposed value" in missing_requirement[0]["reason"]
    assert {item.status for item in result.decisions} == {"mapped"}
    state_submission = next(
        item for item in result.tool_trace
        if item.tool == "submit_candidate" and item.ok
        and item.arguments.get("capability_id") == "joint_position_state"
    )
    assert state_submission.arguments["evidence_ids"] == ["state-evidence"]
    assert state_submission.result["accepted"] is True
    assert [item.call_id for item in provider.recorded_results[0]] == [
        "escape", "promote", "invented",
    ]
    initial = provider.context
    assert "secret-must-never-enter-context" not in json.dumps(initial)
    assert "arrival_tolerance_rad" in initial["required_candidate_fields"]["joint_position"]
    assert "positions_field" in initial["required_candidate_fields"]["joint_position_state"]
    assert initial["capability_contracts"]["joint_position_state"]["binding_operations"] == [
        "joint_state",
    ]
    assert initial["capability_contracts"]["joint_position"]["binding_operations"] == [
        "joint_position",
    ]
    assert initial["resolved_platform_fields"]["joint_position"]["state_binding"] == (
        "right_arm_joint_state"
    )
    assert initial["evidence_contract"]["capabilities"]["joint_position_state"]["fault_field"][
        "evidence_claims"
    ] == ["fault_code_field", "fault_field"]
    assert not any(path.name in {"passwd"} for path in workflow.run_root.rglob("*"))


def test_get_evidence_returns_field_level_provenance(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("inspect", "get_evidence", {"evidence_id": "state-evidence"}),
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s"],
                "reason": "execution policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    inspected = next(item for item in result.tool_trace if item.call_id == "inspect")
    assert inspected.result["provenance"] == {"extractor": "fixture-reviewed-evidence"}


def test_agent_can_review_deterministic_candidates_without_retyping_fields(
    tmp_path: Path,
) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    move = dict(candidates[1].proposed_semantics)
    for field in ("timeout_s", "arrival_tolerance_rad", "settle_window_s"):
        move.pop(field)
    workflow.run_root.joinpath("deterministic-candidates.yaml").write_text(
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
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("accept-state", "accept_deterministic_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "reason": "subscription evidence matches joint state semantics",
            }),
            call("accept-move", "accept_deterministic_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "reason": "action interface maps joint position; policy is separate",
            }),
        )),
        ProviderTurn(None, None, (
            call("move-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": [
                    "timeout_s", "arrival_tolerance_rad", "settle_window_s",
                ],
                "reason": "runtime completion policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    assert result.completed
    assert result.package_status == "candidate"
    assert result.candidate_conformance_passed
    assert provider.context["deterministic_candidates"][0]["source"] == (
        "deterministic_normalized_evidence"
    )
    accepted = [
        item for item in result.tool_trace
        if item.tool == "accept_deterministic_candidate" and item.ok
    ]
    assert len(accepted) == 2
    assert all("proposed_semantics" not in item.arguments for item in accepted)


def test_agent_records_terminal_batch_results_without_another_model_request(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s"],
                "reason": "execution timeout policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    assert result.completed
    assert len(provider.received) == 1
    assert [[item.call_id for item in batch] for batch in provider.recorded_results] == [
        ["state", "gap"],
    ]


def test_agent_preserves_mapping_candidate_while_execution_policy_is_gap(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    evidence_path = workflow.run_root / "interface-evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text())
    move_record = next(
        item for item in evidence["evidence"]
        if item["evidence_id"] == "move-evidence"
    )
    move_record["claims"]["execution_policy_status"] = "unconfirmed"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False))
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move-candidate", "submit_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "proposed_semantics": dict(candidates[1].proposed_semantics),
            }),
        )),
        ProviderTurn(None, None, (
            call("move-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": [
                    "timeout_s", "arrival_tolerance_rad", "settle_window_s",
                ],
                "reason": "application helper values are not confirmed vendor policy",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    candidate_call = next(
        item for item in result.tool_trace if item.call_id == "move-candidate"
    )
    assert candidate_call.ok
    assert candidate_call.result["status"] == "mapping_candidate"
    assert candidate_call.result["unresolved_execution_policy"] == [
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    ]
    coverage = yaml.safe_load(
        (workflow.run_root / "capability-coverage.yaml").read_text()
    )
    move = next(
        item for item in coverage["assessments"]
        if item["capability_id"] == "joint_position"
    )
    assert move["candidate_valid"] is True
    assert move["mapping_complete"] is True
    assert move["execution_policy_complete"] is False
    assert result.package_root == workflow.run_root / "hardware-package-candidate"
    assert result.package_status == "candidate"
    assert result.candidate_conformance_passed
    assert not result.conformance_passed
    candidate_mapping = yaml.safe_load(
        (
            result.package_root
            / "config/right_arm_ros2_mapping.candidate.yaml"
        ).read_text()
    )
    assert candidate_mapping["live_execution_ready"] is False


def test_agent_requires_gap_to_name_every_unresolved_policy_for_accepted_mapping(
    tmp_path: Path,
) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    evidence_path = workflow.run_root / "interface-evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text())
    move_record = next(
        item for item in evidence["evidence"]
        if item["evidence_id"] == "move-evidence"
    )
    move_record["claims"]["execution_policy_status"] = "unconfirmed"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False))
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move-candidate", "submit_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "proposed_semantics": dict(candidates[1].proposed_semantics),
            }),
        )),
        ProviderTurn(None, None, (
            call("incomplete-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s"],
                "reason": "only one of three missing policies was named",
            }),
            call("complete-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": [
                    "timeout_s", "arrival_tolerance_rad", "settle_window_s",
                ],
                "reason": "all runtime completion policies are unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    rejection = next(
        item for item in result.rejections if item.call_id == "incomplete-gap"
    )
    assert rejection.reason == "tool_validation_failed"
    assert "must exactly match unresolved candidate fields" in rejection.message
    assert result.package_status == "candidate"
    assert result.candidate_conformance_passed


def test_agent_run_is_not_completed_when_candidate_conformance_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    evidence_path = workflow.run_root / "interface-evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text())
    move_record = next(
        item for item in evidence["evidence"]
        if item["evidence_id"] == "move-evidence"
    )
    move_record["claims"]["execution_policy_status"] = "unconfirmed"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False))
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move", "submit_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "proposed_semantics": dict(candidates[1].proposed_semantics),
            }),
            call("gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": [
                    "timeout_s", "arrival_tolerance_rad", "settle_window_s",
                ],
                "reason": "runtime completion policy is unresolved",
            }),
        )),
    ])
    monkeypatch.setattr(
        workflow,
        "validate_candidate",
        lambda: SimpleNamespace(passed=False),
    )
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    assert not result.completed
    assert result.package_status == "candidate"
    assert not result.candidate_conformance_passed
    saved = json.loads(
        (workflow.run_root / "agent-capability-decisions.json").read_text()
    )
    assert saved["completed"] is False


def test_agent_rejects_second_terminal_decision_for_same_capability(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("state-overwrite", "record_conclusion", {
                "capability_id": "joint_position_state",
                "status": "gap",
                "evidence_ids": ["state-evidence"],
                "missing_fields": ["positions_field"],
                "reason": "conflicting conclusion in the same batch",
            }),
            call("move-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s"],
                "reason": "execution policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    decisions = {item.capability_id: item.status for item in result.decisions}
    assert decisions == {
        "joint_position_state": "mapped",
        "joint_position": "gap",
    }
    rejection = next(item for item in result.rejections if item.call_id == "state-overwrite")
    assert rejection.reason == "capability_already_decided"


def test_agent_stops_after_repeated_plain_text_with_unknown_conclusions(tmp_path: Path) -> None:
    workflow, _, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn("I am done.", None, ()),
        ProviderTurn("Final answer: complete.", None, ()),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider, max_turns=32).run(goal, workflow)

    assert not result.completed
    assert result.model_turn_count == 2
    assert {item.status for item in result.decisions} == {"unknown"}
    assert {item.missing_fields for item in result.decisions} == {
        ("model_tool_conclusion",),
    }


def test_agent_rejects_gap_with_unrelated_evidence_or_non_contract_field(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("bad-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["state-evidence"],
                "missing_fields": ["invented_policy"],
                "reason": "unrelated evidence and field",
            }),
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move-gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s"],
                "reason": "execution timeout policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    rejection = next(item for item in result.rejections if item.call_id == "bad-gap")
    assert rejection.reason == "tool_validation_failed"
    assert "required candidate fields" in rejection.message


def test_agent_plain_text_does_not_finish_and_gap_is_terminal(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn("I found a likely interface.", None, ()),
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "gap",
                "evidence_ids": ["move-evidence"],
                "missing_fields": ["timeout_s", "arrival_tolerance_rad", "settle_window_s"],
                "reason": "execution policy is unresolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    assert result.completed
    assert not result.conformance_passed
    assert result.package_root is None
    assert {item.capability_id: item.status for item in result.decisions} == {
        "joint_position_state": "mapped",
        "joint_position": "gap",
    }
    assert provider.received[1][1] is not None
    saved = json.loads((workflow.run_root / "agent-capability-decisions.json").read_text())
    assert saved["completed"] is True


def test_agent_malformed_arguments_return_structured_error_and_continue(tmp_path: Path) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("bad", "get_evidence", None, error="invalid JSON"),
        )),
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("gap", "record_conclusion", {
                "capability_id": "joint_position",
                "status": "unknown",
                "evidence_ids": [],
                "missing_fields": ["evidence"],
                "reason": "evidence not resolved",
            }),
        )),
    ])
    goal = OnboardingGoal(
        "right_arm", ("joint_position_state", "joint_position"),
        tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
    )

    result = OnboardingAgent(provider).run(goal, workflow)

    assert result.completed
    error = provider.recorded_results[0][0]
    assert error.call_id == "bad"
    assert not error.ok
    assert error.payload["reason"] == "invalid_tool_arguments"


def test_agent_does_not_report_complete_when_backend_fit_blocks_package(
    tmp_path: Path, monkeypatch,
) -> None:
    workflow, candidates, identity_path = prepare_workflow(tmp_path)
    provider = ScriptedProvider([
        ProviderTurn(None, None, (
            call("state", "submit_candidate", {
                "capability_id": "joint_position_state",
                "evidence_ids": ["state-evidence"],
                "proposed_semantics": dict(candidates[0].proposed_semantics),
            }),
            call("move", "submit_candidate", {
                "capability_id": "joint_position",
                "evidence_ids": ["move-evidence"],
                "proposed_semantics": dict(candidates[1].proposed_semantics),
            }),
        )),
    ])
    monkeypatch.setattr(
        "cross_embodiment.onboarding.agent.BackendFit.evaluate",
        lambda *_: SimpleNamespace(plugin_requirements=(object(),), fits=()),
    )

    result = OnboardingAgent(provider).run(
        OnboardingGoal(
            "right_arm", ("joint_position_state", "joint_position"),
            tuple(f"arm.right.joint.{i}" for i in range(7)), identity_path,
        ),
        workflow,
    )

    assert not result.completed
    assert result.package_root is None
    assert result.package_status == "none"


def test_provider_module_imports_without_optional_openai_dependency() -> None:
    from cross_embodiment.onboarding.providers import DeepSeekProvider

    assert DeepSeekProvider.__name__ == "DeepSeekProvider"


def test_deepseek_provider_reads_literal_local_credential_without_executing_file(
    tmp_path: Path, monkeypatch,
) -> None:
    import sys
    from cross_embodiment.onboarding.providers import DeepSeekProvider

    credential = tmp_path / "deepseek_credentials.py"
    credential.write_text(
        'DEEPSEEK_API_KEY = "local-test-key"\n'
        'raise RuntimeError("must not execute credential file")\n',
        encoding="utf-8",
    )
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fake_openai))

    DeepSeekProvider(credential_path=credential)

    assert captured["api_key"] == "local-test-key"
    assert captured["base_url"] == "https://api.deepseek.com"


class FakeCompletions:
    def __init__(self, messages):
        self.responses = list(messages)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = self.responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fixture_message(name: str):
    path = Path(__file__).parent / "fixtures" / "deepseek_protocol" / f"{name}.json"
    return json.loads(path.read_text())["message"]


def test_deepseek_provider_preserves_multi_tool_call_ids_and_results() -> None:
    from cross_embodiment.onboarding.providers import (
        DeepSeekProvider, ProviderToolResult,
    )

    completions = FakeCompletions([
        fixture_message("multi_tool_calls"),
        fixture_message("plain_text"),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = DeepSeekProvider(client=client)
    provider.start({"goal": "inspect"})

    first = provider.next_turn()
    assert len(first.tool_calls) == 4
    assert len({call.call_id for call in first.tool_calls}) == 4
    results = tuple(
        ProviderToolResult(call.call_id, call.name, True, {"items": [call.name]})
        for call in first.tool_calls
    )
    second = provider.next_turn(results)

    assert second.tool_calls == ()
    sent_messages = completions.requests[1]["messages"]
    assistant = next(item for item in sent_messages if item["role"] == "assistant")
    assert [item["id"] for item in assistant["tool_calls"]] == [
        call.call_id for call in first.tool_calls
    ]
    tool_messages = [item for item in sent_messages if item["role"] == "tool"]
    assert [item["tool_call_id"] for item in tool_messages] == [
        call.call_id for call in first.tool_calls
    ]


def test_deepseek_provider_returns_malformed_arguments_as_call_error() -> None:
    from cross_embodiment.onboarding.providers import DeepSeekProvider

    message = {
        "content": None,
        "tool_calls": [{
            "id": "bad-call",
            "type": "function",
            "function": {"name": "get_evidence", "arguments": "{bad-json"},
        }],
    }
    completions = FakeCompletions([message])
    provider = DeepSeekProvider(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions))
    )
    provider.start({"goal": "inspect"})

    turn = provider.next_turn()

    assert turn.tool_calls[0].call_id == "bad-call"
    assert turn.tool_calls[0].arguments is None
    assert turn.tool_calls[0].argument_error


def test_deepseek_provider_preserves_reasoning_content_for_next_request() -> None:
    from cross_embodiment.onboarding.providers import DeepSeekProvider, ProviderToolResult

    first_message = {
        "content": "",
        "reasoning_content": "inspect evidence before deciding",
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "list_evidence", "arguments": "{}"},
        }],
    }
    completions = FakeCompletions([first_message, fixture_message("plain_text")])
    provider = DeepSeekProvider(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        thinking=True,
    )
    provider.start({"goal": "inspect"})
    turn = provider.next_turn()
    provider.next_turn((ProviderToolResult("call-1", "list_evidence", True, []),))

    assistant = next(
        item for item in completions.requests[1]["messages"]
        if item["role"] == "assistant"
    )
    assert assistant["reasoning_content"] == "inspect evidence before deciding"
    assert completions.requests[0]["extra_body"] == {"thinking": {"type": "enabled"}}
