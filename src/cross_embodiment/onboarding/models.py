from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    category: str
    binding_operations: tuple[str, ...]
    semantics: Mapping[str, Any]
    required_for_profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantics", MappingProxyType(dict(self.semantics)))


@dataclass(frozen=True)
class CapabilityCatalog:
    schema_version: str
    catalog_version: str
    assessment_statuses: tuple[str, ...]
    capabilities: tuple[CapabilityDefinition, ...]

    def get(self, capability_id: str) -> CapabilityDefinition:
        for capability in self.capabilities:
            if capability.id == capability_id:
                return capability
        raise KeyError(capability_id)


class EvidenceLevel(str, Enum):
    DECLARED = "declared"
    OBSERVED = "observed"
    RUNTIME_READ = "runtime_read"
    HARDWARE_MOTION = "hardware_motion"


def _validate_relative_path(path: Path, field: str) -> None:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a contained relative path")


def _validate_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    relative_path: Path
    sha256: str
    kind: str
    size_bytes: int
    source_root: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path, "relative_path")
        _validate_digest(self.sha256, "sha256")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    source_asset_ids: tuple[str, ...]
    source_path: Path
    claim_type: str
    claims: Mapping[str, Any]
    provenance: Mapping[str, Any]
    confidence_boundary: str
    level: EvidenceLevel
    conflict_group: str | None = None

    def __post_init__(self) -> None:
        _validate_relative_path(self.source_path, "source_path")
        object.__setattr__(self, "claims", MappingProxyType(dict(self.claims)))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True)
class IntegrationStage:
    discovered: bool = False
    backend_expressible: bool = False
    mapped: bool = False
    offline_verified: bool = False
    runtime_read_verified: bool = False
    hardware_motion_verified: bool = False
    hardware_motion_record_id: str | None = None

    def __post_init__(self) -> None:
        if self.hardware_motion_verified and not self.hardware_motion_record_id:
            raise ValueError(
                "hardware_motion_verified requires an external execution record"
            )
        if self.hardware_motion_record_id and not self.hardware_motion_verified:
            raise ValueError(
                "hardware_motion_record_id requires hardware_motion_verified"
            )


@dataclass(frozen=True)
class MissingRequirement:
    field: str
    reason: str


@dataclass(frozen=True)
class CapabilityAssessment:
    capability_id: str
    status: str
    evidence_ids: tuple[str, ...]
    stages: IntegrationStage
    missing: tuple[MissingRequirement, ...] = ()
    conflicts: tuple[str, ...] = ()
    candidate_valid: bool = False
    mapping_complete: bool = False
    execution_policy_complete: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"native", "derived", "unsupported", "unknown"}:
            raise ValueError("status must use the canonical assessment vocabulary")


@dataclass(frozen=True)
class CapabilityCandidate:
    capability_id: str
    evidence_ids: tuple[str, ...]
    proposed_semantics: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposed_semantics", MappingProxyType(dict(self.proposed_semantics))
        )
