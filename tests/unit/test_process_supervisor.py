import sys
import time
import unittest

from cross_embodiment.errors import DriverCrash
from cross_embodiment.driver.process import ProcessSupervisor


class ProcessSupervisorTests(unittest.TestCase):
    def test_starts_and_stops_child_process(self):
        supervisor = ProcessSupervisor()
        handle = supervisor.start([sys.executable, "-c", "import time; time.sleep(5)"])
        self.assertIsNone(handle.poll())
        supervisor.stop()
        self.assertIsNotNone(handle.poll())

    def test_reports_child_exit_while_waiting_for_readiness(self):
        supervisor = ProcessSupervisor()
        supervisor.start([sys.executable, "-c", "raise SystemExit(3)"])
        time.sleep(0.05)
        with self.assertRaises(DriverCrash):
            supervisor.wait_ready(lambda: False, timeout=0.2, poll_interval=0.01)
        supervisor.stop()


if __name__ == "__main__":
    unittest.main()
