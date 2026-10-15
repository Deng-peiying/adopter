from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .evidence import EvidenceMatrix
from .evidence_contract import (
    evidence_contract, execution_policy_fields, resolve_platform_value,
    supporting_evidence,
)
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


def required_candidate_fields(capability_id: str) -> tuple[str, ...]:
    """Return the deterministic candidate fields enforced by the matcher."""
    return tuple(evidence_contract(capability_id))


def _endpoint_device_matches(
    endpoint: str, device_ids: set[str],
) -> set[str]:
    matched = {
        device for device in device_ids
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(device)}(?![A-Za-z0-9])",
            endpoint,
        )
    }
    return {
        device for device in matched
        if not any(device != other and device in other for other in matched)
    }


def normalize_candidate(
    catalog: CapabilityCatalog,
    matrix: EvidenceMatrix,
    candidate: CapabilityCandidate,
    device_id: str | None = None,
) -> tuple[CapabilityCandidate, tuple[dict[str, Any], ...]]:
    """Normalize transport vocabulary only when linked evidence proves it."""
    definition = catalog.get(candidate.capability_id)
    semantics = dict(candidate.proposed_semantics)
    operation = semantics.get("binding_operation")
    normalizations: list[dict[str, Any]] = []
    if operation not in definition.binding_operations:
        records = matrix.select(candidate.evidence_ids)
        supporting = supporting_evidence(
            candidate.capability_id, "binding_operation", operation, records,
        )
        rule = evidence_contract(candidate.capability_id).get("binding_operation")
        if supporting and len(definition.binding_operations) == 1 and rule:
            canonical = definition.binding_operations[0]
            semantics["binding_operation"] = canonical
            normalizations.append({
                "field": "binding_operation",
                "input": operation,
                "output": canonical,
                "rule": rule.normalization_rule,
                "evidence_ids": list(supporting),
            })
    if device_id:
        for field, rule in evidence_contract(candidate.capability_id).items():
            proposed = semantics.get(field)
            if proposed not in rule.normalization_inputs:
                continue
            canonical = resolve_platform_value(
                candidate.capability_id,
                field,
                binding_operations=definition.binding_operations,
                device_id=device_id,
                ordered_joints=(),
            )
            if canonical is None:
                continue
            semantics[field] = canonical
            normalizations.append({
                "field": field,
                "input": proposed,
                "output": canonical,
                "rule": rule.normalization_rule,
                "evidence_ids": [],
            })
    return (
        CapabilityCandidate(
            candidate.capability_id, candidate.evidence_ids, semantics,
        ),
        tuple(normalizations),
    )


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
            candidate, _ = normalize_candidate(
                catalog, matrix, candidate, scope.device_id,
            )
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
                endpoint = candidate.proposed_semantics.get("endpoint")
                if isinstance(endpoint, str):
                    configured_devices = {
                        str(item.claims["device"])
                        for item in matrix.records
                        if item.claim_type == "robot_joint_configuration"
                        and isinstance(item.claims.get("device"), str)
                    }
                    explicit_devices = {
                        str(item.claims["device"])
                        for item in records
                        if item.claims.get("endpoint") == endpoint
                        and isinstance(item.claims.get("device"), str)
                    }
                    if explicit_devices:
                        associated_devices = explicit_devices
                    else:
                        associated_devices = _endpoint_device_matches(
                            endpoint, configured_devices | {scope.device_id},
                        )
                    if associated_devices != {scope.device_id}:
                        reason = (
                            "linked transport endpoint is associated with another configured device"
                            if associated_devices
                            else "linked transport endpoint does not prove association with the scoped device"
                        )
                        missing.append(MissingRequirement(
                            "endpoint", reason,
                        ))
                for field in required_candidate_fields(capability_id):
                    if any(item.field == field for item in missing):
                        continue
                    if field not in candidate.proposed_semantics:
                        missing.append(MissingRequirement(field, "candidate omitted required semantic"))
                    else:
                        proposed = candidate.proposed_semantics[field]
                        platform_value = resolve_platform_value(
                            capability_id,
                            field,
                            binding_operations=definition.binding_operations,
                            device_id=scope.device_id,
                            ordered_joints=scope.ordered_joints,
                        )
                        if platform_value is not None and (
                            list(proposed) if isinstance(proposed, tuple) else proposed
                        ) == platform_value:
                            continue
                        if supporting_evidence(
                            capability_id,
                            field,
                            proposed,
                            records,
                            candidate_semantics=dict(candidate.proposed_semantics),
                        ):
                            continue
                        fact = evidence_contract(capability_id)[field].fact
                        missing.append(MissingRequirement(
                            field, f"{fact}; no linked evidence supports proposed value",
                        ))
                for field in conflicts:
                    if not any(item.field == field for item in missing):
                        missing.append(MissingRequirement(field, "linked evidence contains conflicting claims"))
                missing_fields = {item.field for item in missing}
                policy_fields = set(execution_policy_fields(capability_id))
                mapping_missing = missing_fields - policy_fields
                mapping_complete = not mapping_missing and not conflicts
                execution_policy_complete = not (
                    missing_fields & policy_fields
                )
                status = "native" if not missing and not conflicts else "unknown"
                assessments.append(CapabilityAssessment(
                    capability_id, status, candidate.evidence_ids,
                    IntegrationStage(discovered=bool(records)), tuple(missing), conflicts,
                    candidate_valid=mapping_complete,
                    mapping_complete=mapping_complete,
                    execution_policy_complete=execution_policy_complete,
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
                candidate_valid=False,
                mapping_complete=False,
                execution_policy_complete=False,
            ))

        unmapped = tuple(
            record.evidence_id for record in matrix.records if record.evidence_id not in used_evidence
        )
        return CapabilityCoverage(
            tuple(assessments), tuple(candidate_by_capability.values()), unmapped,
        )
