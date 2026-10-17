import unittest
from pathlib import Path

from cross_embodiment import Runtime, connect
from cross_embodiment.errors import CompatibilityError, SafetyViolation
from cross_embodiment.protocol.types import Action, ActionSpec


class Policy:
    def __init__(self, action_type="ee_delta", frame="base"):
        self.spec = ActionSpec(type=action_type, target="right_arm", frame=frame, frequency_hz=20)

    def observation_spec(self):
        return {}

    def action_spec(self):
        return self.spec

    def reset(self):
        pass

    def step(self, observation):
        return Action(self.spec, {"translation": (0.01, 0.0, 0.0), "rotation": (0, 0, 0)})


class V01Tests(unittest.TestCase):
    def setUp(self):
        manifest = Path(__file__).resolve().parents[2] / "examples/assets/mock_ee.yaml"
        self.robot = connect("mock", manifest)

    def tearDown(self):
        self.robot.close()

    def test_ee_runtime_loop(self):
        runtime = Runtime(self.robot, Policy())
        self.assertEqual(runtime.validate().status, "compatible")
        runtime.start()
        runtime.run(steps=2)
        self.assertEqual(len(self.robot.adapter.commands), 2)
        runtime.stop()

    def test_compatibility_rejects_unsupported_action(self):
        report = Runtime(self.robot, Policy("joint_position")).validate()
        self.assertTrue(report.has_blocking_issues)
        with self.assertRaises(CompatibilityError):
            report.raise_if_incompatible()

    def test_safety_rejects_large_delta(self):
        runtime = Runtime(self.robot, Policy())
        runtime.start()
        action = Action(Policy().spec, {"translation": (0.5, 0.0, 0.0), "rotation": (0, 0, 0)})
        with self.assertRaises(SafetyViolation):
            runtime.apply(action)
        runtime.stop()


if __name__ == "__main__":
    unittest.main()
