from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import CapabilityCatalog, CapabilityDefinition


_TOP_FIELDS = {
    "schema_version",
    "catalog_version",
    "assessment_statuses",
    "capabilities",
}
_CAPABILITY_FIELDS = {
    "id",
    "category",
    "binding_operations",
    "semantics",
    "required_for_profiles",
}
_SEMANTIC_FIELDS = {"kind", "input", "output", "units", "frame", "lifecycle"}
_ASSESSMENT_STATUSES = ("native", "derived", "unsupported", "unknown")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return tuple(value)


def load_capability_catalog(path: Path) -> CapabilityCatalog:
    raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "catalog")
    unknown_top = set(raw) - _TOP_FIELDS
    if unknown_top:
        raise ValueError(f"unknown top-level fields: {sorted(unknown_top)}")
    missing_top = _TOP_FIELDS - set(raw)
    if missing_top:
        raise ValueError(f"missing top-level fields: {sorted(missing_top)}")
    if raw["schema_version"] != "capability-catalog/v0.1":
        raise ValueError("schema_version must be capability-catalog/v0.1")

    statuses = _string_list(raw["assessment_statuses"], "assessment_statuses")
    if statuses != _ASSESSMENT_STATUSES:
        raise ValueError(f"assessment_statuses must be {_ASSESSMENT_STATUSES!r}")

    raw_capabilities = raw["capabilities"]
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise ValueError("capabilities must be a non-empty list")

    capabilities: list[CapabilityDefinition] = []
    seen: set[str] = set()
    for index, item_value in enumerate(raw_capabilities):
        item = _mapping(item_value, f"capabilities[{index}]")
        unknown = set(item) - _CAPABILITY_FIELDS
        if unknown:
            raise ValueError(
                f"capabilities[{index}] unknown fields: {sorted(unknown)}"
            )
        missing = _CAPABILITY_FIELDS - set(item)
        if missing:
            raise ValueError(f"capabilities[{index}] missing fields: {sorted(missing)}")
        capability_id = item["id"]
        if not isinstance(capability_id, str) or not capability_id:
            raise ValueError(f"capabilities[{index}].id must be a non-empty string")
        if capability_id in seen:
            raise ValueError(f"duplicate capability id: {capability_id}")
        seen.add(capability_id)

        semantics = _mapping(item["semantics"], f"capabilities[{index}].semantics")
        if set(semantics) != _SEMANTIC_FIELDS:
            raise ValueError(
                f"capabilities[{index}] semantic fields must be "
                f"{sorted(_SEMANTIC_FIELDS)}"
            )
        if not isinstance(item["category"], str) or not item["category"]:
            raise ValueError(f"capabilities[{index}].category must be a non-empty string")
        capabilities.append(
            CapabilityDefinition(
                id=capability_id,
                category=item["category"],
                binding_operations=_string_list(
                    item["binding_operations"],
                    f"capabilities[{index}].binding_operations",
                ),
                semantics=semantics,
                required_for_profiles=_string_list(
                    item["required_for_profiles"],
                    f"capabilities[{index}].required_for_profiles",
                ),
            )
        )

    if not isinstance(raw["catalog_version"], str) or not raw["catalog_version"]:
        raise ValueError("catalog_version must be a non-empty string")
    return CapabilityCatalog(
        schema_version=raw["schema_version"],
        catalog_version=raw["catalog_version"],
        assessment_statuses=statuses,
        capabilities=tuple(capabilities),
    )
