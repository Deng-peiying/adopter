from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_onboarding_documentation_links_and_contract_paths_exist() -> None:
    workflow = ROOT / "docs" / "onboarding" / "workflow.md"
    evidence = ROOT / "docs" / "onboarding" / "evidence-policy.md"
    l3 = ROOT / "docs" / "onboarding" / "weiyi-l3-runbook.md"
    for path in (workflow, evidence, l3):
        assert path.is_file(), path

    workflow_text = workflow.read_text(encoding="utf-8")
    evidence_text = evidence.read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    for relative in (
        "catalogs/capabilities/v0.1.yaml",
        "catalogs/backends/ros2_mapped_v0.1.yaml",
        "schemas/onboarding/asset-inventory.schema.json",
        "schemas/onboarding/interface-evidence.schema.json",
        "schemas/onboarding/capability-coverage.schema.json",
        "schemas/onboarding/backend-support.schema.json",
        "schemas/mapping/interface-mapping-v1.schema.json",
    ):
        assert (ROOT / relative).is_file(), relative
        assert relative in workflow_text or relative in evidence_text

    assert "docs/onboarding/workflow.md" in readme_text
    assert "docs/onboarding/evidence-policy.md" in readme_text
    assert "docs/onboarding/weiyi-l3-runbook.md" in readme_text


def test_docs_state_current_backend_and_verification_limits() -> None:
    combined = "\n".join(
        (ROOT / "docs" / "onboarding" / name).read_text(encoding="utf-8")
        for name in ("workflow.md", "evidence-policy.md")
    )
    for term in (
        "ros2_subscription",
        "ros2_action",
        "ros2_service",
        "ros2_publisher",
        "python_call",
        "native_call",
        "raw_can",
        "hardware_motion_verified",
    ):
        assert term in combined
