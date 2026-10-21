from types import SimpleNamespace

from cross_embodiment.transport.protocol import TransportRequest
from cross_embodiment.transport.ros2 import Ros2Transport


class Future:
    def __init__(self, value): self.value = value
    def add_done_callback(self, callback): callback(self)
    def result(self): return self.value


class Service:
    class Request:
        __slots__ = ('power_enable',)


class Client:
    def __init__(self, available=True, success=True):
        self.available, self.success = available, success
    def wait_for_service(self, timeout_sec): return self.available
    def call_async(self, request):
        self.request = request
        return Future({'success': self.success, 'error': 'vendor response'})


def request():
    return TransportRequest('power', 'ros2', 'service', '/power', 'pkg/srv/Power',
                            {'power_enable': True}, 0.1)


def test_service_preserves_vendor_response_without_interpreting_success():
    transport = Ros2Transport()
    client = Client(success=False)
    transport.services['power'] = (client, Service)
    result = transport.execute(request())
    assert result.status == 'succeeded'
    assert result.dispatched and result.accepted
    assert result.payload['success'] is False
    assert client.request.power_enable is True
    assert transport.ready(['power'])


def test_service_unavailable_and_timeout_preserve_delivery_information():
    transport = Ros2Transport()
    transport.services['power'] = (Client(available=False), Service)
    assert not transport.execute(request()).dispatched
    transport.services['power'] = (Client(), Service)
    transport._wait = lambda *_: (_ for _ in ()).throw(TimeoutError())
    result = transport.execute(request())
    assert result.status == 'timed_out'
    assert result.dispatched


def test_invalid_service_payload_is_not_dispatched():
    transport = Ros2Transport()
    transport.services['power'] = (Client(), Service)
    value = request()
    value.payload['unknown'] = 1
    result = transport.execute(value)
    assert result.status == 'transport_error'
    assert not result.dispatched
