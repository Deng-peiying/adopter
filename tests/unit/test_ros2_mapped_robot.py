import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from cross_embodiment.backend.protocol import TransportEvent, TransportResult
from cross_embodiment.driver.ros2_mapped import MappedRos2Adapter
from cross_embodiment.errors import SafetyViolation
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.mapping.engine import InterfaceMappingEngine
from cross_embodiment.sdk.robot import Robot


NAMES = [f"arm.right.joint.{index}" for index in range(7)]
STATE_BINDING = "right_arm_joint_state"
ACTION_BINDING = "right_arm_joint_position"


def mapping():
    return {
        "schema_version": "interface-mapping/v1",
        "bindings": {
            STATE_BINDING: {
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
            ACTION_BINDING: {
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
                    "state_binding": STATE_BINDING,
                    "arrival_tolerance_rad": 0.015, "settle_window_s": 0.0,
                },
            },
        },
    }


class FakeTransport:
    def __init__(self, *, outcome="success"):
        self.outcome = outcome
        self.goal = None
        self.action_available = True
        self.on_event = None
        self.bindings = []

    def ready(self, binding_ids):
        return self.action_available and set(binding_ids) == {ACTION_BINDING}

    def publish_state(self, positions, *, source_time=None):
        source_time = source_time or datetime.now(timezone.utc)
        stamp = source_time.timestamp()
        sec = int(stamp)
        self.on_event(TransportEvent(
            STATE_BINDING,
            "state",
            {
                "header": {"stamp": {"sec": sec, "nanosec": int((stamp - sec) * 1e9)}},
                "joint_angles": positions,
                "arm_mode": 104,
                "arm_fault": {"fault_code": 0},
            },
            datetime.now(timezone.utc),
        ))

    def connect(self, bindings, on_event):
        self.bindings = list(bindings)
        self.on_event = on_event
        self.publish_state([0.0] * 7)

    def close(self):
        pass

    def execute(self, request):
        self.goal = request.payload
        if self.outcome == "reject":
            return TransportResult(request.binding_id, "rejected", dispatched=True)
        if self.outcome == "timeout":
            return TransportResult(request.binding_id, "timed_out", accepted=True, dispatched=True)
        if self.outcome == "transport_error":
            return TransportResult(
                request.binding_id, "transport_error", accepted=True, dispatched=True,
                error="result channel failed",
            )
        if self.outcome == "cancelled":
            return TransportResult(
                request.binding_id, "cancelled", accepted=True, dispatched=True,
                backend_status=5,
            )
        if self.outcome == "error":
            return TransportResult(
                request.binding_id, "succeeded", accepted=True, dispatched=True,
                payload={"error_code": {"value": 3}, "error_description": "limit"},
                backend_status=4,
            )
        values = request.payload["joint_angles"]
        if self.outcome == "early_only":
            self.publish_state(values)
        elif self.outcome == "replayed_arrival":
            threading.Timer(
                0.01, self.publish_state, args=(values,),
                kwargs={"source_time": datetime.now(timezone.utc) - timedelta(seconds=3)},
            ).start()
        elif self.outcome != "no_arrival":
            threading.Timer(0.01, self.publish_state, args=(values,)).start()
        return TransportResult(
            request.binding_id, "succeeded", accepted=True, dispatched=True,
            payload={"error_code": {"value": 0}, "error_description": ""},
            backend_status=4,
        )


class MappedRobotTests(unittest.TestCase):
    def robot_for(self, outcome="success"):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [
                {"canonical_name": name, "limits": [-1.3, 1.3]} for name in NAMES
            ]}],
            control={"supported_modes": [{
                "type": "joint_position", "target": "right_arm",
                "dimension": 7, "frequency_hz": 20,
            }]},
            safety={"requires_enable": True, "max_state_age_ms": 1000},
        )
        holder = {}

        def factory():
            holder["transport"] = FakeTransport(outcome=outcome)
            return holder["transport"]

        adapter = MappedRos2Adapter(
            manifest,
            connection={"mapping": mapping(), "arrival_timeout_s": 0.2},
            transport_factory=factory,
            control_enabled=True,
            dry_run=False,
        )
        robot = Robot(adapter, manifest)
        robot.lifecycle.connect()
        return robot, holder["transport"]

    def test_public_calls_use_mapping_engine_and_transport(self):
        robot, transport = self.robot_for()
        self.assertIsInstance(robot.adapter.mapping_engine, InterfaceMappingEngine)
        state = robot.get_joint_state("right_arm")
        self.assertEqual(state.status, "ready")
        target = {name: 0.1 * index for index, name in reversed(list(enumerate(NAMES)))}
        result = robot.move_joints("right_arm", target)
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.arrival_confirmed)
        self.assertAlmostEqual(result.max_joint_error_rad, 0.0)
        self.assertEqual(transport.goal["joint_angles"], [target[name] for name in NAMES])
        self.assertEqual(transport.goal["move_type"], "MoveJ")
        robot.close()

    def test_rejection_error_and_timeout_keep_distinct_public_status(self):
        for outcome, expected in (("reject", "rejected"), ("error", "failed"),
                                  ("timeout", "timed_out"),
                                  ("transport_error", "outcome_unknown"),
                                  ("cancelled", "cancelled")):
            with self.subTest(outcome=outcome):
                robot, _ = self.robot_for(outcome=outcome)
                result = robot.move_joints("right_arm", {name: 0.0 for name in NAMES})
                self.assertEqual(result.status, expected)
                self.assertFalse(result.arrival_confirmed)
                self.assertTrue(result.dispatched)
                if outcome == "error":
                    self.assertEqual(result.backend_code, 3)
                robot.close()

    def test_action_success_without_new_measured_arrival_is_not_sdk_success(self):
        robot, _ = self.robot_for(outcome="no_arrival")
        result = robot.move_joints("right_arm", {name: 0.1 for name in NAMES})
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(result.details["backend_status"], 4)
        self.assertFalse(result.arrival_confirmed)
        self.assertIsNone(result.completed_at)
        robot.close()

    def test_goal_response_timeout_is_dispatched_with_unknown_completion(self):
        robot, transport = self.robot_for()
        transport.execute = lambda request: TransportResult(
            request.binding_id, "timed_out", dispatched=True,
        )
        result = robot.move_joints("right_arm", {name: 0.0 for name in NAMES})
        self.assertEqual(result.status, "timed_out")
        self.assertTrue(result.dispatched)
        self.assertFalse(result.accepted)
        self.assertIsNone(result.completed_at)
        robot.close()

    def test_old_source_stamp_is_stale_even_with_recent_receipt(self):
        robot, transport = self.robot_for()
        transport.publish_state([0.0] * 7,
                                source_time=datetime.now(timezone.utc) - timedelta(seconds=3))
        self.assertEqual(robot.get_joint_state("right_arm").status, "stale")
        robot.close()

    def test_enable_and_health_require_fresh_mapped_device_state(self):
        robot, _ = self.robot_for()
        adapter = robot.adapter
        self.assertTrue(adapter.health().ready)
        with adapter._condition:
            adapter._states["right_arm"] = replace(
                adapter._states["right_arm"],
                received_at=datetime.now(timezone.utc) - timedelta(seconds=3),
            )
        self.assertFalse(adapter.health().ready)
        with self.assertRaises(Exception):
            adapter.enable()
        robot.close()

    def test_runtime_readiness_requires_state_and_action_server(self):
        robot, transport = self.robot_for()
        self.assertTrue(robot.adapter.wait_ready(0.01))
        transport.action_available = False
        self.assertFalse(robot.adapter.health().ready)
        self.assertFalse(robot.adapter.wait_ready(0.02))
        robot.close()

    def test_capabilities_do_not_claim_unmapped_estop(self):
        robot, _ = self.robot_for()
        robot.manifest.safety["supports_estop"] = True
        self.assertFalse(robot.capabilities()["safety"]["supports_estop"])
        robot.close()

    def test_measured_sample_before_action_terminal_does_not_prove_arrival(self):
        robot, _ = self.robot_for(outcome="early_only")
        result = robot.move_joints("right_arm", {name: 0.1 for name in NAMES})
        self.assertEqual(result.status, "timed_out")
        self.assertFalse(result.arrival_confirmed)
        robot.close()

    def test_replayed_sample_after_terminal_does_not_prove_arrival(self):
        robot, _ = self.robot_for(outcome="replayed_arrival")
        result = robot.move_joints("right_arm", {name: 0.1 for name in NAMES})
        self.assertEqual(result.status, "timed_out")
        self.assertFalse(result.arrival_confirmed)
        robot.close()

    def test_enable_requires_an_observed_ready_state(self):
        robot, _ = self.robot_for()
        with robot.adapter._condition:
            robot.adapter._states.clear()
        self.assertFalse(robot.adapter.health().ready)
        with self.assertRaises(Exception):
            robot.adapter.enable()
        robot.close()

    def test_dry_run_connect_does_not_open_transport(self):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [
                {"canonical_name": name} for name in NAMES
            ]}],
            control={"supported_modes": [{
                "type": "joint_position", "target": "right_arm", "dimension": 7,
            }]},
        )
        adapter = MappedRos2Adapter(
            manifest,
            connection={"mapping": mapping()},
            dry_run=True,
            transport_factory=lambda: (_ for _ in ()).throw(AssertionError("transport opened")),
        )
        adapter.connect()
        self.assertIsNone(adapter.transport)
        adapter.disconnect()

    def test_ros2_adapter_rejects_non_ros_mapping_before_connect(self):
        wrong_backend = mapping()
        wrong_backend["bindings"][ACTION_BINDING]["transport"]["backend"] = "python"
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [
                {"canonical_name": name} for name in NAMES
            ]}],
            control={"supported_modes": [{
                "type": "joint_position", "target": "right_arm", "dimension": 7,
            }]},
        )
        with self.assertRaisesRegex(ValueError, "ROS2 backend"):
            MappedRos2Adapter(manifest, connection={"mapping": wrong_backend}, dry_run=True)

    def test_stale_device_state_is_visible_and_cannot_start_motion(self):
        robot, _ = self.robot_for()
        adapter = robot.adapter
        with adapter._condition:
            adapter._states["right_arm"] = replace(
                adapter._states["right_arm"],
                received_at=datetime.now(timezone.utc) - timedelta(seconds=2),
            )
        self.assertEqual(robot.get_joint_state("right_arm").status, "stale")
        with self.assertRaises(SafetyViolation):
            robot.move_joints("right_arm", {name: 0.0 for name in NAMES})
        robot.close()

    def test_capabilities_expose_only_bound_devices(self):
        robot, transport = self.robot_for()
        robot.manifest.devices.append({"id": "left_arm", "joints": [
            {"canonical_name": f"arm.left.joint.{index}", "limits": [-1.3, 1.3]}
            for index in range(7)
        ]})
        robot.manifest.control["supported_modes"].append(
            {"type": "joint_position", "target": "left_arm", "dimension": 7}
        )
        view = robot.capabilities()
        self.assertEqual([device["id"] for device in view["devices"]], ["right_arm"])
        self.assertNotIn("frequency_hz", view["actions"][0])
        with self.assertRaises(ValueError):
            robot.move_joints("left_arm", {
                f"arm.left.joint.{index}": 0.0 for index in range(7)
            })
        self.assertIsNone(transport.goal)
        robot.close()


if __name__ == "__main__":
    unittest.main()
