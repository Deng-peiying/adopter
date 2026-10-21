from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

import yaml

from ..package.loader import load_backend_entrypoint
from ..hardware.manifest import load_manifest
from ..package.manifest import load_package_manifest


@dataclass(frozen=True)
class ConformanceReport:
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    resolved_package_root: Path
    resolved_mapping_path: Path | None


@dataclass(frozen=True)
class SemanticDifference:
    field: str
    candidate: Any
    reference: Any


@dataclass(frozen=True)
class SemanticDiff:
    equivalent: bool
    differences: tuple[SemanticDifference, ...]


class ConformanceRunner:
    """Validate package-owned Adapter structure and evidence without interpreting vendor mappings."""

    def __init__(self, denied_markers: tuple[str, ...] = ()):
        self.denied_markers = denied_markers

    def validate_generated_package(self, package_root: Path) -> ConformanceReport:
        root = package_root.resolve()
        checks: list[str] = []
        failures: list[str] = []
        mapping_path: Path | None = None
        try:
            package = load_package_manifest(root / "package.yaml")
            if package.root.resolve() != root:
                raise ValueError("resolved package root selected another package")
            package.validate_assets(require_digests=True)
            checks.extend(("package_schema", "asset_digests", "resolved_package_identity"))
        except Exception as exc:
            return ConformanceReport(False, tuple(checks), (f"package validation: {exc}",), root, None)

        try:
            manifest_path = (root / str(package.embodiment_manifest)).resolve()
            if not manifest_path.is_relative_to(root):
                raise ValueError("embodiment manifest leaves the package")
            load_manifest(manifest_path)
            checks.append("embodiment_manifest")
        except Exception as exc:
            failures.append(f"embodiment manifest: {exc}")

        try:
            config_relative = Path(str(package.defaults["config"]))
            if config_relative.is_absolute() or ".." in config_relative.parts:
                raise ValueError("default config path leaves generated package")
            config = yaml.safe_load((root / config_relative).read_text(encoding="utf-8"))
            mapping_relative = Path(str(config["mapping_path"]))
            if mapping_relative.is_absolute() or ".." in mapping_relative.parts:
                raise ValueError("mapping reference path leaves generated package")
            mapping_path = (root / mapping_relative).resolve()
            declared = package.resolve_asset_path("interface_mapping", "yaml").resolve()
            if mapping_path != declared or not mapping_path.is_relative_to(root):
                raise ValueError("mapping reference does not resolve to its declared package asset")
            mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
            if not isinstance(mapping, dict) or not isinstance(mapping.get("bindings"), dict):
                raise ValueError("mapping reference must contain bindings")
            checks.append("mapping_reference")
        except Exception as exc:
            failures.append(f"mapping reference: {exc}")

        try:
            provenance = yaml.safe_load((root / "generation-provenance.yaml").read_text(encoding="utf-8"))
            for item in provenance.get("evidence", []):
                source = str(item.get("source_path", ""))
                if Path(source).is_absolute() or ".." in Path(source).parts or any(marker in source for marker in self.denied_markers):
                    raise ValueError(f"provenance contains denied reference: {source}")
            checks.append("provenance_isolation")
        except Exception as exc:
            failures.append(f"provenance isolation: {exc}")

        try:
            backend = package.select_backend(
                package.defaults.get("backend"),
                type("Platform", (), {"os": "linux", "arch": "x86_64", "ros_distro": "humble"})(),
            )
            adapter_type = load_backend_entrypoint(backend, root)
            required = ("load_manifest", "configure", "connect", "disconnect", "enable", "disable", "capabilities", "supports_action", "get_joint_state", "get_state", "send_command", "health")
            missing = [name for name in required if not callable(getattr(adapter_type, name, None))]
            if missing:
                raise ValueError(f"Adapter is missing contract methods: {missing}")
            checks.append("package_owned_adapter_contract")
        except Exception as exc:
            failures.append(f"package-owned Adapter: {exc}")

        return ConformanceReport(not failures, tuple(checks), tuple(failures), root, mapping_path)

    def validate_candidate_package(self, package_root: Path) -> ConformanceReport:
        """Validate interface evidence without treating the package as executable."""
        root = package_root.resolve()
        checks: list[str] = []
        failures: list[str] = []
        mapping_path: Path | None = None
        try:
            package = load_package_manifest(root / "package.yaml")
            if package.root.resolve() != root:
                raise ValueError("resolved package root selected another package")
            if package.validation.get("candidate_only") is not True:
                raise ValueError("package is not marked candidate_only")
            if package.validation.get("live_execution_ready") is not False:
                raise ValueError("candidate package must block live execution")
            checks.append("package_schema")
        except Exception as exc:
            return ConformanceReport(
                False, tuple(checks), (f"candidate package schema: {exc}",),
                root, None,
            )

        try:
            package.validate_assets(require_digests=True)
            checks.append("asset_digests")
        except Exception as exc:
            failures.append(f"asset digest validation: {exc}")

        try:
            if "interface_mapping" in package.assets:
                raise ValueError("candidate package exposes a runtime mapping asset")
            mapping_path = package.resolve_asset_path(
                "interface_mapping_candidate", "yaml"
            ).resolve()
            mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
            schema_resource = files("cross_embodiment.onboarding").joinpath(
                "schemas/interface-mapping-candidate.schema.json"
            )
            schema = json.loads(schema_resource.read_text(encoding="utf-8"))
            try:
                import jsonschema  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "candidate schema validation requires the onboarding extra: "
                    "pip install 'cross-embodiment[onboarding]'"
                ) from exc
            jsonschema.validate(mapping, schema)
            checks.append("candidate_mapping_schema")
        except Exception as exc:
            failures.append(f"candidate mapping schema: {exc}")
            mapping = None

        try:
            if package.defaults:
                raise ValueError("candidate package declares runtime defaults")
            if any(
                backend.entrypoint or backend.launch or backend.executable
                for backend in package.backends
            ):
                raise ValueError("candidate package exposes an executable backend")
            if (root / "config/connection.yaml").exists():
                raise ValueError("candidate package contains a runtime connection")
            checks.append("runtime_execution_blocked")
        except Exception as exc:
            failures.append(f"runtime execution isolation: {exc}")

        if isinstance(mapping, dict):
            try:
                operations = {
                    binding["semantic"]["operation"]: binding
                    for binding in mapping["bindings"].values()
                }
                if set(operations) != {"joint_state", "joint_position"}:
                    raise ValueError("candidate requires state and position bindings")
                if not all(
                    binding.get("interface_mapped") is True
                    and binding.get("evidence")
                    for binding in operations.values()
                ):
                    raise ValueError("interface mapping lacks evidence")
                checks.append("interface_mapping_complete")
                policy = operations["joint_position"].get("completion_policy")
                if not isinstance(policy, dict) or policy.get("status") != "unresolved":
                    raise ValueError("completion policy gap is not explicit")
                if not policy.get("missing_fields"):
                    raise ValueError("completion policy has no unresolved fields")
                checks.append("execution_policy_gap_recorded")
            except Exception as exc:
                failures.append(f"candidate interface coverage: {exc}")

        try:
            provenance = yaml.safe_load(
                (root / "generation-provenance.yaml").read_text(encoding="utf-8")
            )
            for item in provenance.get("evidence", []):
                source = str(item.get("source_path", ""))
                if (
                    Path(source).is_absolute()
                    or ".." in Path(source).parts
                    or any(marker in source for marker in self.denied_markers)
                ):
                    raise ValueError(
                        f"provenance contains denied reference: {source}"
                    )
            checks.append("provenance_isolation")
        except Exception as exc:
            failures.append(f"provenance isolation: {exc}")

        return ConformanceReport(
            not failures, tuple(checks), tuple(failures), root, mapping_path,
        )


def _semantic_mapping(root: Path) -> dict[str, Any]:
    package = load_package_manifest(root / "package.yaml")
    mapping_path = package.resolve_asset_path("interface_mapping", "yaml", verify_digest=False)
    mapping = yaml.safe_load(mapping_path.read_text())
    manifest = load_manifest(root / str(package.embodiment_manifest))
    result: dict[str, Any] = {
        "devices": [device.get("id") for device in manifest.devices],
        "bindings": {},
    }
    for name, binding in sorted(mapping["bindings"].items()):
        result["bindings"][name] = {
            "semantic": binding.get("semantic"), "transport": binding.get("transport"),
            "decode": binding.get("decode"), "encode": binding.get("encode"),
            "result": binding.get("result"), "completion": binding.get("completion"),
        }
    return result


def _diff(prefix: str, left: Any, right: Any, output: list[SemanticDifference]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            _diff(f"{prefix}.{key}" if prefix else key, left.get(key), right.get(key), output)
    elif left != right:
        output.append(SemanticDifference(prefix, left, right))


class IndependentEvaluator:
    @staticmethod
    def compare(candidate_root: Path, reference_root: Path) -> SemanticDiff:
        differences: list[SemanticDifference] = []
        _diff("", _semantic_mapping(candidate_root), _semantic_mapping(reference_root), differences)
        return SemanticDiff(not differences, tuple(differences))
