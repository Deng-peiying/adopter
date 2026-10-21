import sys
import time
import unittest

from cross_embodiment.errors import DriverCrash
from cross_embodiment.driver_host.process import ProcessSupervisor


class ProcessSupervisorTests(unittest.TestCase):
    def test_stop_tolerates_child_exiting_between_poll_and_signal(self):
        from unittest.mock import Mock, patch
        from cross_embodiment.driver_host.process import ProcessHandle

        process = Mock(pid=12345)
        process.poll.return_value = None
        supervisor = ProcessSupervisor()
        supervisor.handle = ProcessHandle(process)
        with patch('cross_embodiment.driver_host.process.os.killpg', side_effect=ProcessLookupError):
            supervisor.stop()
        process.wait.assert_called_once()

    def test_dead_owned_driver_cannot_pass_with_cached_readiness(self):
        from unittest.mock import Mock
        from cross_embodiment.driver_host.process import ProcessHandle

        process = Mock()
        process.poll.return_value = 3
        supervisor = ProcessSupervisor()
        supervisor.handle = ProcessHandle(process)
        with self.assertRaises(DriverCrash):
            supervisor.wait_ready(lambda: True, timeout=.1)

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
