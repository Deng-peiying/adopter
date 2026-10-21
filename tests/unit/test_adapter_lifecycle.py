import unittest

from cross_embodiment.adapter.protocol import RobotAdapter
from cross_embodiment.adapter.mock import MockAdapter
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.sdk.robot import Lifecycle, Robot


class Adapter:
    def __init__(self):
        self.calls = []

    def configure(self):
        self.calls.append("configure")

    def connect(self):
        self.calls.append("connect")

    def enable(self):
        self.calls.append("enable")

    def disable(self):
        self.calls.append("disable")

    def disconnect(self):
        self.calls.append("disconnect")


class AdapterLifecycleTests(unittest.TestCase):
    def test_robot_initialization_configures_without_connecting(self):
        adapter = Adapter()
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={}
        )

        robot = Robot(adapter, manifest)

        self.assertEqual(adapter.calls, ["configure"])
        robot.close()
        self.assertEqual(adapter.calls, ["configure"])

    def test_robot_connect_does_not_repeat_initial_configuration_or_enable(self):
        adapter = Adapter()
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={}
        )
        robot = Robot(adapter, manifest)
        self.assertEqual(adapter.calls, ["configure"])

        self.assertIs(robot.connect(), robot)
        robot.connect()
        self.assertEqual(adapter.calls, ["configure", "connect"])

        robot.close()
        robot.connect()
        robot.close()
        self.assertEqual(
            adapter.calls,
            ["configure", "connect", "disconnect", "connect", "disconnect"],
        )

    def test_configuration_error_aborts_robot_construction(self):
        class InvalidAdapter(Adapter):
            def configure(self):
                super().configure()
                raise ValueError("Invalid backend configuration")

        adapter = InvalidAdapter()
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={}
        )

        with self.assertRaisesRegex(ValueError, "Invalid backend configuration"):
            Robot(adapter, manifest)
        self.assertEqual(adapter.calls, ["configure"])

    def test_robot_adapter_protocol_declares_robot_runtime_surface(self):
        for name in (
            "capabilities",
            "supports_action",
            "get_joint_state",
            "get_state",
            "send_command",
        ):
            self.assertTrue(hasattr(RobotAdapter, name), name)

    def test_mock_joint_state_is_derived_from_manifest_devices(self):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"type": "test"},
            devices=[{
                "id": "tool_axis",
                "type": "arm",
                "joints": [
                    {"canonical_name": f"tool.joint.{index}"}
                    for index in range(3)
                ],
            }],
        )
        adapter = MockAdapter(manifest)
        adapter.connect()
        adapter.enable()

        state = adapter.get_joint_state("tool_axis")

        self.assertEqual(state.status, "ready")
        self.assertEqual(
            state.positions,
            {f"tool.joint.{index}": 0.0 for index in range(3)},
        )

    def test_lifecycle_configures_and_stops_idempotently(self):
        adapter = Adapter()
        lifecycle = Lifecycle(adapter)
        lifecycle.configure()
        lifecycle.connect()
        lifecycle.enable()
        lifecycle.stop()
        lifecycle.stop()
        self.assertEqual(adapter.calls, ["configure", "connect", "enable", "disable", "disconnect"])


if __name__ == "__main__":
    unittest.main()
