"""Load package-owned Python code without changing global import search paths."""
from __future__ import annotations

from hashlib import sha256
import importlib
from pathlib import Path
import sys
import threading
from types import ModuleType
from typing import Any

from ..errors import DependencyError
from .manifest import BackendSpec

_IMPORT_LOCK = threading.RLock()


def load_backend_entrypoint(backend: BackendSpec, package_root: str | Path) -> Any:
    if not backend.entrypoint or backend.entrypoint.count(":") != 1:
        raise DependencyError(f"Backend {backend.id} has no valid entrypoint")
    module_name, attribute = backend.entrypoint.split(":")
    if not attribute.isidentifier() or not all(part.isidentifier() for part in module_name.split('.')):
        raise DependencyError(f"Invalid backend entrypoint: {backend.entrypoint}")
    root = Path(package_root).resolve()
    try:
        source = root.joinpath(*module_name.split('.'))
        candidate = source.with_suffix('.py')
        if not candidate.is_file():
            candidate = source / '__init__.py'
        if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
            raise ImportError("entrypoint module is not inside the Hardware Package")
        namespace = '_ce_hardware_' + sha256(str(root).encode()).hexdigest()
        with _IMPORT_LOCK:
            if namespace not in sys.modules:
                package = ModuleType(namespace)
                package.__path__ = [str(root)]
                package.__package__ = namespace
                sys.modules[namespace] = package
            module = importlib.import_module(f'{namespace}.{module_name}')
        factory = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise DependencyError(f"Could not load backend {backend.id} from {backend.entrypoint}: {exc}") from exc
    if not callable(factory):
        raise DependencyError(f"Backend entrypoint is not callable: {backend.entrypoint}")
    return factory
