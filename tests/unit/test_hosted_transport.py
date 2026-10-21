import os
from pathlib import Path
import sys
import threading

import pytest

from cross_embodiment.transport.protocol import TransportRequest


def test_environment_is_prepared_at_connect_without_mutating_parent(tmp_path):
    from cross_embodiment.driver_host.environment import EnvironmentSpec

    marker = tmp_path / 'sourced'
    setup = tmp_path / 'setup.bash'
    setup.write_text(f'touch "{marker}"\nexport CE_TEST_VENDOR=isolated\necho vendor-log\n')
    before = dict(os.environ)
    spec = EnvironmentSpec(setup_scripts=(setup,))
    assert not marker.exists()
    child = spec.resolve()
    assert child['CE_TEST_VENDOR'] == 'isolated'
    assert marker.exists()
    assert dict(os.environ) == before


def test_host_process_relays_events_and_results_and_cleans_up(tmp_path):
    from cross_embodiment.driver_host.environment import EnvironmentSpec
    from cross_embodiment.driver_host.transport import HostedTransport

    (tmp_path / 'host_fixture.py').write_text('''
import os
from array import array
from cross_embodiment.transport.ros2 import _plain
from cross_embodiment.transport.protocol import TransportEvent, TransportResult
class Transport:
    def connect(self, bindings, on_event):
        print('Python log')
        os.write(1, b'native log\\n')
        on_event(TransportEvent('state', 'state', _plain({'value': array('d', [7.0])})))
    def ready(self, ids): return True
    def execute(self, request):
        if request.payload.get('crash'): os._exit(3)
        return TransportResult(request.binding_id, 'succeeded', accepted=True,
                               dispatched=True, payload=request.payload)
    def close(self): pass
''')
    env = EnvironmentSpec(overrides={'PYTHONPATH': str(tmp_path)})
    transport = HostedTransport(python=sys.executable, environment=env,
                                factory='host_fixture:Transport')
    event = threading.Event()
    received = []
    transport.connect([], lambda value: (received.append(value), event.set()))
    child = transport.process
    assert event.wait(1)
    assert received[0].payload == {'value': [7.0]}
    assert transport.ready(['state'])
    request = TransportRequest('move', 'ros2', 'action', '/move', 'pkg/action/Move', {'x': 1}, .1)
    assert transport.execute(request).payload == {'x': 1}
    request.payload['crash'] = True
    result = transport.execute(request)
    assert result.status == 'transport_error' and result.dispatched
    transport.close()
    assert child.poll() is not None
    transport.close()


def test_host_start_failure_does_not_leave_process_running():
    from cross_embodiment.driver_host.transport import HostedTransport

    transport = HostedTransport(factory='does_not_exist:Transport')
    with pytest.raises(ConnectionError):
        transport.connect([], lambda _: None)
    assert transport.process is None


def test_known_dead_host_does_not_report_an_unsent_command_as_dispatched():
    from types import SimpleNamespace
    from cross_embodiment.driver_host.transport import HostedTransport

    transport = HostedTransport()
    transport.process = SimpleNamespace(stdin=None)
    transport._error = 'Transport Host exited'
    result = transport.execute(TransportRequest('move', 'ros2', 'action', '/move', 'pkg/action/Move'))
    assert result.status == 'transport_error'
    assert not result.dispatched
