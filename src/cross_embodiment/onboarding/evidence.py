from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from .inventory import AssetInventory
from .models import EvidenceRecord


@dataclass(frozen=True)
class EvidenceMatrix:
    inventory: AssetInventory
    records: tuple[EvidenceRecord, ...]

    @classmethod
    def build(
        cls, inventory: AssetInventory, evidence: Iterable[EvidenceRecord]
    ) -> "EvidenceMatrix":
        records = tuple(sorted(evidence, key=lambda item: item.evidence_id))
        ids = [item.evidence_id for item in records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence id")
        known_assets = {item.asset_id for item in inventory.assets}
        # Empty inventories are useful for schema-level and agent-candidate tests.
        if known_assets:
            missing = {
                asset_id
                for item in records
                for asset_id in item.source_asset_ids
                if asset_id not in known_assets
            }
            if missing:
                raise ValueError(f"evidence references unknown assets: {sorted(missing)}")
        return cls(inventory, records)

    def get(self, evidence_id: str) -> EvidenceRecord:
        for record in self.records:
            if record.evidence_id == evidence_id:
                return record
        raise KeyError(evidence_id)

    def select(self, evidence_ids: Iterable[str]) -> tuple[EvidenceRecord, ...]:
        return tuple(self.get(identifier) for identifier in evidence_ids)

    @staticmethod
    def conflicts(records: Iterable[EvidenceRecord]) -> tuple[str, ...]:
        sensitive = {"unit", "ordered_joints", "frame", "endpoint", "interface_type"}
        values: dict[str, set[str]] = {}
        for record in records:
            for key in sensitive & set(record.claims):
                values.setdefault(key, set()).add(
                    json.dumps(record.claims[key], sort_keys=True)
                )
        return tuple(sorted(key for key, candidates in values.items() if len(candidates) > 1))
