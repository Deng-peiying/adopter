from __future__ import annotations

from ..errors import SafetyViolation
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Action, Command


class ActionMapper:
    def map(self, action: Action, manifest: EmbodimentManifest) -> list[Command]:
        values = action.values
        if hasattr(values, "__dataclass_fields__"):
            from dataclasses import asdict

            values = asdict(values)
        if action.spec.type == "ee_delta":
            translation = tuple(float(value) for value in values["translation"])
            rotation = tuple(float(value) for value in values.get("rotation", (0, 0, 0)))
            commands = [Command(action.spec.target, "ee_delta", {"translation": translation, "rotation": rotation}, action.spec.frame)]
            if "gripper" in values:
                commands.append(Command(values.get("gripper_target", "right_gripper"), "gripper_position", {"value": float(values["gripper"])}, action.spec.frame))
            return commands
        if action.spec.type in ("joint_position", "bimanual_joint_position"):
            positions = values.get("positions") if isinstance(values, dict) else values
            if isinstance(positions, dict):
                device = manifest.device(action.spec.target)
                joints = [] if device is None else device.get("joints", [])
                expected = {joint.get("canonical_name", joint.get("name")) for joint in joints}
                if expected and set(positions) != expected:
                    raise SafetyViolation(f"Joint target must contain exactly {sorted(expected)}")
                normalized = {str(name): float(value) for name, value in positions.items()}
            elif isinstance(positions, (list, tuple)):
                normalized = tuple(float(value) for value in positions)
            else:
                raise SafetyViolation("Joint position action must contain a sequence or named joint mapping")
            return [Command(action.spec.target, action.spec.type, {"positions": normalized}, action.spec.frame)]
        if action.spec.type == "cartesian_pose":
            pose = values.get("pose", values)
            if hasattr(pose, "__dataclass_fields__"):
                from dataclasses import asdict

                pose = asdict(pose)
            if not isinstance(pose, dict) or "position" not in pose or "quaternion_xyzw" not in pose:
                raise SafetyViolation("Cartesian pose action requires position and quaternion_xyzw")
            position = tuple(float(value) for value in pose["position"])
            quaternion = tuple(float(value) for value in pose["quaternion_xyzw"])
            if len(position) != 3 or len(quaternion) != 4:
                raise SafetyViolation("Cartesian pose must have 3 position and 4 quaternion values")
            frame = pose.get("frame", action.spec.frame)
            return [Command(action.spec.target, "cartesian_pose", {"position": position, "quaternion_xyzw": quaternion}, frame)]
        if action.spec.type == "base_motion_input":
            if not isinstance(values, dict) or set(values) != {"x", "y", "yaw"}:
                raise SafetyViolation("Base motion input requires exactly x, y, and yaw ratios")
            axes = {axis: float(values[axis]) for axis in ("x", "y", "yaw")}
            return [Command(action.spec.target, "base_motion_input", axes, action.spec.frame)]
        if action.spec.type == "quadruped_stand":
            if values not in ({}, None):
                raise SafetyViolation("Quadruped stand action takes no parameters")
            return [Command(action.spec.target, "quadruped_stand", {}, action.spec.frame)]
        raise SafetyViolation(f"Unsupported action mode: {action.spec.type}")
