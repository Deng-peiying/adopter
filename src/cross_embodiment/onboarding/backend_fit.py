from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from .capability import CapabilityCoverage


@dataclass(frozen=True)
class BackendDescriptor:
    schema_version: str
    backend_id: str
    version: str
    entrypoint: str
    transport_kinds: tuple[str, ...]
    binding_operations: tuple[str, ...]
    lifecycle_semantics: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "lifecycle_semantics", MappingProxyType(dict(self.lifecycle_semantics)))


@dataclass(frozen=True)
class BackendCapabilityFit:
    capability_id: str
    backend_id: str
    transport_kind: str
    binding_operation: str


@dataclass(frozen=True)
class BackendPluginRequirement:
    capability_id: str
    missing_mechanism: str
    lifecycle_semantics: str
    evidence_ids: tuple[str, ...]
    minimum_tests: tuple[str, ...]


@dataclass(frozen=True)
class BackendFitReport:
    fits: tuple[BackendCapabilityFit, ...]
    plugin_requirements: tuple[BackendPluginRequirement, ...]


def load_backend_descriptor(path: Path) -> BackendDescriptor:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    allowed = {"schema_version", "backend_id", "version", "entrypoint", "transport_kinds", "binding_operations", "lifecycle_semantics", "excluded_mechanisms"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("invalid backend descriptor fields")
    required = allowed - {"excluded_mechanisms"}
    if required - set(data):
        raise ValueError(f"missing backend descriptor fields: {sorted(required - set(data))}")
    if data["schema_version"] != "backend-support/v0.1":
        raise ValueError("unsupported backend descriptor schema")
    return BackendDescriptor(
        data["schema_version"], data["backend_id"], data["version"], data["entrypoint"],
        tuple(data["transport_kinds"]), tuple(data["binding_operations"]), data["lifecycle_semantics"],
    )


class BackendFit:
    @staticmethod
    def evaluate(coverage: CapabilityCoverage, descriptors: tuple[BackendDescriptor, ...]) -> BackendFitReport:
        fits: list[BackendCapabilityFit] = []
        requirements: list[BackendPluginRequirement] = []
        assessments = {item.capability_id: item for item in coverage.assessments}
        for candidate in coverage.candidates:
            assessment = assessments.get(candidate.capability_id)
            if not assessment or (
                assessment.status not in {"native", "derived"}
                and not assessment.mapping_complete
            ):
                continue
            transport = str(candidate.proposed_semantics.get("transport_kind", "unknown"))
            operation = str(candidate.proposed_semantics.get("binding_operation", "unknown"))
            descriptor = next((item for item in descriptors if transport in item.transport_kinds), None)
            if descriptor and operation in descriptor.binding_operations:
                fits.append(BackendCapabilityFit(candidate.capability_id, descriptor.backend_id, transport, operation))
                continue
            missing = transport if descriptor is None else f"operation:{operation}"
            requirements.append(BackendPluginRequirement(
                capability_id=candidate.capability_id,
                missing_mechanism=missing,
                lifecycle_semantics=str(candidate.proposed_semantics.get("lifecycle", "unknown")),
                evidence_ids=candidate.evidence_ids,
                minimum_tests=("Backend protocol conformance", "error and timeout mapping", "lifecycle result semantics"),
            ))
        return BackendFitReport(tuple(fits), tuple(requirements))
