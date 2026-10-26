import importlib.util
import unittest
from unittest.mock import Mock, patch

from cross_embodiment.transport.udp import UdpDatagramTransport


class UdpTransportTests(unittest.TestCase):
    def test_sdk_contains_vendor_neutral_udp_datagram_transport(self):
        spec = importlib.util.find_spec("cross_embodiment.transport.udp")
        self.assertIsNotNone(spec, "SDK is missing the generic UDP datagram transport")

    def test_udp_transport_sends_and_receives_raw_datagrams(self):
        sock = Mock()
        sock.sendto.return_value = len(b"vendor framed bytes")
        sock.recvfrom.return_value = (b"response bytes", ("127.0.0.1", 30000))
        transport = UdpDatagramTransport(
            "127.0.0.1", 30000, local_host="127.0.0.1"
        )
        with patch("cross_embodiment.transport.udp.socket.socket", return_value=sock):
            transport.connect()
            transport.send(b"vendor framed bytes")
            received = transport.receive()
            self.assertEqual(received.payload, b"response bytes")
            self.assertEqual(received.peer[1], 30000)
            sock.sendto.assert_called_once_with(b"vendor framed bytes", ("127.0.0.1", 30000))
            transport.close()
            transport.close()
        sock.close.assert_called_once()

    def test_udp_transport_rejects_send_before_connect(self):
        transport = UdpDatagramTransport("127.0.0.1", 30000)
        with self.assertRaises(RuntimeError):
            transport.send(b"payload")


if __name__ == "__main__":
    unittest.main()
