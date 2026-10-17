import unittest
from types import SimpleNamespace

from cross_embodiment.backend.protocol import TransportRequest
from cross_embodiment.driver.ros2_transport import Ros2Transport


class ImmediateFuture:
    def __init__(self, value):
        self.value = value

    def add_done_callback(self, callback):
        callback(self)

    def result(self):
        return self.value


class FakeAction:
    class Goal:
        pass


class StrictAction:
    class Goal:
        __slots__ = ("joint_angles",)


class FakeClient:
    def __init__(self, *, available=True, accepted=True, code=0):
        self.available = available
        self.accepted = accepted
        self.code = code
        self.goal = None

    def wait_for_server(self, timeout_sec):
        return self.available

    def send_goal_async(self, goal, feedback_callback=None):
        self.goal = goal
        handle = SimpleNamespace(
            accepted=self.accepted,
            get_result_async=lambda: ImmediateFuture(SimpleNamespace(
                status=4, result={"error_code": {"value": self.code}})),
            cancel_goal_async=lambda: ImmediateFuture(SimpleNamespace(goals_canceling=[1])),
        )
        return ImmediateFuture(handle)


def request(payload=None):
    return TransportRequest(
        binding_id="right_arm_joint_position",
        backend="ros2",
        kind="action",
        endpoint="/wy_robot1/right_arm_move_action",
        interface="arm_control_interface/action/ArmMove",
        payload=payload or {},
        timeout_s=0.1,
    )


class Ros2ActionTransportTests(unittest.TestCase):
    def transport_with(self, client):
        transport = Ros2Transport()
        transport.clients["right_arm_joint_position"] = (client, FakeAction)
        return transport

    def test_action_transport_sets_compiled_fields_and_preserves_result(self):
        client = FakeClient(code=3)
        transport = self.transport_with(client)
        result = transport.execute(request({
            "move_type": "MoveJ", "joint_angles": [0.1] * 7, "cart_pose": [0.0] * 6,
        }))
        self.assertTrue(result.accepted)
        self.assertTrue(result.dispatched)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.backend_status, 4)
        self.assertEqual(result.payload["error_code"]["value"], 3)
        self.assertEqual(client.goal.joint_angles, [0.1] * 7)
        self.assertEqual(client.goal.move_type, "MoveJ")

    def test_action_transport_reports_unavailable_and_rejected(self):
        for available, accepted, expected in ((False, True, "unavailable"),
                                              (True, False, "rejected")):
            transport = self.transport_with(FakeClient(available=available, accepted=accepted))
            result = transport.execute(request())
            self.assertFalse(result.accepted)
            self.assertEqual(result.status, expected)
            self.assertEqual(result.dispatched, available)

    def test_non_ros_binding_and_invalid_goal_fields_are_rejected(self):
        non_ros = request()
        object.__setattr__(non_ros, "backend", "python")
        with self.assertRaisesRegex(ValueError, "backend"):
            self.transport_with(FakeClient()).execute(non_ros)

        transport = Ros2Transport()
        transport.clients["right_arm_joint_position"] = (FakeClient(), StrictAction)
        result = transport.execute(request({"unknown_field": 1}))
        self.assertEqual(result.status, "transport_error")
        self.assertFalse(result.dispatched)
        self.assertIn("unknown_field", result.error)

    def test_goal_response_timeout_keeps_attempted_delivery_visible(self):
        transport = self.transport_with(FakeClient())
        transport._wait = lambda *_: (_ for _ in ()).throw(TimeoutError())
        result = transport.execute(request())
        self.assertEqual(result.status, "timed_out")
        self.assertFalse(result.accepted)
        self.assertTrue(result.dispatched)
        self.assertFalse(result.cancel_requested)

    def test_result_timeout_records_cancel_request(self):
        transport = self.transport_with(FakeClient())
        original_wait = transport._wait
        calls = 0

        def timeout_result(future, timeout):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError()
            return original_wait(future, timeout)

        transport._wait = timeout_result
        result = transport.execute(request())
        self.assertEqual(result.status, "timed_out")
        self.assertTrue(result.accepted)
        self.assertTrue(result.cancel_requested)
        self.assertTrue(result.cancel_accepted)

    def test_goal_and_result_future_errors_preserve_dispatch_attempt(self):
        for failed_stage in ("goal", "result"):
            with self.subTest(failed_stage=failed_stage):
                transport = self.transport_with(FakeClient())
                original_wait = transport._wait
                calls = 0

                def fail_once(future, timeout):
                    nonlocal calls
                    calls += 1
                    if (failed_stage == "goal" and calls == 1) or (failed_stage == "result" and calls == 2):
                        raise RuntimeError("transport broken")
                    return original_wait(future, timeout)

                transport._wait = fail_once
                result = transport.execute(request())
                self.assertEqual(result.status, "transport_error")
                self.assertTrue(result.dispatched)
                self.assertIn("transport broken", result.error)


if __name__ == "__main__":
    unittest.main()
