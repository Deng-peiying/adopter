from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    category: str
    binding_operations: tuple[str, ...]
    semantics: Mapping[str, Any]
    required_for_profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantics", MappingProxyType(dict(self.semantics)))


@dataclass(frozen=True)
class CapabilityCatalog:
    schema_version: str
    catalog_version: str
    assessment_statuses: tuple[str, ...]
    capabilities: tuple[CapabilityDefinition, ...]

    def get(self, capability_id: str) -> CapabilityDefinition:
        for capability in self.capabilities:
            if capability.id == capability_id:
                return capability
        raise KeyError(capability_id)
