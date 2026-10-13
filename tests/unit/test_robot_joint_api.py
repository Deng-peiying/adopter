import unittest
from datetime import datetime, timezone

from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.protocol.types import Action, ActionSpec, Command, CommandResult, RobotState, SafetyState
from cross_embodiment.sdk.robot import Robot


class JointBackend:
    def __init__(self):
        self.sent = []
        self.control_enabled = True
        self.dry_run = False

    def get_state(self):
        return RobotState(
            timestamp=datetime.now(timezone.utc),
            joint_positions={f"arm.right.joint.{i}": 0.0 for i in range(7)},
            safety=SafetyState(enabled=True),
        )

    def send_command(self, command):
        self.sent.append(command)
        return CommandResult(True, status="succeeded", dispatched=True)

    def get_joint_state(self, device_id):
        from cross_embodiment.protocol.types import JointState

        return JointState(
            device_id=device_id,
            positions={f"arm.right.joint.{i}": 0.0 for i in range(7)},
            source_timestamp=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
            status="ready",
        )


class RobotJointApiTests(unittest.TestCase):
    def setUp(self):
        self.backend = JointBackend()
        self.manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [
                {"canonical_name": f"arm.right.joint.{i}", "limits": [-1.0, 1.0]}
                for i in range(7)
            ]}],
            control={"supported_modes": [{"type": "joint_position", "target": "right_arm", "dimension": 7}]},
            safety={"requires_enable": True},
        )
        self.robot = Robot(self.backend, self.manifest)

    def test_public_state_and_move_use_canonical_names(self):
        state = self.robot.get_joint_state("right_arm")
        self.assertEqual(state.status, "ready")
        target = {f"arm.right.joint.{i}": float(i) / 10 for i in reversed(range(7))}
        result = self.robot.move_joints("right_arm", target)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(self.backend.sent), 1)
        self.assertEqual(self.backend.sent[0].payload["positions"], target)

    def test_public_move_rejects_missing_or_extra_names(self):
        target = {f"arm.right.joint.{i}": 0.0 for i in range(7)}
        for invalid in ({k: v for k, v in target.items() if k != "arm.right.joint.6"},
                        {**target, "unknown": 0.0}):
            with self.assertRaises(ValueError):
                self.robot.move_joints("right_arm", invalid)
        self.assertEqual(self.backend.sent, [])

    def test_raw_command_cannot_bypass_public_safety(self):
        with self.assertRaises(TypeError):
            self.robot.command(Command("right_arm", "joint_position", {"positions": [0.0] * 7}))
        self.assertEqual(self.backend.sent, [])

    def test_typed_action_cannot_bypass_exact_joint_names(self):
        action = Action(ActionSpec("joint_position", "right_arm", dimension=7),
                        {"positions": {**{f"arm.right.joint.{i}": 0.0 for i in range(6)},
                                       "unknown": 0.0}})
        with self.assertRaises(ValueError):
            self.robot.command(action)
        self.assertEqual(self.backend.sent, [])


if __name__ == "__main__":
    unittest.main()
