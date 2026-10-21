from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..errors import DriverCrash


@dataclass
class ProcessHandle:
    process: subprocess.Popen

    def poll(self):
        return self.process.poll()


class ProcessSupervisor:
    def __init__(self):
        self.handle: ProcessHandle | None = None

    def start(
        self,
        command: Sequence[str],
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> ProcessHandle:
        if self.handle is not None and self.handle.poll() is None:
            return self.handle
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            # Inherit the owning CLI host's log stream. An undrained PIPE can
            # fill and block a long-running ROS launch.
            start_new_session=True,
        )
        self.handle = ProcessHandle(process)
        return self.handle

    def wait_ready(
        self,
        predicate: Callable[[], bool],
        timeout: float,
        poll_interval: float = 0.05,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.handle is not None and self.handle.poll() is not None:
                raise DriverCrash(f"Managed driver exited with code {self.handle.poll()}")
            if predicate():
                return
            time.sleep(poll_interval)
        raise ConnectionError("Timed out waiting for managed driver readiness")

    def stop(self, grace_period: float = 2.0) -> None:
        if self.handle is None:
            return
        if self.handle.poll() is not None:
            return
        process = self.handle.process
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                process.wait()
                return
            try:
                process.wait(timeout=None if sig == signal.SIGKILL else grace_period)
                return
            except subprocess.TimeoutExpired:
                continue
