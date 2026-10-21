from __future__ import annotations

from typing import Any

from cross_embodiment.adapter.health import HealthReport


class GeneratedAdapter:
    """Scaffold only. Implement vendor-specific behavior before hardware use."""

    adapter_id = "generated.adapter"
    version = "0.1.0"

    def __init__(self, manifest, *, connection=None, control_enabled=False, dry_run=False, **_):
        self.manifest = manifest
        self.connection = dict(connection or {})
        self.control_enabled = bool(control_enabled)
        self.dry_run = bool(dry_run)

    def load_manifest(self):
        return self.manifest

    def configure(self) -> None:
        return None

    def connect(self) -> None:
        raise NotImplementedError("Implement package-owned driver and transport connection")

    def disconnect(self) -> None:
        return None

    def enable(self) -> None:
        raise NotImplementedError("Implement and verify vendor enable semantics")

    def disable(self) -> None:
        raise NotImplementedError("Implement only with verified vendor disable semantics")

    def capabilities(self) -> dict[str, Any]:
        return self.manifest.capabilities()

    def supports_action(self, action_type: str, device_id: str) -> bool:
        return False

    def get_joint_state(self, device_id: str):
        raise NotImplementedError("Implement measured state decoding")

    def get_state(self):
        raise NotImplementedError("Implement vendor state decoding")

    def send_command(self, command):
        raise NotImplementedError("Implement command encoding and result confirmation")

    def health(self) -> HealthReport:
        return HealthReport(False, "Adapter implementation required")
