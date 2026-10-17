import unittest

from cross_embodiment.sdk.robot import Lifecycle


class Adapter:
    def __init__(self):
        self.calls = []

    def configure(self):
        self.calls.append("configure")

    def connect(self):
        self.calls.append("connect")

    def enable(self):
        self.calls.append("enable")

    def disable(self):
        self.calls.append("disable")

    def disconnect(self):
        self.calls.append("disconnect")


class AdapterLifecycleTests(unittest.TestCase):
    def test_lifecycle_configures_and_stops_idempotently(self):
        adapter = Adapter()
        lifecycle = Lifecycle(adapter)
        lifecycle.configure()
        lifecycle.connect()
        lifecycle.enable()
        lifecycle.stop()
        lifecycle.stop()
        self.assertEqual(adapter.calls, ["configure", "connect", "enable", "disable", "disconnect"])


if __name__ == "__main__":
    unittest.main()
