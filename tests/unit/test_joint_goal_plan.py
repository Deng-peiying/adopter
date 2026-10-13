import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cross_embodiment.errors import PackageError
from cross_embodiment.kinematics import (
    JointGoalPlanner,
    forward_kinematics,
    load_kdl_chain,
)
from cross_embodiment.package.manifest import load_package_manifest
from cross_embodiment.protocol.types import JointState, Pose


HARDWARE_ROOT = Path(__file__).resolve().parents[3] / "ce-hardware-weiyi-dual-o6"
JOINTS = tuple(f"arm.right.joint.{index}" for index in range(7))
LOWERED = dict(
    zip(
        JOINTS,
        (-0.0033670878, 1.4220001904, -1.4747183164, 0.2770752798,
         -0.0200855609, 0.050284849, 0.070801842),
    )
)


def state(positions=LOWERED, *, seconds=0):
    stamp = datetime(2026, 10, 13, 10, 35, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return JointState(
        device_id="right_arm",
        positions=dict(positions),
        source_timestamp=stamp,
        received_at=stamp,
        status="ready",
    )


class JointGoalPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = load_package_manifest(HARDWARE_ROOT / "package.yaml")
        cls.chain = load_kdl_chain(package)
        cls.planner = JointGoalPlanner(cls.chain)
        cls.current_pose = forward_kinematics(cls.chain, LOWERED)

    def test_plan_binds_source_model_frame_and_complete_generated_target(self):
        source = state()

        plan = self.planner.plan(
            source,
            self.current_pose,
            position_tolerance_m=0.002,
            orientation_tolerance_rad=0.02,
        )

        self.assertEqual(plan.device_id, "right_arm")
        self.assertEqual(plan.source_state_timestamp, source.source_timestamp)
        self.assertEqual(plan.model_digest, self.chain.model_digest)
        self.assertEqual(plan.goal_frame, "7axis_base_link")
        self.assertEqual(tuple(plan.joint_target), JOINTS)
        self.assertEqual(plan.execution_semantics, "joint_space_move_to_ik_solution")
        self.assertTrue(plan.endpoint_ik_validated)
        self.assertFalse(plan.path_validated)
        self.assertFalse(plan.collision_validated)
        self.assertFalse(plan.cartesian_path_guaranteed)

        serialized = plan.as_dict()
        self.assertEqual(serialized["evidence"]["path_validated"], False)
        self.assertEqual(serialized["evidence"]["collision_validated"], False)
        self.assertNotIn("validated_motion_plan", str(serialized).lower())

    def test_plan_requires_fresh_source_frame_and_positive_explicit_tolerances(self):
        missing_stamp = JointState(
            device_id="right_arm",
            positions=LOWERED,
            source_timestamp=None,
            received_at=datetime.now(timezone.utc),
            status="ready",
        )
        with self.assertRaisesRegex(PackageError, "source timestamp"):
            self.planner.plan(
                missing_stamp,
                self.current_pose,
                position_tolerance_m=0.002,
                orientation_tolerance_rad=0.02,
            )
        with self.assertRaisesRegex(PackageError, "target frame"):
            self.planner.plan(
                state(),
                Pose(self.current_pose.position, self.current_pose.quaternion_xyzw, frame=""),
                position_tolerance_m=0.002,
                orientation_tolerance_rad=0.02,
            )
        for position_tolerance, orientation_tolerance in ((0.0, 0.02), (0.002, 0.0)):
            with self.assertRaisesRegex(PackageError, "tolerance"):
                self.planner.plan(
                    state(),
                    self.current_pose,
                    position_tolerance_m=position_tolerance,
                    orientation_tolerance_rad=orientation_tolerance,
                )

    def test_plan_rejects_failed_endpoint_ik(self):
        unreachable = Pose(position=(10.0, 10.0, 10.0), frame="7axis_base_link")

        with self.assertRaisesRegex(PackageError, "IK endpoint"):
            self.planner.plan(
                state(),
                unreachable,
                position_tolerance_m=0.002,
                orientation_tolerance_rad=0.02,
            )

    def test_verify_uses_new_measured_state_and_forward_kinematics(self):
        plan = self.planner.plan(
            state(),
            self.current_pose,
            position_tolerance_m=0.002,
            orientation_tolerance_rad=0.02,
        )

        verification = self.planner.verify(plan, state(plan.joint_target, seconds=1))

        self.assertTrue(verification.achieved)
        self.assertEqual(verification.measured_source_timestamp, state(seconds=1).source_timestamp)
        self.assertLessEqual(verification.position_error_m, plan.position_tolerance_m)
        self.assertLessEqual(verification.orientation_error_rad, plan.orientation_tolerance_rad)


if __name__ == "__main__":
    unittest.main()
