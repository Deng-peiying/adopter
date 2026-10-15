from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ..models import EvidenceLevel, EvidenceRecord
from .base import ScanContext


class RobotModelExtractor:
    def scan_files(self, context: ScanContext) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for path in sorted(context.root.rglob("*")):
            if path.suffix.lower() not in {".urdf", ".xacro"} or not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(context.root)
            text = path.read_text(encoding="utf-8", errors="replace")
            root = ET.fromstring(text)
            links = [node.attrib["name"] for node in root.findall("link") if "name" in node.attrib]
            joints: list[dict[str, object]] = []
            parents: set[str] = set()
            children: set[str] = set()
            for node in root.findall("joint"):
                parent = node.find("parent")
                child = node.find("child")
                if parent is not None and parent.get("link"):
                    parents.add(parent.get("link", ""))
                if child is not None and child.get("link"):
                    children.add(child.get("link", ""))
                if node.get("type") == "fixed":
                    continue
                axis = node.find("axis")
                limit = node.find("limit")
                joints.append({
                    "name": node.get("name"), "type": node.get("type"),
                    "axis": [float(v) for v in (axis.get("xyz", "1 0 0") if axis is not None else "1 0 0").split()],
                    "limits": {key: float(value) for key, value in (limit.attrib.items() if limit is not None else [])},
                    "unit": "radian" if node.get("type") in {"revolute", "continuous"} else "meter",
                })
            meshes = sorted({node.get("filename", "") for node in root.findall(".//mesh") if node.get("filename")})
            includes = sorted({node.get("filename", "") for node in root.iter() if node.tag.endswith("include") and node.get("filename")})
            unresolved = sorted(set(re.findall(r"\$\{([^}]+)\}", text)))
            digest = sha256(path.read_bytes()).hexdigest()
            records.append(EvidenceRecord(
                evidence_id=f"evidence:model:{context.root_id}:{relative.as_posix()}:{digest[:12]}",
                source_asset_ids=(f"asset:{context.root_id}:{relative.as_posix()}:{digest[:12]}",), source_path=relative,
                claim_type="robot_model",
                claims={"format": path.suffix.lower()[1:], "name": root.get("name"), "joints": joints,
                        "joint_order": [item["name"] for item in joints],
                        "base_candidates": sorted(set(links) - children), "tip_candidates": sorted(set(links) - parents),
                        "mesh_references": meshes, "includes": includes, "unresolved_requirements": unresolved},
                provenance={"extractor": "robot-model-xml", "source_sha256": digest},
                confidence_boundary="model_definition_only", level=EvidenceLevel.DECLARED,
            ))
        return records
