from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Action, Command, RobotState
from ..runtime.mapping import ActionMapper
from ..runtime.safety import SafetyGuard

if TYPE_CHECKING:
    from ..runtime.installed import RuntimeInfo


from .lifecycle import Lifecycle


class RobotBase(ABC):
    """A configured robot handle; hardware connection remains explicit.

    Backend configuration errors propagate from construction. Adapter.configure
    must only prepare configuration and environment descriptions; it must not
    start a Driver, connect hardware, enable devices, or mutate process-wide
    environment settings.
    """

    def __init__(
        self,
        adapter: Any,
        manifest: EmbodimentManifest,
        *,
        runtime_info: RuntimeInfo | None = None,
        allow_motion: bool | None = None,
        dry_run: bool | None = None,
    ) -> None:
        self.adapter = adapter
        self.manifest = manifest
        self.runtime_info = runtime_info
        self._allow_motion = (
            bool(getattr(adapter, "control_enabled", True))
            if allow_motion is None
            else bool(allow_motion)
        )
        self._dry_run = (
            bool(getattr(adapter, "dry_run", False))
            if dry_run is None
            else bool(dry_run)
        )
        self.lifecycle = Lifecycle(adapter)
        self.lifecycle.configure()

    @classmethod
    @abstractmethod
    def profile_id(cls) -> str:
        """Return the SDK category profile implemented by this facade."""
        raise NotImplementedError

    @classmethod
    def from_instance(
        cls,
        instance_id: str,
        *,
        store: str | Path | None = None,
        allow_motion: bool = False,
    ) -> RobotBase:
        from ..runtime.installed import create_robot_from_instance

        return create_robot_from_instance(
            instance_id,
            store=store,
            allow_motion=allow_motion,
            robot_class=None if cls is RobotBase else cls,
        )

    def connect(self) -> RobotBase:
        """Connect through Lifecycle without implicitly enabling hardware."""
        self.lifecycle.connect()
        return self

    def state(self) -> RobotState:
        return self.adapter.get_state()

    def capabilities(self) -> dict[str, Any]:
        getter = getattr(self.adapter, "capabilities", None)
        return getter() if getter is not None else self.manifest.capabilities()

    def observe(self) -> RobotState:
        return self.state()

    def command(self, command: Command | Action):
        if not isinstance(command, Action):
            raise TypeError("Public Robot.command accepts Action only; raw Command is backend-internal")
        if isinstance(command, Action):
            if not self.manifest.supports(command.spec.type, command.spec.target):
                raise ValueError(f"Action {command.spec.type!r} is not advertised for {command.spec.target!r}")
            supports = getattr(self.adapter, "supports_action", None)
            if supports is not None and not supports(command.spec.type, command.spec.target):
                raise ValueError(f"Action {command.spec.type!r} has no active binding for {command.spec.target!r}")
            state = self.state()
            SafetyGuard().validate(
                command,
                state,
                self.manifest,
                control_enabled=self._allow_motion,
                dry_run=self._dry_run,
            )
            mapped = ActionMapper().map(command, self.manifest)
            return [self.adapter.send_command(item) for item in mapped]

    def close(self) -> None:
        self.lifecycle.close()

    def __enter__(self) -> RobotBase:
        return self.connect()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
