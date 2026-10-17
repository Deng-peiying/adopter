from __future__ import annotations

from pathlib import Path

import pytest

from cross_embodiment.onboarding.backend_fit import BackendFit, load_backend_descriptor
from cross_embodiment.onboarding.capability import CapabilityCoverage
from cross_embodiment.onboarding.models import CapabilityAssessment, CapabilityCandidate, IntegrationStage


ROOT = Path(__file__).resolve().parents[2]


def coverage(*candidates: CapabilityCandidate) -> CapabilityCoverage:
    assessments = tuple(
        CapabilityAssessment(c.capability_id, "native", c.evidence_ids, IntegrationStage(discovered=True))
        for c in candidates
    )
    return CapabilityCoverage(assessments, candidates, ())


def candidate(capability: str, transport: str, operation: str) -> CapabilityCandidate:
    return CapabilityCandidate(capability, (f"evidence:{capability}",), {
        "transport_kind": transport,
        "binding_operation": operation,
        "lifecycle": "request_accept_execute_terminal_result",
    })


def test_ros2_subscription_and_action_fit_existing_backend() -> None:
    descriptor = load_backend_descriptor(ROOT / "catalogs/backends/ros2_mapped_v0.1.yaml")
    report = BackendFit.evaluate(coverage(
        candidate("joint_position_state", "ros2_subscription", "joint_state"),
        candidate("joint_position", "ros2_action", "joint_position"),
    ), (descriptor,))
    assert {(item.capability_id, item.backend_id) for item in report.fits} == {
        ("joint_position_state", "ros2_mapped"),
        ("joint_position", "ros2_mapped"),
    }
    assert report.plugin_requirements == ()


@pytest.mark.parametrize("transport", ["ros2_service", "ros2_publisher", "python_call", "native_call", "raw_can"])
def test_unsupported_mechanisms_emit_plugin_requirements(transport: str) -> None:
    descriptor = load_backend_descriptor(ROOT / "catalogs/backends/ros2_mapped_v0.1.yaml")
    item = candidate("joint_position", transport, "joint_position")
    report = BackendFit.evaluate(coverage(item), (descriptor,))
    requirement = report.plugin_requirements[0]
    assert report.fits == ()
    assert requirement.missing_mechanism == transport
    assert requirement.lifecycle_semantics == "request_accept_execute_terminal_result"
    assert requirement.evidence_ids == ("evidence:joint_position",)
    assert "conformance" in " ".join(requirement.minimum_tests).lower()


def test_known_transport_with_unknown_operation_does_not_fit() -> None:
    descriptor = load_backend_descriptor(ROOT / "catalogs/backends/ros2_mapped_v0.1.yaml")
    report = BackendFit.evaluate(
        coverage(candidate("stop", "ros2_action", "stop")), (descriptor,)
    )
    assert report.plugin_requirements[0].missing_mechanism == "operation:stop"


def test_backend_fit_accepts_complete_interface_mapping_with_unresolved_runtime_policy() -> None:
    descriptor = load_backend_descriptor(ROOT / "catalogs/backends/ros2_mapped_v0.1.yaml")
    item = candidate("joint_position", "ros2_action", "joint_position")
    partial = CapabilityCoverage((
        CapabilityAssessment(
            item.capability_id,
            "unknown",
            item.evidence_ids,
            IntegrationStage(discovered=True),
            candidate_valid=True,
            mapping_complete=True,
            execution_policy_complete=False,
        ),
    ), (item,), ())

    report = BackendFit.evaluate(partial, (descriptor,))

    assert [(fit.capability_id, fit.backend_id) for fit in report.fits] == [
        ("joint_position", "ros2_mapped"),
    ]
    assert report.plugin_requirements == ()
