from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..errors import DependencyError, PackageError
from ..hardware.manifest import load_manifest
from ..package.manifest import HardwarePackage
from ..protocol.types import Pose
from .types import IKResult, KinematicChain, KinematicSemantics


def _require_kdl():
    try:
        import PyKDL  # type: ignore
    except ImportError as exc:
        raise DependencyError(
            "KDL kinematics requires PyKDL (Ubuntu package python3-pykdl)"
        ) from exc
    return PyKDL


def _vector(text: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if text is None:
        return default
    values = tuple(float(value) for value in text.split())
    if len(values) != 3:
        raise PackageError(f"Expected three URDF values, got: {text}")
    return values


def _read_semantics(path: Path) -> KinematicSemantics:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PackageError(f"Kinematic semantics root must be a mapping: {path}")
    units = data.get("units") or {}
    joints = data.get("joints") or []
    canonical = tuple(str(item["canonical_name"]) for item in joints)
    model = tuple(str(item["model_name"]) for item in joints)
    if not canonical or len(canonical) != len(model):
        raise PackageError("Kinematic semantics requires paired canonical/model joints")
    if len(set(canonical)) != len(canonical) or len(set(model)) != len(model):
        raise PackageError("Kinematic semantics joint names must be unique")
    if units.get("length") != "metre" or units.get("angle") != "radian":
        raise PackageError("Kinematic semantics requires metre/radian units")
    return KinematicSemantics(
        device_id=str(data["device_id"]),
        base_link=str(data["base_link"]),
        tip_link=str(data["tip_link"]),
        canonical_joints=canonical,
        model_joints=model,
        length_unit="metre",
        angle_unit="radian",
    )


def _urdf_joint_chain(root: ET.Element, base_link: str, tip_link: str) -> list[ET.Element]:
    joints = {joint.attrib["name"]: joint for joint in root.findall("joint")}
    child_to_joint = {
        joint.find("child").attrib["link"]: joint
        for joint in joints.values()
        if joint.find("child") is not None
    }
    result: list[ET.Element] = []
    link = tip_link
    visited: set[str] = set()
    while link != base_link:
        if link in visited:
            raise PackageError(f"URDF contains a cycle at link {link}")
        visited.add(link)
        joint = child_to_joint.get(link)
        if joint is None:
            raise PackageError(f"No URDF chain from {base_link} to {tip_link}; stopped at {link}")
        result.append(joint)
        parent = joint.find("parent")
        if parent is None:
            raise PackageError(f"URDF joint {joint.attrib['name']} has no parent link")
        link = parent.attrib["link"]
    result.reverse()
    return result


def _kdl_frame(kdl: Any, origin: ET.Element | None):
    xyz = _vector(origin.attrib.get("xyz") if origin is not None else None, (0.0, 0.0, 0.0))
    rpy = _vector(origin.attrib.get("rpy") if origin is not None else None, (0.0, 0.0, 0.0))
    return kdl.Frame(kdl.Rotation.RPY(*rpy), kdl.Vector(*xyz))


def _build_kdl_chain(kdl: Any, joints: list[ET.Element]):
    chain = kdl.Chain()
    model_joint_names: list[str] = []
    for element in joints:
        name = element.attrib["name"]
        kind = element.attrib.get("type")
        origin = _kdl_frame(kdl, element.find("origin"))
        child = element.find("child")
        if child is None:
            raise PackageError(f"URDF joint {name} has no child link")
        if kind == "fixed":
            joint = kdl.Joint(name, kdl.Joint.Fixed)
        elif kind in {"revolute", "continuous"}:
            axis_element = element.find("axis")
            axis = _vector(
                axis_element.attrib.get("xyz") if axis_element is not None else None,
                (1.0, 0.0, 0.0),
            )
            local_axis = kdl.Vector(*axis)
            parent_axis = origin.M * local_axis
            joint = kdl.Joint(name, origin.p, parent_axis, kdl.Joint.RotAxis)
            model_joint_names.append(name)
        else:
            raise PackageError(f"Unsupported URDF joint type for {name}: {kind}")
        chain.addSegment(kdl.Segment(child.attrib["link"], joint, origin))
    return chain, tuple(model_joint_names)


def _manifest_limits(package: HardwarePackage, semantics: KinematicSemantics) -> tuple[tuple[float, float], ...]:
    if not package.embodiment_manifest:
        raise PackageError("Hardware Package does not declare an embodiment manifest")
    manifest = load_manifest(package.root / package.embodiment_manifest)
    device = manifest.device(semantics.device_id)
    by_name = {joint["canonical_name"]: joint for joint in device["joints"]}
    limits: list[tuple[float, float]] = []
    for name in semantics.canonical_joints:
        joint = by_name.get(name)
        if joint is None or "limits" not in joint:
            raise PackageError(f"Missing execution limits for canonical joint {name}")
        lower, upper = joint["limits"]
        limits.append((float(lower), float(upper)))
    return tuple(limits)


def load_kdl_chain(
    package: HardwarePackage,
    *,
    semantics: KinematicSemantics | None = None,
) -> KinematicChain:
    kdl = _require_kdl()
    model_path = package.resolve_asset_path("kinematic_model", "urdf")
    semantics_path = package.resolve_asset_path("kinematic_semantics", "yaml")
    declared = semantics or _read_semantics(semantics_path)
    root = ET.parse(model_path).getroot()
    links = {link.attrib["name"] for link in root.findall("link")}
    if declared.base_link not in links or declared.tip_link not in links:
        raise PackageError(
            f"Kinematic frames are absent from URDF: {declared.base_link} -> {declared.tip_link}"
        )
    elements = _urdf_joint_chain(root, declared.base_link, declared.tip_link)
    backend, model_joint_names = _build_kdl_chain(kdl, elements)
    if model_joint_names != declared.model_joints:
        missing = [name for name in declared.model_joints if name not in model_joint_names]
        raise PackageError(
            "Kinematic semantics model joints do not match the URDF chain"
            + (f"; missing: {', '.join(missing)}" if missing else "")
        )
    if backend.getNrOfJoints() != len(declared.canonical_joints):
        raise PackageError("Canonical joint count does not match the KDL chain")
    return KinematicChain(
        semantics=declared,
        model_digest=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        joint_limits=_manifest_limits(package, declared),
        backend=backend,
    )


def _ordered_values(chain: KinematicChain, positions: Mapping[str, float]) -> tuple[float, ...]:
    expected = set(chain.canonical_joints)
    actual = set(positions)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PackageError(f"Joint positions do not match chain; missing={missing}, extra={extra}")
    values = tuple(float(positions[name]) for name in chain.canonical_joints)
    if not all(math.isfinite(value) for value in values):
        raise PackageError("Joint positions must be finite")
    return values


def _pose_to_frame(kdl: Any, pose: Pose):
    x, y, z, w = pose.quaternion_xyzw
    return kdl.Frame(kdl.Rotation.Quaternion(x, y, z, w), kdl.Vector(*pose.position))


def _validate_pose(pose: Pose) -> None:
    if len(pose.position) != 3 or len(pose.quaternion_xyzw) != 4:
        raise PackageError("Pose requires three position and four quaternion values")
    values = tuple(pose.position) + tuple(pose.quaternion_xyzw)
    if not all(math.isfinite(value) for value in values):
        raise PackageError("Pose values must be finite")
    quaternion_norm = math.sqrt(sum(value * value for value in pose.quaternion_xyzw))
    if not math.isclose(quaternion_norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        raise PackageError("Pose quaternion must have unit length")


def _frame_to_pose(frame: Any, reference_frame: str) -> Pose:
    x, y, z, w = frame.M.GetQuaternion()
    return Pose(
        position=(float(frame.p.x()), float(frame.p.y()), float(frame.p.z())),
        quaternion_xyzw=(float(x), float(y), float(z), float(w)),
        frame=reference_frame,
    )


def forward_kinematics(chain: KinematicChain, positions: Mapping[str, float]) -> Pose:
    kdl = _require_kdl()
    values = _ordered_values(chain, positions)
    joints = kdl.JntArray(chain.joint_count)
    for index, value in enumerate(values):
        joints[index] = value
    frame = kdl.Frame()
    code = kdl.ChainFkSolverPos_recursive(chain.backend).JntToCart(joints, frame)
    if code < 0:
        raise PackageError(f"KDL forward kinematics failed with code {code}")
    return _frame_to_pose(frame, chain.base_link)


def _pose_errors(actual: Pose, target: Pose) -> tuple[float, float]:
    position = math.sqrt(sum((a - b) ** 2 for a, b in zip(actual.position, target.position)))
    dot = abs(sum(a * b for a, b in zip(actual.quaternion_xyzw, target.quaternion_xyzw)))
    orientation = 2.0 * math.acos(max(-1.0, min(1.0, dot)))
    return position, orientation


def solve_inverse_kinematics(
    chain: KinematicChain,
    target: Pose,
    seed: Mapping[str, float],
    *,
    max_iterations: int = 200,
    tolerance: float = 1e-8,
) -> IKResult:
    _validate_pose(target)
    if target.frame != chain.base_link:
        raise PackageError(
            f"IK target frame must be {chain.base_link}, received {target.frame}"
        )
    kdl = _require_kdl()
    seed_values = _ordered_values(chain, seed)
    lower = kdl.JntArray(chain.joint_count)
    upper = kdl.JntArray(chain.joint_count)
    initial = kdl.JntArray(chain.joint_count)
    result = kdl.JntArray(chain.joint_count)
    for index, (value, bounds) in enumerate(zip(seed_values, chain.joint_limits)):
        initial[index] = value
        lower[index], upper[index] = bounds
    fk_solver = kdl.ChainFkSolverPos_recursive(chain.backend)
    velocity_solver = kdl.ChainIkSolverVel_pinv(chain.backend)
    solver = kdl.ChainIkSolverPos_NR_JL(
        chain.backend,
        lower,
        upper,
        fk_solver,
        velocity_solver,
        max_iterations,
        tolerance,
    )
    code = int(solver.CartToJnt(initial, _pose_to_frame(kdl, target), result))
    if code < 0:
        return IKResult(
            success=False,
            positions={},
            position_error_m=math.inf,
            orientation_error_rad=math.inf,
            solver_code=code,
            message=f"KDL inverse kinematics did not converge (code {code})",
        )
    positions = {
        name: float(result[index]) for index, name in enumerate(chain.canonical_joints)
    }
    solved_pose = forward_kinematics(chain, positions)
    position_error, orientation_error = _pose_errors(solved_pose, target)
    return IKResult(
        success=True,
        positions=positions,
        position_error_m=position_error,
        orientation_error_rad=orientation_error,
        solver_code=code,
        message="KDL inverse kinematics converged",
    )
