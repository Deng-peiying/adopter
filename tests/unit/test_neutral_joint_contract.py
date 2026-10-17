import unittest
from datetime import datetime, timezone

from cross_embodiment.errors import SafetyViolation
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.protocol.types import Action, ActionSpec, RobotState, SafetyState
from cross_embodiment.runtime.safety import SafetyGuard


class NeutralJointContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"type": "bimanual"},
            devices=[
                {"id": "left_arm", "joints": [
                    {"canonical_name": f"arm.left.joint.{i}", "limits": [-1.0, 1.0]}
                    for i in range(2)
                ]},
                {"id": "right_arm", "joints": [
                    {"canonical_name": f"arm.right.joint.{i}", "limits": [-1.0, 1.0]}
                    for i in range(2)
                ]},
            ],
            control={"supported_modes": [{
                "type": "joint_position",
                "target": "left_arm",
                "dimension": 2,
                "max_delta": [0.1, 0.1],
            }]},
            safety={"joint_step_limit": 0.05},
        )
        self.state = RobotState(
            timestamp=datetime.now(timezone.utc),
            joint_positions={"arm.left.joint.0": 0.0, "arm.left.joint.1": 0.0},
            safety=SafetyState(enabled=True),
        )

    def test_named_action_checks_limits_by_canonical_name(self):
        action = Action(
            ActionSpec("joint_position", "left_arm", dimension=2),
            {"positions": {"arm.left.joint.0": 0.02, "arm.left.joint.1": 0.0}},
        )
        SafetyGuard().validate(action, self.state, self.manifest, control_enabled=True, dry_run=False)

    def test_named_absolute_goal_is_not_capped_by_a_step_limit(self):
        action = Action(
            ActionSpec("joint_position", "left_arm", dimension=2),
            {"positions": {"arm.left.joint.0": 0.8, "arm.left.joint.1": 0.0}},
        )
        SafetyGuard().validate(action, self.state, self.manifest, control_enabled=True, dry_run=False)

    def test_legacy_group_alias_uses_the_declared_mode_limits(self):
        self.manifest.control["supported_modes"].append({
            "type": "bimanual_joint_position",
            "target": "whole_robot",
            "legacy_target_aliases": ["legacy_group"],
            "dimension": 4,
            "max_delta": [0.1, 0.1, 0.1, 0.1],
        })
        self.state.joint_positions.update({
            "arm.left.joint.0": 0.0,
            "arm.left.joint.1": 0.0,
            "arm.right.joint.0": 0.0,
            "arm.right.joint.1": 0.0,
        })
        action = Action(
            ActionSpec("bimanual_joint_position", "legacy_group", dimension=4),
            {"positions": {
                "arm.left.joint.0": 0.08,
                "arm.left.joint.1": 0.0,
                "arm.right.joint.0": 0.0,
                "arm.right.joint.1": 0.0,
            }},
        )
        SafetyGuard().validate(action, self.state, self.manifest, control_enabled=True, dry_run=False)

    def test_capability_view_excludes_backend_joint_names_and_vendor_metadata(self):
        self.manifest.embodiment.update({"vendor": "private", "model": "private_model", "name": "private name"})
        self.manifest.devices[0]["joints"][0]["name"] = "backend_joint_name"
        view = self.manifest.capabilities()
        self.assertNotIn("vendor", view["embodiment"])
        self.assertNotIn("backend_joint_name", str(view))
        self.assertIn("arm.left.joint.0", str(view))


if __name__ == "__main__":
    unittest.main()
