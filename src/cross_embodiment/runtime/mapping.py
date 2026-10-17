from __future__ import annotations

from ..errors import SafetyViolation
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Action, Command


class ActionMapper:
    def map(self, action: Action, manifest: EmbodimentManifest) -> list[Command]:
        values = action.values
        if action.spec.type == "ee_delta":
            translation = tuple(float(value) for value in values["translation"])
            rotation = tuple(float(value) for value in values.get("rotation", (0, 0, 0)))
            commands = [Command(action.spec.target, "ee_delta", {"translation": translation, "rotation": rotation}, action.spec.frame)]
            if "gripper" in values:
                commands.append(Command(values.get("gripper_target", "right_gripper"), "gripper_position", {"value": float(values["gripper"])}, action.spec.frame))
            return commands
        if action.spec.type in ("joint_position", "bimanual_joint_position"):
            positions = values.get("positions") if isinstance(values, dict) else values
            if not isinstance(positions, (list, tuple)):
                raise SafetyViolation("Joint position action must contain a sequence")
            return [Command(action.spec.target, action.spec.type, {"positions": tuple(float(value) for value in positions)}, action.spec.frame)]
        raise SafetyViolation(f"Unsupported action mode: {action.spec.type}")
