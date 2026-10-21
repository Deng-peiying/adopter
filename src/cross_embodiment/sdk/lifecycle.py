"""Vendor-neutral lifecycle ordering; hardware behavior belongs to the Adapter."""
from __future__ import annotations

from ..errors import LifecycleError


class Lifecycle:
    def __init__(self, adapter):
        self.adapter = adapter
        self._configured = False
        self._connected = False
        self._enabled = False
        self._stopped = False

    def configure(self) -> None:
        if not self._configured:
            self.adapter.configure()
            self._configured = True

    def connect(self) -> None:
        self.configure()
        if not self._connected:
            self.adapter.connect()
            self._connected = True
            self._stopped = False

    def enable(self) -> None:
        if not self._connected:
            raise LifecycleError("Explicitly connect before enabling hardware")
        # Always let the adapter confirm hardware state: local history is not
        # authoritative after an external operation or controller restart.
        self.adapter.enable()
        self._enabled = True

    def disable(self) -> None:
        if not self._connected:
            raise LifecycleError("Explicitly connect before disabling hardware")
        self.adapter.disable()
        self._enabled = False

    def close(self) -> None:
        """Release this handle; do not implicitly power down hardware."""
        if self._connected:
            self.adapter.disconnect()
            self._connected = False
            self._enabled = False

    def stop(self) -> None:
        """Legacy disable-and-disconnect operation; not a motion-stop API."""
        if self._stopped:
            return
        try:
            if self._connected and self._enabled:
                self.disable()
        finally:
            self.close()
        self._stopped = True
