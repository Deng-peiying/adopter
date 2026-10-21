from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Any

import yaml

from ..package.manifest import load_package_manifest
from .backend_fit import BackendDescriptor, BackendFitReport
from .capability import CapabilityCoverage, required_candidate_fields
from .evidence import EvidenceMatrix
from .evidence_contract import execution_policy_fields
from .runtime_policy import RuntimeCompletionPolicy


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
    package_status: str = "runtime"


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


_ADAPTER_ENTRYPOINT = "adapters.ros2.adapter:GeneratedAdapter"


def _write_adapter_scaffold(root: Path) -> Path:
    source = Path(__file__).parent / "templates" / "ros2_adapter.py"
    target = root / "adapters" / "ros2" / "adapter.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    (root / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    target.parent.joinpath("__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(source, target)
    return target


def package_tree_digest(root: Path) -> str:
    digest = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PackageGenerator:
    @staticmethod
    def generate_candidate(
        coverage: CapabilityCoverage,
        evidence: EvidenceMatrix,
        backend_fit: BackendFitReport,
        output_root: Path,
        package_identity: PackageIdentity,
    ) -> GeneratedPackage:
        """Generate an auditable package candidate that cannot start a runtime.

        This form is used when the vendor interface mapping and Backend fit are
        complete but Runtime Completion Policy is unresolved. It deliberately
        has no runtime mapping asset, connection defaults, or Backend
        entrypoint.
        """
        required = {"joint_position_state", "joint_position"}
        assessments = {item.capability_id: item for item in coverage.assessments}
        candidates = {item.capability_id: item for item in coverage.candidates}
        fit_ids = {
            item.capability_id for item in backend_fit.fits
            if item.backend_id == package_identity.backend_id
        }
        for capability_id in sorted(required):
            assessment = assessments.get(capability_id)
            if assessment is None or not assessment.mapping_complete:
                raise ValueError(
                    f"required capability {capability_id} interface mapping is incomplete"
                )
            if assessment.conflicts:
                raise ValueError(
                    f"required capability {capability_id} has conflicts: "
                    f"{assessment.conflicts}"
                )
            if capability_id not in candidates:
                raise ValueError(
                    f"required capability {capability_id} has no mapping candidate"
                )
            if capability_id not in fit_ids:
                raise ValueError(
                    f"required capability {capability_id} has no backend fit"
                )
            for evidence_id in assessment.evidence_ids:
                evidence.get(evidence_id)

        state = dict(candidates["joint_position_state"].proposed_semantics)
        move = dict(candidates["joint_position"].proposed_semantics)
        expected_state_binding = f"{package_identity.device_id}_joint_state"
        if move.get("state_binding") != expected_state_binding:
            raise ValueError(
                "package identity device does not match assessed state binding"
            )
        joints = tuple(state.get("ordered_joints", ()))
        limits = tuple(state.get("joint_limits", ()))
        if (
            len(joints) == 0
            or len(joints) != len(limits)
            or tuple(move.get("ordered_joints", ())) != joints
        ):
            raise ValueError(
                "state and action require the same explicit joints and joint limits"
            )
        if (
            state.get("unit") != "radian"
            or move.get("unit") != "radian"
            or move.get("target_unit") not in {"radian", "degree"}
        ):
            raise ValueError("required units are missing or unsupported")

        policy_fields = set(execution_policy_fields("joint_position"))
        required_state = set(required_candidate_fields("joint_position_state"))
        required_move = (
            set(required_candidate_fields("joint_position")) - policy_fields
        )
        missing = sorted(
            (required_state - set(state)) | (required_move - set(move))
        )
        if missing:
            raise ValueError(
                f"candidate interface mapping is missing required fields: {missing}"
            )
        unresolved = sorted(
            item.field for item in assessments["joint_position"].missing
            if item.field in policy_fields
        )
        if not unresolved:
            raise ValueError(
                "candidate package requires explicitly unresolved execution policy"
            )

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"generation output must be empty: {root}")
        (root / "config").mkdir(parents=True, exist_ok=True)
        mapping_name = f"{package_identity.device_id}_ros2_mapping.candidate.yaml"
        mapping_path = root / "config" / mapping_name
        embodiment_path = root / "embodiment.yaml"
        provenance_path = root / "generation-provenance.yaml"
        package_path = root / "package.yaml"

        state_id = f"{package_identity.device_id}_joint_state"
        move_id = f"{package_identity.device_id}_joint_position"
        semantic = {
            "device": package_identity.device_id,
            "joints": joints,
            "unit": "radian",
        }
        mapping = {
            "schema_version": "interface-mapping-candidate/v0.1",
            "live_execution_ready": False,
            "bindings": {
                state_id: {
                    "interface_mapped": True,
                    "semantic": {"operation": "joint_state", **semantic},
                    "transport": {
                        "backend": "ros2",
                        "kind": "subscription",
                        "endpoint": state["endpoint"],
                        "interface": state["interface_type"],
                    },
                    "decode": {
                        "positions": state["positions_field"],
                        "stamp": state["stamp_field"],
                        "mode": state["mode_field"],
                        "ready_values": state["ready_values"],
                        "fault": state["fault_field"],
                        "unit": state["unit"],
                    },
                    "evidence": candidates["joint_position_state"].evidence_ids,
                },
                move_id: {
                    "interface_mapped": True,
                    "semantic": {"operation": "joint_position", **semantic},
                    "transport": {
                        "backend": "ros2",
                        "kind": "action",
                        "endpoint": move["endpoint"],
                        "interface": move["interface_type"],
                    },
                    "encode": {
                        "positions": {
                            "source": "positions",
                            "field": move["target_field"],
                            "unit": move["target_unit"],
                        },
                        "constants": move["constants"],
                    },
                    "result": {
                        "error_code": move["result_code_field"],
                        "description": move["result_description_field"],
                        "success_code": move["success_code"],
                    },
                    "completion_policy": {
                        "status": "unresolved",
                        "state_binding": state_id,
                        "completion": move["completion"],
                        "missing_fields": unresolved,
                    },
                    "evidence": candidates["joint_position"].evidence_ids,
                },
            },
        }
        _write_yaml(mapping_path, mapping)

        device_joints = [
            {
                "canonical_name": name,
                "type": "revolute",
                "unit": "radian",
                "limits": list(limit),
            }
            for name, limit in zip(joints, limits)
        ]
        embodiment = {
            "schema_version": "embodiment/v0.2",
            "embodiment": {
                "type": package_identity.embodiment_type,
                "dof": len(joints),
            },
            "devices": [{
                "id": package_identity.device_id,
                "type": "arm",
                "capabilities": ["joint_state"],
                "candidate_capabilities": ["joint_position"],
                "joints": device_joints,
            }],
            "control": {"supported_modes": []},
            "adapter": {"backend": package_identity.backend_id},
        }
        _write_yaml(embodiment_path, embodiment)

        used_ids = tuple(sorted(set(
            candidates["joint_position_state"].evidence_ids
            + candidates["joint_position"].evidence_ids
        )))
        provenance = {
            "schema_version": "generation-provenance/v0.1",
            "package": package_identity.package_name,
            "package_status": "candidate",
            "live_execution_ready": False,
            "capabilities": {
                capability_id: {
                    "status": assessments[capability_id].status,
                    "interface_mapped": assessments[capability_id].mapping_complete,
                    "execution_policy_complete": assessments[
                        capability_id
                    ].execution_policy_complete,
                    "unresolved_fields": [
                        item.field for item in assessments[capability_id].missing
                    ],
                    "evidence_ids": list(candidates[capability_id].evidence_ids),
                    "backend": package_identity.backend_id,
                }
                for capability_id in sorted(required)
            },
            "evidence": [
                {
                    "evidence_id": identifier,
                    "source_path": evidence.get(identifier).source_path.as_posix(),
                    "confidence_boundary": evidence.get(
                        identifier
                    ).confidence_boundary,
                }
                for identifier in used_ids
            ],
            "unmapped_evidence_ids": list(
                coverage.discovered_unmapped_evidence_ids
            ),
        }
        _write_yaml(provenance_path, provenance)
        package = {
            "schema_version": "hardware-package/v0.1",
            "package": {
                "name": package_identity.package_name,
                "version": package_identity.version,
                "vendor": package_identity.vendor,
                "model": package_identity.model,
                "type": "robot",
            },
            "embodiment_manifest": "embodiment.yaml",
            "assets": {
                "interface_mapping_candidate": [{
                    "format": "yaml",
                    "path": f"config/{mapping_name}",
                    "source": True,
                    "digest": f"sha256:{_digest(mapping_path)}",
                }],
                "generation_provenance": [{
                    "format": "yaml",
                    "path": "generation-provenance.yaml",
                    "source": True,
                    "digest": f"sha256:{_digest(provenance_path)}",
                }],
            },
            "backends": [{
                "id": package_identity.backend_id,
                "type": "candidate",
                "requirements": {"ros_distro": package_identity.ros_distro},
            }],
            "validation": {
                "scope": [package_identity.device_id],
                "capabilities": sorted(required),
                "candidate_only": True,
                "interface_mapped": True,
                "completion_policy": "unresolved",
                "unresolved_fields": unresolved,
                "live_execution_ready": False,
            },
        }
        _write_yaml(package_path, package)
        return GeneratedPackage(
            root, package_path, embodiment_path, mapping_path, provenance_path,
            package_status="candidate",
        )

    @staticmethod
    def promote_candidate(
        candidate_root: Path,
        output_root: Path,
        policy: RuntimeCompletionPolicy,
        backend: BackendDescriptor,
    ) -> GeneratedPackage:
        """Create a runtime package without changing interface evidence.

        Only the sealed candidate mapping, an explicitly confirmed operator
        policy, and the fixed Backend descriptor are consumed here.
        """
        candidate_root = candidate_root.resolve()
        candidate_package = load_package_manifest(candidate_root / "package.yaml")
        candidate_package.validate_assets(require_digests=True)
        if candidate_package.validation.get("candidate_only") is not True:
            raise ValueError("source package is not a candidate package")
        if candidate_package.validation.get("interface_mapped") is not True:
            raise ValueError("candidate interface mapping is incomplete")
        if candidate_package.validation.get("live_execution_ready") is not False:
            raise ValueError("candidate must not already be live executable")
        if len(candidate_package.backends) != 1:
            raise ValueError("candidate must declare exactly one backend")
        candidate_backend = candidate_package.backends[0]
        if candidate_backend.id != backend.backend_id:
            raise ValueError("candidate backend does not match fixed platform backend")

        candidate_mapping_path = candidate_package.resolve_asset_path(
            "interface_mapping_candidate", "yaml"
        )
        candidate_mapping = yaml.safe_load(
            candidate_mapping_path.read_text(encoding="utf-8")
        )
        if candidate_mapping.get("schema_version") != "interface-mapping-candidate/v0.1":
            raise ValueError("unsupported candidate mapping schema")
        bindings = candidate_mapping.get("bindings") or {}
        by_operation = {
            value.get("semantic", {}).get("operation"): (name, value)
            for name, value in bindings.items()
        }
        if set(by_operation) != {"joint_state", "joint_position"}:
            raise ValueError("candidate must contain state and position bindings")
        state_name, state_candidate = by_operation["joint_state"]
        move_name, move_candidate = by_operation["joint_position"]
        if not state_candidate.get("interface_mapped") or not move_candidate.get(
            "interface_mapped"
        ):
            raise ValueError("candidate bindings are not interface-mapped")
        unresolved = move_candidate.get("completion_policy") or {}
        expected_policy_fields = {
            "timeout_s", "arrival_tolerance_rad", "settle_window_s",
        }
        if (
            unresolved.get("status") != "unresolved"
            or set(unresolved.get("missing_fields", ())) != expected_policy_fields
        ):
            raise ValueError("candidate does not expose the expected policy gap")
        device_id = str(state_candidate["semantic"]["device"])
        if move_candidate["semantic"].get("device") != device_id:
            raise ValueError("candidate state and action devices differ")
        policy.validate()

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"generation output must be empty: {root}")
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "validation").mkdir(parents=True, exist_ok=True)
        mapping_path = root / "config" / f"{device_id}_ros2_mapping.yaml"
        embodiment_path = root / "embodiment.yaml"
        provenance_path = root / "generation-provenance.yaml"
        package_path = root / "package.yaml"
        policy_path = root / "validation" / "runtime-completion-policy.yaml"

        candidate_digest = package_tree_digest(candidate_root)
        policy_document = policy.document(
            device_id=device_id,
            candidate_package_digest=candidate_digest,
        )
        _write_yaml(policy_path, policy_document)

        state = deepcopy(state_candidate)
        move = deepcopy(move_candidate)
        state.pop("interface_mapped", None)
        move.pop("interface_mapped", None)
        move.pop("completion_policy", None)
        move["transport"]["timeout_s"] = float(policy.timeout_s)
        move["completion"] = {
            "state_binding": state_name,
            "arrival_tolerance_rad": float(policy.arrival_tolerance_rad),
            "settle_window_s": float(policy.settle_window_s),
        }
        _write_yaml(mapping_path, {
            "schema_version": "interface-mapping/v1",
            "bindings": {state_name: state, move_name: move},
        })

        candidate_embodiment = yaml.safe_load(
            (candidate_root / str(candidate_package.embodiment_manifest)).read_text(
                encoding="utf-8"
            )
        )
        embodiment = deepcopy(candidate_embodiment)
        devices = embodiment.get("devices") or []
        if len(devices) != 1 or devices[0].get("id") != device_id:
            raise ValueError("candidate embodiment scope does not match mapping")
        devices[0]["capabilities"] = ["joint_state", "joint_position"]
        devices[0].pop("candidate_capabilities", None)
        joint_count = len(devices[0].get("joints") or [])
        embodiment["control"] = {"supported_modes": [{
            "type": "joint_position",
            "target": device_id,
            "dimension": joint_count,
            "unit": "radian",
        }]}
        _write_yaml(embodiment_path, embodiment)
        _write_yaml(root / "config" / "connection.yaml", {
            "mapping_path": f"config/{mapping_path.name}",
            "manage_process": False,
        })

        adapter_path = _write_adapter_scaffold(root)
        candidate_provenance = yaml.safe_load(
            (candidate_root / "generation-provenance.yaml").read_text(
                encoding="utf-8"
            )
        )
        provenance = {
            "schema_version": "generation-provenance/v0.1",
            "package": candidate_package.name,
            "package_status": "runtime",
            "source_candidate": {
                "tree_sha256": candidate_digest,
                "mapping_sha256": _digest(candidate_mapping_path),
            },
            "runtime_policy": {
                "sha256": _digest(policy_path),
                "source": policy.source,
                "operator": policy.operator,
                "confirmed_at": policy.confirmed_at,
                "reference": policy.reference,
                "vendor_declared": False,
            },
            "backend": {
                "id": backend.backend_id,
                "version": backend.version,
                "entrypoint": _ADAPTER_ENTRYPOINT,
            },
            "capabilities": {
                "joint_position_state": {
                    "interface_mapped": True,
                    "completion_policy_resolved": True,
                },
                "joint_position": {
                    "interface_mapped": True,
                    "completion_policy_resolved": True,
                },
            },
            "evidence": candidate_provenance.get("evidence", []),
            "live_execution_ready": False,
        }
        _write_yaml(provenance_path, provenance)

        package = {
            "schema_version": "hardware-package/v0.1",
            "package": {
                "name": candidate_package.name,
                "version": candidate_package.version,
                "vendor": candidate_package.vendor,
                "model": candidate_package.model,
                "type": candidate_package.type,
            },
            "embodiment_manifest": "embodiment.yaml",
            "assets": {
                "adapter_code": [{"format": "python", "path": "adapters/ros2/adapter.py", "source": True, "digest": f"sha256:{_digest(adapter_path)}"}],
                "interface_mapping": [{
                    "format": "yaml",
                    "path": f"config/{mapping_path.name}",
                    "source": True,
                    "digest": f"sha256:{_digest(mapping_path)}",
                }],
                "generation_provenance": [{
                    "format": "yaml",
                    "path": "generation-provenance.yaml",
                    "source": True,
                    "digest": f"sha256:{_digest(provenance_path)}",
                }],
                "runtime_completion_policy": [{
                    "format": "yaml",
                    "path": "validation/runtime-completion-policy.yaml",
                    "source": True,
                    "digest": f"sha256:{_digest(policy_path)}",
                }],
            },
            "backends": [{
                "id": backend.backend_id,
                "type": "python",
                "entrypoint": _ADAPTER_ENTRYPOINT,
                "requirements": dict(candidate_backend.requirements),
            }],
            "defaults": {
                "backend": backend.backend_id,
                "config": "config/connection.yaml",
            },
            "validation": {
                "scope": [device_id],
                "capabilities": ["joint_position", "joint_position_state"],
                "candidate_only": False,
                "interface_mapped": True,
                "completion_policy_resolved": True,
                "runtime_package_generated": True,
                "runtime_preflight_passed": False,
                "live_execution_ready": False,
            },
        }
        _write_yaml(package_path, package)
        return GeneratedPackage(
            root, package_path, embodiment_path, mapping_path, provenance_path,
            package_status="runtime",
        )

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
        expected_state_binding = f"{package_identity.device_id}_joint_state"
        if move.get("state_binding") != expected_state_binding:
            raise ValueError(
                "package identity device does not match assessed state binding"
            )
        joints = tuple(state.get("ordered_joints", ()))
        limits = tuple(state.get("joint_limits", ()))
        if len(joints) == 0 or len(joints) != len(limits) or tuple(move.get("ordered_joints", ())) != joints:
            raise ValueError("state and action require the same explicit joints and joint limits")
        if state.get("unit") != "radian" or move.get("unit") != "radian" or move.get("target_unit") not in {"radian", "degree"}:
            raise ValueError("required units are missing or unsupported")

        # The generator consumes the same versioned field contract as the
        # matcher. It must not maintain a second, hidden list of required
        # candidate fields.
        required_state = set(required_candidate_fields("joint_position_state"))
        required_move = set(required_candidate_fields("joint_position"))
        missing = sorted((required_state - set(state)) | (required_move - set(move)))
        if missing:
            raise ValueError(f"mapping candidate is missing required fields: {missing}")

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"generation output must be empty: {root}")
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        mapping_name = f"{package_identity.device_id}_ros2_mapping.yaml"
        mapping_path = root / "config" / mapping_name
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
        _write_yaml(
            root / "config" / "connection.yaml",
            {"mapping_path": f"config/{mapping_name}", "manage_process": False},
        )

        adapter_path = _write_adapter_scaffold(root)
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
                "adapter_code": [{"format": "python", "path": "adapters/ros2/adapter.py", "source": True, "digest": f"sha256:{_digest(adapter_path)}"}],
                "interface_mapping": [{"format": "yaml", "path": f"config/{mapping_name}", "source": True, "digest": f"sha256:{_digest(mapping_path)}"}],
                "generation_provenance": [{"format": "yaml", "path": "generation-provenance.yaml", "source": True, "digest": f"sha256:{_digest(provenance_path)}"}],
            },
            "backends": [{"id": package_identity.backend_id, "type": "python", "entrypoint": _ADAPTER_ENTRYPOINT, "platforms": [{"os": package_identity.os, "arch": package_identity.arch}], "requirements": {"ros_distro": package_identity.ros_distro}}],
            "defaults": {"backend": package_identity.backend_id, "config": "config/connection.yaml"},
            "validation": {"scope": [package_identity.device_id], "capabilities": sorted(required), "runtime_package_generated": True, "runtime_preflight_passed": False, "live_execution_ready": False, "adapter_implementation_required": True},
        }
        _write_yaml(package_path, package)
        return GeneratedPackage(root, package_path, embodiment_path, mapping_path, provenance_path)
