from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence import EvidenceMatrix
from .models import (
    CapabilityAssessment,
    CapabilityCandidate,
    CapabilityCatalog,
    IntegrationStage,
    MissingRequirement,
)


@dataclass(frozen=True)
class OnboardingScope:
    device_id: str
    capability_ids: tuple[str, ...]
    ordered_joints: tuple[str, ...]
    candidates: tuple[CapabilityCandidate, ...]


@dataclass(frozen=True)
class CapabilityCoverage:
    assessments: tuple[CapabilityAssessment, ...]
    candidates: tuple[CapabilityCandidate, ...]
    discovered_unmapped_evidence_ids: tuple[str, ...]

    def get(self, capability_id: str) -> CapabilityAssessment:
        for item in self.assessments:
            if item.capability_id == capability_id:
                return item
        raise KeyError(capability_id)


_REQUIREMENTS = {
    "joint_position_state": (
        "transport_kind", "endpoint", "interface_type", "value_field", "unit", "ordered_joints"
    ),
    "joint_position": (
        "transport_kind", "endpoint", "interface_type", "mode", "target_field",
        "result_code_field", "result_description_field", "unit", "ordered_joints", "completion",
    ),
}


def _supported(key: str, value: Any, records) -> bool:
    return any(key in record.claims and record.claims[key] == value for record in records)


class CapabilityMatcher:
    def assess(
        self,
        catalog: CapabilityCatalog,
        matrix: EvidenceMatrix,
        scope: OnboardingScope,
    ) -> CapabilityCoverage:
        candidate_by_capability: dict[str, CapabilityCandidate] = {}
        for candidate in scope.candidates:
            catalog.get(candidate.capability_id)
            if candidate.capability_id in candidate_by_capability:
                raise ValueError(f"duplicate capability candidate: {candidate.capability_id}")
            candidate_by_capability[candidate.capability_id] = candidate

        assessments: list[CapabilityAssessment] = []
        used_evidence: set[str] = set()
        for capability_id in scope.capability_ids:
            catalog.get(capability_id)
            candidate = candidate_by_capability.get(capability_id)
            if candidate:
                records = matrix.select(candidate.evidence_ids)
                used_evidence.update(candidate.evidence_ids)
                conflicts = EvidenceMatrix.conflicts(records)
                missing: list[MissingRequirement] = []
                for field in _REQUIREMENTS.get(capability_id, ()):
                    if field not in candidate.proposed_semantics:
                        missing.append(MissingRequirement(field, "candidate omitted required semantic"))
                    elif not _supported(field, candidate.proposed_semantics[field], records):
                        missing.append(MissingRequirement(field, "no linked evidence supports proposed value"))
                for field in conflicts:
                    if not any(item.field == field for item in missing):
                        missing.append(MissingRequirement(field, "linked evidence contains conflicting claims"))
                status = "native" if not missing and not conflicts else "unknown"
                assessments.append(CapabilityAssessment(
                    capability_id, status, candidate.evidence_ids,
                    IntegrationStage(discovered=bool(records)), tuple(missing), conflicts,
                ))
                continue

            derived = tuple(
                record.evidence_id for record in matrix.records
                if record.claim_type == "derivation" and record.claims.get("capability_id") == capability_id
            )
            unsupported = tuple(
                record.evidence_id for record in matrix.records
                if record.claim_type == "unsupported" and record.claims.get("capability_id") == capability_id
            )
            evidence_ids = derived or unsupported
            used_evidence.update(evidence_ids)
            status = "derived" if derived else ("unsupported" if unsupported else "unknown")
            assessments.append(CapabilityAssessment(
                capability_id, status, evidence_ids,
                IntegrationStage(discovered=bool(evidence_ids)),
                () if evidence_ids else (MissingRequirement("evidence", "no evidence supports or rejects capability"),),
            ))

        unmapped = tuple(
            record.evidence_id for record in matrix.records if record.evidence_id not in used_evidence
        )
        return CapabilityCoverage(tuple(assessments), scope.candidates, unmapped)
