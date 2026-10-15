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


def _record(path: Path, root: Path, claim_type: str, claims: dict[str, Any], boundary: str, level: EvidenceLevel = EvidenceLevel.DECLARED) -> EvidenceRecord:
    relative = path.relative_to(root)
    digest = sha256(path.read_bytes()).hexdigest()
    claim_digest = sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest()[:12]
    return EvidenceRecord(
        evidence_id=f"evidence:ros2:{relative.as_posix()}:{claim_digest}",
        source_asset_ids=(f"asset:{relative.as_posix()}:{digest[:12]}",),
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


class Ros2Extractor:
    def scan_files(self, context: ScanContext) -> list[EvidenceRecord]:
        root = context.root.resolve()
        records: list[EvidenceRecord] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if any(part in context.ignored_components for part in relative.parts):
                continue
            suffix = path.suffix.lower()
            if path.name == "package.xml":
                tree = ET.parse(path).getroot()
                records.append(_record(path, root, "ros2_package", {
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
                elif suffix == ".srv":
                    claims["request_fields"] = _fields(parts[0])
                    claims["response_fields"] = _fields(parts[1]) if len(parts) > 1 else []
                else:
                    claims["goal_fields"] = _fields(parts[0])
                    claims["result_fields"] = _fields(parts[1]) if len(parts) > 1 else []
                    claims["feedback_fields"] = _fields(parts[2]) if len(parts) > 2 else []
                records.append(_record(path, root, "ros2_interface_definition", claims, "type_definition_only"))
            elif suffix == ".idl":
                records.append(_record(path, root, "ros2_interface_definition", {
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
                records.append(_record(path, root, "ros2_launch_definition", {
                    "launch_file": relative.as_posix(),
                    "arguments": arguments,
                    "nodes": nodes,
                    "namespace_candidates": namespaces,
                }, "static_launch_syntax_only"))
            elif suffix in {".so", ".bin"} or ".so." in path.name:
                content = path.read_bytes()[:4 * 1024 * 1024]
                for token in sorted(set(re.findall(rb"/[A-Za-z0-9_/-]+_(?:action|state|service)", content))):
                    value = token.decode("ascii", errors="ignore")
                    records.append(_record(path, root, "ros2_endpoint_candidate", {
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
