# Installed Robot Instance Runtime API Design

## Purpose

Complete the missing public handoff from an activated Hardware Package to the
existing Unified Robot API. An application that has installed and activated a
`.cepack` must be able to create a `Robot` from its Robot Instance ID without
reading package internals, importing Onboarding code, or reconstructing a
vendor Mapping.

The public entry point is:

```python
robot = Robot.from_instance(
    "lab/right-arm-01",
    store="~/.cross_embodiment",
    allow_motion=False,
)
```

This work reuses the existing `Robot`, `RobotAdapter`, Mapping Engine, Backend,
Package Store, and safety behavior. It does not introduce another Robot API or
Adapter implementation.

## Verified capability boundary

The API exposes only capabilities declared by the installed embodiment
manifest and implemented by the selected Backend Mapping. For the validated
Weiyi right-arm package these are:

- measured joint state through `Robot.get_joint_state("right_arm")`;
- complete absolute joint-position targets through
  `Robot.move_joints("right_arm", positions)`;
- the existing typed `Robot.command(Action(...))` advanced entry point;
- the effective capability view through `Robot.capabilities()`.

The Onboarding capability ID `joint_position_state` describes evidence needed
to create the state binding. The runtime binding and public state concept are
canonically named `joint_state` and `JointState`. The conversion is performed
when the Hardware Package is generated; the public runtime does not add a
second state capability or infer aliases.

A complete absolute target remains mandatory. An application that wants to
change one joint reads a fresh state, copies all measured positions, changes
one value, then submits the complete dictionary. The SDK does not claim that
the vendor provides an independent single-joint operation.

Velocity, torque, trajectories, Cartesian motion, stop, power, left-arm, and
hand APIs are outside the current verified package and are not added here.

## Public API

### Construct a disconnected Robot

```python
from cross_embodiment import Robot

robot = Robot.from_instance(
    instance_id: str,
    *,
    store: str | Path | None = None,
    allow_motion: bool = False,
) -> Robot
```

`store=None` resolves `CROSS_EMBODIMENT_STORE`, then falls back to
`~/.cross_embodiment`, matching the package CLI. Construction performs these
deterministic operations:

1. resolve the exact activation with `PackageLifecycle.resolve_use()`;
2. verify the installed package digest, identity, version, Backend, manifest,
   connection file, and Store path;
3. verify that a declared Mapping path stays inside the package and identifies
   the declared Mapping asset;
4. load the selected Backend entrypoint and construct its Adapter;
5. compute immutable runtime provenance and the effective Mapping digest.

Construction does not call `adapter.connect()`, source ROS setup files, start a
Driver, enable a device, call a power service, or send a command.

### Explicit connection and context management

`Robot` gains these convenience methods around its existing `Lifecycle`:

```python
robot.connect() -> Robot
robot.close() -> None

with Robot.from_instance(...) as robot:
    state = robot.get_joint_state("right_arm")
```

`connect()` configures and connects the selected Adapter and returns the same
`Robot`. `__enter__()` calls `connect()` and `__exit__()` calls `close()`.
`close()` delegates to the idempotent lifecycle stop path so exceptions and
repeated cleanup do not leave the transport open.

Connection attaches to an already prepared external vendor Runtime. It does
not launch or enable that Runtime. The Weiyi Driver and controller power state
remain explicit deployment responsibilities.

### Motion permission

`allow_motion` defaults to `False`. It maps to the existing Adapter
`control_enabled` flag while keeping `dry_run=False`, so a default session can
read real state but the existing `SafetyGuard` rejects motion before dispatch.
An application must pass `allow_motion=True` to create a control-capable
session. This permission does not bypass state freshness, device readiness,
fault, joint-name, joint-limit, Mapping, or Backend checks.

The factory never changes controller power and never treats package activation
as motion authorization.

### Runtime provenance

An installed Robot exposes immutable, read-only provenance as
`robot.runtime_info`. Directly constructed legacy Robots may have
`runtime_info=None`.

```python
@dataclass(frozen=True)
class RuntimeInfo:
    instance_id: str
    package_name: str
    package_version: str
    package_tree_digest: str
    package_root: Path
    manifest_path: Path
    backend_id: str
    backend_entrypoint: str
    mapping_path: Path | None
    mapping_sha256: str | None
    allow_motion: bool
```

The object has a JSON-safe `to_dict()` representation for logs and diagnostics.
It intentionally omits credentials and arbitrary connection values.

## Shared Runtime loader

Installed package resolution moves out of the private
`cross_embodiment.onboarding.l3` implementation into a protocol-independent
Runtime module, for example `cross_embodiment.runtime.installed`. The module
owns:

- default Store resolution;
- immutable activation and package validation;
- manifest, Backend, and declared Mapping resolution;
- Backend entrypoint construction;
- `RuntimeInfo` creation;
- construction of the existing `Robot` with no connection side effect.

`Robot.from_instance()` and installed-package L3 preflight/acceptance call this
same loader. Onboarding remains responsible for evidence, generation,
conformance, and acceptance records; the normal application Runtime no longer
imports Onboarding to open an installed package.

The explicit generated-package L3 path may keep its candidate-specific loader.
The installed path must not search a generated directory, legacy Registry,
source checkout, old Mapping, or cache when Store resolution fails.

## Data flow

```text
Robot.from_instance(instance_id, store, allow_motion)
    -> PackageLifecycle.resolve_use(instance_id)
    -> verify activation + installed tree digest + exact package version
    -> load package.yaml + embodiment.yaml + selected Backend
    -> verify declared Mapping and compute Mapping digest
    -> load_backend_entrypoint()
    -> existing connect(adapter, manifest, control_enabled=allow_motion,
                        dry_run=False, manage_process=False)
    -> disconnected Robot + RuntimeInfo

robot.connect() / with robot
    -> existing Lifecycle.connect()
    -> existing Adapter.connect()

robot.get_joint_state(device)
    -> existing Adapter + Mapping + Transport state path

robot.move_joints(device, complete_target)
    -> existing Robot validation + SafetyGuard + ActionMapper
    -> existing Adapter + Mapping + Transport command path
```

## Capability and extension behavior

The factory does not hard-code Weiyi, seven joints, ROS endpoints, message
types, MoveJ, or right-arm names. Those remain package data. A package can
declare another joint count or device set without changing the factory.

Backend loading remains driven by `package.yaml`. A future Backend can be used
without changing `Robot.from_instance()` when it implements the existing
Adapter contract and has a package entrypoint. A Backend-specific package may
omit an interface Mapping; `mapping_path` and `mapping_sha256` are then `None`.
If a package declares a Mapping, it must be verified inside the immutable
package before the Adapter is constructed.

The effective capability view remains the intersection produced by the
Adapter between manifest declarations and active Mapping bindings. A manifest
declaration alone does not make an operation callable.

## Errors

Existing exception types are retained:

- missing activation or package: `FileNotFoundError`;
- invalid identity, digest, Store path, manifest, or Mapping provenance:
  `PackageError`;
- incompatible or unloadable Backend: `DependencyError`;
- connection lifecycle failure: `LifecycleError`;
- motion attempted without permission or outside safety constraints:
  `SafetyViolation` or the existing command rejection result.

Resolution fails closed. No fallback path or guessed Mapping is permitted.

## Compatibility

- Existing `Robot(adapter, manifest)` and `connect(...)` callers remain valid.
- Existing Robot action signatures and return types do not change.
- Mapping Engine, `Ros2Transport`, and verified Weiyi control semantics do not
  change.
- Package install, activate, use, and uninstall remain file-only operations.
- `Robot.from_instance()` imports and constructs the Backend only when the
  application explicitly asks for a runtime Robot.
- DeepSeek and Onboarding dependencies are unnecessary for normal package use.

## Example

```python
from cross_embodiment import Robot

with Robot.from_instance(
    "lab/weiyi-right-arm-01",
    store="/opt/cross-embodiment/store",
    allow_motion=True,
) as robot:
    print(robot.runtime_info.to_dict())
    print(robot.capabilities())

    measured = robot.get_joint_state("right_arm")
    if measured.status != "ready":
        raise RuntimeError(f"right_arm is {measured.status}")

    target = dict(measured.positions)
    target["arm.right.joint.6"] = 0.17
    result = robot.move_joints("right_arm", target)
```

The example assumes the external Driver is already running, the device has
been explicitly enabled, and the application has established an independently
reviewed target and authorization process.

## Acceptance tests

The implementation must prove, without sending hardware motion:

1. `Robot.from_instance()` resolves only the activated immutable Store package.
2. Factory construction does not call Adapter `connect`, `enable`, or command
   methods.
3. Store, package, manifest, Backend, and Mapping paths and digests are exposed
   in `RuntimeInfo` and match installed content.
4. Missing or changed activation/package content is rejected with no fallback.
5. The default read-only Robot can read state after explicit connection and
   rejects motion before Backend dispatch.
6. `allow_motion=True` routes a valid complete joint target through the
   existing action path without changing its semantics.
7. Effective capabilities exclude manifest actions without active bindings.
8. Context-manager exit closes the Adapter, including exceptional exit.
9. Installed-package L3 preflight and acceptance use the shared Runtime loader.
10. A fixed `.cepack` fixture can be installed, activated, resolved, and
    loaded without ROS, DeepSeek, vendor assets, or historical Mapping data.
11. Existing SDK regression tests continue to pass.

Real hardware execution is not repeated for this change. The implementation
reuses the already accepted command chain and makes its installed-instance
entry point public.
