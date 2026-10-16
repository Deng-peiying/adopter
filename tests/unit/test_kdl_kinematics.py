import math
import unittest
from dataclasses import replace
from pathlib import Path

from cross_embodiment.errors import PackageError
from cross_embodiment.kinematics import (
    forward_kinematics,
    load_kdl_chain,
    solve_inverse_kinematics,
)
from cross_embodiment.package.manifest import load_package_manifest
from cross_embodiment.protocol.types import Pose


HARDWARE_ROOT = Path(__file__).resolve().parents[1] / "fixtures/kinematics/two_joint_arm"
CANONICAL_JOINTS = ("arm.test.joint.0", "arm.test.joint.1")
LOWERED = {
    "arm.test.joint.0": 0.2,
    "arm.test.joint.1": -0.4,
}


class KdlKinematicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = load_package_manifest(HARDWARE_ROOT / "package.yaml")

    def test_loads_exact_canonical_order_and_model_frames(self):
        chain = load_kdl_chain(self.package)

        self.assertEqual(chain.device_id, "test_arm")
        self.assertEqual(chain.canonical_joints, CANONICAL_JOINTS)
        self.assertEqual(chain.model_joints, ("joint_1", "joint_2"))
        self.assertEqual(chain.base_link, "base_link")
        self.assertEqual(chain.tip_link, "tip_link")
        self.assertEqual(chain.joint_count, 2)
        self.assertEqual(len(chain.model_digest), 64)

    def test_rejects_a_semantics_map_that_does_not_match_the_chain(self):
        chain = load_kdl_chain(self.package)
        malformed = replace(chain.semantics, model_joints=chain.model_joints[:-1] + ("missing_joint",))

        with self.assertRaisesRegex(PackageError, "missing_joint"):
            load_kdl_chain(self.package, semantics=malformed)

    def test_forward_kinematics_returns_a_finite_pose_in_declared_base(self):
        chain = load_kdl_chain(self.package)

        pose = forward_kinematics(chain, LOWERED)

        self.assertEqual(pose.frame, "base_link")
        self.assertTrue(all(math.isfinite(value) for value in pose.position + pose.quaternion_xyzw))
        quaternion_norm = math.sqrt(sum(value * value for value in pose.quaternion_xyzw))
        self.assertAlmostEqual(quaternion_norm, 1.0, places=8)

    def test_seeded_ik_round_trip_meets_residual_tolerances(self):
        chain = load_kdl_chain(self.package)
        current = forward_kinematics(chain, LOWERED)

        result = solve_inverse_kinematics(chain, current, LOWERED)

        self.assertTrue(result.success, result.message)
        self.assertEqual(tuple(result.positions), CANONICAL_JOINTS)
        self.assertLessEqual(result.position_error_m, 1e-6)
        self.assertLessEqual(result.orientation_error_rad, 1e-6)

    def test_unreachable_target_returns_a_failed_result(self):
        chain = load_kdl_chain(self.package)
        target = Pose(position=(10.0, 10.0, 10.0), frame="base_link")

        result = solve_inverse_kinematics(chain, target, LOWERED)

        self.assertFalse(result.success)
        self.assertEqual(result.positions, {})
        self.assertIn("did not converge", result.message)


if __name__ == "__main__":
    unittest.main()
