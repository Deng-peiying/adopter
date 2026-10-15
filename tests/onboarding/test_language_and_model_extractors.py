from __future__ import annotations

from pathlib import Path
import shutil

from cross_embodiment.onboarding.extractors.base import ScanContext
from cross_embodiment.onboarding.extractors.native import NativeExtractor
from cross_embodiment.onboarding.extractors.python import PythonExtractor
from cross_embodiment.onboarding.extractors.robot_model import RobotModelExtractor


def _context(root: Path) -> ScanContext:
    return ScanContext(root, "vendor", frozenset())


def test_python_extractor_uses_ast_without_importing_vendor_code(tmp_path: Path) -> None:
    marker = tmp_path / "IMPORTED"
    module = tmp_path / "vendor_sdk.py"
    module.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
        "class Arm:\n    def move(self, joints, speed=None):\n        return joints\n"
        "def connect(host: str):\n    pass\n"
    )
    evidence = PythonExtractor().scan_files(_context(tmp_path))
    assert not marker.exists()
    claim = evidence[0].claims
    assert claim["classes"] == [{"name": "Arm", "methods": [{"name": "move", "parameters": ["self", "joints", "speed"]}]}]
    assert {item["name"] for item in claim["functions"]} == {"connect"}


def test_native_extractor_reports_headers_missing_includes_and_elf_platform(tmp_path: Path) -> None:
    (tmp_path / "driver.hpp").write_text('#include "missing_vendor.hpp"\nvoid move_arm();\n')
    shutil.copy2("/bin/true", tmp_path / "libdriver.so")
    evidence = NativeExtractor().scan_files(_context(tmp_path))
    header = next(item for item in evidence if item.claim_type == "native_header")
    assert header.claims["missing_includes"] == ["missing_vendor.hpp"]
    binary = next(item for item in evidence if item.claim_type == "native_binary")
    assert binary.claims["format"] == "ELF"
    assert binary.claims["architecture"] in {"x86-64", "x86_64", "AMD x86-64"}
    assert "tool_status" in binary.claims


def test_urdf_extractor_reports_chain_as_model_evidence(tmp_path: Path) -> None:
    (tmp_path / "arm.urdf").write_text('''
<robot name="arm">
  <link name="base"/><link name="link1"/><link name="tip"/>
  <joint name="joint_a" type="revolute">
    <parent link="base"/><child link="link1"/><axis xyz="0 0 1"/>
    <limit lower="-1.0" upper="1.0" velocity="2.0" effort="4.0"/>
  </joint>
  <joint name="fixed_tip" type="fixed"><parent link="link1"/><child link="tip"/></joint>
  <link name="visual"><visual><geometry><mesh filename="package://arm/mesh.stl"/></geometry></visual></link>
</robot>''')
    evidence = RobotModelExtractor().scan_files(_context(tmp_path))
    claim = evidence[0].claims
    assert claim["format"] == "urdf"
    assert claim["joint_order"] == ["joint_a"]
    assert claim["joints"][0]["axis"] == [0.0, 0.0, 1.0]
    assert claim["joints"][0]["unit"] == "radian"
    assert claim["base_candidates"] == ["base", "visual"]
    assert claim["tip_candidates"] == ["tip", "visual"]
    assert claim["mesh_references"] == ["package://arm/mesh.stl"]
    assert evidence[0].confidence_boundary == "model_definition_only"


def test_xacro_unresolved_requirements_are_explicit(tmp_path: Path) -> None:
    (tmp_path / "arm.xacro").write_text('<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="${robot_name}"><xacro:include filename="$(find vendor)/part.xacro"/></robot>')
    claim = RobotModelExtractor().scan_files(_context(tmp_path))[0].claims
    assert claim["format"] == "xacro"
    assert "robot_name" in claim["unresolved_requirements"]
    assert "$(find vendor)/part.xacro" in claim["includes"]
