# Hardware Package Lifecycle Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-16-hardware-package-lifecycle-design.md`

**Goal:** Add a protocol independent, offline package lifecycle on top of the
existing immutable local store without changing robot control semantics.

**Global constraints:** No Backend imports or hardware calls in lifecycle
operations. Preserve existing `ce install/up` behavior. Use exact package
identity and digest checks. Do not add Weiyi specific logic.

## Task 1: Deterministic package artifact

**Files:** `src/cross_embodiment/package/artifact.py`,
`tests/unit/test_package_lifecycle.py`

**Interfaces:**

- `build_package_artifact(package_root: Path, output: Path) -> ArtifactRecord`
- `inspect_package_artifact(path: Path) -> ArtifactRecord`
- `extract_package_artifact(path: Path, destination: Path) -> ArtifactRecord`

1. Add failing tests proving identical trees build byte identical `.cepack`
   files, cache files are excluded, manifest/assets are validated, symlinks are
   rejected, and unsafe/tampered archives cannot extract.
2. Run `pytest -q tests/unit/test_package_lifecycle.py -k artifact`; expect RED.
3. Implement deterministic ZIP creation, metadata parsing, and safe extraction.
4. Run the same command; expect PASS.
5. Commit `feat(package): add deterministic package artifacts`.

## Task 2: Installed package records and queries

**Files:** `src/cross_embodiment/package/lifecycle.py`,
`src/cross_embodiment/package/registry.py`,
`src/cross_embodiment/package/__init__.py`,
`tests/unit/test_package_lifecycle.py`

**Interfaces:**

- `PackageLifecycle.install(artifact: Path) -> InstalledPackageRecord`
- `PackageLifecycle.list() -> tuple[InstalledPackageRecord, ...]`
- `PackageLifecycle.inspect(reference: str) -> InstalledPackageRecord`

1. Add failing tests for atomic install, idempotent reinstall, immutable
   name/version conflict, multi-version coexistence, Backend/external
   requirement recording, and digest verification during inspect.
2. Run `pytest -q tests/unit/test_package_lifecycle.py -k 'install or list or inspect'`; expect RED.
3. Implement lifecycle records while reusing the existing store layout and
   directory digest.
4. Run the same command; expect PASS.
5. Commit `feat(package): add install records and package queries`.

## Task 3: Activation, use resolution, and safe uninstall

**Files:** `src/cross_embodiment/package/lifecycle.py`,
`tests/unit/test_package_lifecycle.py`

**Interfaces:**

- `PackageLifecycle.activate(reference: str, instance_path: Path) -> ActivationRecord`
- `PackageLifecycle.resolve_use(instance_id: str) -> PackageUse`
- `PackageLifecycle.deactivate(instance_id: str) -> None`
- `PackageLifecycle.uninstall(reference: str) -> UninstallResult`

1. Add failing tests that activation validates exact instance/package identity,
   writes only files, use detects digest drift, active uninstall is refused,
   deactivate permits uninstall, external dependency paths remain untouched,
   and package versions are independent.
2. Run `pytest -q tests/unit/test_package_lifecycle.py -k 'activate or use or uninstall'`; expect RED.
3. Implement atomic activation records, side effect free use resolution,
   reference aware uninstall, and owned directory pruning.
4. Run the same command; expect PASS.
5. Commit `feat(package): add activation and safe uninstall`.

## Task 4: Package lifecycle CLI

**Files:** `src/cross_embodiment/cli/__init__.py`,
`tests/integration/test_package_lifecycle_cli.py`

**Interfaces:** `ce package build|install|list|inspect|activate|use|deactivate|uninstall`.

1. Add failing CLI tests covering the complete lifecycle in a temporary store,
   JSON output, exact references, active uninstall refusal, and proving the
   package Backend is never imported.
2. Run `pytest -q tests/integration/test_package_lifecycle_cli.py`; expect RED.
3. Add the `package` subparser and dispatch using `PackageLifecycle`.
4. Run the same command; expect PASS.
5. Commit `feat(cli): expose hardware package lifecycle`.

## Task 5: Clean room acceptance and documentation

**Files:** `README.md`, `docs/package-lifecycle.md`,
`tests/integration/test_package_lifecycle_cleanroom.py`

1. Add a failing integration test that copies the clean room package fixture,
   runs the lifecycle with ROS unavailable, confirms a second version can
   coexist, and verifies no process, connection, enable, or command hook runs.
2. Run `pytest -q tests/integration/test_package_lifecycle_cleanroom.py`; expect RED.
3. Document commands, store layout, safety boundary, Runtime Package use, and
   migration from project based install. Add fixture data needed by the test.
4. Run focused lifecycle and existing registry tests; expect PASS.
5. Commit `docs(package): document lifecycle and clean room acceptance`.

## Task 6: Regression and wheel verification

1. Run `pytest -q`; expect all tests PASS.
2. Build a wheel, install it into a fresh temporary virtual environment, and
   execute the package lifecycle CLI against a fixture; expect PASS without
   repository `PYTHONPATH`.
3. Inspect `git diff`, verify no control semantics changed, and commit any
   packaging corrections as `fix(package): ship lifecycle assets`.

## Review Focus

- Archive traversal, symlink, and tampering rejection.
- Name/version identity ambiguity and immutable conflict behavior.
- Activation must never import a Backend or call hardware lifecycle methods.
- Uninstall must refuse active references and preserve external dependencies.
- Installed wheel must include every lifecycle module and expose every CLI
  command without relying on the source checkout.
