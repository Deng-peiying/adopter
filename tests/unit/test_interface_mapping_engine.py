from copy import deepcopy
import unittest
from datetime import datetime, timezone

from cross_embodiment.backend.protocol import TransportEvent, TransportResult
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.mapping.engine import InterfaceMappingEngine
from cross_embodiment.protocol.types import Command


NAMES = [f"arm.right.joint.{index}" for index in range(7)]


def manifest():
    return EmbodimentManifest(
        schema_version="embodiment/v0.2",
        embodiment={"type": "arm"},
        devices=[{"id": "right_arm", "joints": [
            {"canonical_name": name, "limits": [-2.0, 2.0]} for name in NAMES
        ]}],
        control={"supported_modes": [{
            "type": "joint_position", "target": "right_arm", "dimension": 7,
        }]},
    )


def mapping():
    return {
        "schema_version": "interface-mapping/v1",
        "bindings": {
            "right_arm_joint_state": {
                "semantic": {
                    "operation": "joint_state", "device": "right_arm",
                    "joints": NAMES, "unit": "radian",
                },
                "transport": {
                    "backend": "ros2", "kind": "subscription",
                    "endpoint": "/wy_robot1/right_arm_state",
                    "interface": "arm_control_interface/msg/ArmState",
                },
                "decode": {
                    "positions": "joint_angles", "stamp": "header.stamp",
                    "mode": "arm_mode", "ready_values": [104],
                    "fault": "arm_fault.fault_code", "unit": "radian",
                },
            },
            "right_arm_joint_position": {
                "semantic": {
                    "operation": "joint_position", "device": "right_arm",
                    "joints": NAMES, "unit": "radian",
                },
                "transport": {
                    "backend": "ros2", "kind": "action",
                    "endpoint": "/wy_robot1/right_arm_move_action",
                    "interface": "arm_control_interface/action/ArmMove",
                    "timeout_s": 90.0,
                },
                "encode": {
                    "positions": {"source": "positions", "field": "joint_angles", "unit": "radian"},
                    "constants": {"move_type": "MoveJ", "cart_pose": [0.0] * 6},
                },
                "result": {
                    "error_code": "error_code.value", "description": "error_description",
                    "success_code": 0,
                },
                "completion": {
                    "state_binding": "right_arm_joint_state",
                    "arrival_tolerance_rad": 0.015, "settle_window_s": 1.0,
                },
            },
        },
    }


class InterfaceMappingEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = InterfaceMappingEngine.from_connection({"mapping": mapping()}, manifest())

    def test_transport_bindings_contain_endpoints_without_joint_conversion_logic(self):
        bindings = {request.binding_id: request for request in self.engine.transport_bindings()}
        self.assertEqual(bindings["right_arm_joint_state"].kind, "subscription")
        self.assertEqual(bindings["right_arm_joint_state"].backend, "ros2")
        self.assertEqual(bindings["right_arm_joint_position"].kind, "action")
        self.assertEqual(bindings["right_arm_joint_position"].endpoint,
                         "/wy_robot1/right_arm_move_action")
        self.assertEqual(bindings["right_arm_joint_position"].payload, {})

    def test_compile_command_orders_names_and_builds_typed_transport_request(self):
        positions = {name: index / 10 for index, name in reversed(list(enumerate(NAMES)))}
        compiled = self.engine.compile_command(
            Command("right_arm", "joint_position", {"positions": positions})
        )
        self.assertEqual(compiled.request.payload["joint_angles"],
                         [positions[name] for name in NAMES])
        self.assertEqual(compiled.request.payload["move_type"], "MoveJ")
        self.assertEqual(compiled.target_positions, [positions[name] for name in NAMES])
        self.assertEqual(compiled.completion["state_binding"], "right_arm_joint_state")

    def test_decode_state_event_restores_canonical_joint_state(self):
        now = datetime.now(timezone.utc)
        event = TransportEvent(
            binding_id="right_arm_joint_state", kind="state",
            payload={
                "header": {"stamp": {"sec": int(now.timestamp()), "nanosec": 0}},
                "joint_angles": [0.1] * 7,
                "arm_mode": 104,
                "arm_fault": {"fault_code": 0},
            },
            received_at=now,
        )
        state = self.engine.decode_event(event)
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.positions, {name: 0.1 for name in NAMES})
        self.assertEqual(state.details["backend_mode"], 104)

    def test_decode_result_keeps_transport_and_vendor_results_distinct(self):
        compiled = self.engine.compile_command(Command(
            "right_arm", "joint_position", {"positions": {name: 0.0 for name in NAMES}},
        ))
        decoded = self.engine.decode_result(TransportResult(
            binding_id=compiled.request.binding_id,
            status="succeeded", accepted=True, dispatched=True,
            payload={"error_code": {"value": 3}, "error_description": "limit"},
            backend_status=4,
        ), compiled)
        self.assertFalse(decoded.vendor_succeeded)
        self.assertEqual(decoded.backend_code, 3)
        self.assertEqual(decoded.description, "limit")

    def test_mapping_engine_module_does_not_import_ros(self):
        import cross_embodiment.mapping.engine as engine_module

        names = set(engine_module.__dict__)
        self.assertNotIn("rclpy", names)
        self.assertFalse(any(name.startswith("ActionClient") for name in names))

    def test_invalid_units_and_incomplete_result_mapping_fail_at_load_time(self):
        invalid_unit = deepcopy(mapping())
        invalid_unit["bindings"]["right_arm_joint_state"]["decode"]["unit"] = "UNCONFIRMED"
        with self.assertRaisesRegex(ValueError, "unit"):
            InterfaceMappingEngine.from_connection({"mapping": invalid_unit}, manifest())

        missing_result = deepcopy(mapping())
        del missing_result["bindings"]["right_arm_joint_position"]["result"]["description"]
        with self.assertRaisesRegex(ValueError, "description"):
            InterfaceMappingEngine.from_connection({"mapping": missing_result}, manifest())

        noncanonical_unit = deepcopy(mapping())
        noncanonical_unit["bindings"]["right_arm_joint_state"]["semantic"]["unit"] = "degree"
        with self.assertRaisesRegex(ValueError, "canonical semantic unit"):
            InterfaceMappingEngine.from_connection({"mapping": noncanonical_unit}, manifest())


if __name__ == "__main__":
    unittest.main()
