# Unified Robot API Implementation Plan

**Goal:** Define and implement a capability-driven, vendor-neutral robot API, then align the current robot package and demo with it.

**Architecture:** SDK owns canonical action/state/result types and capability negotiation. Hardware packages translate canonical units and commands into each backend's native interface. Demo demonstrates API discovery, state observation, policy action, and result handling.

**Tech Stack:** Python 3.10+, dataclasses, YAML manifests, ROS 2 Humble hardware adapter.

**Spec:** `docs/architecture/unified-robot-api-v1.md`

## Work slices

1. Record interface evidence and unresolved semantics in `docs/architecture/interface-evidence-inventory.md`.
2. Add canonical action payloads, richer command results, capability reporting, and named-joint/cartesian mapping in `cross_embody_sdk`.
3. Align the embodiment manifest and adapter to individually named arm/hand actions; translate hand radians to/from the driver's integer coordinate and expose available arm pose state using explicit configured pose semantics.
4. Replace the demo readiness-only task with a capability/state/policy/action-result example that can run against a mock backend.
5. Review all declarations against adapter behavior and mark any endpoint/unit that the compiled artifacts do not establish as unresolved rather than claiming it is live-verified.

## Constraints

- Public SDK and manifest identifiers remain vendor-neutral.
- Existing array-based joint and group actions remain supported as a migration path.
- No robot connection or physical command is part of this implementation pass.
- Backend-specific topic names, generated messages, and unit conversion stay inside the hardware package.
- Do not advertise an action capability until there is an adapter mapping for it.

## Review focus

- Named joint maps must preserve canonical ordering only at the adapter boundary.
- Step limits must be checked per named joint, not by dictionary iteration order.
- Hand driver counts must map through the O6 calibration table to radians in both directions.
- Pose conversion must state and configure the six-value convention and frame.
- Command acceptance must not be represented as action completion.
