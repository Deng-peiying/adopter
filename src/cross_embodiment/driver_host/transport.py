"""Run a transport in a child Python environment, with a plain-data protocol."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .environment import EnvironmentSpec
from .process import ProcessHandle, ProcessSupervisor
from ..transport.protocol import TransportEvent, TransportResult


class _HostConnectionError(ConnectionError):
    def __init__(self, message, *, dispatched):
        super().__init__(message)
        self.dispatched = dispatched


class HostedTransport:
    def __init__(self, *, python: str = sys.executable,
                 environment: EnvironmentSpec | None = None,
                 factory: str = 'cross_embodiment.transport.ros2:Ros2Transport',
                 timeout_s: float = 20.0):
        self.python, self.environment, self.factory = python, environment or EnvironmentSpec(), factory
        self.timeout_s = timeout_s
        self.process = None
        self._supervisor = ProcessSupervisor()
        self._condition = threading.Condition()
        self._rpc_lock = threading.Lock()
        self._responses = {}
        self._sequence = 0
        self._error = None
        self._reader = None

    def connect(self, bindings, on_event):
        if self.process is not None:
            raise ConnectionError('Transport Host is already connected')
        self._on_event = on_event
        self._error = None
        self._responses.clear()
        try:
            env = self.environment.resolve()
            # Make the current SDK available to the selected child interpreter;
            # caller paths and global Python state remain unchanged.
            sdk_root = str(Path(__file__).resolve().parents[2])
            env['PYTHONPATH'] = os.pathsep.join(filter(None, (sdk_root, env.get('PYTHONPATH'))))
            self.process = subprocess.Popen(
                [self.python, '-m', 'cross_embodiment.driver_host.worker', '--factory', self.factory],
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, bufsize=1, start_new_session=True,
            )
            self._supervisor.handle = ProcessHandle(self.process)
            self._reader = threading.Thread(target=self._read, daemon=True, name='ce-host-reader')
            self._reader.start()
            self._rpc('connect', {'bindings': [asdict(value) for value in bindings]})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if 'event' in message:
                    event = message['event']
                    event['received_at'] = datetime.fromisoformat(event['received_at'])
                    self._on_event(TransportEvent(**event))
                else:
                    with self._condition:
                        self._responses[message['id']] = message
                        self._condition.notify_all()
        except Exception as exc:
            self._error = str(exc)
        finally:
            with self._condition:
                self._error = self._error or 'Transport Host exited'
                self._condition.notify_all()

    def _rpc(self, method, params, timeout_s=None):
        with self._rpc_lock:
            with self._condition:
                if self._error or self.process is None:
                    raise _HostConnectionError(self._error or 'Transport Host is disconnected', dispatched=False)
                self._sequence += 1
                key = self._sequence
                try:
                    self.process.stdin.write(json.dumps({'id': key, 'method': method, **params}) + '\n')
                    self.process.stdin.flush()
                except (OSError, ValueError) as exc:
                    raise _HostConnectionError('Transport Host pipe closed', dispatched=True) from exc
                deadline = time.monotonic() + (self.timeout_s if timeout_s is None else timeout_s)
                while key not in self._responses:
                    if self._error:
                        raise _HostConnectionError(self._error, dispatched=True)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f'Transport Host {method} timed out')
                    self._condition.wait(remaining)
                response = self._responses.pop(key)
                if 'error' in response:
                    raise _HostConnectionError(response['error'], dispatched=True)
                return response.get('result')

    def execute(self, request):
        if self.process is None:
            return TransportResult(request.binding_id, 'unavailable')
        try:
            result = self._rpc('execute', {'request': asdict(request)},
                               (request.timeout_s or self.timeout_s) + 15.0)
            return TransportResult(**result)
        except TimeoutError as exc:
            return TransportResult(request.binding_id, 'timed_out', dispatched=True, error=str(exc))
        except ConnectionError as exc:
            return TransportResult(request.binding_id, 'transport_error',
                                   dispatched=getattr(exc, 'dispatched', True), error=str(exc))

    def ready(self, binding_ids):
        try:
            return bool(self._rpc('ready', {'bindings': list(binding_ids)}))
        except (ConnectionError, TimeoutError):
            return False

    def close(self):
        self._supervisor.stop()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
        self.process = self._reader = None
        self._supervisor.handle = None
