from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import xml.etree.ElementTree as ET

import yaml

from ..models import EvidenceLevel, EvidenceRecord
from .base import ScanContext


def _fields(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            result.append({"type": parts[0], "name": parts[1]})
    return result


def _record(path: Path, root: Path, root_id: str, claim_type: str, claims: dict[str, Any], boundary: str, level: EvidenceLevel = EvidenceLevel.DECLARED) -> EvidenceRecord:
    relative = path.relative_to(root)
    digest = sha256(path.read_bytes()).hexdigest()
    claim_digest = sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest()[:12]
    return EvidenceRecord(
        evidence_id=f"evidence:ros2:{root_id}:{relative.as_posix()}:{claim_digest}",
        source_asset_ids=(f"asset:{root_id}:{relative.as_posix()}:{digest[:12]}",),
        source_path=relative,
        claim_type=claim_type,
        claims=claims,
        provenance={"extractor": "ros2-static", "source_sha256": digest},
        confidence_boundary=boundary,
        level=level,
    )


def _constant_keywords(call: ast.Call) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg and isinstance(keyword.value, ast.Constant):
            values[keyword.arg] = keyword.value.value
    return values


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal(node: ast.AST, constants: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(item, constants) for item in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _literal(node.left, constants)
        right = _literal(node.right, constants)
        if isinstance(left, list) and isinstance(right, int):
            return left * right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                resolved = _literal(value.value, constants)
                if not isinstance(resolved, (str, int, float)):
                    raise ValueError("unresolved formatted value")
                parts.append(str(resolved))
            else:
                raise ValueError("unresolved joined string")
        return "".join(parts)
    raise ValueError("expression is not statically resolvable")


def _attribute_path(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _function_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    names = [item.arg for item in node.args.args]
    values: dict[str, Any] = {}
    for name, default in zip(names[-len(node.args.defaults):], node.args.defaults):
        try:
            values[name] = _literal(default, {})
        except ValueError:
            pass
    return values


def _interface_package(path: Path, root: Path) -> str | None:
    current = path.parent
    while current != root and root in current.parents:
        manifest = current / "package.xml"
        if manifest.is_file():
            return (ET.parse(manifest).getroot().findtext("name") or "").strip() or None
        current = current.parent
    relative = path.relative_to(root)
    if "share" in relative.parts:
        index = relative.parts.index("share")
        if index + 1 < len(relative.parts):
            return relative.parts[index + 1]
    return None


def _field_paths(fields: list[dict[str, str]], definitions: dict[str, list[dict[str, str]]], prefix: str = "", seen: frozenset[str] = frozenset()) -> list[str]:
    output: list[str] = []
    primitives = {"bool", "byte", "char", "float32", "float64", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "string", "wstring"}
    for field in fields:
        name = f"{prefix}.{field['name']}" if prefix else field["name"]
        base_type = re.sub(r"\[.*\]$", "", field["type"]).split("/")[-1]
        if field["type"] in {"std_msgs/Header", "Header"}:
            output.append(f"{name}.stamp")
        elif base_type in definitions and base_type not in seen:
            output.extend(_field_paths(definitions[base_type], definitions, name, seen | {base_type}))
        elif base_type.lower() in primitives:
            output.append(name)
        else:
            output.append(name)
    return output


def _python_ros_usage(path: Path, root: Path, root_id: str) -> list[EvidenceRecord]:
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path.relative_to(root)))
    constants: dict[str, Any] = {}
    imported_types: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            try:
                resolved = _literal(value, constants)
            except ValueError:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = resolved
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[-1] in {"msg", "srv", "action"}:
                for alias in node.names:
                    imported_types[alias.asname or alias.name] = f"{'/'.join(parts)}/{alias.name}"

    observed_fields: set[str] = set()
    ready_values: set[int] = set()
    result_code_field: str | None = None
    success_code: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            path_value = _attribute_path(node)
            if path_value and path_value.startswith("msg."):
                observed_fields.add(path_value[4:])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None:
                try:
                    resolved = _literal(value, constants)
                except ValueError:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and "idle" in target.id.lower() and isinstance(resolved, int):
                        ready_values.add(resolved)
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1:
            attribute = _attribute_path(node.left)
            try:
                compared = _literal(node.comparators[0], constants)
            except ValueError:
                continue
            if attribute and "error" in attribute and isinstance(compared, int):
                parts = attribute.split(".")
                result_code_field = ".".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
                success_code = compared

    action_details: dict[str, dict[str, Any]] = {}
    arrival: dict[str, Any] | None = None
    for function in (item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))):
        defaults = _function_defaults(function)
        if "tol" in defaults and "settle" in defaults:
            arrival = {
                "arrival_tolerance_rad": defaults["tol"],
                "settle_window_s": defaults["settle"],
                "completion": ["terminal_result", "measured_arrival"],
            }
        for call in (item for item in ast.walk(function) if isinstance(item, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "Goal" and isinstance(call.func.value, ast.Name):
                interface_name = call.func.value.id
                details: dict[str, Any] = {"constants": {}, "dynamic_goal_fields": []}
                for keyword in call.keywords:
                    if keyword.arg is None:
                        continue
                    try:
                        details["constants"][keyword.arg] = _literal(keyword.value, constants)
                    except ValueError:
                        details["dynamic_goal_fields"].append(keyword.arg)
                if len(details["dynamic_goal_fields"]) == 1:
                    details["target_field"] = details["dynamic_goal_fields"][0]
                if "timeout" in defaults:
                    details["timeout_s"] = defaults["timeout"]
                action_details[interface_name] = details

    records: list[EvidenceRecord] = []
    for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
        name = _call_name(call.func)
        if name not in {"ActionClient", "create_subscription"} or len(call.args) < 3:
            continue
        interface_name = call.args[1].id if name == "ActionClient" and isinstance(call.args[1], ast.Name) else (
            call.args[0].id if name == "create_subscription" and isinstance(call.args[0], ast.Name) else ""
        )
        endpoint_node = call.args[2] if name == "ActionClient" else call.args[1]
        try:
            endpoint = _literal(endpoint_node, constants)
        except ValueError:
            continue
        interface_type = imported_types.get(interface_name)
        if not interface_type or not isinstance(endpoint, str):
            continue
        if name == "create_subscription":
            claims: dict[str, Any] = {"transport_kind": "ros2_subscription", "endpoint": endpoint, "interface_type": interface_type}
            positions = sorted(field for field in observed_fields if "joint" in field and ("angle" in field or "position" in field))
            modes = sorted(field for field in observed_fields if "mode" in field)
            if len(positions) == 1:
                claims["positions_field"] = positions[0]
            if len(modes) == 1:
                claims["mode_field"] = modes[0]
            if ready_values:
                claims["ready_values"] = sorted(ready_values)
            records.append(_record(path, root, root_id, "ros2_subscription_usage", claims, "static_python_usage_only"))
        else:
            details = action_details.get(interface_name, {})
            claims = {"transport_kind": "ros2_action", "endpoint": endpoint, "interface_type": interface_type, **details}
            if result_code_field is not None:
                claims["result_code_field"] = result_code_field
                claims["success_code"] = success_code
            records.append(_record(path, root, root_id, "ros2_action_usage", claims, "static_python_usage_only"))
    if arrival:
        records.append(_record(path, root, root_id, "joint_arrival_policy", arrival, "static_python_policy_only"))
    return records


def _joint_configurations(path: Path, root: Path, root_id: str) -> list[EvidenceRecord]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        return []
    records: list[EvidenceRecord] = []
    text = path.read_text(encoding="utf-8", errors="replace")

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for device, config in value.items():
                if isinstance(config, dict) and isinstance(config.get("joint_list"), list):
                    order = [str(item) for item in config["joint_list"]]
                    limits: list[list[float]] = []
                    for joint in order:
                        joint_config = value.get(joint)
                        raw_limit = joint_config.get("joint_soft_limit") if isinstance(joint_config, dict) else None
                        if not isinstance(raw_limit, list) or len(raw_limit) != 2:
                            limits = []
                            break
                        limits.append([float(raw_limit[0]), float(raw_limit[1])])
                    if limits:
                        claims: dict[str, Any] = {"device": str(device), "vendor_joint_order": order, "joint_limits": limits}
                        if "radian" in text:
                            claims["unit"] = "radian"
                        records.append(_record(path, root, root_id, "robot_joint_configuration", claims, "static_parameter_configuration_only"))
                visit(config)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(data)
    return records


class Ros2Extractor:
    def scan_files(self, context: ScanContext) -> list[EvidenceRecord]:
        root = context.root.resolve()
        records: list[EvidenceRecord] = []
        definitions: dict[str, list[dict[str, str]]] = {}
        for interface_path in sorted(root.rglob("*.msg")):
            relative = interface_path.relative_to(root)
            if interface_path.is_symlink() or any(part in context.ignored_components for part in relative.parts):
                continue
            definitions[interface_path.stem] = _fields(interface_path.read_text(encoding="utf-8", errors="replace"))
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if any(part in context.ignored_components for part in relative.parts):
                continue
            suffix = path.suffix.lower()
            if path.name == "package.xml":
                tree = ET.parse(path).getroot()
                records.append(_record(path, root, context.root_id, "ros2_package", {
                    "package": (tree.findtext("name") or "").strip(),
                    "version": (tree.findtext("version") or "").strip(),
                    "build_type": (tree.findtext("export/build_type") or "unknown").strip(),
                }, "manifest_declaration_only"))
            elif suffix in {".msg", ".srv", ".action"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                parts = text.split("---")
                claims: dict[str, Any] = {
                    "interface": path.stem,
                    "interface_kind": suffix[1:],
                }
                if suffix == ".msg":
                    claims["fields"] = _fields(parts[0])
                    claims["field_paths"] = _field_paths(claims["fields"], definitions)
                elif suffix == ".srv":
                    claims["request_fields"] = _fields(parts[0])
                    claims["response_fields"] = _fields(parts[1]) if len(parts) > 1 else []
                    claims["request_field_paths"] = _field_paths(claims["request_fields"], definitions)
                    claims["response_field_paths"] = _field_paths(claims["response_fields"], definitions)
                else:
                    claims["goal_fields"] = _fields(parts[0])
                    claims["result_fields"] = _fields(parts[1]) if len(parts) > 1 else []
                    claims["feedback_fields"] = _fields(parts[2]) if len(parts) > 2 else []
                    claims["goal_field_paths"] = _field_paths(claims["goal_fields"], definitions)
                    claims["result_field_paths"] = _field_paths(claims["result_fields"], definitions)
                package = _interface_package(path, root)
                if package:
                    claims["qualified_interface"] = f"{package}/{suffix[1:]}/{path.stem}"
                records.append(_record(path, root, context.root_id, "ros2_interface_definition", claims, "type_definition_only"))
            elif suffix == ".idl":
                records.append(_record(path, root, context.root_id, "ros2_interface_definition", {
                    "interface": path.stem,
                    "interface_kind": "idl",
                    "text_sha256": sha256(path.read_bytes()).hexdigest(),
                }, "type_definition_only"))
            elif path.name.endswith(".launch.py"):
                source = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(relative))
                arguments: dict[str, Any] = {}
                nodes: list[dict[str, Any]] = []
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name = node.func.id if isinstance(node.func, ast.Name) else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                    keywords = _constant_keywords(node)
                    if name == "DeclareLaunchArgument" and node.args and isinstance(node.args[0], ast.Constant):
                        arguments[str(node.args[0].value)] = keywords.get("default_value")
                    elif name == "Node":
                        nodes.append({key: keywords[key] for key in ("package", "executable", "namespace") if key in keywords})
                namespaces = sorted({f"/{str(n['namespace']).strip('/')}" for n in nodes if n.get("namespace")})
                records.append(_record(path, root, context.root_id, "ros2_launch_definition", {
                    "launch_file": relative.as_posix(),
                    "arguments": arguments,
                    "nodes": nodes,
                    "namespace_candidates": namespaces,
                }, "static_launch_syntax_only"))
            elif suffix == ".py":
                records.extend(_python_ros_usage(path, root, context.root_id))
            elif suffix in {".yaml", ".yml"}:
                records.extend(_joint_configurations(path, root, context.root_id))
            elif suffix in {".so", ".bin"} or ".so." in path.name:
                content = path.read_bytes()[:4 * 1024 * 1024]
                for token in sorted(set(re.findall(rb"/[A-Za-z0-9_/-]+_(?:action|state|service)", content))):
                    value = token.decode("ascii", errors="ignore")
                    records.append(_record(path, root, context.root_id, "ros2_endpoint_candidate", {
                        "token": value,
                        "fully_qualified_confirmed": False,
                    }, "binary_string_candidate_only", EvidenceLevel.OBSERVED))
        return sorted(records, key=lambda item: item.evidence_id)


@dataclass(frozen=True)
class RosGraphSnapshot:
    topics: tuple[dict[str, str], ...]
    services: tuple[dict[str, str], ...]
    actions: tuple[dict[str, str], ...]
    nodes: tuple[str, ...]

    @classmethod
    def from_json(cls, path: Path) -> "RosGraphSnapshot":
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = {"topics", "services", "actions", "nodes"}
        if set(data) != expected:
            raise ValueError(f"graph snapshot fields must be {sorted(expected)}")
        return cls(
            topics=tuple(data["topics"]),
            services=tuple(data["services"]),
            actions=tuple(data["actions"]),
            nodes=tuple(data["nodes"]),
        )

    def to_evidence(self, snapshot_id: str) -> tuple[EvidenceRecord, ...]:
        records: list[EvidenceRecord] = []
        for kind, entries in (("topic", self.topics), ("service", self.services), ("action", self.actions)):
            for index, entry in enumerate(entries):
                claims = {"endpoint_kind": kind, **entry}
                records.append(EvidenceRecord(
                    evidence_id=f"evidence:ros-graph:{snapshot_id}:{kind}:{index}",
                    source_asset_ids=(),
                    source_path=Path(f"{snapshot_id}.json"),
                    claim_type="ros2_runtime_endpoint",
                    claims=claims,
                    provenance={"extractor": "ros2-graph-snapshot", "snapshot_id": snapshot_id},
                    confidence_boundary="runtime_graph_presence_only",
                    level=EvidenceLevel.RUNTIME_READ,
                ))
        for index, node in enumerate(self.nodes):
            records.append(EvidenceRecord(
                evidence_id=f"evidence:ros-graph:{snapshot_id}:node:{index}",
                source_asset_ids=(), source_path=Path(f"{snapshot_id}.json"),
                claim_type="ros2_runtime_node", claims={"node": node},
                provenance={"extractor": "ros2-graph-snapshot", "snapshot_id": snapshot_id},
                confidence_boundary="runtime_graph_presence_only", level=EvidenceLevel.RUNTIME_READ,
            ))
        return tuple(records)
