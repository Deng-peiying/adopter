from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path

from ..models import EvidenceLevel, EvidenceRecord
from .base import ScanContext


def _parameters(arguments: ast.arguments) -> list[str]:
    return [item.arg for item in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)]


class PythonExtractor:
    def scan_files(self, context: ScanContext) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for path in sorted(context.root.rglob("*.py")):
            relative = path.relative_to(context.root)
            if path.is_symlink() or any(part in context.ignored_components for part in relative.parts):
                continue
            content = path.read_bytes()
            tree = ast.parse(content, filename=str(relative))
            classes: list[dict[str, object]] = []
            functions: list[dict[str, object]] = []
            imports: list[str] = []
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append({"name": node.name, "parameters": _parameters(node.args)})
                elif isinstance(node, ast.ClassDef):
                    methods = [
                        {"name": child.name, "parameters": _parameters(child.args)}
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    classes.append({"name": node.name, "methods": methods})
            digest = sha256(content).hexdigest()
            records.append(EvidenceRecord(
                evidence_id=f"evidence:python:{context.root_id}:{relative.as_posix()}:{digest[:12]}",
                source_asset_ids=(f"asset:{context.root_id}:{relative.as_posix()}:{digest[:12]}",),
                source_path=relative,
                claim_type="python_module",
                claims={"module": relative.with_suffix("").as_posix().replace("/", "."), "classes": classes, "functions": functions, "imports": sorted(imports)},
                provenance={"extractor": "python-ast", "source_sha256": digest},
                confidence_boundary="static_ast_only_not_imported",
                level=EvidenceLevel.DECLARED,
            ))
        return records
