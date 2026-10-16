# Installed Robot Instance Runtime API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let applications create the existing Unified `Robot` from an activated immutable Hardware Package using `Robot.from_instance()`.

**Architecture:** Extract installed Store resolution from the private Onboarding L3 module into `cross_embodiment.runtime.installed`. The shared module validates immutable package provenance, constructs the selected existing Adapter without connecting it, and supplies `RuntimeInfo`; `Robot.from_instance()` and installed L3 both consume it.

**Tech Stack:** Python 3.10, dataclasses, pathlib, PyYAML, pytest, existing Package Lifecycle and Adapter protocols.

**Spec:** `docs/superpowers/specs/2026-10-16-installed-instance-runtime-api-design.md`

## Global Constraints

- Keep `Robot(adapter, manifest)` and existing action/return semantics compatible.
- Do not modify InterfaceMappingEngine, Ros2Transport, or verified Weiyi control semantics.
- Do not hard-code Weiyi, ROS endpoints, seven joints, device names, or execution-policy values.
- Factory construction must not connect, start, enable, or command hardware.
- `allow_motion=False` is the default and must reject commands before dispatch.
- Package Store activation is the only installed runtime source; no Registry, generated-directory, cache, or historical Mapping fallback.
- Driver launch and power enable remain explicit external deployment actions.
- Do not send real robot motion during implementation or verification.

## Review Focus

- A relative Mapping path containing `..` or an absolute Mapping path must fail before Backend construction (Task 1 tests).
- A changed installed package tree or mismatched activation digest must fail without fallback (Task 1 tests).
- A Backend without an interface Mapping must still construct with `mapping_path=None` when its package contract permits it (Task 1 tests).
- Repeated `close()` and exceptional context-manager exit must disconnect exactly once (Task 2 tests).
- An installed L3 run must preserve existing provenance and control flags while using the shared resolver (Task 3 tests).

---

### Task 1: Shared installed Runtime resolver

**Files:**
- Create: `src/cross_embodiment/runtime/installed.py`
- Modify: `src/cross_embodiment/runtime/__init__.py`
- Create: `tests/unit/test_installed_runtime.py`

**Interfaces:**
- Consumes: `PackageLifecycle.resolve_use(instance_id) -> PackageUse`, `load_package_manifest()`, `load_manifest()`, `load_backend_entrypoint()`, and existing `connect()`.
- Produces: `RuntimeInfo`, `ResolvedInstalledRuntime`, `resolve_installed_runtime(instance_id, store=None)`, and `create_robot_from_instance(instance_id, store=None, allow_motion=False, connect_fn=connect)`.

- [ ] **Step 1: Write failing resolver and construction tests**

Create fixture packages with a package-owned test Adapter and assert:

```python
resolved = resolve_installed_runtime("lab/arm01", store)
assert resolved.info.instance_id == "lab/arm01"
assert resolved.info.package_tree_digest == installed.package_tree_digest
assert resolved.info.mapping_path == installed_root / "config/mapping.yaml"
assert resolved.info.mapping_sha256 == sha256(mapping.read_bytes()).hexdigest()

robot = create_robot_from_instance("lab/arm01", store=store)
assert robot.runtime_info.allow_motion is False
assert adapter.connect_calls == 0
```

Add separate tests for package drift, escaping Mapping paths, a Backend with no Mapping, default Store resolution through `CROSS_EMBODIMENT_STORE`, and omission of connection secrets from `RuntimeInfo.to_dict()`.

- [ ] **Step 2: Run Task 1 tests and verify RED**

Run: `python3 -m pytest tests/unit/test_installed_runtime.py -q`

Expected: collection/import failure because `cross_embodiment.runtime.installed` does not exist.

- [ ] **Step 3: Implement the resolver and provenance types**

Implement:

```python
@dataclass(frozen=True)
class RuntimeInfo: ...

@dataclass(frozen=True)
class ResolvedInstalledRuntime:
    package_root: Path
    manifest: EmbodimentManifest
    backend: BackendSpec
    connection: dict[str, Any]
    info: RuntimeInfo

def resolve_installed_runtime(
    instance_id: str,
    store: str | Path | None = None,
) -> ResolvedInstalledRuntime: ...

def create_robot_from_instance(
    instance_id: str,
    *,
    store: str | Path | None = None,
    allow_motion: bool = False,
    connect_fn: Callable[..., Robot] = connect,
) -> Robot: ...
```

Resolve the default Store from `CROSS_EMBODIMENT_STORE` or
`~/.cross_embodiment`. Validate package assets and exact Store provenance.
Pass `dry_run=False`, `control_enabled=allow_motion`, `require_ros=True`, and
`manage_process=False` to the existing constructor. Do not call Robot or
Adapter lifecycle methods.

- [ ] **Step 4: Run Task 1 tests and verify GREEN**

Run: `python3 -m pytest tests/unit/test_installed_runtime.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/cross_embodiment/runtime/installed.py \
  src/cross_embodiment/runtime/__init__.py tests/unit/test_installed_runtime.py
git commit -m "feat(runtime): resolve installed robot instances"
```

### Task 2: Public Robot factory and lifecycle API

**Files:**
- Modify: `src/cross_embodiment/sdk/robot.py`
- Modify: `src/cross_embodiment/sdk/__init__.py`
- Modify: `src/cross_embodiment/__init__.py`
- Modify: `tests/unit/test_robot_joint_api.py`
- Modify: `tests/unit/test_installed_runtime.py`

**Interfaces:**
- Consumes: Task 1 `RuntimeInfo` and `create_robot_from_instance()`.
- Produces: `Robot.from_instance()`, `Robot.connect()`, `Robot.__enter__()`, `Robot.__exit__()`, idempotent `Robot.close()`, and public `RuntimeInfo` export.

- [ ] **Step 1: Write failing public API and lifecycle tests**

Add tests asserting:

```python
robot = Robot.from_instance("lab/arm01", store=store)
assert robot.runtime_info.instance_id == "lab/arm01"
assert robot.connect() is robot

with Robot(adapter, manifest) as active:
    assert active is robot
assert adapter.disconnect_calls == 1
robot.close()
assert adapter.disconnect_calls == 1
```

Test exceptional context exit, default read-only command rejection before
Adapter dispatch, and `allow_motion=True` routing the existing complete
joint-position Action without changing its payload.

- [ ] **Step 2: Run Task 2 tests and verify RED**

Run: `python3 -m pytest tests/unit/test_robot_joint_api.py tests/unit/test_installed_runtime.py -q`

Expected: failures for missing `Robot.from_instance`, `Robot.connect`, context methods, or `RuntimeInfo` export.

- [ ] **Step 3: Implement the public Robot surface**

Change the compatible constructor to:

```python
def __init__(
    self,
    adapter: Any,
    manifest: EmbodimentManifest,
    *,
    runtime_info: RuntimeInfo | None = None,
) -> None: ...
```

Use a local import inside `Robot.from_instance()` to avoid a module cycle.
Make `connect()` delegate to `self.lifecycle.connect()` and return `self`.
Make `close()` call `self.lifecycle.stop()`. Context entry connects; context
exit closes and returns `None`.

- [ ] **Step 4: Run Task 2 tests and verify GREEN**

Run: `python3 -m pytest tests/unit/test_robot_joint_api.py tests/unit/test_installed_runtime.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/cross_embodiment/sdk/robot.py src/cross_embodiment/sdk/__init__.py \
  src/cross_embodiment/__init__.py tests/unit/test_robot_joint_api.py \
  tests/unit/test_installed_runtime.py
git commit -m "feat(sdk): open Robot from installed instance"
```

### Task 3: Reuse the shared loader in installed L3

**Files:**
- Modify: `src/cross_embodiment/onboarding/l3.py`
- Modify: `tests/onboarding/test_l3_preflight.py`

**Interfaces:**
- Consumes: Task 1 `ResolvedInstalledRuntime` and its Robot constructor.
- Produces: installed preflight and round-trip paths using the same resolution and Adapter construction as `Robot.from_instance()`.

- [ ] **Step 1: Write a failing shared-loader L3 test**

Patch `cross_embodiment.onboarding.l3.resolve_installed_runtime` with a
recording wrapper and assert both `preflight_installed_package()` and
`execute_installed_package_round_trip()` call it with the requested Store and
instance. Preserve assertions for `load_source="installed_activation"`,
installed digest, Mapping path, `control_enabled=False` for preflight, and
`control_enabled=True` only after L3 authorization.

- [ ] **Step 2: Run Task 3 tests and verify RED**

Run: `python3 -m pytest tests/onboarding/test_l3_preflight.py -q`

Expected: the new shared-loader assertion fails because L3 still owns
`_load_installed_runtime()`.

- [ ] **Step 3: Refactor installed L3 paths**

Remove the private installed resolver. Convert `ResolvedInstalledRuntime` into
the arguments already consumed by `_preflight_runtime()` and
`_execute_runtime_round_trip()`. Construct installed Robots from the resolved
descriptor, while leaving the explicit generated-package path unchanged.

- [ ] **Step 4: Run Task 3 tests and verify GREEN**

Run: `python3 -m pytest tests/onboarding/test_l3_preflight.py -q`

Expected: all L3 tests pass with unchanged execution records.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/cross_embodiment/onboarding/l3.py tests/onboarding/test_l3_preflight.py
git commit -m "refactor(onboarding): share installed runtime loader"
```

### Task 4: User documentation and release verification

**Files:**
- Modify: `README.md`
- Modify: `docs/package-lifecycle.md`
- Modify: `docs/onboarding/installed-package-l3.md`
- Test: existing complete suite

**Interfaces:**
- Consumes: public `Robot.from_instance()`, `RuntimeInfo`, `connect()`,
  `get_joint_state()`, and `move_joints()` from Tasks 1–2.
- Produces: one clear application-development path after Package activation,
  with Driver start/power explicitly outside automatic SDK behavior.

- [ ] **Step 1: Add documentation contract assertions**

Extend the existing documentation policy test to require README examples for
`Robot.from_instance`, `allow_motion=False`, explicit external Driver setup,
and the complete-target single-joint pattern. Assert the docs do not claim
that install, activate, factory construction, or connection enables hardware.

- [ ] **Step 2: Run documentation tests and verify RED**

Run: `python3 -m pytest tests/integration/test_docs_policy.py -q`

Expected: failure because the public installed-instance Python example is not
yet documented.

- [ ] **Step 3: Document deployment and application use**

Update the README to distinguish:

1. external Driver start and device enable;
2. Package install and activation;
3. read-only Python use with `allow_motion=False`;
4. explicit motion-capable use with `allow_motion=True` and a complete target;
5. current verified capability limits;
6. optional future explicit Driver lifecycle support, which is not provided by
   the current Weiyi package.

Update package and L3 docs to name the shared installed Runtime loader and
public factory.

- [ ] **Step 4: Run focused and complete verification**

Run:

```bash
python3 -m pytest tests/integration/test_docs_policy.py -q
python3 -m pytest -q
python3 -m build
```

Expected: all tests pass; wheel and sdist build successfully; no ROS
connection or motion occurs.

- [ ] **Step 5: Inspect distribution contents**

Verify the built wheel contains `cross_embodiment/runtime/installed.py`, the
public exports, Catalogs, Backend descriptor, and all 13 Schemas. Install the
wheel into a clean temporary virtual environment and import `Robot` and
`RuntimeInfo` without vendor assets.

- [ ] **Step 6: Commit Task 4**

```bash
git add README.md docs/package-lifecycle.md docs/onboarding/installed-package-l3.md \
  tests/integration/test_docs_policy.py
git commit -m "docs(sdk): document installed Robot application API"
```

### Task 5: Final audit and remote handoff

**Files:**
- Inspect: all files changed since `5f7ac6a`
- No production behavior added beyond Tasks 1–4.

**Interfaces:**
- Consumes: complete branch implementation and verification evidence.
- Produces: reviewed commits ready for an explicit push to `dpy`.

- [ ] **Step 1: Review the complete diff against the design spec**

Check for SDK Core vendor leakage, automatic Driver/power behavior, fallback
paths, unsupported capability claims, secrets, absolute local paths, and API
compatibility regressions.

- [ ] **Step 2: Run final verification**

Run:

```bash
git diff 5f7ac6a --check
python3 -m pytest -q
```

Expected: clean diff check and complete green suite.

- [ ] **Step 3: Report and request the existing shared-branch push boundary**

Report commits, test/build results, API example, limitations, and whether the
branch is ready. Pushing `dpy` is a shared remote side effect and remains a
separate explicit final action.
