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
        "binding_operation", "transport_kind", "endpoint", "interface_type",
        "positions_field", "stamp_field", "mode_field", "ready_values", "fault_field",
        "unit", "ordered_joints", "joint_limits",
    ),
    "joint_position": (
        "binding_operation", "transport_kind", "endpoint", "interface_type", "timeout_s",
        "target_field", "target_unit", "constants", "result_code_field",
        "result_description_field", "success_code", "unit", "ordered_joints",
        "state_binding", "arrival_tolerance_rad", "settle_window_s", "completion",
    ),
}


def _supported(key: str, value: Any, records) -> bool:
    def normalized(item):
        if isinstance(item, (tuple, list)):
            return [normalized(child) for child in item]
        if isinstance(item, dict):
            return {name: normalized(child) for name, child in item.items()}
        return item
    expected = normalized(value)
    for record in records:
        if key in record.claims and normalized(record.claims[key]) == expected:
            return True
        if key == "target_unit" and normalized(record.claims.get("unit")) == expected:
            return True
        if key.endswith("_field"):
            for claim_name in (
                "field_paths", "goal_field_paths", "result_field_paths",
                "request_field_paths", "response_field_paths", "dynamic_goal_fields",
            ):
                paths = normalized(record.claims.get(claim_name, ()))
                if isinstance(paths, list) and expected in paths:
                    return True
    return False


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
            definition = catalog.get(capability_id)
            candidate = candidate_by_capability.get(capability_id)
            if candidate:
                records = matrix.select(candidate.evidence_ids)
                used_evidence.update(candidate.evidence_ids)
                conflicts = EvidenceMatrix.conflicts(records)
                missing: list[MissingRequirement] = []
                for field in _REQUIREMENTS.get(capability_id, ()):
                    if field not in candidate.proposed_semantics:
                        missing.append(MissingRequirement(field, "candidate omitted required semantic"))
                    elif field == "binding_operation" and candidate.proposed_semantics[field] in definition.binding_operations:
                        continue
                    elif field == "ordered_joints" and tuple(candidate.proposed_semantics[field]) == scope.ordered_joints:
                        continue
                    elif field == "state_binding" and candidate.proposed_semantics[field] == f"{scope.device_id}_joint_state":
                        continue
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
