from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Type

from ..adapter.mock import MockAdapter
from ..hardware.manifest import EmbodimentManifest, load_manifest
from .manipulator import ManipulatorRobot
from .quadruped import QuadrupedRobot
from .robot_base import RobotBase


_PROFILE_TYPES: dict[str, type[RobotBase]] = {
    "manipulator": ManipulatorRobot,
    "quadruped": QuadrupedRobot,
}
def facade_for_manifest(manifest: EmbodimentManifest) -> type[RobotBase]:
    profile = manifest.embodiment.get("profile")
    facade = _PROFILE_TYPES.get(str(profile))
    if facade is None:
        raise ValueError("Manifest must declare a supported embodiment profile")
    return facade


def connect(
    adapter: str | Callable[..., Any] = "mock",
    manifest: str | Path | EmbodimentManifest | None = None,
    *,
    control_enabled: bool = False,
    dry_run: bool = True,
    connection: dict | None = None,
    manage_process: bool = False,
    robot_class: Type[RobotBase] | None = None,
    **_,
) -> RobotBase:
    if manifest is None:
        raise ValueError("A manifest is required")
    loaded = load_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    declared_facade = facade_for_manifest(loaded)
    facade = robot_class or declared_facade
    if facade is not declared_facade:
        raise ValueError(
            f"Requested {facade.profile_id()} facade for {declared_facade.profile_id()} manifest"
        )
    if adapter == "mock":
        adapter_impl = MockAdapter(loaded)
    elif callable(adapter):
        options = dict(connection or {})
        options["manage_process"] = bool(options.get("manage_process", manage_process))
        adapter_impl = adapter(
            loaded,
            connection=options,
            control_enabled=control_enabled,
            dry_run=dry_run,
        )
    else:
        raise ValueError(f"Adapter '{adapter}' is not installed or was not loaded from a Hardware Package")
    return facade(
        adapter_impl,
        loaded,
        allow_motion=control_enabled,
        dry_run=dry_run,
    )
