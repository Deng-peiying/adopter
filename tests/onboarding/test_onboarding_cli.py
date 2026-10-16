from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

from cross_embodiment.cli import _build_parser, _write_provider_transcript, main
from cross_embodiment.onboarding.generator import PackageGenerator
from cross_embodiment.onboarding.workflow import OnboardingWorkflow
from tests.onboarding.test_package_generator import inputs, partial_policy_inputs
from tests.onboarding.test_runtime_policy import _unresolved_run


ROOT = Path(__file__).resolve().parents[2]
VENDOR = Path(__file__).parent / "fixtures" / "ros2_vendor"


def test_agent_cli_is_the_formal_deepseek_entrypoint(tmp_path: Path) -> None:
    args = _build_parser().parse_args([
        "onboard", "agent",
        "--run-root", str(tmp_path / "run"),
        "--platform-root", str(ROOT),
        "--identity", str(tmp_path / "identity.yaml"),
        "--device", "right_arm",
        "--capability", "joint_position_state",
        "--capability", "joint_position",
        "--joint", "arm.right.joint.0",
        "--provider", "deepseek",
    ])

    assert args.onboard_phase == "agent"
    assert args.capability == ["joint_position_state", "joint_position"]
    assert args.joint == ["arm.right.joint.0"]
    assert args.provider == "deepseek"


def test_agent_cli_requires_exact_first_version_capability_scope(tmp_path: Path, capsys) -> None:
    identity = tmp_path / "identity.yaml"
    identity.write_text("package_name: example/test\n")
    code = main([
        "onboard", "agent",
        "--run-root", str(tmp_path / "run"),
        "--platform-root", str(ROOT),
        "--identity", str(identity),
        "--device", "right_arm",
        "--capability", "joint_position_state",
        "--joint", "arm.right.joint.0",
    ])

    assert code == 2
    assert "joint_position_state and joint_position" in capsys.readouterr().err


def test_provider_transcript_records_messages_without_credentials(tmp_path: Path) -> None:
    output = tmp_path / "provider-transcript.json"
    provider = type("Provider", (), {
        "messages": (
            {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "{\"ok\": true}"},
        ),
    })()

    _write_provider_transcript(output, provider, "deepseek", "deepseek-chat")

    saved = json.loads(output.read_text())
    assert saved["schema_version"] == "onboarding-provider-transcript/v0.1"
    assert [item["role"] for item in saved["messages"]] == ["assistant", "tool"]
    text = output.read_text()
    assert "api_key" not in text.lower()
    assert "authorization" not in text.lower()


def test_inspect_requires_explicit_roots_and_writes_stable_artifacts(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run"
    args = ["onboard", "inspect", "--vendor-root", str(VENDOR), "--platform-root", str(ROOT), "--run-root", str(run_root), "--json"]
    assert main(args) == 0
    first = (run_root / "asset-inventory.json").read_bytes()
    assert (run_root / "interface-evidence.yaml").is_file()
    assert (run_root / "isolation-manifest.yaml").is_file()
    output = json.loads(capsys.readouterr().out)
    assert output["phase"] == "inspect"
    assert output["motion_sent"] is False
    assert main(args) == 0
    assert (run_root / "asset-inventory.json").read_bytes() == first


def test_inspect_rejects_denied_vendor_root(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run"
    code = main(["onboard", "inspect", "--vendor-root", str(VENDOR), "--platform-root", str(ROOT), "--run-root", str(run_root), "--denied-root", str(VENDOR)])
    assert code == 2
    assert "denied" in capsys.readouterr().err.lower()


def test_resumed_workflow_restores_platform_root_from_isolation_manifest(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    platform_root = tmp_path / "installed-platform"
    run_root.mkdir()
    platform_root.mkdir()
    (run_root / "isolation-manifest.yaml").write_text(yaml.safe_dump({
        "schema_version": "onboarding-isolation/v0.1",
        "vendor_roots": [],
        "platform_root": str(platform_root),
        "output_root": str(run_root),
        "denied_roots": [],
    }))

    workflow = OnboardingWorkflow(run_root)

    assert workflow.platform_root == platform_root.resolve()


def test_assess_resumes_from_artifacts_and_reports_insufficient_evidence(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    assert main(["onboard", "inspect", "--vendor-root", str(VENDOR), "--platform-root", str(ROOT), "--run-root", str(run_root)]) == 0
    scope = tmp_path / "scope.yaml"
    scope.write_text(yaml.safe_dump({"device_id": "right_arm", "capability_ids": ["joint_position_state", "joint_position"], "ordered_joints": [f"arm.right.joint.{i}" for i in range(7)]}))
    candidates = tmp_path / "candidates.yaml"
    candidates.write_text("candidates: []\n")
    code = main(["onboard", "assess", "--run-root", str(run_root), "--scope", str(scope), "--candidates", str(candidates)])
    assert code == 10
    coverage = yaml.safe_load((run_root / "capability-coverage.yaml").read_text())
    assert {item["status"] for item in coverage["assessments"]} == {"unknown"}
    assert "rclpy" not in sys.modules


def test_validate_and_report_use_only_staged_generated_package(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    coverage, evidence, backend, identity = inputs()
    PackageGenerator.generate(coverage, evidence, backend, run_root / "hardware-package", identity)
    assert main(["onboard", "validate", "--run-root", str(run_root), "--json"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["resolved_package_root"] == str((run_root / "hardware-package").resolve())
    assert main(["onboard", "report", "--run-root", str(run_root), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["l2"] == "passed"
    assert report["motion_sent"] is False


def test_validate_candidate_cli_keeps_unresolved_policy_non_executable(
    tmp_path: Path, capsys,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    coverage, evidence, backend, identity = partial_policy_inputs()
    PackageGenerator.generate_candidate(
        coverage, evidence, backend, run_root / "hardware-package-candidate",
        identity,
    )

    assert main([
        "onboard", "validate-candidate", "--run-root", str(run_root), "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["passed"] is True
    assert result["candidate_only"] is True
    assert result["live_execution_ready"] is False
    assert result["motion_sent"] is False
    assert "execution_policy_gap_recorded" in result["checks"]


def test_confirm_policy_cli_builds_runtime_package_without_motion(
    tmp_path: Path, capsys,
) -> None:
    workflow, identity_path, scope_path = _unresolved_run(tmp_path)
    workflow.assess(scope_path, workflow.run_root / "deterministic-candidates.yaml")
    workflow.generate_candidate(identity_path)

    code = main([
        "onboard", "confirm-policy",
        "--run-root", str(workflow.run_root),
        "--timeout-s", "90",
        "--arrival-tolerance-rad", "0.015",
        "--settle-window-s", "1.0",
        "--source", "previously_live_validated_runtime_policy",
        "--operator", "robot",
        "--reference", "2026-10-13 right-arm measured-arrival validation",
        "--confirmed-at", "2026-10-15T23:30:00+08:00",
        "--json",
    ])

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phase"] == "confirm_policy"
    assert result["conformance_passed"] is True
    assert result["completion_policy_resolved"] is True
    assert result["runtime_package_loadable"] is True
    assert result["runtime_preflight_passed"] is False
    assert result["live_execution_ready"] is False
    assert result["motion_sent"] is False
    assert result["policy_source"] == "previously_live_validated_runtime_policy"
    assert result["package_root"] == str(
        workflow.run_root / "hardware-package-runtime"
    )


def test_read_only_preflight_cli_has_no_run_root_or_motion(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = []

    class Result:
        classification = "passed"

        def to_dict(self):
            return {
                "schema_version": "l3-execution-record/v0.1",
                "package_root": str(tmp_path / "generated"),
                "device_id": "right_arm",
                "commands": [],
                "classification": "preflight_read_only",
                "motion_sent": False,
            }

        def write_json(self, path):
            calls.append(("write", path))

    def fake_preflight(package_root, device_id):
        calls.append((package_root, device_id))
        return Result()

    monkeypatch.setattr(
        "cross_embodiment.onboarding.l3.preflight_generated_package", fake_preflight,
    )
    code = main([
        "onboard", "preflight", "--package-root", str(tmp_path / "generated"),
        "--device", "right_arm", "--json",
    ])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["classification"] == "preflight_read_only"
    assert output["motion_sent"] is False
    assert calls == [(tmp_path / "generated", "right_arm")]


def test_preflight_cli_can_resolve_an_activated_installed_package(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    calls = []

    class Result:
        def to_dict(self):
            return {
                "classification": "preflight_read_only",
                "load_source": "installed_activation",
                "motion_sent": False,
            }

        def write_json(self, path):
            calls.append(("write", path))

    def fake_preflight(store, instance_id, device_id):
        calls.append((store, instance_id, device_id))
        return Result()

    monkeypatch.setattr(
        "cross_embodiment.onboarding.l3.preflight_installed_package",
        fake_preflight,
    )
    code = main([
        "onboard", "preflight",
        "--store", str(tmp_path / "store"),
        "--instance", "lab/right-arm",
        "--device", "right_arm",
        "--json",
    ])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["load_source"] == "installed_activation"
    assert calls == [(tmp_path / "store", "lab/right-arm", "right_arm")]


def test_l3_acceptance_cli_requires_exact_interactive_confirmation(monkeypatch, tmp_path: Path, capsys) -> None:
    target_path = tmp_path / "target.yaml"
    target = {f"arm.right.joint.{index}": float(index) for index in range(7)}
    target_path.write_text(yaml.safe_dump({"positions": target}), encoding="utf-8")
    calls = []

    class Preview:
        package_root = tmp_path / "generated"
        package_tree_sha256 = "a" * 64
        mapping_path = tmp_path / "generated" / "config" / "mapping.yaml"
        mapping_sha256 = "b" * 64
        backend_id = "ros2_mapped"
        backend_entrypoint = "cross_embodiment.driver.ros2_mapped:MappedRos2Adapter"
        state_sample = {"status": "ready", "positions": target}

    class Result:
        classification = "passed"

        def to_dict(self):
            return {"classification": "passed", "motion_sent": True, "commands": [{}, {}]}

        def write_json(self, path):
            calls.append(("write", path))

    monkeypatch.setattr("cross_embodiment.onboarding.l3.preflight_generated_package", lambda *args: Preview())

    def fake_execute(package_root, device_id, positions, **kwargs):
        calls.append((package_root, device_id, positions, kwargs))
        return Result()

    monkeypatch.setattr("cross_embodiment.onboarding.l3.execute_generated_package_round_trip", fake_execute)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    code = main([
        "onboard", "accept-l3", "--package-root", str(tmp_path / "generated"),
        "--device", "right_arm", "--target", str(target_path), "--operator", "robot",
    ])
    assert code == 2
    assert calls == []

    monkeypatch.setattr("builtins.input", lambda prompt: "  EXECUTE L3  ")
    code = main([
        "onboard", "accept-l3", "--package-root", str(tmp_path / "generated"),
        "--device", "right_arm", "--target", str(target_path), "--operator", "robot",
    ])
    assert code == 0
    assert calls[0][0] == tmp_path / "generated"
    assert calls[0][2] == target
    assert calls[0][3] == {"operator": "robot", "authorized": True}
    assert "L3 acceptance preview" in capsys.readouterr().out


def test_l3_acceptance_cli_executes_through_activated_store_package(
    monkeypatch, tmp_path: Path,
) -> None:
    target_path = tmp_path / "target.yaml"
    target = {f"arm.right.joint.{index}": float(index) for index in range(7)}
    target_path.write_text(yaml.safe_dump({"positions": target}), encoding="utf-8")
    calls = []

    class Preview:
        package_root = tmp_path / "store/packages/hardware/example/arm/1.0.0"
        package_tree_sha256 = "a" * 64
        mapping_path = package_root / "config/mapping.yaml"
        mapping_sha256 = "b" * 64
        backend_id = "ros2_mapped"
        backend_entrypoint = "cross_embodiment.driver.ros2_mapped:MappedRos2Adapter"
        load_source = "installed_activation"
        instance_id = "lab/right-arm"
        installed_package_digest = "sha256:" + "c" * 64
        state_sample = {"status": "ready", "positions": target}

    class Result:
        classification = "passed"

        def to_dict(self):
            return {"classification": "passed", "motion_sent": True}

        def write_json(self, path):
            calls.append(("write", path))

    monkeypatch.setattr(
        "cross_embodiment.onboarding.l3.preflight_installed_package",
        lambda store, instance, device: Preview(),
    )

    def fake_execute(store, instance, device, positions, **kwargs):
        calls.append((store, instance, device, positions, kwargs))
        return Result()

    monkeypatch.setattr(
        "cross_embodiment.onboarding.l3.execute_installed_package_round_trip",
        fake_execute,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "EXECUTE L3")

    assert main([
        "onboard", "accept-l3",
        "--store", str(tmp_path / "store"),
        "--instance", "lab/right-arm",
        "--device", "right_arm",
        "--target", str(target_path),
        "--operator", "robot",
    ]) == 0
    assert calls == [(
        tmp_path / "store",
        "lab/right-arm",
        "right_arm",
        target,
        {"operator": "robot", "authorized": True},
    )]


def test_l3_acceptance_cli_rejects_not_ready_before_asking_for_authorization(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    target_path = tmp_path / "target.yaml"
    target = {f"arm.right.joint.{index}": 0.0 for index in range(7)}
    target_path.write_text(yaml.safe_dump({"positions": target}), encoding="utf-8")

    class Preview:
        package_root = tmp_path / "generated"
        package_tree_sha256 = "a" * 64
        mapping_path = tmp_path / "generated" / "config" / "mapping.yaml"
        mapping_sha256 = "b" * 64
        backend_id = "ros2_mapped"
        backend_entrypoint = "cross_embodiment.driver.ros2_mapped:MappedRos2Adapter"
        state_sample = {
            "status": "not_ready",
            "positions": target,
            "details": {"backend_mode": 101, "backend_fault_code": 0},
        }

    monkeypatch.setattr(
        "cross_embodiment.onboarding.l3.preflight_generated_package",
        lambda *args: Preview(),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(
            AssertionError("authorization prompt must not be shown")
        ),
    )

    code = main([
        "onboard", "accept-l3",
        "--package-root", str(tmp_path / "generated"),
        "--device", "right_arm",
        "--target", str(target_path),
        "--operator", "robot",
    ])

    assert code == 2
    assert "not ready (mode=101" in capsys.readouterr().err
