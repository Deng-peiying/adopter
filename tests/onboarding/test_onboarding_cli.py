from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

from cross_embodiment.cli import main
from cross_embodiment.onboarding.generator import PackageGenerator
from tests.onboarding.test_package_generator import inputs


ROOT = Path(__file__).resolve().parents[2]
VENDOR = Path(__file__).parent / "fixtures" / "ros2_vendor"


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
