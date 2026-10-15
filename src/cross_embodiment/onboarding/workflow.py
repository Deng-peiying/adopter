from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .backend_fit import BackendFit, BackendFitReport, load_backend_descriptor
from .capability import CapabilityCoverage, CapabilityMatcher, OnboardingScope
from .catalog import load_capability_catalog
from .conformance import ConformanceReport, ConformanceRunner
from .evidence import EvidenceMatrix
from .extractors.base import ScanContext
from .extractors.native import NativeExtractor
from .extractors.python import PythonExtractor
from .extractors.robot_model import RobotModelExtractor
from .extractors.ros2 import Ros2Extractor
from .generator import GeneratedPackage, PackageGenerator, PackageIdentity
from .inventory import AssetInventory, DuplicateDigest, InventoryBuilder, InventoryIssue
from .isolation import IsolationPolicy, PlatformLock
from .models import (
    AssetRecord, CapabilityAssessment, CapabilityCandidate, EvidenceLevel,
    EvidenceRecord, IntegrationStage, MissingRequirement,
)


class OnboardingWorkflowError(ValueError):
    exit_code = 2


class AssetInsufficiency(OnboardingWorkflowError):
    exit_code = 10


class SemanticConflict(OnboardingWorkflowError):
    exit_code = 11


class BackendGap(OnboardingWorkflowError):
    exit_code = 12


class SchemaFailure(OnboardingWorkflowError):
    exit_code = 13


class ConformanceFailure(OnboardingWorkflowError):
    exit_code = 14


def _plain(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, EvidenceLevel):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    return value


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_plain(value), sort_keys=False), encoding="utf-8")


def _load_inventory(path: Path) -> AssetInventory:
    data = json.loads(path.read_text(encoding="utf-8"))
    assets = tuple(AssetRecord(
        item["asset_id"], Path(item["relative_path"]), item["sha256"], item["kind"],
        int(item["size_bytes"]), item["source_root"],
    ) for item in data["assets"])
    issues = tuple(InventoryIssue(**item) for item in data.get("issues", []))
    duplicates = tuple(DuplicateDigest(item["sha256"], tuple(item["relative_paths"])) for item in data.get("duplicate_digests", []))
    return AssetInventory(assets, issues, duplicates)


def _load_evidence(path: Path) -> tuple[EvidenceRecord, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(EvidenceRecord(
        evidence_id=item["evidence_id"], source_asset_ids=tuple(item["source_asset_ids"]),
        source_path=Path(item["source_path"]), claim_type=item["claim_type"],
        claims=item["claims"], provenance=item["provenance"],
        confidence_boundary=item["confidence_boundary"], level=EvidenceLevel(item["level"]),
        conflict_group=item.get("conflict_group"),
    ) for item in data["evidence"])


def _load_candidates(path: Path) -> tuple[CapabilityCandidate, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return tuple(CapabilityCandidate(
        item["capability_id"], tuple(item.get("evidence_ids", ())), item.get("proposed_semantics", {})
    ) for item in data.get("candidates", []))


def _coverage_payload(coverage: CapabilityCoverage) -> dict[str, Any]:
    return {
        "schema_version": "capability-coverage/v0.1",
        "assessments": [_plain(item) for item in coverage.assessments],
        "candidates": [_plain(item) for item in coverage.candidates],
        "discovered_unmapped_evidence_ids": list(coverage.discovered_unmapped_evidence_ids),
    }


def _load_coverage(path: Path) -> CapabilityCoverage:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assessments = []
    for item in data["assessments"]:
        stage = item["stages"]
        assessments.append(CapabilityAssessment(
            item["capability_id"], item["status"], tuple(item["evidence_ids"]),
            IntegrationStage(**stage),
            tuple(MissingRequirement(**entry) for entry in item.get("missing", [])),
            tuple(item.get("conflicts", [])),
        ))
    candidates = tuple(CapabilityCandidate(
        item["capability_id"], tuple(item["evidence_ids"]), item["proposed_semantics"]
    ) for item in data.get("candidates", []))
    return CapabilityCoverage(tuple(assessments), candidates, tuple(data.get("discovered_unmapped_evidence_ids", [])))


class OnboardingWorkflow:
    def __init__(self, run_root: Path, platform_root: Path | None = None):
        self.run_root = run_root.resolve()
        self.platform_root = (platform_root or Path(__file__).resolve().parents[3]).resolve()

    def inspect(self, vendor_roots: tuple[Path, ...], denied_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        policy = IsolationPolicy(tuple(vendor_roots), (self.platform_root,), self.run_root, denied_roots)
        for root in vendor_roots:
            policy.authorize_read(root)
        inventory = InventoryBuilder().build(vendor_roots)
        inventory.write_json(policy.authorize_write(self.run_root / "asset-inventory.json"))
        evidence: list[EvidenceRecord] = []
        extractors = (Ros2Extractor(), PythonExtractor(), NativeExtractor(), RobotModelExtractor())
        for root_value in vendor_roots:
            root = root_value.resolve()
            context = ScanContext(root, root.name, frozenset({".git", ".cache", ".pytest_cache", "__pycache__", "logs", "log"}))
            for extractor in extractors:
                evidence.extend(extractor.scan_files(context))
        matrix = EvidenceMatrix.build(inventory, evidence)
        _write_yaml(self.run_root / "interface-evidence.yaml", {
            "schema_version": "interface-evidence/v0.1",
            "evidence": [_plain(item) for item in matrix.records],
        })
        schema_paths = [self.platform_root / "catalogs/capabilities/v0.1.yaml", *sorted((self.platform_root / "schemas").rglob("*.json")), *sorted((self.platform_root / "catalogs/backends").glob("*.yaml"))]
        PlatformLock.capture(self.platform_root, schema_paths).write(self.run_root / "platform-lock.yaml")
        _write_yaml(self.run_root / "isolation-manifest.yaml", {
            "schema_version": "onboarding-isolation/v0.1",
            "vendor_roots": [str(path.resolve()) for path in vendor_roots],
            "platform_root": str(self.platform_root),
            "output_root": str(self.run_root),
            "denied_roots": [str(path.resolve()) for path in denied_roots],
        })
        return {"phase": "inspect", "asset_count": len(inventory.assets), "evidence_count": len(matrix.records), "motion_sent": False}

    def evidence_matrix(self) -> EvidenceMatrix:
        return EvidenceMatrix.build(
            _load_inventory(self.run_root / "asset-inventory.json"),
            _load_evidence(self.run_root / "interface-evidence.yaml"),
        )

    def assess(self, scope_path: Path, candidates_path: Path) -> CapabilityCoverage:
        scope_data = yaml.safe_load(scope_path.read_text(encoding="utf-8"))
        candidates = _load_candidates(candidates_path)
        return self.assess_candidates(scope_data, candidates)

    def assess_candidates(
        self, scope_data: Mapping[str, Any], candidates: tuple[CapabilityCandidate, ...]
    ) -> CapabilityCoverage:
        scope = OnboardingScope(
            scope_data["device_id"], tuple(scope_data["capability_ids"]),
            tuple(scope_data["ordered_joints"]), candidates,
        )
        catalog = load_capability_catalog(self.platform_root / "catalogs/capabilities/v0.1.yaml")
        coverage = CapabilityMatcher().assess(catalog, self.evidence_matrix(), scope)
        _write_yaml(self.run_root / "capability-coverage.yaml", _coverage_payload(coverage))
        return coverage

    def generate(self, identity_path: Path) -> GeneratedPackage:
        coverage = _load_coverage(self.run_root / "capability-coverage.yaml")
        if any(item.conflicts for item in coverage.assessments):
            raise SemanticConflict("capability coverage contains semantic conflicts")
        if any(item.status not in {"native", "derived"} for item in coverage.assessments):
            raise AssetInsufficiency("required capability evidence is incomplete")
        descriptor = load_backend_descriptor(self.platform_root / "catalogs/backends/ros2_mapped_v0.1.yaml")
        fit = BackendFit.evaluate(coverage, (descriptor,))
        _write_yaml(self.run_root / "backend-fit.yaml", _plain(fit))
        if fit.plugin_requirements:
            raise BackendGap("current backend cannot express every required capability")
        identity = PackageIdentity(**yaml.safe_load(identity_path.read_text(encoding="utf-8")))
        return PackageGenerator.generate(coverage, self.evidence_matrix(), fit, self.run_root / "hardware-package", identity)

    def validate(self) -> ConformanceReport:
        report = ConformanceRunner().validate_generated_package(self.run_root / "hardware-package")
        payload = {
            "passed": report.passed, "checks": list(report.checks), "failures": list(report.failures),
            "resolved_package_root": str(report.resolved_package_root),
            "resolved_mapping_path": str(report.resolved_mapping_path) if report.resolved_mapping_path else None,
            "motion_sent": False,
        }
        (self.run_root / "conformance-report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return report

    def report(self) -> dict[str, Any]:
        conformance = self.run_root / "conformance-report.json"
        validation = json.loads(conformance.read_text()) if conformance.is_file() else None
        return {
            "run_root": str(self.run_root),
            "l1": "completed" if (self.run_root / "interface-evidence.yaml").is_file() else "not_started",
            "l2": "passed" if validation and validation.get("passed") else ("failed" if validation else "not_started"),
            "motion_sent": False,
        }
