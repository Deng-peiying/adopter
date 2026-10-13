import unittest
from types import SimpleNamespace

from cross_embodiment.driver.ros2_mapped import NativeRos2JointTransport


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


class FakeClient:
    def __init__(self, *, available=True, accepted=True, code=0):
        self.available = available
        self.accepted = accepted
        self.code = code
        self.goal = None

    def wait_for_server(self, timeout_sec):
        return self.available

    def send_goal_async(self, goal):
        self.goal = goal
        handle = SimpleNamespace(
            accepted=self.accepted,
            get_result_async=lambda: ImmediateFuture(SimpleNamespace(
                status=4, result=SimpleNamespace(error_code=SimpleNamespace(value=self.code)))),
        )
        return ImmediateFuture(handle)


class Ros2ActionTransportTests(unittest.TestCase):
    def test_native_action_transport_sets_mapped_fields_and_preserves_result(self):
        client = FakeClient(code=3)
        transport = NativeRos2JointTransport({"devices": {}}, lambda *_: None)
        transport.clients["right_arm"] = (client, FakeAction)
        result = transport.execute("right_arm", {
            "move_type": "MoveJ", "joint_angles": [0.1] * 7, "cart_pose": [0.0] * 6,
        }, 0.1)
        self.assertTrue(result["accepted"])
        self.assertTrue(result["dispatched"])
        self.assertEqual(result["status"], 4)
        self.assertEqual(result["result"].error_code.value, 3)
        self.assertEqual(client.goal.joint_angles, [0.1] * 7)
        self.assertEqual(client.goal.move_type, "MoveJ")

    def test_native_action_transport_reports_unavailable_and_rejected(self):
        for available, accepted, expected in ((False, True, "unavailable"),
                                              (True, False, "rejected")):
            transport = NativeRos2JointTransport({"devices": {}}, lambda *_: None)
            transport.clients["right_arm"] = (FakeClient(available=available, accepted=accepted), FakeAction)
            result = transport.execute("right_arm", {}, 0.1)
            self.assertFalse(result["accepted"])
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["dispatched"], available)

    def test_goal_response_timeout_keeps_attempted_delivery_visible(self):
        client = FakeClient()
        transport = NativeRos2JointTransport({"devices": {}}, lambda *_: None)
        transport.clients["right_arm"] = (client, FakeAction)
        transport._wait = lambda *_: (_ for _ in ()).throw(TimeoutError())
        result = transport.execute("right_arm", {}, 0.1)
        self.assertEqual(result["status"], "timed_out")
        self.assertFalse(result["accepted"])
        self.assertTrue(result["dispatched"])

    def test_goal_and_result_future_errors_preserve_dispatch_attempt(self):
        for failed_stage in ("goal", "result"):
            with self.subTest(failed_stage=failed_stage):
                client = FakeClient()
                transport = NativeRos2JointTransport({"devices": {}}, lambda *_: None)
                transport.clients["right_arm"] = (client, FakeAction)
                original_wait = transport._wait
                calls = 0

                def fail_once(future, timeout):
                    nonlocal calls
                    calls += 1
                    if (failed_stage == "goal" and calls == 1) or (failed_stage == "result" and calls == 2):
                        raise RuntimeError("transport broken")
                    return original_wait(future, timeout)

                transport._wait = fail_once
                result = transport.execute("right_arm", {}, 0.1)
                self.assertEqual(result["status"], "transport_error")
                self.assertTrue(result["dispatched"])
                self.assertIn("transport broken", result["error"])


if __name__ == "__main__":
    unittest.main()
