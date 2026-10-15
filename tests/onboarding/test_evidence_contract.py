from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from cross_embodiment.onboarding.capability import required_candidate_fields
from cross_embodiment.onboarding.evidence_contract import (
    evidence_contract, evidence_contract_document,
)
from cross_embodiment.onboarding.extractors.base import ScanContext
from cross_embodiment.onboarding.extractors.ros2 import Ros2Extractor
from tests.onboarding.test_ros2_extractor import FIXTURE


ROOT = Path(__file__).resolve().parents[2]


def test_evidence_contract_exports_a_versioned_schema_valid_document() -> None:
    document = evidence_contract_document(("joint_position_state", "joint_position"))
    schema = json.loads(
        (ROOT / "schemas/onboarding/evidence-contract.schema.json").read_text()
    )

    jsonschema.validate(document, schema)

    assert document["schema_version"] == "evidence-contract/v0.1"


def test_packaged_candidate_schema_matches_public_schema() -> None:
    public = ROOT / "schemas/onboarding/interface-mapping-candidate.schema.json"
    packaged = (
        ROOT
        / "src/cross_embodiment/onboarding/schemas/interface-mapping-candidate.schema.json"
    )

    assert packaged.read_bytes() == public.read_bytes()


def test_every_required_candidate_field_has_an_explicit_evidence_contract() -> None:
    for capability_id in ("joint_position_state", "joint_position"):
        contract = evidence_contract(capability_id)
        assert set(contract) == set(required_candidate_fields(capability_id))
        for field, rule in contract.items():
            assert rule.fact, field
            assert rule.source in {
                "vendor_evidence",
                "platform_catalog+vendor_evidence",
                "onboarding_scope",
                "adapter_runtime",
            }
            if rule.source in {"vendor_evidence", "platform_catalog+vendor_evidence"}:
                assert rule.evidence_claims or rule.structural_claims, field
                assert rule.evidence_types, field


def test_scanner_emits_contract_claims_with_field_level_provenance() -> None:
    records = Ros2Extractor().scan_files(ScanContext(FIXTURE, "vendor", frozenset()))
    state = next(item for item in records if item.claim_type == "ros2_subscription_usage")
    move = next(item for item in records if item.claim_type == "ros2_action_usage")
    config = next(item for item in records if item.claim_type == "robot_joint_configuration")
    state_type = next(
        item for item in records
        if item.claims.get("interface") == "ArmState"
    )

    for record, fields in (
        (state, ("transport_operation", "transport_kind", "endpoint", "interface_type",
                 "positions_field", "mode_field", "fault_code_field")),
        (move, ("transport_operation", "transport_kind", "endpoint", "interface_type",
                "target_field", "constants", "result_code_field", "success_code")),
        (config, ("vendor_joint_order", "joint_limits", "unit")),
    ):
        sources = record.provenance["claim_sources"]
        for field in fields:
            assert field in record.claims
            assert sources[field]["source_path"] == record.source_path.as_posix()
            assert sources[field]["line"] >= 1
            assert sources[field]["normalization_rule"]

    interface_sources = state_type.provenance["claim_sources"]["interface_paths"]
    assert interface_sources["header.stamp"]["source_path"] == "msg/ArmState.msg"
    assert interface_sources["header.stamp"]["line"] == 1
