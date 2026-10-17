# v0.2 Package and Managed Runtime Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the Cross-Embodiment SDK around the v0.2 Hardware Package architecture, move design and planning documents out of `outputs/`, and provide a managed WY dual-arm/O6 hardware path that can start and supervise `robot_launch` without a separate manual ROS2 launch.

**Architecture:** Keep the core SDK independent of ROS and vendor libraries. Add versioned Package/Asset/Instance models, a local resolver and lock file, a managed Adapter process supervisor, and a Runtime safety/action pipeline. The WY backend remains optional and is loaded only when its ROS2 environment is available; the default path remains Mock and Dry-run.

**Tech Stack:** Python 3.10+, dataclasses, PyYAML, unittest, optional ROS 2 Humble/rclpy, subprocess-based Driver Host, YAML manifests, local filesystem package registry.

**Spec:** `docs/architecture/cross-embodiment-sdk-design-v0.2.md`

## Global Constraints

- Core package must not import ROS2, vendor SDKs, or hardware-specific libraries at import time.
- Hardware Package, Embodiment Manifest, Robot Instance, Policy Package, and lock data remain separately addressable.
- `control_enabled` defaults to `false`; Dry-run must never publish hardware commands.
- Runtime safety checks run before Adapter command dispatch; the Adapter performs a second hardware/backend gate.
- WY startup is managed by the Adapter, but privileged CAN setup must fail clearly when non-interactive authorization is unavailable; the Adapter must never store a sudo password.
- `outputs/` contains generated artifacts only. Architecture documents live under `docs/architecture/`; implementation plans live under `docs/superpowers/plans/`.
- Existing Mock Adapter and v0.1 EE tests remain passing throughout the refactor.
- Real-hardware tests are opt-in and are never part of the default test command.

## Review Focus

- Malformed package or asset references fail with a useful `PackageError` before any process starts; cover in package schema tests.
- A lock file with a digest or platform/backend mismatch is rejected; cover in resolver/lock tests.
- A managed WY process that exits before readiness is reaped and reported without leaving a child process; cover in supervisor tests.
- A stale/faulted/disabled robot state or a 26-dimensional action with wrong ordering/range is rejected before publish; cover in safety and WY mapping tests.
- `control_enabled=false` and Dry-run record mapped commands without ROS publication; cover in adapter tests.

### Task 1: Move architecture documents and establish repository layout

**Files:**
- Move: `outputs/cross-embodiment-sdk-design-v0.2.md` → `docs/architecture/cross-embodiment-sdk-design-v0.2.md`
- Move: `outputs/cross-embodiment-sdk-design.md` → `docs/architecture/cross-embodiment-sdk-design-v0.1.md`
- Create: `docs/README.md`
- Modify: `README.md`
- Test: `tests/test_repository_layout.py`

**Interfaces:** Produces stable documentation paths referenced by later tasks.

- [ ] **Step 1:** Write a layout test asserting both architecture documents are under `docs/architecture/`, no design/plan Markdown remains directly under `outputs/`, and `docs/superpowers/plans/` exists.
- [ ] **Step 2:** Run `python3 -m unittest tests.test_repository_layout -v`; verify it fails against the current layout.
- [ ] **Step 3:** Move the documents, add `docs/README.md` explaining architecture/specs/plans versus generated outputs, and update README links and examples.
- [ ] **Step 4:** Run the layout test and the existing suite; verify both pass.

### Task 2: Add v0.2 Package, Asset, Instance, and Lock models

**Files:**
- Create: `src/cross_embodiment/package.py`
- Create: `src/cross_embodiment/assets.py`
- Create: `src/cross_embodiment/instance.py`
- Create: `src/cross_embodiment/lock.py`
- Modify: `src/cross_embodiment/errors.py`
- Modify: `src/cross_embodiment/__init__.py`
- Test: `tests/test_package_models.py`

**Interfaces:** `load_package_manifest`, `load_robot_instance`, `load_lock`, `HardwarePackage.resolve_asset`, `HardwarePackage.select_backend`, and `EmbodimentLock.verify` with typed dataclass return values.

- [ ] **Step 1:** Write failing tests for package/asset/backend parsing, slot/variant resolution, instance overrides, and lock digest/platform validation.
- [ ] **Step 2:** Run `python3 -m unittest tests.test_package_models -v`; verify the expected missing-model failures.
- [ ] **Step 3:** Implement typed dataclasses and YAML loaders. Preserve raw vendor asset paths, distinguish source and derived assets, and raise typed `PackageError`, `AssetError`, or `DependencyError` for invalid data.
- [ ] **Step 4:** Run focused tests and add representative fixtures under `tests/fixtures/packages/`.
- [ ] **Step 5:** Run `python3 -m unittest discover -s tests -v`; verify legacy tests still pass.

### Task 3: Add local registry, resolver, and project lock generation

**Files:**
- Create: `src/cross_embodiment/registry.py`
- Create: `src/cross_embodiment/resolver.py`
- Create: `src/cross_embodiment/project.py`
- Create: `assets/catalog.yaml`
- Create: `projects/wy_dual_o6_demo/project.yaml`
- Test: `tests/test_registry_resolver.py`

**Interfaces:** `LocalRegistry.find`, `PackageResolver.resolve`, `Resolution.write_lock`, and `load_project`.

- [ ] **Step 1:** Write failing tests for local package discovery, preferred backend selection, project dependency resolution, and deterministic lock output.
- [ ] **Step 2:** Run the focused test file and verify failures.
- [ ] **Step 3:** Implement filesystem catalog lookup, the v0.2 version constraints used by examples, platform/backend filtering, and SHA-256 digest collection.
- [ ] **Step 4:** Add the WY project fixture with package, instance, policy, runtime, and safety references; verify the generated lock is stable across runs.
- [ ] **Step 5:** Run all tests and inspect the lock fixture for reproducibility.

### Task 4: Refactor Adapter and lifecycle contracts around managed processes

**Files:**
- Create: `src/cross_embodiment/driver.py`
- Create: `src/cross_embodiment/process.py`
- Modify: `src/cross_embodiment/adapters/base.py`
- Modify: `src/cross_embodiment/sdk.py`
- Modify: `src/cross_embodiment/errors.py`
- Test: `tests/test_process_supervisor.py`
- Test: `tests/test_adapter_lifecycle.py`

**Interfaces:** `ProcessSupervisor.start`, `wait_ready`, `stop`; `RobotAdapter.health`; idempotent configure/connect/enable/disable/disconnect; and `connect(..., control_enabled=False, dry_run=True)`.

- [ ] **Step 1:** Write failing supervisor tests using a short fake child process for startup, early exit, readiness timeout, SIGINT, and cleanup.
- [ ] **Step 2:** Run the focused tests and verify failures.
- [ ] **Step 3:** Implement process supervision with captured logs, deterministic cleanup, typed `DriverCrash`/`ConnectionError`, and no password handling.
- [ ] **Step 4:** Extend the Adapter Protocol and SDK lifecycle to support configure/health and managed startup while preserving Mock behavior.
- [ ] **Step 5:** Run lifecycle tests and the full suite.

### Task 5: Extract Runtime safety and extend action mapping

**Files:**
- Create: `src/cross_embodiment/safety.py`
- Create: `src/cross_embodiment/mapping.py`
- Modify: `src/cross_embodiment/runtime.py`
- Modify: `src/cross_embodiment/types.py`
- Modify: `src/cross_embodiment/manifest.py`
- Test: `tests/test_safety.py`
- Test: `tests/test_action_mapping.py`

**Interfaces:** `SafetyGuard.validate`, `ActionMapper.map`, and supported modes `ee_delta`, `joint_position`, and `bimanual_joint_position` with explicit dimensions, joint order, units, bounds, and frequency.

- [ ] **Step 1:** Write failing tests for finite values, dimensions, stale observations, fault/estop, per-joint bounds, max step/velocity, Dry-run, and 26-dimensional WY ordering.
- [ ] **Step 2:** Run focused tests and verify failures.
- [ ] **Step 3:** Implement `SafetyGuard` as the Runtime gate and `ActionMapper` as a pure mapping layer; keep adapter-specific checks outside the core guard.
- [ ] **Step 4:** Refactor `Runtime.apply` to run guard → mapping → Adapter dispatch and preserve existing EE delta behavior.
- [ ] **Step 5:** Run all focused and legacy tests.

### Task 6: Add the managed WY dual-arm/O6 Hardware Package

**Files:**
- Create: `packages/wy/dual_o6/package.yaml`
- Create: `packages/wy/dual_o6/embodiment.yaml`
- Create: `packages/wy/dual_o6/instance.example.yaml`
- Create: `packages/wy/dual_o6/config/safety.yaml`
- Create: `packages/wy/dual_o6/config/startup.yaml`
- Create: `src/cross_embodiment/adapters/wy_ros2.py`
- Create: `src/cross_embodiment/adapters/wy_process.py`
- Modify: `src/cross_embodiment/adapters/__init__.py`
- Modify: `src/cross_embodiment/sdk.py`
- Test: `tests/test_wy_package.py`
- Test: `tests/test_wy_mapping.py`
- Test: `tests/test_wy_adapter_dry_run.py`

**Interfaces:** `WyProcessAdapter` manages `robot_launch` CAN/ROS startup and waits for arm/hand state topics. `WyRos2Adapter` translates WY `ArmState`, `ArmRtCtrlCmd`, and O6 `JointState` messages when ROS2 is available. Core imports remain ROS-free. Defaults are `control_enabled=False`, `dry_run=True`. Native 7+7+6+6 ordering is declared in the manifest.

- [ ] **Step 1:** Write package and adapter tests with fake ROS message objects and a fake process supervisor; assert no ROS publisher is called in Dry-run.
- [ ] **Step 2:** Run focused WY tests and verify failures.
- [ ] **Step 3:** Add package manifests, safety/startup profiles, and mappings for `/wy_robot1`, arm state/RT topics, and O6 hand state/control topics.
- [ ] **Step 4:** Implement optional ROS2 loading and managed process startup. Fail clearly when ROS2, CAN authorization, or launch artifacts are missing.
- [ ] **Step 5:** Implement state conversion, 26-dimensional command splitting, health/readiness checks, and adapter-level command gating.
- [ ] **Step 6:** Run package/Dry-run tests without hardware; only run ROS graph checks when the user explicitly starts the hardware stack.

### Task 7: Add the single-project CLI and generated outputs policy

**Files:**
- Create: `src/cross_embodiment/cli.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `.gitignore`
- Test: `tests/test_cli.py`
- Test: `tests/test_docs_policy.py`

**Interfaces:** `ce install`, `ce validate`, `ce up`, `ce status`, `ce run`, and `ce down`; validation and install never start hardware; `up` delegates startup to the managed Adapter; `down` performs safe stop and cleanup.

- [ ] **Step 1:** Write failing CLI tests for validate, Dry-run up, lock generation, and no hardware start during validation.
- [ ] **Step 2:** Run focused tests and verify failures.
- [ ] **Step 3:** Implement the CLI entry point with explicit Dry-run defaults and structured errors.
- [ ] **Step 4:** Update README with the single-project workflow and document that `outputs/` is generated-only.
- [ ] **Step 5:** Run the complete suite and a CLI smoke test against `projects/wy_dual_o6_demo/`.

### Task 8: Final verification and architecture consistency review

**Files:**
- Modify: `docs/architecture/cross-embodiment-sdk-design-v0.2.md` only if implementation decisions reveal an inconsistency
- Create: `docs/verification/v0.2-refactor.md`

- [ ] **Step 1:** Run `python3 -m unittest discover -s tests -v`.
- [ ] **Step 2:** Run `python3 -m compileall src tests`.
- [ ] **Step 3:** Run `ce validate --project projects/wy_dual_o6_demo/project.yaml` with hardware startup disabled.
- [ ] **Step 4:** Verify core imports without ROS2 and the WY adapter reports a clear optional-dependency error.
- [ ] **Step 5:** Record test commands, results, hardware prerequisites, and whether any real motion test was run.

