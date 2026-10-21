from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .backend_fit import BackendFit, load_backend_descriptor
from .capability import (
    CapabilityMatcher, OnboardingScope, normalize_candidate,
    required_candidate_fields,
)
from .catalog import load_capability_catalog
from .evidence_contract import (
    evidence_contract_document, execution_policy_fields, resolved_platform_fields,
)
from .models import CapabilityCandidate, MissingRequirement
from .providers import (
    OnboardingModelProvider,
    ProviderToolCall,
    ProviderToolResult,
)
from .workflow import OnboardingWorkflow


@dataclass(frozen=True)
class OnboardingGoal:
    device_id: str
    capability_ids: tuple[str, ...]
    ordered_joints: tuple[str, ...]
    identity_path: Path


@dataclass(frozen=True)
class CapabilityDecision:
    capability_id: str
    status: str
    evidence_ids: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class AgentRejection:
    call_id: str
    tool: str
    reason: str
    message: str


@dataclass(frozen=True)
class ToolTrace:
    call_id: str
    tool: str
    ok: bool
    arguments: Mapping[str, Any] | None
    result: Any


@dataclass(frozen=True)
class OnboardingRunResult:
    completed: bool
    final_message: str
    package_root: Path | None
    conformance_passed: bool
    package_status: str
    interface_mapped: bool
    candidate_generated: bool
    candidate_conformance_passed: bool
    completion_policy_resolved: bool
    live_execution_ready: bool
    decisions: tuple[CapabilityDecision, ...]
    rejections: tuple[AgentRejection, ...]
    tool_trace: tuple[ToolTrace, ...]
    model_turn_count: int


_ALLOWED_TOOLS = {
    "list_evidence", "get_evidence", "submit_candidate",
    "accept_deterministic_candidate",
    "record_conclusion", "assess",
}

_FIRST_VERSION_CAPABILITIES = frozenset({"joint_position_state", "joint_position"})


class CandidateRejected(ValueError):
    def __init__(
        self,
        missing_requirements: tuple[MissingRequirement, ...],
        conflicts: tuple[str, ...],
    ):
        super().__init__("candidate is not fully supported by linked evidence")
        self.missing_requirements = missing_requirements
        self.missing_fields = tuple(item.field for item in missing_requirements)
        self.conflicts = conflicts


def _context(
    goal: OnboardingGoal,
    matrix,
    catalog,
    deterministic_candidates: tuple[CapabilityCandidate, ...] = (),
) -> dict[str, Any]:
    return {
        "goal": {
            "device_id": goal.device_id,
            "capability_ids": list(goal.capability_ids),
            "ordered_joints": list(goal.ordered_joints),
        },
        "terminal_statuses": ["mapped", "gap", "unsupported", "unknown"],
        "required_candidate_fields": {
            capability_id: list(required_candidate_fields(capability_id))
            for capability_id in goal.capability_ids
        },
        "capability_contracts": {
            capability_id: {
                "category": catalog.get(capability_id).category,
                "binding_operations": list(catalog.get(capability_id).binding_operations),
                "semantics": dict(catalog.get(capability_id).semantics),
            }
            for capability_id in goal.capability_ids
        },
        "evidence_contract": evidence_contract_document(goal.capability_ids),
        "deterministic_candidates": [
            {
                "source": "deterministic_normalized_evidence",
                "capability_id": candidate.capability_id,
                "evidence_ids": list(candidate.evidence_ids),
                "proposed_semantics": dict(candidate.proposed_semantics),
            }
            for candidate in deterministic_candidates
        ],
        "resolved_platform_fields": {
            capability_id: resolved_platform_fields(
                capability_id,
                binding_operations=catalog.get(capability_id).binding_operations,
                device_id=goal.device_id,
                ordered_joints=goal.ordered_joints,
            )
            for capability_id in goal.capability_ids
        },
        "evidence_summary": [
            {
                "evidence_id": item.evidence_id,
                "claim_type": item.claim_type,
                "source_path": item.source_path.as_posix(),
                "confidence_boundary": item.confidence_boundary,
            }
            for item in matrix.records
        ],
        "rules": [
            "Cite evidence IDs for every mapped candidate or gap conclusion",
            "Only the scoped capabilities may be decided",
            "Submit independently supported capabilities even if another capability has a gap",
            "Unconfirmed application execution policy is not vendor semantics",
            "Use record_conclusion for a gap, unsupported, or unknown capability",
            "The deterministic orchestrator ends when every capability has one terminal status",
            "No shell, arbitrary file reads, arbitrary writes, verification promotion, or motion",
        ],
    }


class OnboardingAgent:
    def __init__(self, provider: OnboardingModelProvider, max_turns: int = 32):
        self.provider = provider
        self.max_turns = max_turns

    def run(self, goal: OnboardingGoal, workflow: OnboardingWorkflow) -> OnboardingRunResult:
        if (
            len(goal.capability_ids) != len(_FIRST_VERSION_CAPABILITIES)
            or set(goal.capability_ids) != _FIRST_VERSION_CAPABILITIES
        ):
            raise ValueError(
                "first-version onboarding requires exactly joint_position_state and joint_position"
            )
        matrix = workflow.evidence_matrix()
        catalog = load_capability_catalog(workflow.platform_root / "catalogs/capabilities/v0.1.yaml")
        deterministic_candidates = workflow.deterministic_candidates()
        deterministic_by_capability = {
            item.capability_id: item for item in deterministic_candidates
        }
        candidates: dict[str, CapabilityCandidate] = {}
        decisions: dict[str, CapabilityDecision] = {}
        rejections: list[AgentRejection] = []
        trace: list[ToolTrace] = []
        feedback: str | None = None
        model_text: list[str] = []
        consecutive_text_turns = 0
        self.provider.start(_context(
            goal, matrix, catalog, deterministic_candidates,
        ))

        for turn_index in range(1, self.max_turns + 1):
            turn = self.provider.next_turn(feedback=feedback)
            feedback = None
            if turn.content:
                model_text.append(turn.content)
            if not turn.tool_calls:
                consecutive_text_turns += 1
                if consecutive_text_turns >= 2:
                    for capability_id in goal.capability_ids:
                        decisions.setdefault(capability_id, CapabilityDecision(
                            capability_id=capability_id,
                            status="unknown",
                            evidence_ids=(),
                            missing_fields=("model_tool_conclusion",),
                            reason="model returned ordinary text twice without a typed conclusion",
                        ))
                    return self._finalize(
                        goal, workflow, matrix, catalog, candidates, decisions,
                        rejections, trace, turn_index, model_text, completed=False,
                    )
                unresolved = [item for item in goal.capability_ids if item not in decisions]
                feedback = (
                    "Ordinary text does not complete onboarding. Use "
                    "accept_deterministic_candidate, submit_candidate, or "
                    f"record_conclusion for unresolved capabilities: {unresolved}."
                )
                continue

            consecutive_text_turns = 0
            batch_results: list[ProviderToolResult] = []
            for call in turn.tool_calls:
                result = self._execute_call(
                    call, goal, workflow, matrix, catalog,
                    candidates, decisions, rejections, trace,
                    deterministic_by_capability,
                )
                batch_results.append(result)
            self.provider.record_tool_results(tuple(batch_results))

            if all(capability_id in decisions for capability_id in goal.capability_ids):
                return self._finalize(
                    goal, workflow, matrix, catalog, candidates, decisions,
                    rejections, trace, turn_index, model_text,
                )

        for capability_id in goal.capability_ids:
            decisions.setdefault(capability_id, CapabilityDecision(
                capability_id=capability_id,
                status="unknown",
                evidence_ids=(),
                missing_fields=("model_assessment",),
                reason="model turn limit reached before a terminal decision",
            ))
        return self._finalize(
            goal, workflow, matrix, catalog, candidates, decisions,
            rejections, trace, self.max_turns, model_text, completed=False,
        )

    def _execute_call(
        self,
        call: ProviderToolCall,
        goal: OnboardingGoal,
        workflow: OnboardingWorkflow,
        matrix,
        catalog,
        candidates: dict[str, CapabilityCandidate],
        decisions: dict[str, CapabilityDecision],
        rejections: list[AgentRejection],
        trace: list[ToolTrace],
        deterministic_by_capability: Mapping[str, CapabilityCandidate],
    ) -> ProviderToolResult:
        if call.arguments is None:
            return self._reject(
                call, "invalid_tool_arguments", call.argument_error or "invalid JSON arguments",
                {"raw_arguments": call.raw_arguments}, rejections, trace,
            )
        arguments = dict(call.arguments)
        if call.name not in _ALLOWED_TOOLS:
            return self._reject(
                call, "tool_not_allowed", "Only typed onboarding tools are available",
                {}, rejections, trace,
            )
        if call.name in {
            "submit_candidate", "accept_deterministic_candidate",
            "record_conclusion",
        }:
            capability_id = arguments.get("capability_id")
            if capability_id in decisions:
                return self._reject(
                    call,
                    "capability_already_decided",
                    f"{capability_id} already has terminal status {decisions[capability_id].status}",
                    {"existing_status": decisions[capability_id].status},
                    rejections,
                    trace,
                )
        try:
            result: Any
            if call.name == "list_evidence":
                claim_type = arguments.get("claim_type")
                result = [
                    item.evidence_id for item in matrix.records
                    if claim_type is None or item.claim_type == claim_type
                ]
            elif call.name == "get_evidence":
                item = matrix.get(str(arguments["evidence_id"]))
                result = {
                    "evidence_id": item.evidence_id,
                    "claim_type": item.claim_type,
                    "claims": dict(item.claims),
                    "source_path": item.source_path.as_posix(),
                    "confidence_boundary": item.confidence_boundary,
                    "provenance": dict(item.provenance),
                }
            elif call.name in {
                "submit_candidate", "accept_deterministic_candidate",
            }:
                capability_id = str(arguments["capability_id"])
                self._require_scope(capability_id, goal)
                evidence_ids = tuple(
                    str(item) for item in arguments.get("evidence_ids", ())
                )
                if call.name == "accept_deterministic_candidate":
                    reason = str(arguments.get("reason", "")).strip()
                    if not reason:
                        raise ValueError("reason is required")
                    candidate = deterministic_by_capability.get(capability_id)
                    if candidate is None:
                        raise ValueError(
                            f"no deterministic candidate exists for {capability_id}"
                        )
                    if set(evidence_ids) != set(candidate.evidence_ids):
                        raise ValueError(
                            "evidence_ids must exactly reference the deterministic candidate"
                        )
                else:
                    candidate = CapabilityCandidate(
                        capability_id,
                        evidence_ids,
                        arguments.get("proposed_semantics", {}),
                    )
                candidate, normalizations = normalize_candidate(
                    catalog, matrix, candidate, goal.device_id,
                )
                assessment = CapabilityMatcher().assess(
                    catalog, matrix,
                    OnboardingScope(
                        goal.device_id, (capability_id,), goal.ordered_joints, (candidate,),
                    ),
                ).get(capability_id)
                if (
                    assessment.mapping_complete
                    and not assessment.execution_policy_complete
                    and not assessment.conflicts
                ):
                    candidates[capability_id] = candidate
                    result = {
                        "accepted": True,
                        "capability_id": capability_id,
                        "status": "mapping_candidate",
                        "evidence_ids": list(candidate.evidence_ids),
                        "unresolved_execution_policy": [
                            item.field for item in assessment.missing
                            if item.field in set(execution_policy_fields(capability_id))
                        ],
                        "normalizations": list(normalizations),
                    }
                    trace.append(ToolTrace(call.call_id, call.name, True, arguments, result))
                    return ProviderToolResult(call.call_id, call.name, True, result)
                if assessment.status != "native" or assessment.conflicts:
                    raise CandidateRejected(
                        assessment.missing,
                        assessment.conflicts,
                    )
                candidates[capability_id] = candidate
                decisions[capability_id] = CapabilityDecision(
                    capability_id, "mapped", candidate.evidence_ids,
                    reason="candidate accepted by deterministic evidence matcher",
                )
                result = {
                    "accepted": True,
                    "capability_id": capability_id,
                    "status": "mapped",
                    "evidence_ids": list(candidate.evidence_ids),
                    "normalizations": list(normalizations),
                }
            elif call.name == "record_conclusion":
                capability_id = str(arguments["capability_id"])
                self._require_scope(capability_id, goal)
                status = str(arguments["status"])
                if status not in {"gap", "unsupported", "unknown"}:
                    raise ValueError("status must be gap, unsupported, or unknown")
                evidence_ids = tuple(str(item) for item in arguments.get("evidence_ids", ()))
                records = tuple(matrix.get(item) for item in evidence_ids)
                missing_fields = tuple(str(item) for item in arguments.get("missing_fields", ()))
                reason = str(arguments.get("reason", "")).strip()
                if not reason:
                    raise ValueError("reason is required")
                if status == "gap" and (not evidence_ids or not missing_fields):
                    raise ValueError("gap requires evidence_ids and missing_fields")
                if status == "gap":
                    required_fields = set(required_candidate_fields(capability_id))
                    invalid_fields = sorted(set(missing_fields) - required_fields)
                    if invalid_fields:
                        raise ValueError(
                            "gap missing_fields must be required candidate fields: "
                            + ", ".join(invalid_fields)
                        )
                    if not any(
                        required_fields.intersection(record.claims)
                        or record.claims.get("capability_id") == capability_id
                        for record in records
                    ):
                        raise ValueError("gap evidence is unrelated to the capability contract")
                    candidate = candidates.get(capability_id)
                    interface_mapping_retained = False
                    if candidate is None:
                        deterministic = deterministic_by_capability.get(capability_id)
                        if deterministic is not None:
                            deterministic, _ = normalize_candidate(
                                catalog, matrix, deterministic, goal.device_id,
                            )
                            deterministic_assessment = CapabilityMatcher().assess(
                                catalog,
                                matrix,
                                OnboardingScope(
                                    goal.device_id,
                                    (capability_id,),
                                    goal.ordered_joints,
                                    (deterministic,),
                                ),
                            ).get(capability_id)
                            unresolved_policy = {
                                item.field for item in deterministic_assessment.missing
                                if item.field in set(execution_policy_fields(capability_id))
                            }
                            if (
                                deterministic_assessment.mapping_complete
                                and not deterministic_assessment.conflicts
                                and unresolved_policy
                                and set(missing_fields) == unresolved_policy
                            ):
                                candidates[capability_id] = deterministic
                                candidate = deterministic
                                interface_mapping_retained = True
                    if candidate is not None:
                        assessment = CapabilityMatcher().assess(
                            catalog,
                            matrix,
                            OnboardingScope(
                                goal.device_id,
                                (capability_id,),
                                goal.ordered_joints,
                                (candidate,),
                            ),
                        ).get(capability_id)
                        unresolved = {
                            item.field for item in assessment.missing
                        }
                        if assessment.mapping_complete and (
                            set(missing_fields) != unresolved
                        ):
                            raise ValueError(
                                "gap missing_fields must exactly match unresolved "
                                "candidate fields: "
                                + ", ".join(sorted(unresolved))
                            )
                if status == "unsupported" and not any(
                    item.claim_type == "unsupported"
                    and item.claims.get("capability_id") == capability_id
                    for item in records
                ):
                    raise ValueError("unsupported requires explicit unsupported evidence")
                decisions[capability_id] = CapabilityDecision(
                    capability_id, status, evidence_ids, missing_fields, reason,
                )
                result = {
                    "recorded": True,
                    "capability_id": capability_id,
                    "status": status,
                }
                if status == "gap":
                    result["interface_mapping_retained"] = (
                        interface_mapping_retained or capability_id in candidates
                    )
            else:
                coverage = CapabilityMatcher().assess(
                    catalog, matrix,
                    OnboardingScope(
                        goal.device_id, goal.capability_ids, goal.ordered_joints,
                        tuple(candidates[key] for key in goal.capability_ids if key in candidates),
                    ),
                )
                result = {
                    "assessments": [
                        {
                            "capability_id": item.capability_id,
                            "status": item.status,
                            "missing": [entry.field for entry in item.missing],
                            "conflicts": list(item.conflicts),
                        }
                        for item in coverage.assessments
                    ],
                    "terminal_decisions": [asdict(item) for item in decisions.values()],
                }
            trace.append(ToolTrace(call.call_id, call.name, True, arguments, result))
            return ProviderToolResult(call.call_id, call.name, True, result)
        except CandidateRejected as exc:
            return self._reject(
                call, "candidate_not_supported_by_evidence", str(exc),
                {
                    "missing_fields": list(exc.missing_fields),
                    "missing_requirements": [
                        asdict(item) for item in exc.missing_requirements
                    ],
                    "conflicts": list(exc.conflicts),
                },
                rejections, trace,
            )
        except Exception as exc:
            return self._reject(
                call, "tool_validation_failed", str(exc), {}, rejections, trace,
            )

    @staticmethod
    def _require_scope(capability_id: str, goal: OnboardingGoal) -> None:
        if capability_id not in goal.capability_ids:
            raise ValueError("capability is outside the authorized scope")

    @staticmethod
    def _reject(
        call: ProviderToolCall,
        reason: str,
        message: str,
        details: Mapping[str, Any],
        rejections: list[AgentRejection],
        trace: list[ToolTrace],
    ) -> ProviderToolResult:
        payload = {"reason": reason, "message": message, **details}
        rejections.append(AgentRejection(call.call_id, call.name, reason, message))
        trace.append(ToolTrace(call.call_id, call.name, False, call.arguments, payload))
        return ProviderToolResult(call.call_id, call.name, False, payload)

    @staticmethod
    def _finalize(
        goal: OnboardingGoal,
        workflow: OnboardingWorkflow,
        matrix,
        catalog,
        candidates: dict[str, CapabilityCandidate],
        decisions: dict[str, CapabilityDecision],
        rejections: list[AgentRejection],
        trace: list[ToolTrace],
        model_turn_count: int,
        model_text: list[str],
        completed: bool = True,
    ) -> OnboardingRunResult:
        coverage = workflow.assess_candidates(
            {
                "device_id": goal.device_id,
                "capability_ids": list(goal.capability_ids),
                "ordered_joints": list(goal.ordered_joints),
            },
            tuple(candidates[key] for key in goal.capability_ids if key in candidates),
        )
        ordered_decisions = tuple(decisions[key] for key in goal.capability_ids)
        package_root: Path | None = None
        conformance_passed = False
        package_status = "none"
        candidate_conformance_passed = False
        backend_fit_blocked = False
        if completed and all(item.status == "mapped" for item in ordered_decisions):
            descriptor = load_backend_descriptor(
                workflow.platform_root / "catalogs/backends/ros2_v0.1.yaml"
            )
            fit = BackendFit.evaluate(coverage, (descriptor,))
            if not fit.plugin_requirements:
                generated = workflow.generate(goal.identity_path)
                package_root = generated.root
                package_status = "runtime"
                conformance_passed = workflow.validate().passed
            else:
                backend_fit_blocked = True
        elif completed and all(
            item.status in {"mapped", "gap"} for item in ordered_decisions
        ) and all(
            item.mapping_complete and not item.conflicts
            for item in coverage.assessments
        ):
            descriptor = load_backend_descriptor(
                workflow.platform_root / "catalogs/backends/ros2_v0.1.yaml"
            )
            fit = BackendFit.evaluate(coverage, (descriptor,))
            if not fit.plugin_requirements:
                generated = workflow.generate_candidate(goal.identity_path)
                package_root = generated.root
                package_status = "candidate"
                candidate_conformance_passed = (
                    workflow.validate_candidate().passed
                )
            else:
                backend_fit_blocked = True

        if backend_fit_blocked:
            completed = False
        if package_status == "runtime" and not conformance_passed:
            completed = False
        if package_status == "candidate" and not candidate_conformance_passed:
            completed = False

        interface_mapped = all(
            item.mapping_complete and not item.conflicts
            for item in coverage.assessments
        )
        completion_policy_resolved = all(
            item.execution_policy_complete
            for item in coverage.assessments
        )
        candidate_generated = package_status == "candidate"
        live_execution_ready = (
            package_status == "runtime" and conformance_passed
        )

        decision_path = workflow.run_root / "agent-capability-decisions.json"
        decision_path.write_text(json.dumps({
            "schema_version": "agent-capability-decisions/v0.1",
            "completed": completed,
            "interface_mapped": interface_mapped,
            "candidate_generated": candidate_generated,
            "candidate_conformance_passed": candidate_conformance_passed,
            "completion_policy_resolved": completion_policy_resolved,
            "live_execution_ready": live_execution_ready,
            "decisions": [asdict(item) for item in ordered_decisions],
            "deterministic_assessments": [
                {
                    "capability_id": item.capability_id,
                    "status": item.status,
                    "missing": [entry.field for entry in item.missing],
                    "conflicts": list(item.conflicts),
                }
                for item in coverage.assessments
            ],
            "model_text": model_text,
            "motion_sent": False,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        statuses = ", ".join(
            f"{item.capability_id}={item.status}" for item in ordered_decisions
        )
        return OnboardingRunResult(
            completed=completed,
            final_message=f"Capability assessment complete: {statuses}",
            package_root=package_root,
            conformance_passed=conformance_passed,
            package_status=package_status,
            interface_mapped=interface_mapped,
            candidate_generated=candidate_generated,
            candidate_conformance_passed=candidate_conformance_passed,
            completion_policy_resolved=completion_policy_resolved,
            live_execution_ready=live_execution_ready,
            decisions=ordered_decisions,
            rejections=tuple(rejections),
            tool_trace=tuple(trace),
            model_turn_count=model_turn_count,
        )
