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


def _field_lines(text: str, section: int = 0) -> dict[str, int]:
    result: dict[str, int] = {}
    current_section = 0
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.strip() == "---":
            current_section += 1
            continue
        if current_section != section:
            continue
        line = raw.split("#", 1)[0].strip()
        if not line or "=" in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            result[parts[1]] = number
    return result


def _record(
    path: Path,
    root: Path,
    root_id: str,
    claim_type: str,
    claims: dict[str, Any],
    boundary: str,
    level: EvidenceLevel = EvidenceLevel.DECLARED,
    claim_sources: dict[str, dict[str, Any]] | None = None,
) -> EvidenceRecord:
    relative = path.relative_to(root)
    digest = sha256(path.read_bytes()).hexdigest()
    claim_digest = sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest()[:12]
    return EvidenceRecord(
        evidence_id=f"evidence:ros2:{root_id}:{relative.as_posix()}:{claim_digest}",
        source_asset_ids=(f"asset:{root_id}:{relative.as_posix()}:{digest[:12]}",),
        source_path=relative,
        claim_type=claim_type,
        claims=claims,
        provenance={
            "extractor": "ros2-static",
            "source_sha256": digest,
            **({"claim_sources": claim_sources} if claim_sources else {}),
        },
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


def _resolved_attribute_path(node: ast.AST, aliases: dict[str, str]) -> str | None:
    value = _attribute_path(node)
    if value is None:
        return None
    parts = value.split(".")
    if parts[0] in aliases:
        return ".".join([*aliases[parts[0]].split("."), *parts[1:]])
    return value


def _source(relative: Path, line: int, rule: str) -> dict[str, Any]:
    return {
        "source_path": relative.as_posix(),
        "line": line,
        "normalization_rule": rule,
    }


def _function_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    names = [item.arg for item in node.args.args]
    values: dict[str, Any] = {}
    for name, default in zip(names[-len(node.args.defaults):], node.args.defaults):
        try:
            values[name] = _literal(default, {})
        except ValueError:
            pass
    return values


def _message_observations(scope: ast.AST) -> tuple[
    set[str], dict[str, int], dict[str, int], dict[str, int]
]:
    """Return message fields tied to parameters within one lexical scope."""
    parameter_names = {
        argument.arg
        for function in ast.walk(scope)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in function.args.args
        if argument.arg not in {"self", "cls"}
    }
    aliases: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(scope):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = _resolved_attribute_path(node.value, aliases)
            if value is None or value.split(".")[0] not in parameter_names:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and aliases.get(target.id) != value:
                    aliases[target.id] = value
                    changed = True

    observed_fields: set[str] = set()
    observed_field_lines: dict[str, int] = {}
    fault_code_fields: dict[str, int] = {}
    fault_type_fields: dict[str, int] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Attribute):
            path_value = _resolved_attribute_path(node, aliases)
            if path_value and path_value.split(".")[0] in parameter_names:
                field = ".".join(path_value.split(".")[1:])
                if field:
                    observed_fields.add(field)
                    observed_field_lines.setdefault(field, node.lineno)
        elif (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and len(node.comparators) == 1
        ):
            attribute = _resolved_attribute_path(node.left, aliases)
            try:
                compared = _literal(node.comparators[0], {})
            except ValueError:
                continue
            if attribute and compared == 0 and attribute.split(".")[0] in parameter_names:
                field = ".".join(attribute.split(".")[1:])
                if field.endswith("fault_code"):
                    fault_code_fields[field] = node.lineno
                elif field.endswith("fault_type.value"):
                    fault_type_fields[field] = node.lineno
    return (
        observed_fields,
        observed_field_lines,
        fault_code_fields,
        fault_type_fields,
    )


def _subscription_callback_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Lambda) and isinstance(node.body, ast.Call):
        return _call_name(node.body.func) or None
    return None


def _action_result_observation(
    scope: ast.AST, constants: dict[str, Any],
) -> tuple[str, int, int] | None:
    observations: set[tuple[str, int, int]] = set()
    for node in ast.walk(scope):
        if not (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
        ):
            continue
        attribute = _attribute_path(node.left)
        try:
            compared = _literal(node.comparators[0], constants)
        except ValueError:
            continue
        if attribute and "error" in attribute and isinstance(compared, int):
            parts = attribute.split(".")
            field = ".".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            observations.add((field, compared, node.lineno))
    if len(observations) == 1:
        return next(iter(observations))
    return None


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

    relative = path.relative_to(root)
    (
        observed_fields,
        observed_field_lines,
        fault_code_fields,
        fault_type_fields,
    ) = _message_observations(tree)
    ready_values: set[int] = set()
    ready_value_lines: dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
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
                        ready_value_lines.setdefault(resolved, node.lineno)
    function_observations: dict[
        tuple[str | None, str],
        tuple[set[str], dict[str, int], dict[str, int], dict[str, int]],
    ] = {}
    call_owners: dict[int, str | None] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_observations[(None, node.name)] = _message_observations(node)
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    call_owners[id(child)] = None
        elif isinstance(node, ast.ClassDef):
            for function in node.body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                function_observations[(node.name, function.name)] = (
                    _message_observations(function)
                )
                for child in ast.walk(function):
                    if isinstance(child, ast.Call):
                        call_owners[id(child)] = node.name
    subscription_interfaces = {
        call.args[0].id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and _call_name(call.func) == "create_subscription"
        and len(call.args) >= 3
        and isinstance(call.args[0], ast.Name)
    }
    allow_file_wide_subscription_facts = len(subscription_interfaces) == 1

    action_detail_candidates: dict[
        str, list[tuple[dict[str, Any], dict[str, dict[str, Any]]]]
    ] = {}
    arrival: dict[str, Any] | None = None
    for function in (item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))):
        defaults = _function_defaults(function)
        if "tol" in defaults and "settle" in defaults:
            arrival = {
                "arrival_tolerance_rad": defaults["tol"],
                "settle_window_s": defaults["settle"],
                "completion": ["terminal_result", "measured_arrival"],
                "execution_policy_status": "unconfirmed",
                "execution_policy_origin": "application_helper_default",
                "arrival_metric": "unverified_application_comparison",
                "settle_semantics": "unverified_application_behavior",
            }
        goal_calls = [
            item for item in ast.walk(function)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "Goal"
            and isinstance(item.func.value, ast.Name)
        ]
        goal_interfaces = {call.func.value.id for call in goal_calls}
        result_observation = (
            _action_result_observation(function, constants)
            if len(goal_interfaces) == 1 else None
        )
        for call in goal_calls:
            if isinstance(call.func, ast.Attribute) and call.func.attr == "Goal" and isinstance(call.func.value, ast.Name):
                interface_name = call.func.value.id
                details: dict[str, Any] = {"constants": {}, "dynamic_goal_fields": []}
                detail_sources: dict[str, dict[str, Any]] = {}
                for keyword in call.keywords:
                    if keyword.arg is None:
                        continue
                    try:
                        details["constants"][keyword.arg] = _literal(keyword.value, constants)
                        detail_sources["constants"] = _source(
                            relative, keyword.value.lineno,
                            "literal action Goal keyword",
                        )
                    except ValueError:
                        details["dynamic_goal_fields"].append(keyword.arg)
                        detail_sources["dynamic_goal_fields"] = _source(
                            relative, keyword.value.lineno,
                            "non-literal action Goal keyword",
                        )
                if len(details["dynamic_goal_fields"]) == 1:
                    details["target_field"] = details["dynamic_goal_fields"][0]
                    detail_sources["target_field"] = detail_sources["dynamic_goal_fields"]
                if "timeout" in defaults:
                    details["timeout_s"] = defaults["timeout"]
                    details["execution_policy_status"] = "unconfirmed"
                    details["execution_policy_origin"] = "python_function_default"
                    detail_sources["timeout_s"] = _source(
                        relative, function.lineno,
                        "Python function default; execution policy remains unconfirmed",
                    )
                if result_observation is not None:
                    result_field, result_code, result_line = result_observation
                    details["result_code_field"] = result_field
                    details["success_code"] = result_code
                    detail_sources["result_code_field"] = _source(
                        relative, result_line,
                        "action result field compared with integer success code",
                    )
                    detail_sources["success_code"] = detail_sources["result_code_field"]
                action_detail_candidates.setdefault(interface_name, []).append(
                    (details, detail_sources)
                )

    action_details: dict[str, dict[str, Any]] = {}
    action_detail_sources: dict[str, dict[str, dict[str, Any]]] = {}
    for interface_name, candidates in action_detail_candidates.items():
        merged: dict[str, Any] = {}
        merged_sources: dict[str, dict[str, Any]] = {}
        ordinary_keys = set.intersection(*(
            set(details) for details, _ in candidates
        )) - {"result_code_field", "success_code"}
        for key in ordinary_keys:
            values = {
                json.dumps(details[key], sort_keys=True)
                for details, _ in candidates
            }
            if len(values) == 1:
                merged[key] = candidates[0][0][key]
                if key in candidates[0][1]:
                    merged_sources[key] = candidates[0][1][key]
        result_pairs = {
            (details.get("result_code_field"), details.get("success_code"))
            for details, _ in candidates
            if "result_code_field" in details and "success_code" in details
        }
        if len(result_pairs) == 1 and all(
            "result_code_field" in details and "success_code" in details
            for details, _ in candidates
        ):
            result_field, success = next(iter(result_pairs))
            merged["result_code_field"] = result_field
            merged["success_code"] = success
            for key in ("result_code_field", "success_code"):
                if key in candidates[0][1]:
                    merged_sources[key] = candidates[0][1][key]
        action_details[interface_name] = merged
        action_detail_sources[interface_name] = merged_sources

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
            callback_name = _subscription_callback_name(call.args[2])
            callback_observation = function_observations.get(
                (call_owners.get(id(call)), callback_name or "")
            )
            if callback_observation and callback_observation[0]:
                (
                    subscription_fields,
                    subscription_field_lines,
                    subscription_fault_codes,
                    subscription_fault_types,
                ) = callback_observation
            elif allow_file_wide_subscription_facts:
                subscription_fields = observed_fields
                subscription_field_lines = observed_field_lines
                subscription_fault_codes = fault_code_fields
                subscription_fault_types = fault_type_fields
            else:
                subscription_fields = set()
                subscription_field_lines = {}
                subscription_fault_codes = {}
                subscription_fault_types = {}
            claims: dict[str, Any] = {
                "transport_operation": "subscribe",
                "transport_kind": "ros2_subscription",
                "endpoint": endpoint,
                "interface_type": interface_type,
            }
            sources = {
                "transport_operation": _source(
                    relative, call.lineno,
                    "rclpy.create_subscription -> subscribe",
                ),
                "transport_kind": _source(
                    relative, call.lineno,
                    "rclpy.create_subscription -> ros2_subscription",
                ),
                "endpoint": _source(
                    relative, call.lineno,
                    "statically resolve create_subscription endpoint argument",
                ),
                "interface_type": _source(
                    relative, call.lineno,
                    "resolve imported create_subscription message type",
                ),
            }
            positions = sorted(
                field for field in subscription_fields
                if "joint" in field and ("angle" in field or "position" in field)
            )
            modes = sorted(field for field in subscription_fields if "mode" in field)
            if len(positions) == 1:
                claims["positions_field"] = positions[0]
                sources["positions_field"] = _source(
                    relative, subscription_field_lines[positions[0]],
                    "message field consumed as measured joint positions",
                )
            if len(modes) == 1:
                claims["mode_field"] = modes[0]
                sources["mode_field"] = _source(
                    relative, subscription_field_lines[modes[0]],
                    "message field consumed as arm mode",
                )
            if ready_values and allow_file_wide_subscription_facts:
                claims["ready_values"] = sorted(ready_values)
                sources["ready_values"] = _source(
                    relative, min(ready_value_lines.values()),
                    "integer constant named as idle mode",
                )
            if len(subscription_fault_codes) == 1:
                field, line = next(iter(subscription_fault_codes.items()))
                claims["fault_code_field"] = field
                sources["fault_code_field"] = _source(
                    relative, line,
                    "message field compared with zero as numeric fault code",
                )
            if len(subscription_fault_types) == 1:
                field, line = next(iter(subscription_fault_types.items()))
                claims["fault_type_field"] = field
                sources["fault_type_field"] = _source(
                    relative, line,
                    "message field compared with zero as fault category",
                )
            records.append(_record(
                path, root, root_id, "ros2_subscription_usage", claims,
                "static_python_usage_only", claim_sources=sources,
            ))
        else:
            details = action_details.get(interface_name, {})
            detail_sources = action_detail_sources.get(interface_name, {})
            claims = {
                "transport_operation": "send_action_goal",
                "transport_kind": "ros2_action",
                "endpoint": endpoint,
                "interface_type": interface_type,
                **details,
            }
            sources = {
                "transport_operation": _source(
                    relative, call.lineno,
                    "rclpy.action.ActionClient -> send_action_goal",
                ),
                "transport_kind": _source(
                    relative, call.lineno,
                    "rclpy.action.ActionClient -> ros2_action",
                ),
                "endpoint": _source(
                    relative, call.lineno,
                    "statically resolve ActionClient endpoint argument",
                ),
                "interface_type": _source(
                    relative, call.lineno,
                    "resolve imported ActionClient action type",
                ),
                **detail_sources,
            }
            records.append(_record(
                path, root, root_id, "ros2_action_usage", claims,
                "static_python_usage_only", claim_sources=sources,
            ))
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
                        joint_list_line = next(
                            (index for index, raw in enumerate(text.splitlines(), 1) if "joint_list:" in raw),
                            1,
                        )
                        sources = {
                            "vendor_joint_order": _source(
                                path.relative_to(root), joint_list_line,
                                "ordered YAML joint_list",
                            ),
                            "joint_limits": _source(
                                path.relative_to(root),
                                next((index for index, raw in enumerate(text.splitlines(), 1) if "joint_soft_limit:" in raw), 1),
                                "joint_soft_limit values ordered by joint_list",
                            ),
                        }
                        if "radian" in text:
                            claims["unit"] = "radian"
                            sources["unit"] = _source(
                                path.relative_to(root),
                                next((index for index, raw in enumerate(text.splitlines(), 1) if "radian" in raw), 1),
                                "explicit radian marker in vendor configuration",
                            )
                        records.append(_record(
                            path, root, root_id, "robot_joint_configuration", claims,
                            "static_parameter_configuration_only", claim_sources=sources,
                        ))
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
                path_sources: dict[str, dict[str, Any]] = {}
                sections = text.split("---")
                top_level_lines = _field_lines(text, section=0)
                for claim_name in (
                    "field_paths", "goal_field_paths", "request_field_paths",
                ):
                    for field_path in claims.get(claim_name, ()):
                        top = field_path.split(".", 1)[0]
                        path_sources[field_path] = _source(
                            relative, top_level_lines.get(top, 1),
                            "expand ROS interface field declaration",
                        )
                if suffix in {".srv", ".action"} and len(sections) > 1:
                    result_lines = _field_lines(text, section=1)
                    for claim_name in ("response_field_paths", "result_field_paths"):
                        for field_path in claims.get(claim_name, ()):
                            top = field_path.split(".", 1)[0]
                            path_sources[field_path] = _source(
                                relative, result_lines.get(top, 1),
                                "expand ROS interface result field declaration",
                            )
                records.append(_record(
                    path, root, context.root_id, "ros2_interface_definition", claims,
                    "type_definition_only",
                    claim_sources={"interface_paths": path_sources},
                ))
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
