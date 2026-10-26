"""Small, vendor-neutral UDP datagram transport primitive."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import socket


@dataclass(frozen=True)
class Datagram:
    payload: bytes
    peer: tuple[str, int]
    received_at: datetime


class UdpDatagramTransport:
    """Own one UDP socket; framing and message semantics belong to callers."""

    def __init__(
        self,
        remote_host: str,
        remote_port: int,
        *,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
        receive_timeout_s: float = 0.1,
        max_datagram_bytes: int = 65535,
    ) -> None:
        if not remote_host or not 1 <= int(remote_port) <= 65535:
            raise ValueError("A remote host and valid UDP port are required")
        if not 0 <= int(local_port) <= 65535:
            raise ValueError("Local UDP port must be in [0, 65535]")
        if receive_timeout_s <= 0 or not 1 <= max_datagram_bytes <= 65535:
            raise ValueError("Invalid UDP timeout or maximum datagram size")
        self.remote_address = (remote_host, int(remote_port))
        self.local_address = (local_host, int(local_port))
        self.receive_timeout_s = float(receive_timeout_s)
        self.max_datagram_bytes = int(max_datagram_bytes)
        self._socket: socket.socket | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(self.local_address)
            sock.settimeout(self.receive_timeout_s)
        except Exception:
            sock.close()
            raise
        self._socket = sock

    def send(self, payload: bytes) -> None:
        sock = self._require_socket()
        if not isinstance(payload, bytes):
            raise TypeError("UDP payload must be bytes")
        sent = sock.sendto(payload, self.remote_address)
        if sent != len(payload):
            raise OSError(f"UDP datagram was only partially sent ({sent}/{len(payload)} bytes)")

    def receive(self) -> Datagram:
        sock = self._require_socket()
        payload, peer = sock.recvfrom(self.max_datagram_bytes)
        return Datagram(
            payload=payload,
            peer=(str(peer[0]), int(peer[1])),
            received_at=datetime.now(timezone.utc),
        )

    def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("UDP transport is not connected")
        return self._socket
