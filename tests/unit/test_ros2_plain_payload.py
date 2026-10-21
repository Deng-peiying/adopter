"""ROS numeric fields must cross the Host boundary as JSON-native data."""
import json

import pytest

from cross_embodiment.transport.ros2 import _plain


np = pytest.importorskip("numpy")


@pytest.mark.parametrize(("value", "expected"), [
    (np.array([0.1, 0.2], dtype=np.float64), [0.1, 0.2]),
    (np.array([[1, 2], [3, 4]], dtype=np.int32), [[1, 2], [3, 4]]),
    (np.array([], dtype=np.float32), []),
    (np.array(7, dtype=np.int64), 7),
    (np.int32(104), 104),
    (np.bool_(True), True),
])
def test_numpy_fields_round_trip_through_json(value, expected):
    assert json.loads(json.dumps(_plain({"field": value}))) == {"field": expected}


def test_ros_message_nested_numpy_fields_round_trip_through_json():
    class JointMessage:
        __slots__ = ("joint_angles", "mode", "flags")

        def __init__(self):
            self.joint_angles = np.array([0.0, 0.5, -0.5], dtype=np.float32)
            self.mode = np.int32(104)
            self.flags = {"enabled": np.bool_(True)}

        def get_fields_and_field_types(self):
            return {"joint_angles": "float[3]", "mode": "int32", "flags": "Flags"}

    assert json.loads(json.dumps(_plain(JointMessage()))) == {
        "joint_angles": [0.0, 0.5, -0.5],
        "mode": 104,
        "flags": {"enabled": True},
    }
