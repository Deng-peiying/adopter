import threading
import math
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from cross_embodiment.driver.ros2_mapped import MappedRos2Adapter
from cross_embodiment.hardware.manifest import EmbodimentManifest, load_manifest
from pathlib import Path
from cross_embodiment.sdk.robot import Robot
from cross_embodiment.errors import SafetyViolation


NAMES = [f"arm.right.joint.{i}" for i in range(7)]


def mapping(*, alternate=False):
    if alternate:
        return {"schema_version": "ros2-joint-mapping/v1", "devices": {"right_arm": {
            "joints": list(reversed(NAMES)),
            "state": {"topic": "/other/state", "type": "other/msg/JointReport",
                      "positions": "angles", "stamp": "header.stamp", "mode": "operating_mode",
                      "ready_modes": [7], "fault": "error", "unit": "degree"},
            "action": {"name": "/other/move", "type": "other/action/Move",
                       "goal_positions": "q", "goal_constants": {"kind": "absolute"},
                       "result_error": "code", "result_description": "reason", "success_code": 0,
                       "unit": "degree"},
            "arrival_tolerance_rad": 0.015, "settle_window_s": 0.0,
        }}}
    return {"schema_version": "ros2-joint-mapping/v1", "devices": {"right_arm": {
        "joints": NAMES,
        "state": {"topic": "/wy_robot1/right_arm_state", "type": "arm_control_interface/msg/ArmState",
                  "positions": "joint_angles", "stamp": "header.stamp", "mode": "arm_mode",
                  "ready_modes": [104], "fault": "arm_fault.fault_code"},
        "action": {"name": "/wy_robot1/right_arm_move_action", "type": "arm_control_interface/action/ArmMove",
                   "goal_positions": "joint_angles",
                   "goal_constants": {"move_type": "MoveJ", "cart_pose": [0.0] * 6},
                   "result_error": "error_code.value", "result_description": "error_description",
                   "success_code": 0},
        "arrival_tolerance_rad": 0.015, "settle_window_s": 0.0,
    }}}


class FakeTransport:
    def __init__(self, mapping_data, on_state, *, alternate=False, outcome="success"):
        self.config = mapping_data["devices"]["right_arm"]
        self.on_state = on_state
        self.alternate = alternate
        self.outcome = outcome
        self.goal = None
        self.action_available = True

    def actions_ready(self):
        return self.action_available

    def publish_state(self, positions, *, source_time=None):
        stamp = (source_time or datetime.now(timezone.utc)).timestamp()
        sec = int(stamp)
        report = {"header": {"stamp": {"sec": sec, "nanosec": int((stamp - sec) * 1e9)}}}
        if self.alternate:
            report.update({"angles": positions, "operating_mode": 7, "error": 0})
        else:
            report.update({"joint_angles": positions, "arm_mode": 104, "arm_fault": {"fault_code": 0}})
        self.on_state("right_arm", report)

    def connect(self):
        self.publish_state([0.0] * 7)

    def close(self):
        pass

    def execute(self, device_id, goal, timeout_s):
        self.goal = goal
        if self.outcome == "reject":
            return {"accepted": False, "dispatched": True, "status": "rejected", "result": None}
        if self.outcome == "timeout":
            return {"accepted": True, "dispatched": True, "status": "timed_out", "result": None}
        if self.outcome == "transport_error":
            return {"accepted": True, "dispatched": True, "status": "transport_error",
                    "result": None, "error": "result channel failed"}
        if self.outcome == "cancelled":
            return {"accepted": True, "dispatched": True, "status": 5, "result": None}
        if self.outcome == "error":
            result = {"code": 3, "reason": "limit"} if self.alternate else {
                "error_code": {"value": 3}, "error_description": "limit"}
            return {"accepted": True, "dispatched": True, "status": 4, "result": result}
        values = goal["q" if self.alternate else "joint_angles"]
        if self.outcome == "early_only":
            self.publish_state(values)
        elif self.outcome == "replayed_arrival":
            threading.Timer(0.01, self.publish_state, args=(values,),
                            kwargs={"source_time": datetime.now(timezone.utc) - timedelta(seconds=3)}).start()
        elif self.outcome != "no_arrival":
            threading.Timer(0.01, self.publish_state, args=(values,)).start()
        result = {"code": 0, "reason": ""} if self.alternate else {
            "error_code": {"value": 0}, "error_description": ""}
        return {"accepted": True, "dispatched": True, "status": 4, "result": result}


class MappedRobotTests(unittest.TestCase):
    def robot_for(self, alternate=False, outcome="success"):
        ordered_names = list(reversed(NAMES)) if alternate else NAMES
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [{"canonical_name": name, "limits": [-1.3, 1.3]}
                                                    for name in ordered_names]}],
            control={"supported_modes": [{"type": "joint_position", "target": "right_arm",
                                           "dimension": 7, "frequency_hz": 20}]},
            safety={"requires_enable": True, "max_state_age_ms": 1000},
        )
        holder = {}

        def factory(data, callback):
            holder["transport"] = FakeTransport(data, callback, alternate=alternate, outcome=outcome)
            return holder["transport"]

        adapter = MappedRos2Adapter(manifest, connection={"mapping": mapping(alternate=alternate),
                                                     "arrival_timeout_s": 0.2},
                                   transport_factory=factory, control_enabled=True, dry_run=False)
        robot = Robot(adapter, manifest)
        robot.lifecycle.connect()
        return robot, holder["transport"]

    def test_same_public_calls_work_with_two_distinct_vendor_field_maps(self):
        for alternate in (False, True):
            with self.subTest(alternate=alternate):
                robot, transport = self.robot_for(alternate)
                state = robot.get_joint_state("right_arm")
                self.assertEqual(state.status, "ready")
                self.assertEqual(set(state.positions), set(NAMES))
                target = {name: 0.1 * index for index, name in reversed(list(enumerate(NAMES)))}
                result = robot.move_joints("right_arm", target)
                self.assertEqual(result.status, "succeeded")
                self.assertTrue(result.arrival_confirmed)
                self.assertAlmostEqual(result.max_joint_error_rad, 0.0)
                self.assertEqual(transport.goal["q" if alternate else "joint_angles"],
                                 [math.degrees(target[name]) if alternate else target[name]
                                  for name in (list(reversed(NAMES)) if alternate else NAMES)])
                robot.close()

    def test_second_vendor_package_files_load_without_sdk_changes(self):
        root = Path(__file__).resolve().parents[1] / "fixtures/mock_vendor"
        manifest = load_manifest(root / "embodiment.yaml")
        self.assertTrue((root / "package.yaml").is_file())

        def factory(data, callback):
            return FakeTransport(data, callback, alternate=True)

        adapter = MappedRos2Adapter(
            manifest, connection={"package_root": str(root), "mapping_path": "config/joint_mapping.yaml",
                                  "arrival_timeout_s": 0.2},
            transport_factory=factory, control_enabled=True, dry_run=False,
        )
        robot = Robot(adapter, manifest)
        robot.lifecycle.connect()
        target = {name: 0.1 * index for index, name in enumerate(NAMES)}
        self.assertEqual(set(robot.get_joint_state("right_arm").positions), set(NAMES))
        self.assertEqual(robot.move_joints("right_arm", target).status, "succeeded")
        self.assertEqual(adapter.transport.goal["q"],
                         [math.degrees(target[name]) for name in reversed(NAMES)])
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

    def test_goal_response_timeout_is_dispatched_with_unknown_outcome(self):
        robot, transport = self.robot_for()
        transport.execute = lambda *_: {"accepted": False, "dispatched": True,
                                        "status": "timed_out", "result": None}
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
                adapter._states["right_arm"], received_at=datetime.now(timezone.utc) - timedelta(seconds=3))
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

    def test_dry_run_connect_does_not_open_ros_transport(self):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2", embodiment={"type": "arm"},
            devices=[{"id": "right_arm", "joints": [{"canonical_name": name} for name in NAMES]}],
            control={"supported_modes": [{"type": "joint_position", "target": "right_arm", "dimension": 7}]},
        )
        adapter = MappedRos2Adapter(
            manifest, connection={"mapping": mapping()}, dry_run=True,
            transport_factory=lambda *_: (_ for _ in ()).throw(AssertionError("ROS transport opened")),
        )
        adapter.connect()
        self.assertIsNone(adapter.transport)
        adapter.disconnect()

    def test_stale_device_state_is_visible_and_cannot_start_motion(self):
        robot, _ = self.robot_for()
        adapter = robot.adapter
        with adapter._condition:
            adapter._states["right_arm"] = replace(
                adapter._states["right_arm"], received_at=datetime.now(timezone.utc) - timedelta(seconds=2))
        self.assertEqual(robot.get_joint_state("right_arm").status, "stale")
        with self.assertRaises(SafetyViolation):
            robot.move_joints("right_arm", {name: 0.0 for name in NAMES})
        robot.close()

    def test_capabilities_expose_only_bound_devices(self):
        robot, transport = self.robot_for()
        robot.manifest.devices.append({"id": "left_arm", "joints": [
            {"canonical_name": f"arm.left.joint.{i}", "limits": [-1.3, 1.3]}
            for i in range(7)]})
        robot.manifest.control["supported_modes"].append(
            {"type": "joint_position", "target": "left_arm", "dimension": 7})
        view = robot.capabilities()
        self.assertEqual([device["id"] for device in view["devices"]], ["right_arm"])
        self.assertNotIn("frequency_hz", view["actions"][0])
        with self.assertRaises(ValueError):
            robot.move_joints("left_arm", {f"arm.left.joint.{i}": 0.0 for i in range(7)})
        self.assertIsNone(transport.goal)
        robot.close()


if __name__ == "__main__":
    unittest.main()
