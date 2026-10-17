# v0.3 Package Boundary, Registry, and WY Project Refactor

## Goal

Align the repository with `docs/architecture/cross-embodiment-sdk-design-v0.3.md`: separate SDK core, installable WY Hardware Package, and user project; make package resolution and installation real; allow the WY project to start from its own declared package without referencing a developer-local vendor runtime path.

## Constraints and success criteria

- Keep the SDK core vendor-neutral and ROS-free at import time.
- Put WY-specific ROS message conversion, startup wiring, assets, and conformance tests in a separately installable Hardware Package.
- Make local Registry installation materialize a versioned package into the SDK-managed store, verify all declared asset digests, and write a complete lock.
- Resolve all WY launch paths from the installed Hardware Package; do not read or write another checkout at runtime.
- Keep the user project limited to project, instance, task, project config/calibration, and lock data.
- Treat ROS 2 Humble, OS packages, CAN hardware, and operating-system permissions as host prerequisites. Never store sudo credentials or silently configure privileged interfaces.
- Exclude build/install/log/cache/teleoperation data from any vendored runtime bundle. Do not run real hardware during implementation verification.

## Intended layout

```text
cross-embody-sdk/                 # core SDK, generic adapters, registry client, CLI
ce-hardware-weiyi-dual-o6/        # WY Hardware Package and its clean runtime bundle
wy-dual-o6-demo/                  # user project and instance-specific data
~/.cross_embodiment/              # installed package store, cache, registry config
```

During development these may be sibling repositories under the existing workspace parent. Runtime discovery must use package identity and installed package paths, never sibling checkout paths.

## Tasks

### 1. Asset and package integrity contracts

Add typed asset metadata for slot, format, package-relative path, source/derived status, and SHA-256. Resolve paths safely beneath the package root. Validate missing assets and digest mismatches before launch. Tests cover variants, traversal, missing files, and modified content.

### 2. Local package store and Registry installation

Implement a registry index for package versions and artifact locations, a local install store under `~/.cross_embodiment/packages`, atomic install/copy of local package artifacts, cache reuse, platform/backend selection, and useful dependency errors. `ce install` must install packages and produce a lock that records exact versions, backend, package digest, and asset digests. Installation must not launch hardware.

### 3. Generic Backend loading in SDK core

Define the SDK-side Backend/Adapter loading contract and load installed package entry points only after resolution. Remove direct WY imports and hard-coded `wy_ros2` dispatch from core. Preserve Mock operation and core import without ROS packages.

### 4. Standalone WY Hardware Package

Create the independent `ce-hardware-weiyi-dual-o6` distribution with its own package manifest, embodiment manifest, WY Adapter/process integration, launch/configuration, checksums, license notices, and package tests. Curate only the runtime files required for dual-arm/O6 startup from `robot_launch`; exclude generated and unrelated LeRobot/teleop artifacts. Convert startup and topic paths to package-relative configuration. CAN setup requires explicit host permission and fails with a clear instruction when unavailable.

### 5. Separate the WY user project

Move the demo project out of the SDK source repository. Keep project.yaml, robot instance, task/config, project-specific calibration, and generated lock in the user project. Replace `../../packages/...` and absolute launch paths with package/version and instance references.

### 6. CLI lifecycle and migration

Implement install → validate → up → run → down against the installed package and lock. `up` delegates process ownership to the installed package backend; `down` stops it. Preserve a Mock demo and provide migration guidance from the current in-repository catalog/project layout.

### 7. End-to-end verification and documentation

Run focused tests then the complete suite; test install into a temporary package store, relocation of the user project, and package startup command resolution from an installed package fixture. Verify no code path references a developer-local vendor runtime path. Document host prerequisites and explicitly record that no real motion test was run.

## Review risks

- The existing `robot_launch` tree is about 1.9 GB, including generated artifacts; only curated required files may enter the Hardware Package.
- The 460 MB vendor runtime contains compiled binaries and has no root license file. Keep this package local to the user's workspace and preserve embedded notices; do not publish it as an external artifact without explicit distribution rights.
- Native package installation removes checkout-path coupling, but still requires a compatible host OS/ROS2 environment and physical CAN devices.
- A standalone project checkout still resolves packages from the SDK-managed package store after `ce install`; it is not an offline single-directory bundle.
