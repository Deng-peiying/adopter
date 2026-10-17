from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from ..errors import DependencyError
from ..package.manifest import BackendSpec


def load_backend_entrypoint(backend: BackendSpec, package_root: str | Path) -> Any:
    """Load a package-owned backend only after package resolution.

    Entry points use ``python.module:Factory`` syntax.  The package root is
    added for the duration of import, so SDK core does not import vendor code
    until the selected package has been installed and opened.
    """
    if not backend.entrypoint or ":" not in backend.entrypoint:
        raise DependencyError(f"Backend {backend.id} has no valid entrypoint")
    module_name, attribute = backend.entrypoint.split(":", 1)
    if not module_name or not attribute:
        raise DependencyError(f"Invalid backend entrypoint: {backend.entrypoint}")
    root = str(Path(package_root).resolve())
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise DependencyError(f"Could not load backend {backend.id} from {backend.entrypoint}: {exc}") from exc
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
    if not callable(factory):
        raise DependencyError(f"Backend entrypoint is not callable: {backend.entrypoint}")
    return factory
