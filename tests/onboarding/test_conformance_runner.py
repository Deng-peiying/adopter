from __future__ import annotations

from pathlib import Path
import shutil
import yaml

import pytest

from cross_embodiment.onboarding.conformance import ConformanceRunner, IndependentEvaluator
from tests.onboarding.test_package_generator import inputs, partial_policy_inputs
from cross_embodiment.onboarding.generator import PackageGenerator


def generated(tmp_path: Path, name: str = "candidate") -> Path:
    coverage, evidence, backend, identity = inputs()
    return PackageGenerator.generate(coverage, evidence, backend, tmp_path / name, identity).root


def test_generated_package_passes_offline_runtime_conformance(tmp_path: Path) -> None:
    root = generated(tmp_path)
    report = ConformanceRunner().validate_generated_package(root)
    assert report.passed
    assert set(report.checks) >= {
        "package_schema", "asset_digests", "package_owned_adapter_contract",
        "mapping_reference", "provenance_isolation", "resolved_package_identity",
    }
    assert report.resolved_package_root == root.resolve()
    assert report.resolved_mapping_path == (root / "config/right_arm_ros2_mapping.yaml").resolve()


def test_candidate_package_passes_static_conformance_and_cannot_be_runtime_loaded(
    tmp_path: Path,
) -> None:
    coverage, evidence, backend, identity = partial_policy_inputs()
    generated = PackageGenerator.generate_candidate(
        coverage, evidence, backend, tmp_path / "candidate-only", identity,
    )

    report = ConformanceRunner().validate_candidate_package(generated.root)

    assert report.passed
    assert set(report.checks) >= {
        "package_schema", "asset_digests", "candidate_mapping_schema",
        "interface_mapping_complete", "runtime_execution_blocked",
        "execution_policy_gap_recorded",
    }
    assert report.resolved_mapping_path == generated.mapping_yaml.resolve()
    package = yaml.safe_load(generated.package_yaml.read_text())
    assert package.get("defaults", {}) == {}
    assert not (generated.root / "config/connection.yaml").exists()


def test_tampered_asset_digest_fails(tmp_path: Path) -> None:
    root = generated(tmp_path)
    mapping = root / "config/right_arm_ros2_mapping.yaml"
    mapping.write_text(mapping.read_text() + "# tampered\n")
    report = ConformanceRunner().validate_generated_package(root)
    assert not report.passed
    assert any("digest" in failure.lower() for failure in report.failures)


def test_provenance_cannot_include_denied_or_absolute_reference(tmp_path: Path) -> None:
    root = generated(tmp_path)
    provenance = yaml.safe_load((root / "generation-provenance.yaml").read_text())
    provenance["evidence"][0]["source_path"] = "/old/ce-hardware-weiyi-dual-o6/config/mapping.yaml"
    (root / "generation-provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))
    # Keep the package digest valid so the isolation failure is independently observed.
    package = yaml.safe_load((root / "package.yaml").read_text())
    import hashlib
    package["assets"]["generation_provenance"][0]["digest"] = "sha256:" + hashlib.sha256((root / "generation-provenance.yaml").read_bytes()).hexdigest()
    (root / "package.yaml").write_text(yaml.safe_dump(package, sort_keys=False))
    report = ConformanceRunner(denied_markers=("ce-hardware-weiyi-dual-o6",)).validate_generated_package(root)
    assert not report.passed
    assert any("provenance" in failure.lower() for failure in report.failures)


def test_mapping_resolution_cannot_select_another_package(tmp_path: Path) -> None:
    root = generated(tmp_path)
    connection = yaml.safe_load((root / "config/connection.yaml").read_text())
    connection["mapping_path"] = "../other/config/mapping.yaml"
    (root / "config/connection.yaml").write_text(yaml.safe_dump(connection))
    report = ConformanceRunner().validate_generated_package(root)
    assert not report.passed
    assert any("mapping reference" in failure.lower() for failure in report.failures)


def test_independent_comparison_reports_semantic_endpoint_difference(tmp_path: Path) -> None:
    candidate = generated(tmp_path, "candidate")
    reference = tmp_path / "reference"
    shutil.copytree(candidate, reference)
    path = reference / "config/right_arm_ros2_mapping.yaml"
    data = yaml.safe_load(path.read_text())
    data["bindings"]["right_arm_joint_position"]["transport"]["endpoint"] = "/different/action"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    diff = IndependentEvaluator.compare(candidate, reference)
    assert not diff.equivalent
    assert any(item.field.endswith("transport.endpoint") for item in diff.differences)
