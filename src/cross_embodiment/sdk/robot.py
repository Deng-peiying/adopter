from __future__ import annotations

from pathlib import Path
from typing import Callable, Any

from ..adapter.mock import MockAdapter
from ..hardware.manifest import EmbodimentManifest, load_manifest
from ..protocol.types import Command, RobotState


class Lifecycle:
    def __init__(self, adapter):
        self.adapter = adapter
        self._configured = False
        self._connected = False
        self._enabled = False
        self._stopped = False

    def configure(self) -> None:
        if not self._configured:
            configure = getattr(self.adapter, "configure", None)
            if configure is not None:
                configure()
            self._configured = True

    def connect(self) -> None:
        self.configure()
        if not self._connected:
            self.adapter.connect()
            self._connected = True
            self._stopped = False

    def enable(self) -> None:
        self.connect()
        if not self._enabled:
            self.adapter.enable()
            self._enabled = True

    def disable(self) -> None:
        if self._enabled:
            self.adapter.disable()
            self._enabled = False

    def stop(self) -> None:
        if self._stopped:
            return
        self.disable()
        if self._connected:
            self.adapter.disconnect()
            self._connected = False
        self._stopped = True


class Robot:
    def __init__(self, adapter, manifest: EmbodimentManifest):
        self.adapter = adapter
        self.manifest = manifest
        self.lifecycle = Lifecycle(adapter)

    def state(self) -> RobotState:
        return self.adapter.get_state()

    def command(self, command: Command):
        return self.adapter.send_command(command)

    def close(self) -> None:
        self.adapter.disconnect()


def connect(
    adapter: str | Callable[..., Any] = "mock",
    manifest: str | Path | EmbodimentManifest | None = None,
    *,
    control_enabled: bool = False,
    dry_run: bool = True,
    connection: dict | None = None,
    manage_process: bool = False,
    **_,
) -> Robot:
    if manifest is None:
        raise ValueError("A manifest is required")
    loaded = load_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    if adapter == "mock":
        return Robot(MockAdapter(loaded), loaded)
    if callable(adapter):
        options = dict(connection or {})
        options["manage_process"] = bool(options.get("manage_process", manage_process))
        adapter_impl = adapter(
            loaded,
            connection=options,
            control_enabled=control_enabled,
            dry_run=dry_run,
        )
        return Robot(adapter_impl, loaded)
    raise ValueError(f"Adapter '{adapter}' is not installed or was not loaded from a Hardware Package")
