from __future__ import annotations

from pathlib import Path
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Callable, Any

from ..adapter.mock import MockAdapter
from ..hardware.manifest import EmbodimentManifest, load_manifest
from ..protocol.types import Action, ActionSpec, Command, CommandResult, JointState, RobotState
from ..runtime.mapping import ActionMapper
from ..runtime.safety import SafetyGuard

if TYPE_CHECKING:
    from ..runtime.installed import RuntimeInfo


from .lifecycle import Lifecycle


class Robot:
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
    def from_instance(
        cls,
        instance_id: str,
        *,
        store: str | Path | None = None,
        allow_motion: bool = False,
    ) -> Robot:
        from ..runtime.installed import create_robot_from_instance

        return create_robot_from_instance(
            instance_id,
            store=store,
            allow_motion=allow_motion,
        )

    def connect(self) -> Robot:
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

    def get_joint_state(self, device_id: str) -> JointState:
        if self.manifest.device(device_id) is None:
            raise ValueError(f"Unknown device: {device_id}")
        getter = getattr(self.adapter, "get_joint_state", None)
        if getter is None:
            raise NotImplementedError(f"Backend has no measured joint-state binding for {device_id}")
        return getter(device_id)

    def move_joints(self, device_id: str, positions: dict[str, float]) -> CommandResult:
        device = self.manifest.device(device_id)
        if device is None or not self.manifest.supports("joint_position", device_id):
            raise ValueError(f"Device {device_id!r} does not support joint_position")
        supports = getattr(self.adapter, "supports_action", None)
        if supports is not None and not supports("joint_position", device_id):
            raise ValueError(f"Device {device_id!r} has no active joint-position binding")
        expected = {joint.get("canonical_name", joint.get("name")) for joint in device.get("joints", [])}
        if not isinstance(positions, dict) or set(positions) != expected:
            raise ValueError(f"Absolute joint target must contain exactly {sorted(expected)}")
        results = self.command(Action(ActionSpec("joint_position", device_id, dimension=len(expected)),
                                      {"positions": positions}))
        if len(results) != 1:
            raise RuntimeError("Single-device joint move must produce exactly one backend result")
        return results[0]

    def command(self, command: Command | Action):
        if not isinstance(command, Action):
            raise TypeError("Public Robot.command accepts Action only; raw Command is backend-internal")
        if isinstance(command, Action):
            if not self.manifest.supports(command.spec.type, command.spec.target):
                raise ValueError(f"Action {command.spec.type!r} is not advertised for {command.spec.target!r}")
            supports = getattr(self.adapter, "supports_action", None)
            if supports is not None and not supports(command.spec.type, command.spec.target):
                raise ValueError(f"Action {command.spec.type!r} has no active binding for {command.spec.target!r}")
            device = self.manifest.device(command.spec.target)
            if command.spec.type == "joint_position" and device is not None:
                values = asdict(command.values) if is_dataclass(command.values) else command.values
                positions = values.get("positions") if isinstance(values, dict) else None
                if isinstance(positions, dict):
                    expected = {joint.get("canonical_name", joint.get("name"))
                                for joint in device.get("joints", [])}
                    if set(positions) != expected:
                        raise ValueError(f"Joint target must contain exactly {sorted(expected)}")
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

    def __enter__(self) -> Robot:
        return self.connect()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def connect(
    adapter: str | Callable[..., Any] = "mock",
    manifest: str | Path | EmbodimentManifest | None = None,
    *,
    control_enabled: bool = False,
    dry_run: bool = True,
    connection: dict | None = None,
    manage_process: bool = False,
    **_,
) -> Robot:
    if manifest is None:
        raise ValueError("A manifest is required")
    loaded = load_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    if adapter == "mock":
        return Robot(
            MockAdapter(loaded),
            loaded,
            allow_motion=control_enabled,
            dry_run=dry_run,
        )
    if callable(adapter):
        options = dict(connection or {})
        options["manage_process"] = bool(options.get("manage_process", manage_process))
        adapter_impl = adapter(
            loaded,
            connection=options,
            control_enabled=control_enabled,
            dry_run=dry_run,
        )
        return Robot(
            adapter_impl,
            loaded,
            allow_motion=control_enabled,
            dry_run=dry_run,
        )
    raise ValueError(f"Adapter '{adapter}' is not installed or was not loaded from a Hardware Package")
