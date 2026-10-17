"""ROS 2 implementation of the mechanism-only backend transport protocol."""

from __future__ import annotations

import threading
from typing import Any, Callable, Sequence

from ..backend.protocol import TransportEvent, TransportRequest, TransportResult
from ..errors import DependencyError


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    fields = getattr(value, "get_fields_and_field_types", None)
    if callable(fields):
        return {name: _plain(getattr(value, name)) for name in fields()}
    if hasattr(value, "__dict__"):
        return {name: _plain(item) for name, item in vars(value).items()
                if not name.startswith("_")}
    return value


class Ros2Transport:
    """Own ROS nodes, subscriptions and Action clients without robot semantics."""

    def __init__(self) -> None:
        self.node = None
        self.executor = None
        self.thread = None
        self.clients: dict[str, tuple[Any, Any]] = {}
        self._owns_rclpy = False
        self._on_event: Callable[[TransportEvent], None] | None = None

    def connect(
        self,
        bindings: Sequence[TransportRequest],
        on_event: Callable[[TransportEvent], None],
    ) -> None:
        if any(binding.backend != "ros2" for binding in bindings):
            raise ValueError("Ros2Transport received a non-ROS2 backend binding")
        try:
            import rclpy
            from rclpy.action import ActionClient
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.node import Node
            from rosidl_runtime_py.utilities import get_action, get_message
        except ImportError as exc:
            raise DependencyError("ROS 2 transport requires rclpy and rosidl_runtime_py") from exc
        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_rclpy = True
        self._on_event = on_event
        self.node = Node("cross_embodiment_ros2_transport")
        for binding in bindings:
            if binding.kind == "subscription":
                message_type = get_message(binding.interface)
                self.node.create_subscription(
                    message_type,
                    binding.endpoint,
                    lambda message, key=binding.binding_id: self._emit(
                        TransportEvent(key, "state", _plain(message))
                    ),
                    10,
                )
            elif binding.kind == "action":
                action_type = get_action(binding.interface)
                self.clients[binding.binding_id] = (
                    ActionClient(self.node, action_type, binding.endpoint), action_type,
                )
            else:
                raise ValueError(f"ROS 2 transport does not support binding kind {binding.kind}")
        self.executor = MultiThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(
            target=self.executor.spin, daemon=True, name="ros2-transport-executor",
        )
        self.thread.start()

    def _emit(self, event: TransportEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)

    @staticmethod
    def _wait(future: Any, timeout_s: float) -> Any:
        done = threading.Event()
        future.add_done_callback(lambda _: done.set())
        if not done.wait(timeout_s):
            raise TimeoutError("ROS Action response timed out; physical outcome is unknown")
        return future.result()

    def execute(self, request: TransportRequest) -> TransportResult:
        if request.backend != "ros2":
            raise ValueError("Ros2Transport received a non-ROS2 backend request")
        if request.kind != "action":
            raise ValueError(f"ROS 2 execute requires an action request, got {request.kind}")
        client_entry = self.clients.get(request.binding_id)
        if client_entry is None:
            return TransportResult(request.binding_id, "unavailable")
        client, action_type = client_entry
        if not client.wait_for_server(timeout_sec=3.0):
            return TransportResult(request.binding_id, "unavailable")
        try:
            goal = action_type.Goal()
            for field, value in request.payload.items():
                setattr(goal, field, value)
        except Exception as exc:
            return TransportResult(
                request.binding_id, "transport_error", error=str(exc),
            )

        def feedback_callback(message: Any) -> None:
            feedback = getattr(message, "feedback", message)
            self._emit(TransportEvent(request.binding_id, "feedback", _plain(feedback)))

        try:
            goal_future = client.send_goal_async(goal, feedback_callback=feedback_callback)
        except Exception as exc:
            return TransportResult(
                request.binding_id, "transport_error", error=str(exc),
            )
        try:
            handle = self._wait(goal_future, 5.0)
        except TimeoutError:
            return TransportResult(
                request.binding_id, "timed_out", dispatched=True,
            )
        except Exception as exc:
            return TransportResult(
                request.binding_id, "transport_error", dispatched=True, error=str(exc),
            )
        if not handle.accepted:
            return TransportResult(
                request.binding_id, "rejected", dispatched=True,
            )
        timeout_s = request.timeout_s
        if timeout_s is None:
            raise ValueError(f"Action request {request.binding_id} requires timeout_s")
        try:
            terminal = self._wait(handle.get_result_async(), timeout_s)
        except TimeoutError:
            cancel_accepted = None
            try:
                cancel = self._wait(handle.cancel_goal_async(), 3.0)
                cancel_accepted = bool(getattr(cancel, "goals_canceling", []))
            except Exception:
                cancel_accepted = False
            return TransportResult(
                request.binding_id, "timed_out", accepted=True, dispatched=True,
                cancel_requested=True, cancel_accepted=cancel_accepted,
            )
        except Exception as exc:
            return TransportResult(
                request.binding_id, "transport_error", accepted=True, dispatched=True,
                error=str(exc),
            )
        backend_status = terminal.status
        status = {4: "succeeded", 5: "cancelled", 6: "aborted"}.get(
            backend_status, "failed"
        )
        return TransportResult(
            request.binding_id,
            status,
            accepted=True,
            dispatched=True,
            payload=_plain(terminal.result),
            backend_status=backend_status,
        )

    def ready(self, binding_ids: Sequence[str]) -> bool:
        return bool(binding_ids) and all(
            binding_id in self.clients
            and self.clients[binding_id][0].wait_for_server(timeout_sec=0.0)
            for binding_id in binding_ids
        )

    def close(self) -> None:
        if self.executor is not None:
            self.executor.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.node is not None:
            self.node.destroy_node()
        if self._owns_rclpy:
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()
