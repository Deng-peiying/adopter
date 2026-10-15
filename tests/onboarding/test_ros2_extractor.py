from __future__ import annotations

import json
from pathlib import Path

from cross_embodiment.onboarding.extractors.base import ScanContext
from cross_embodiment.onboarding.extractors.ros2 import Ros2Extractor, RosGraphSnapshot
from cross_embodiment.onboarding.models import EvidenceLevel


FIXTURE = Path(__file__).parent / "fixtures" / "ros2_vendor"


def _evidence():
    return Ros2Extractor().scan_files(ScanContext(FIXTURE, "vendor", frozenset()))


def test_extracts_package_interfaces_and_empty_action_feedback() -> None:
    evidence = _evidence()
    claims = [dict(item.claims) for item in evidence]
    assert any(c.get("package") == "demo_arm" and c.get("version") == "1.2.3" for c in claims)
    state = next(c for c in claims if c.get("interface") == "ArmState" and c.get("interface_kind") == "msg")
    assert state["fields"][1] == {"type": "float64[7]", "name": "joint_angles"}
    service = next(c for c in claims if c.get("interface") == "SetPower")
    assert service["request_fields"][0]["name"] == "power_enable"
    action = next(c for c in claims if c.get("interface") == "ArmMove")
    assert action["goal_fields"][0]["name"] == "mode"
    assert action["feedback_fields"] == []
    assert any(c.get("interface_kind") == "idl" and c.get("interface") == "Installed" for c in claims)


def test_extracts_launch_without_importing_vendor_python() -> None:
    claims = [dict(item.claims) for item in _evidence()]
    launch = next(c for c in claims if c.get("launch_file") == "launch/bringup.launch.py")
    assert launch["arguments"]["namespace"] == "wy_robot1"
    assert launch["nodes"] == [{"package": "arm_control", "executable": "arm_system_node", "namespace": "wy_robot1"}]
    assert launch["namespace_candidates"] == ["/wy_robot1"]


def test_binary_endpoint_text_is_only_a_candidate() -> None:
    endpoint = next(item for item in _evidence() if item.claim_type == "ros2_endpoint_candidate")
    assert endpoint.claims["token"] == "/right_arm_move_action"
    assert endpoint.confidence_boundary == "binary_string_candidate_only"
    assert endpoint.level is EvidenceLevel.OBSERVED
    assert endpoint.claims["fully_qualified_confirmed"] is False


def test_type_definition_does_not_claim_runtime_endpoint() -> None:
    interface_records = [item for item in _evidence() if item.claim_type == "ros2_interface_definition"]
    assert interface_records
    assert all(item.confidence_boundary == "type_definition_only" for item in interface_records)
    assert all("endpoint" not in item.claims for item in interface_records)


def test_graph_snapshot_is_read_only_runtime_evidence(tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({
        "topics": [{"name": "/wy/right_arm_state", "type": "demo/msg/ArmState"}],
        "services": [{"name": "/wy/set_power", "type": "demo/srv/SetPower"}],
        "actions": [{"name": "/wy/right_arm_move_action", "type": "demo/action/ArmMove"}],
        "nodes": ["/wy/arm_system_node"],
    }))
    snapshot = RosGraphSnapshot.from_json(path)
    evidence = snapshot.to_evidence("graph-snapshot")
    assert {item.claims["endpoint_kind"] for item in evidence if "endpoint_kind" in item.claims} == {"topic", "service", "action"}
    assert all(item.level is EvidenceLevel.RUNTIME_READ for item in evidence)
    assert all(item.level is not EvidenceLevel.HARDWARE_MOTION for item in evidence)


def test_extracts_ros2_python_usage_without_importing_vendor_code() -> None:
    records = _evidence()
    state = next(item for item in records if item.claim_type == "ros2_subscription_usage")
    assert state.claims == {
        "transport_kind": "ros2_subscription",
        "endpoint": "/wy/right_arm_state",
        "interface_type": "demo_arm/msg/ArmState",
        "positions_field": "joint_angles",
        "mode_field": "arm_mode",
    }
    move = next(item for item in records if item.claim_type == "ros2_action_usage")
    assert move.claims["endpoint"] == "/wy/right_arm_move_action"
    assert move.claims["interface_type"] == "demo_arm/action/ArmMove"
    assert move.claims["target_field"] == "joint_angles"
    assert move.claims["constants"] == {"move_type": "MoveJ", "cart_pose": [0.0] * 6}
    assert move.claims["result_code_field"] == "error_code.value"
    assert move.claims["success_code"] == 0
    assert move.claims["timeout_s"] == 20.0
    arrival = next(item for item in records if item.claim_type == "joint_arrival_policy")
    assert arrival.claims == {
        "arrival_tolerance_rad": 0.03,
        "settle_window_s": 0.2,
        "completion": ["terminal_result", "measured_arrival"],
    }


def test_extracts_nested_interface_paths_and_joint_configuration() -> None:
    records = _evidence()
    state = next(item for item in records if item.claims.get("interface") == "ArmState")
    assert "header.stamp" in state.claims["field_paths"]
    assert "arm_fault.fault_code" in state.claims["field_paths"]
    move = next(item for item in records if item.claims.get("interface") == "ArmMove")
    assert "error_code.value" in move.claims["result_field_paths"]
    config = next(item for item in records if item.claim_type == "robot_joint_configuration")
    assert config.claims == {
        "device": "right_arm",
        "vendor_joint_order": ["right_1", "right_2"],
        "joint_limits": [[-2.0, 2.0], [-1.0, 1.0]],
        "unit": "radian",
    }
