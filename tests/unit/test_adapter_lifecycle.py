import unittest

from cross_embodiment.adapter.base import RobotAdapter
from cross_embodiment.adapter.mock import MockAdapter
from cross_embodiment.driver.ros2_mapped import MappedRos2Adapter
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.sdk.robot import Lifecycle


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
    def test_robot_adapter_protocol_declares_robot_runtime_surface(self):
        for name in (
            "capabilities",
            "supports_action",
            "get_joint_state",
            "get_state",
            "send_command",
        ):
            self.assertTrue(hasattr(RobotAdapter, name), name)

    def test_mapped_adapter_implements_declared_protocol_methods(self):
        required = (
            "load_manifest",
            "configure",
            "connect",
            "disconnect",
            "enable",
            "disable",
            "capabilities",
            "supports_action",
            "get_joint_state",
            "get_state",
            "send_command",
            "health",
        )
        for name in required:
            self.assertTrue(hasattr(MappedRos2Adapter, name), name)
            self.assertTrue(hasattr(MockAdapter, name), name)

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
