from __future__ import annotations

from pathlib import Path

import pytest

from cross_embodiment.onboarding.models import (
    AssetRecord,
    CapabilityAssessment,
    EvidenceLevel,
    EvidenceRecord,
    IntegrationStage,
    MissingRequirement,
)


DIGEST = "a" * 64


def test_asset_and_evidence_records_keep_provenance() -> None:
    asset = AssetRecord(
        asset_id="asset:arm-state",
        relative_path=Path("install/share/arm/msg/ArmState.msg"),
        sha256=DIGEST,
        kind="ros2_interface",
        size_bytes=120,
        source_root="vendor",
    )
    evidence = EvidenceRecord(
        evidence_id="evidence:arm-state-joints",
        source_asset_ids=(asset.asset_id,),
        source_path=asset.relative_path,
        claim_type="ros2_message_field",
        claims={"message": "ArmState", "field": "joint_angles", "unit": "radian"},
        provenance={"extractor": "ros2", "version": "0.1"},
        confidence_boundary="definition_only",
        level=EvidenceLevel.DECLARED,
    )

    assert evidence.source_asset_ids == ("asset:arm-state",)
    assert evidence.claims["unit"] == "radian"
    assert evidence.level is EvidenceLevel.DECLARED


@pytest.mark.parametrize("path", [Path("/etc/passwd"), Path("../escape")])
def test_records_reject_non_relative_source_paths(path: Path) -> None:
    with pytest.raises(ValueError, match="relative_path"):
        AssetRecord("a", path, DIGEST, "source", 1, "vendor")


def test_records_reject_invalid_sha256() -> None:
    with pytest.raises(ValueError, match="sha256"):
        AssetRecord("a", Path("safe.txt"), "not-a-digest", "source", 1, "vendor")


def test_integration_stages_are_independent() -> None:
    stages = IntegrationStage(discovered=True, offline_verified=True)
    assert stages.discovered is True
    assert stages.offline_verified is True
    assert stages.backend_expressible is False
    assert stages.mapped is False
    assert stages.runtime_read_verified is False


def test_motion_verification_requires_external_execution_record() -> None:
    with pytest.raises(ValueError, match="external execution record"):
        IntegrationStage(hardware_motion_verified=True)

    stages = IntegrationStage(
        hardware_motion_verified=True,
        hardware_motion_record_id="l3-record:2026-10-15",
    )
    assert stages.hardware_motion_verified


def test_capability_assessment_preserves_conflicts_and_missing_requirements() -> None:
    assessment = CapabilityAssessment(
        capability_id="joint_position",
        status="unknown",
        evidence_ids=("e1", "e2"),
        stages=IntegrationStage(discovered=True),
        missing=(MissingRequirement("unit", "conflicting radian/degree claims"),),
        conflicts=("unit",),
    )
    assert assessment.status == "unknown"
    assert assessment.conflicts == ("unit",)
    assert assessment.stages.mapped is False


def test_assessment_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        CapabilityAssessment(
            capability_id="joint_position",
            status="supported",
            evidence_ids=(),
            stages=IntegrationStage(),
        )


def test_onboarding_json_schemas_exist_and_are_strict() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (
        "asset-inventory.schema.json",
        "interface-evidence.schema.json",
        "evidence-contract.schema.json",
        "capability-coverage.schema.json",
        "backend-support.schema.json",
    ):
        text = (root / "schemas" / "onboarding" / name).read_text(encoding="utf-8")
        assert '"additionalProperties": false' in text
        assert '"$schema": "https://json-schema.org/draft/2020-12/schema"' in text
