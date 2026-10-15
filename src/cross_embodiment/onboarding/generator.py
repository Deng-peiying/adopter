from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .backend_fit import BackendFitReport
from .capability import CapabilityCoverage
from .evidence import EvidenceMatrix


@dataclass(frozen=True)
class PackageIdentity:
    package_name: str
    version: str
    vendor: str
    model: str
    device_id: str
    embodiment_type: str
    backend_id: str
    backend_entrypoint: str
    ros_distro: str
    os: str
    arch: str


@dataclass(frozen=True)
class GeneratedPackage:
    root: Path
    package_yaml: Path
    embodiment_yaml: Path
    mapping_yaml: Path
    provenance_yaml: Path


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_plain(data), sort_keys=False), encoding="utf-8")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class PackageGenerator:
    @staticmethod
    def generate(
        coverage: CapabilityCoverage,
        evidence: EvidenceMatrix,
        backend_fit: BackendFitReport,
        output_root: Path,
        package_identity: PackageIdentity,
    ) -> GeneratedPackage:
        required = {"joint_position_state", "joint_position"}
        assessments = {item.capability_id: item for item in coverage.assessments}
        candidates = {item.capability_id: item for item in coverage.candidates}
        fit_ids = {item.capability_id for item in backend_fit.fits if item.backend_id == package_identity.backend_id}
        # Generation promotes nothing: matcher and backend-fit results are prerequisites.
        for capability_id in sorted(required):
            assessment = assessments.get(capability_id)
            if assessment is None or assessment.status != "native":
                raise ValueError(f"required capability {capability_id} is not native")
            if assessment.conflicts:
                raise ValueError(f"required capability {capability_id} has conflicts: {assessment.conflicts}")
            if capability_id not in candidates:
                raise ValueError(f"required capability {capability_id} has no mapping candidate")
            if capability_id not in fit_ids:
                raise ValueError(f"required capability {capability_id} has no backend fit")
            for evidence_id in assessment.evidence_ids:
                evidence.get(evidence_id)

        state = dict(candidates["joint_position_state"].proposed_semantics)
        move = dict(candidates["joint_position"].proposed_semantics)
        joints = tuple(state.get("ordered_joints", ()))
        limits = tuple(state.get("joint_limits", ()))
        if len(joints) == 0 or len(joints) != len(limits) or tuple(move.get("ordered_joints", ())) != joints:
            raise ValueError("state and action require the same explicit joints and joint limits")
        if state.get("unit") != "radian" or move.get("unit") != "radian" or move.get("target_unit") not in {"radian", "degree"}:
            raise ValueError("required units are missing or unsupported")

        required_state = {"endpoint", "interface_type", "positions_field", "stamp_field", "mode_field", "ready_values", "fault_field"}
        required_move = {"endpoint", "interface_type", "timeout_s", "target_field", "constants", "result_code_field", "result_description_field", "success_code", "state_binding", "arrival_tolerance_rad", "settle_window_s"}
        missing = sorted((required_state - set(state)) | (required_move - set(move)))
        if missing:
            raise ValueError(f"mapping candidate is missing required fields: {missing}")

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"generation output must be empty: {root}")
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        mapping_path = root / "config" / "right_arm_ros2_mapping.yaml"
        embodiment_path = root / "embodiment.yaml"
        provenance_path = root / "generation-provenance.yaml"
        package_path = root / "package.yaml"

        state_id = f"{package_identity.device_id}_joint_state"
        move_id = f"{package_identity.device_id}_joint_position"
        semantic = {"device": package_identity.device_id, "joints": joints, "unit": "radian"}
        mapping = {
            "schema_version": "interface-mapping/v1",
            "bindings": {
                state_id: {
                    "semantic": {"operation": "joint_state", **semantic},
                    "transport": {"backend": "ros2", "kind": "subscription", "endpoint": state["endpoint"], "interface": state["interface_type"]},
                    "decode": {"positions": state["positions_field"], "stamp": state["stamp_field"], "mode": state["mode_field"], "ready_values": state["ready_values"], "fault": state["fault_field"], "unit": state["unit"]},
                    "evidence": candidates["joint_position_state"].evidence_ids,
                },
                move_id: {
                    "semantic": {"operation": "joint_position", **semantic},
                    "transport": {"backend": "ros2", "kind": "action", "endpoint": move["endpoint"], "interface": move["interface_type"], "timeout_s": move["timeout_s"]},
                    "encode": {"positions": {"source": "positions", "field": move["target_field"], "unit": move["target_unit"]}, "constants": move["constants"]},
                    "result": {"error_code": move["result_code_field"], "description": move["result_description_field"], "success_code": move["success_code"]},
                    "completion": {"state_binding": state_id, "arrival_tolerance_rad": move["arrival_tolerance_rad"], "settle_window_s": move["settle_window_s"]},
                    "evidence": candidates["joint_position"].evidence_ids,
                },
            },
        }
        _write_yaml(mapping_path, mapping)

        device_joints = [
            {"canonical_name": name, "type": "revolute", "unit": "radian", "limits": list(limit)}
            for name, limit in zip(joints, limits)
        ]
        embodiment = {
            "schema_version": "embodiment/v0.2",
            "embodiment": {"type": package_identity.embodiment_type, "dof": len(joints)},
            "devices": [{"id": package_identity.device_id, "type": "arm", "capabilities": ["joint_state", "joint_position"], "joints": device_joints}],
            "control": {"supported_modes": [{"type": "joint_position", "target": package_identity.device_id, "dimension": len(joints), "unit": "radian"}]},
            "adapter": {"backend": package_identity.backend_id},
        }
        _write_yaml(embodiment_path, embodiment)
        _write_yaml(root / "config" / "connection.yaml", {"mapping_path": "config/right_arm_ros2_mapping.yaml", "manage_process": False})

        used_ids = tuple(sorted(set(candidates["joint_position_state"].evidence_ids + candidates["joint_position"].evidence_ids)))
        provenance = {
            "schema_version": "generation-provenance/v0.1",
            "package": package_identity.package_name,
            "capabilities": {
                capability_id: {"status": assessments[capability_id].status, "evidence_ids": list(candidates[capability_id].evidence_ids), "backend": package_identity.backend_id}
                for capability_id in sorted(required)
            },
            "evidence": [
                {"evidence_id": identifier, "source_path": evidence.get(identifier).source_path.as_posix(), "confidence_boundary": evidence.get(identifier).confidence_boundary}
                for identifier in used_ids
            ],
            "unmapped_evidence_ids": list(coverage.discovered_unmapped_evidence_ids),
        }
        _write_yaml(provenance_path, provenance)
        (root / "tests" / "test_generated_contract.py").write_text(
            "# Generated conformance entrypoint; executed by ConformanceRunner.\n"
            "REQUIRED_CAPABILITIES = ('joint_position_state', 'joint_position')\n",
            encoding="utf-8",
        )
        package = {
            "schema_version": "hardware-package/v0.1",
            "package": {"name": package_identity.package_name, "version": package_identity.version, "vendor": package_identity.vendor, "model": package_identity.model, "type": "robot"},
            "embodiment_manifest": "embodiment.yaml",
            "assets": {
                "interface_mapping": [{"format": "yaml", "path": "config/right_arm_ros2_mapping.yaml", "source": True, "digest": f"sha256:{_digest(mapping_path)}"}],
                "generation_provenance": [{"format": "yaml", "path": "generation-provenance.yaml", "source": True, "digest": f"sha256:{_digest(provenance_path)}"}],
            },
            "backends": [{"id": package_identity.backend_id, "type": "python", "entrypoint": package_identity.backend_entrypoint, "platforms": [{"os": package_identity.os, "arch": package_identity.arch}], "requirements": {"ros_distro": package_identity.ros_distro}}],
            "defaults": {"backend": package_identity.backend_id, "config": "config/connection.yaml"},
            "validation": {"scope": [package_identity.device_id], "capabilities": sorted(required)},
        }
        _write_yaml(package_path, package)
        return GeneratedPackage(root, package_path, embodiment_path, mapping_path, provenance_path)
