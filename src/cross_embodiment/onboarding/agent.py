from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backend_fit import BackendFit, load_backend_descriptor
from .capability import CapabilityMatcher, OnboardingScope
from .catalog import load_capability_catalog
from .models import CapabilityCandidate
from .providers import OnboardingModelProvider
from .workflow import OnboardingWorkflow, _load_coverage


@dataclass(frozen=True)
class OnboardingGoal:
    device_id: str
    capability_ids: tuple[str, ...]
    ordered_joints: tuple[str, ...]
    identity_path: Path


@dataclass(frozen=True)
class AgentRejection:
    tool: str
    reason: str
    message: str


@dataclass(frozen=True)
class ToolTrace:
    tool: str
    ok: bool
    summary: str


@dataclass(frozen=True)
class OnboardingRunResult:
    completed: bool
    final_message: str
    package_root: Path | None
    conformance_passed: bool
    rejections: tuple[AgentRejection, ...]
    tool_trace: tuple[ToolTrace, ...]


_ALLOWED_TOOLS = {
    "list_evidence", "get_evidence", "submit_candidate", "assess",
    "backend_fit", "generate", "validate",
}


class OnboardingAgent:
    def __init__(self, provider: OnboardingModelProvider, max_turns: int = 64):
        self.provider = provider
        self.max_turns = max_turns

    def run(self, goal: OnboardingGoal, workflow: OnboardingWorkflow) -> OnboardingRunResult:
        matrix = workflow.evidence_matrix()
        catalog = load_capability_catalog(workflow.platform_root / "catalogs/capabilities/v0.1.yaml")
        candidates: dict[str, CapabilityCandidate] = {}
        rejections: list[AgentRejection] = []
        trace: list[ToolTrace] = []
        package_root: Path | None = None
        conformance_passed = False
        context: list[dict[str, Any]] = [{
            "goal": {
                "device_id": goal.device_id,
                "capability_ids": list(goal.capability_ids),
                "ordered_joints": list(goal.ordered_joints),
            },
            "allowed_tools": sorted(_ALLOWED_TOOLS),
            "evidence_summary": [
                {"evidence_id": item.evidence_id, "claim_type": item.claim_type, "source_path": item.source_path.as_posix(), "confidence_boundary": item.confidence_boundary}
                for item in matrix.records
            ],
            "rules": [
                "Cite evidence IDs for every candidate",
                "Only joint_position_state and joint_position are in scope",
                "Verification stages are produced by deterministic tests only",
                "No shell, arbitrary file reads, arbitrary writes, or motion",
            ],
        }]

        for _ in range(self.max_turns):
            action = self.provider.next_turn(context)
            if "final" in action:
                return OnboardingRunResult(
                    completed=conformance_passed,
                    final_message=str(action["final"]), package_root=package_root,
                    conformance_passed=conformance_passed,
                    rejections=tuple(rejections), tool_trace=tuple(trace),
                )
            tool = str(action.get("tool", ""))
            arguments = action.get("arguments") or {}
            if tool not in _ALLOWED_TOOLS:
                rejection = AgentRejection(tool, "tool_not_allowed", "Only typed onboarding tools are available")
                rejections.append(rejection)
                trace.append(ToolTrace(tool, False, rejection.message))
                context.append({"tool_result": {"tool": tool, "ok": False, "reason": rejection.reason, "message": rejection.message}})
                continue
            try:
                result: Any
                if tool == "list_evidence":
                    claim_type = arguments.get("claim_type")
                    result = [item.evidence_id for item in matrix.records if claim_type is None or item.claim_type == claim_type]
                elif tool == "get_evidence":
                    item = matrix.get(str(arguments["evidence_id"]))
                    result = {"evidence_id": item.evidence_id, "claim_type": item.claim_type, "claims": dict(item.claims), "source_path": item.source_path.as_posix(), "confidence_boundary": item.confidence_boundary}
                elif tool == "submit_candidate":
                    capability_id = str(arguments["capability_id"])
                    if capability_id not in goal.capability_ids:
                        raise ValueError("capability is outside the authorized scope")
                    candidate = CapabilityCandidate(
                        capability_id,
                        tuple(arguments.get("evidence_ids", ())),
                        arguments.get("proposed_semantics", {}),
                    )
                    assessment = CapabilityMatcher().assess(
                        catalog, matrix,
                        OnboardingScope(goal.device_id, (capability_id,), goal.ordered_joints, (candidate,)),
                    ).get(capability_id)
                    if assessment.status != "native" or assessment.conflicts:
                        missing = [item.field for item in assessment.missing]
                        raise ValueError(f"candidate_not_supported_by_evidence: missing/conflicting {missing or assessment.conflicts}")
                    candidates[capability_id] = candidate
                    result = {"accepted": True, "capability_id": capability_id, "evidence_ids": list(candidate.evidence_ids)}
                elif tool == "assess":
                    coverage = workflow.assess_candidates(
                        {"device_id": goal.device_id, "capability_ids": list(goal.capability_ids), "ordered_joints": list(goal.ordered_joints)},
                        tuple(candidates[key] for key in goal.capability_ids if key in candidates),
                    )
                    result = {"assessments": [{"capability_id": item.capability_id, "status": item.status, "missing": [entry.field for entry in item.missing], "conflicts": list(item.conflicts)} for item in coverage.assessments]}
                elif tool == "backend_fit":
                    coverage = _load_coverage(workflow.run_root / "capability-coverage.yaml")
                    descriptor = load_backend_descriptor(workflow.platform_root / "catalogs/backends/ros2_mapped_v0.1.yaml")
                    fit = BackendFit.evaluate(coverage, (descriptor,))
                    result = {"fits": [item.capability_id for item in fit.fits], "plugin_requirements": [item.missing_mechanism for item in fit.plugin_requirements]}
                elif tool == "generate":
                    generated = workflow.generate(goal.identity_path)
                    package_root = generated.root
                    result = {"package_root": str(generated.root)}
                else:
                    report = workflow.validate()
                    conformance_passed = report.passed
                    result = {"passed": report.passed, "checks": list(report.checks), "failures": list(report.failures)}
                trace.append(ToolTrace(tool, True, str(result)[:500]))
                context.append({"tool_result": {"tool": tool, "ok": True, "result": result}})
            except Exception as exc:
                text = str(exc)
                reason = "candidate_not_supported_by_evidence" if text.startswith("candidate_not_supported_by_evidence") else "tool_validation_failed"
                rejection = AgentRejection(tool, reason, text)
                rejections.append(rejection)
                trace.append(ToolTrace(tool, False, text))
                context.append({"tool_result": {"tool": tool, "ok": False, "reason": reason, "message": text}})

        return OnboardingRunResult(False, "maximum onboarding turns reached", package_root, conformance_passed, tuple(rejections), tuple(trace))
