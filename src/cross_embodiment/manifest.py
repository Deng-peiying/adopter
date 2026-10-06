from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EmbodimentManifest:
    schema_version: str
    embodiment: dict[str, Any]
    frames: dict[str, Any] = field(default_factory=dict)
    devices: list[dict[str, Any]] = field(default_factory=list)
    control: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    adapter: dict[str, Any] = field(default_factory=dict)

    def device(self, device_id: str) -> dict[str, Any] | None:
        return next((d for d in self.devices if d.get("id") == device_id), None)

    def supports(self, action_type: str, target: str | None = None) -> bool:
        for mode in self.control.get("supported_modes", []):
            if mode.get("type") == action_type and (target is None or mode.get("target") == target):
                return True
        device = self.device(target) if target else None
        return bool(device and action_type in device.get("capabilities", []))


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("YAML manifests require PyYAML; install with `pip install pyyaml`." ) from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a mapping")
    return data


def load_manifest(path: str | Path) -> EmbodimentManifest:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else _parse_yaml(text)
    required = ("schema_version", "embodiment")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Manifest missing required fields: {', '.join(missing)}")
    return EmbodimentManifest(**{key: data.get(key, default) for key, default in {
        "schema_version": None, "embodiment": None, "frames": {}, "devices": [],
        "control": {}, "safety": {}, "adapter": {},
    }.items()})
