import unittest

from cross_embodiment.runtime.mapping import ActionMapper
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.protocol.types import Action, ActionSpec


class ActionMappingTests(unittest.TestCase):
    def test_maps_bimanual_26d_action_as_structured_command(self):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"id": "wy"},
            control={"supported_modes": [{"type": "bimanual_joint_position", "target": "wy_dual", "dimension": 26}]},
        )
        spec = ActionSpec(type="bimanual_joint_position", target="wy_dual", dimension=26)
        commands = ActionMapper().map(Action(spec, list(range(26))), manifest)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].mode, "bimanual_joint_position")
        self.assertEqual(commands[0].payload["positions"][14], 14.0)

    def test_maps_single_joint_position(self):
        manifest = EmbodimentManifest(
            schema_version="embodiment/v0.2",
            embodiment={"id": "arm"},
            control={"supported_modes": [{"type": "joint_position", "target": "arm", "dimension": 2}]},
        )
        spec = ActionSpec(type="joint_position", target="arm", dimension=2)
        command = ActionMapper().map(Action(spec, [0.1, 0.2]), manifest)[0]
        self.assertEqual(command.payload["positions"], (0.1, 0.2))


if __name__ == "__main__":
    unittest.main()
