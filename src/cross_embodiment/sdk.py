from __future__ import annotations

from pathlib import Path

from .adapters.mock import MockAdapter
from .manifest import EmbodimentManifest, load_manifest
from .types import Command, RobotState


class Lifecycle:
    def __init__(self, adapter):
        self.adapter = adapter

    def connect(self) -> None:
        self.adapter.connect()

    def enable(self) -> None:
        self.adapter.enable()

    def disable(self) -> None:
        self.adapter.disable()

    def stop(self) -> None:
        self.adapter.disable()


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


def connect(adapter: str = "mock", manifest: str | Path | EmbodimentManifest | None = None, **_) -> Robot:
    if manifest is None:
        raise ValueError("A manifest is required")
    loaded = load_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    if adapter != "mock":
        raise ValueError(f"Adapter '{adapter}' is not installed in v0.1")
    return Robot(MockAdapter(loaded), loaded)
