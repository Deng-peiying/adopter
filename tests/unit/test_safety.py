import unittest
from datetime import datetime, timedelta, timezone

from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.runtime.safety import SafetyGuard
from cross_embodiment.errors import SafetyViolation
from cross_embodiment.protocol.types import Action, ActionSpec, RobotState, SafetyState


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"id": "wy"},
            devices=[{"id": "arm", "capabilities": ["joint_position"]}],
            control={
                "supported_modes": [
                    {
                        "type": "joint_position",
                        "target": "arm",
                        "dimension": 2,
                        "bounds": [[-1.0, 1.0], [-2.0, 2.0]],
                        "max_delta": [0.2, 0.2],
                    }
                ]
            },
            safety={"requires_enable": True, "max_state_age_ms": 1000},
        )
        self.spec = ActionSpec(type="joint_position", target="arm", dimension=2, frequency_hz=20)
        self.state = RobotState(
            timestamp=datetime.now(timezone.utc),
            joint_positions={"j0": 0.0, "j1": 0.0},
            safety=SafetyState(enabled=True),
        )

    def test_rejects_wrong_dimension_and_bounds(self):
        guard = SafetyGuard()
        with self.assertRaises(SafetyViolation):
            guard.validate(Action(self.spec, [0.1]), self.state, self.manifest, control_enabled=True, dry_run=False)
        with self.assertRaises(SafetyViolation):
            guard.validate(Action(self.spec, [1.1, 0.0]), self.state, self.manifest, control_enabled=True, dry_run=False)

    def test_rejects_stale_or_faulted_state(self):
        guard = SafetyGuard()
        stale = RobotState(
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=2),
            joint_positions={"j0": 0.0, "j1": 0.0},
            safety=SafetyState(enabled=True),
        )
        with self.assertRaises(SafetyViolation):
            guard.validate(Action(self.spec, [0.1, 0.1]), stale, self.manifest, control_enabled=True, dry_run=False)
        self.state.safety = SafetyState(enabled=True, fault=True)
        with self.assertRaises(SafetyViolation):
            guard.validate(Action(self.spec, [0.1, 0.1]), self.state, self.manifest, control_enabled=True, dry_run=False)

    def test_dry_run_allows_disabled_state_but_real_control_requires_enable(self):
        guard = SafetyGuard()
        disabled = RobotState(timestamp=datetime.now(timezone.utc), safety=SafetyState(enabled=False))
        guard.validate(Action(self.spec, [0.1, 0.1]), disabled, self.manifest, control_enabled=False, dry_run=True)
        with self.assertRaises(SafetyViolation):
            guard.validate(Action(self.spec, [0.1, 0.1]), disabled, self.manifest, control_enabled=True, dry_run=False)
