# Mapping Engine and Backend Transport Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate the verified right-arm mapping logic from ROS 2 communication while preserving the public Robot API and physical command semantics.

**Architecture:** A small typed Backend Transport protocol carries transport requests, state events, and results. A transport-independent Mapping Engine compiles internal Commands and decodes vendor payloads. `MappedRos2Adapter` remains the Hardware Package entry point and becomes a thin runtime composition of the engine and ROS 2 transport.

**Tech Stack:** Python 3.10, dataclasses, Protocol, ROS 2 Humble loaded lazily, YAML, unittest.

**Spec:** User specification “Cross-Embodiment SDK：Mapping Engine 与 Backend Transport 解耦”, 2026-10-13.

## Global Constraints

- Keep `Robot.get_joint_state()`, `Robot.move_joints()`, Action/State semantics, right-arm targets, wave parameters, limits, and completion behavior unchanged.
- Implement only the verified right-arm ROS 2 state/Action path.
- Do not add another vendor, Python/native backend, LLM/MCP/Skill, fallback path, or motion constraint.
- Do not send live robot commands during implementation or verification.
- Keep vendor endpoints, types, fields, constants, and result paths in the Hardware Package mapping.

## Review Focus

- Action acceptance must not become command success without terminal success and fresh measured arrival.
- Transport timeout after dispatch must preserve outcome uncertainty.
- Mapping Engine must import without `rclpy`.
- ROS 2 Transport must not order canonical joints or convert degrees/radians.
- Mapping schema validation must reject incomplete right-arm bindings rather than guess values.

---

### Task 1: Typed Backend Transport protocol

**Files:**
- Create: `src/cross_embodiment/backend/protocol.py`
- Create: `src/cross_embodiment/backend/__init__.py`
- Test: `tests/unit/test_backend_transport_protocol.py`

**Interfaces:**
- Produces immutable `TransportRequest`, `TransportEvent`, `TransportResult` and `BackendTransport`.

- [ ] Write and run failing protocol tests.
- [ ] Implement the minimum dataclasses and Protocol.
- [ ] Run protocol tests green.

### Task 2: Transport-independent Mapping Engine

**Files:**
- Create: `src/cross_embodiment/mapping/schema.py`
- Create: `src/cross_embodiment/mapping/engine.py`
- Create: `src/cross_embodiment/mapping/__init__.py`
- Test: `tests/unit/test_interface_mapping_engine.py`

**Interfaces:**
- Consumes: `Command`, mapping YAML/dict, `TransportEvent`, `TransportResult`.
- Produces: validated mapping spec, `TransportRequest`, decoded `JointState`, decoded vendor result fields, completion policy.

- [ ] Write and run failing mapping tests for load, encode, decode, units, and no ROS dependency.
- [ ] Implement the minimum schema loader and engine.
- [ ] Run mapping tests green.

### Task 3: ROS 2 Transport implementation

**Files:**
- Create: `src/cross_embodiment/driver/ros2_transport.py`
- Modify: `tests/unit/test_ros2_action_transport.py`

**Interfaces:**
- Consumes: typed requests and subscription bindings already compiled by Mapping Engine.
- Produces: `TransportEvent` and `TransportResult` without SDK joint semantics.

- [ ] Update tests first and run them red.
- [ ] Move ROS lifecycle, subscription, ActionClient, timeout and cancellation mechanics.
- [ ] Run transport tests green.

### Task 4: Thin mapped Adapter Runtime and Hardware mapping migration

**Files:**
- Modify: `src/cross_embodiment/driver/ros2_mapped.py`
- Modify: `tests/unit/test_ros2_mapped_robot.py`
- Modify: `ce-hardware-weiyi-dual-o6/config/right_arm_ros2_mapping.yaml`
- Modify: `ce-hardware-weiyi-dual-o6/package.yaml`
- Modify: architecture and Hardware Package documentation.

**Interfaces:**
- Consumes: Mapping Engine and `BackendTransport`.
- Preserves: `MappedRos2Adapter` entry point and all public Robot behavior.

- [ ] Update tests for the new schema/runtime and run them red.
- [ ] Replace duplicated mapping/ROS code with composition.
- [ ] Update only the right-arm Hardware Package mapping and its digest.
- [ ] Run focused tests, full SDK suite, Hardware Package suite, and Demo offline preview.
