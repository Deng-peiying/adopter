from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import shutil
import subprocess

from ..models import EvidenceLevel, EvidenceRecord
from .base import ScanContext


_HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx"}


def _run(tool: str, arguments: list[str]) -> tuple[str, str]:
    executable = shutil.which(tool)
    if not executable:
        return "unavailable", ""
    completed = subprocess.run([executable, *arguments], capture_output=True, text=True)
    return ("ok" if completed.returncode == 0 else f"exit_{completed.returncode}", completed.stdout + completed.stderr)


def _evidence(path: Path, root: Path, kind: str, claims: dict[str, object], boundary: str) -> EvidenceRecord:
    relative = path.relative_to(root)
    digest = sha256(path.read_bytes()).hexdigest()
    return EvidenceRecord(
        evidence_id=f"evidence:native:{relative.as_posix()}:{digest[:12]}",
        source_asset_ids=(f"asset:{relative.as_posix()}:{digest[:12]}",),
        source_path=relative, claim_type=kind, claims=claims,
        provenance={"extractor": "native-static", "source_sha256": digest},
        confidence_boundary=boundary, level=EvidenceLevel.OBSERVED,
    )


class NativeExtractor:
    def scan_files(self, context: ScanContext) -> list[EvidenceRecord]:
        root = context.root.resolve()
        records: list[EvidenceRecord] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if any(part in context.ignored_components for part in relative.parts):
                continue
            if path.suffix.lower() in _HEADER_SUFFIXES:
                text = path.read_text(encoding="utf-8", errors="replace")
                includes = re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', text, re.MULTILINE)
                missing = [name for name in includes if not (path.parent / name).exists() and "/" not in name]
                symbols = re.findall(r"\b(?:void|bool|int|float|double|class|struct)\s+([A-Za-z_]\w*)", text)
                records.append(_evidence(path, root, "native_header", {"includes": includes, "missing_includes": sorted(missing), "declared_symbols": sorted(set(symbols))}, "header_declaration_only"))
                continue
            magic = path.read_bytes()[:4]
            if magic != b"\x7fELF":
                continue
            file_status, file_output = _run("file", ["-b", str(path)])
            readelf_status, readelf_output = _run("readelf", ["-d", str(path)])
            nm_status, nm_output = _run("nm", ["-D", "-C", str(path)])
            architecture = "unknown"
            for candidate in ("x86-64", "AArch64", "ARM", "Intel 80386", "RISC-V"):
                if candidate in file_output:
                    architecture = candidate
                    break
            dependencies = re.findall(r"Shared library: \[([^]]+)\]", readelf_output)
            symbols = []
            for line in nm_output.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    symbols.append(" ".join(parts[2:]))
            records.append(_evidence(path, root, "native_binary", {
                "format": "ELF", "architecture": architecture,
                "dependencies": sorted(set(dependencies)),
                "exported_symbols": sorted(set(symbols)),
                "tool_status": {"file": file_status, "readelf": readelf_status, "nm": nm_status},
            }, "binary_metadata_only"))
        return records
