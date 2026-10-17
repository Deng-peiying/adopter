"""Evidence-driven hardware onboarding tools.

This package is deliberately separate from the runtime SDK import path.
"""

from .catalog import load_capability_catalog
from .models import CapabilityCatalog, CapabilityDefinition

__all__ = ["CapabilityCatalog", "CapabilityDefinition", "load_capability_catalog"]
