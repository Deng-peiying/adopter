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
            aliases = mode.get("legacy_target_aliases", [])
            if mode.get("type") == action_type and (target is None or mode.get("target") == target or target in aliases):
                return True
        device = self.device(target) if target else None
        return bool(device and action_type in device.get("capabilities", []))

    def capabilities(self) -> dict[str, Any]:
        """Return a vendor-neutral, serializable view of declared capabilities."""
        devices = []
        for device in self.devices:
            devices.append({
                "id": device.get("id"),
                "type": device.get("type"),
                "joints": [{key: joint[key] for key in ("canonical_name", "type", "unit", "limits") if key in joint}
                           for joint in device.get("joints", [])],
                "capabilities": list(device.get("capabilities", [])),
            })
        return {
            "embodiment": {key: self.embodiment[key] for key in ("type", "dof") if key in self.embodiment},
            "frames": dict(self.frames),
            "devices": devices,
            "actions": [{key: value for key, value in mode.items() if key != "legacy_target_aliases"}
                        for mode in self.control.get("supported_modes", [])],
            "safety": dict(self.safety),
        }


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
    manifest = EmbodimentManifest(**{key: data.get(key, default) for key, default in {
        "schema_version": None, "embodiment": None, "frames": {}, "devices": [],
        "control": {}, "safety": {}, "adapter": {},
    }.items()})
    # Package safety settings provide instance-wide policy defaults.
    safety_path = path.parent / "config" / "safety.yaml"
    if safety_path.is_file():
        package_safety = _parse_yaml(safety_path.read_text(encoding="utf-8"))
        for key in ("max_state_age_ms", "requires_enable", "supports_estop"):
            if key in package_safety:
                manifest.safety[key] = package_safety[key]
    return manifest
