import unittest
from datetime import datetime, timezone

import cross_embodiment.sdk as sdk
from cross_embodiment.errors import SafetyViolation
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.protocol.types import CommandResult, JointState, RobotState, SafetyState
from cross_embodiment.sdk.quadruped import QuadrupedRobot


class Adapter:
    control_enabled = True
    dry_run = False

    def __init__(self):
        self.commands = []

    def configure(self): pass
    def connect(self): pass
    def disconnect(self): pass
    def enable(self): pass
    def disable(self): pass
    def capabilities(self): return {}
    def supports_action(self, action_type, device_id): return action_type in {"base_motion_input", "quadruped_stand"}
    def get_state(self):
        return RobotState(timestamp=datetime.now(timezone.utc), safety=SafetyState(enabled=True))
    def send_command(self, command):
        self.commands.append(command)
        return CommandResult(True, status="accepted", dispatched=True)


def quadruped_manifest():
    return EmbodimentManifest(
        schema_version="embodiment/v0.2",
        embodiment={"type": "quadruped", "profile": "quadruped"},
        devices=[{"id": "base", "type": "mobile_base", "capabilities": ["base_motion_input", "quadruped_stand"]}],
        control={"supported_modes": [
            {"type": "base_motion_input", "target": "base", "dimension": 3,
             "bounds": [[-1.0, 1.0], [-1.0, 1.0], [-1.0, 1.0]]},
            {"type": "quadruped_stand", "target": "base"},
        ]},
        safety={"requires_enable": True},
    )


class RobotProfileTests(unittest.TestCase):
    def test_sdk_exports_shared_and_embodiment_specific_robot_profiles(self):
        for name in ("RobotBase", "ManipulatorRobot", "QuadrupedRobot"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(sdk, name), f"missing SDK class {name}")

    def test_joint_convenience_is_only_on_manipulator_profile(self):
        self.assertTrue(hasattr(sdk.ManipulatorRobot, "move_joints"))
        self.assertFalse(hasattr(sdk.RobotBase, "move_joints"))
        self.assertFalse(hasattr(sdk.QuadrupedRobot, "move_joints"))

    def test_profile_is_required_and_not_guessed_from_vendor_type(self):
        from cross_embodiment.sdk.factory import facade_for_manifest
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"type": "arm"},
            devices=[],
        )
        with self.assertRaises(ValueError):
            facade_for_manifest(manifest)

    def test_quadruped_maps_normalized_base_motion(self):
        adapter = Adapter()
        robot = QuadrupedRobot(adapter, quadruped_manifest())
        result = robot.move_base_input("base", x=0.2, y=-0.1, yaw=0.3)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(adapter.commands), 1)
        command = adapter.commands[0]
        self.assertEqual(command.mode, "base_motion_input")
        self.assertEqual(command.payload, {"x": 0.2, "y": -0.1, "yaw": 0.3})

    def test_quadruped_stand_maps_to_vendor_independent_stand_action(self):
        adapter = Adapter()
        robot = QuadrupedRobot(adapter, quadruped_manifest())
        result = robot.stand("base")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(adapter.commands), 1)
        self.assertEqual(adapter.commands[0].mode, "quadruped_stand")
        self.assertEqual(adapter.commands[0].payload, {})

    def test_quadruped_rejects_input_outside_normalized_range(self):
        adapter = Adapter()
        robot = QuadrupedRobot(adapter, quadruped_manifest())
        with self.assertRaises(SafetyViolation):
            robot.move_base_input("base", x=1.01, y=0.0, yaw=0.0)
        self.assertEqual(adapter.commands, [])

    def test_quadruped_exposes_declared_measured_joint_state(self):
        adapter = Adapter()
        expected = JointState("legs", {"leg.left_front.hip_x": 0.2}, None,
                              datetime.now(timezone.utc), "measured")
        adapter.get_joint_state = lambda device_id: expected
        manifest = quadruped_manifest()
        manifest.devices.append({"id": "legs", "type": "leg_joints", "capabilities": ["joint_state"]})
        robot = QuadrupedRobot(adapter, manifest)
        self.assertIs(robot.get_joint_state("legs"), expected)


if __name__ == "__main__":
    unittest.main()
