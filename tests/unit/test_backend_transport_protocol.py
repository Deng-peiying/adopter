import unittest
from datetime import datetime, timezone

from cross_embodiment.transport.protocol import (
    BackendTransport,
    TransportEvent,
    TransportRequest,
    TransportResult,
)


class BackendTransportProtocolTests(unittest.TestCase):
    def test_request_event_and_result_keep_transport_lifecycle_explicit(self):
        request = TransportRequest(
            binding_id="right_arm_joint_position",
            backend="ros2",
            kind="action",
            endpoint="/robot/right_arm_move",
            interface="vendor/action/Move",
            payload={"joint_angles": [0.1] * 7},
            timeout_s=90.0,
        )
        event = TransportEvent(
            binding_id="right_arm_joint_state",
            kind="state",
            payload={"joint_angles": [0.0] * 7},
            received_at=datetime.now(timezone.utc),
        )
        result = TransportResult(
            binding_id=request.binding_id,
            status="succeeded",
            accepted=True,
            dispatched=True,
            payload={"error_code": {"value": 0}},
            backend_status=4,
        )

        self.assertEqual(request.kind, "action")
        self.assertEqual(request.backend, "ros2")
        self.assertEqual(event.kind, "state")
        self.assertTrue(result.accepted)
        self.assertTrue(result.dispatched)
        self.assertEqual(result.backend_status, 4)

    def test_backend_transport_is_a_structural_protocol(self):
        class MinimalTransport:
            def connect(self, bindings, on_event):
                pass

            def execute(self, request):
                return TransportResult(request.binding_id, "succeeded")

            def ready(self, binding_ids):
                return True

            def close(self):
                pass

        self.assertIsInstance(MinimalTransport(), BackendTransport)


if __name__ == "__main__":
    unittest.main()
