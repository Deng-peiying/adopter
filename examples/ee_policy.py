from pathlib import Path

from cross_embodiment import Runtime, connect
from cross_embodiment.protocol.types import Action, ActionSpec


class DemoEEPolicy:
    def __init__(self):
        self._spec = ActionSpec(
            type="ee_delta", target="right_arm", frame="base", frequency_hz=20,
        )

    def observation_spec(self):
        return {"robot.ee_pose.right_arm": {"type": "pose", "required": True}}

    def action_spec(self):
        return self._spec

    def reset(self):
        pass

    def step(self, observation):
        return Action(
            self._spec,
            {"translation": (0.01, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "gripper": 0.5},
        )


robot = connect("mock", Path(__file__).resolve().parent / "assets/mock_ee.yaml")
runtime = Runtime(robot, DemoEEPolicy())
report = runtime.validate()
print(report.status, report.summary())
runtime.start()
runtime.run(steps=3)
print(robot.state().ee_poses["right_arm"])
runtime.stop()
