# Hardware Package Lifecycle Design

## Purpose

Turn a generated Hardware Package directory into a portable, immutable, and
inspectable installed package without coupling the lifecycle to ROS2, Weiyi,
or any other transport. The lifecycle is:

`build → install → list → inspect → activate → use → uninstall`

The existing project based `ce install`, resolver, lock file, and runtime
commands remain compatible. This addition supplies the missing package level
product surface.

## Safety boundary

`build`, `install`, `list`, `inspect`, `activate`, and `uninstall` only read or
write files. They never import a Backend entrypoint, create a Robot, connect to
a driver, start a process, enable a device, or issue a command.

`use` resolves an activated Robot Instance into a typed runtime description.
It validates the immutable package digest, package identity, Backend selection,
manifest, default configuration path, and instance binding. It does not import
the Backend or connect to hardware. Existing explicit runtime commands remain
responsible for opening a control session.

## Artifact format

`ce package build` validates the source package and creates a deterministic ZIP
artifact with the `.cepack` extension. The archive contains:

- the package tree under `package/`;
- `artifact.json` with schema version, package identity, source tree digest,
  Backend descriptors, external requirements, and artifact format.

Generated caches, VCS metadata, and root build/install/log directories are
excluded using the same rules as the existing immutable package digest. ZIP
entries have stable paths, timestamps, permissions, ordering, and compression,
so identical inputs produce identical bytes. Symlinks and unsafe archive paths
are rejected.

## Store and registry records

The SDK managed store defaults to `CROSS_EMBODIMENT_STORE` or
`~/.cross_embodiment`. The existing package layout is retained:

`packages/hardware/<package name>/<version>/`

One name/version identifies one immutable tree. Different versions and vendor
names coexist. Installing different content under an existing name/version is
an error.

Installation records are stored separately under:

`records/hardware/<package name>/<version>.json`

They contain package and artifact digests, Backend descriptors, external
requirements, installed path, installation time, and validation metadata.
Records do not claim ownership of external drivers.

## Activation and use

`ce package activate` takes an installed package reference and a Robot Instance
YAML. It verifies that the instance names the same package and exact version,
selects a compatible declared Backend, copies the instance document into the
store, and atomically writes:

`activations/<instance id>.json`

The activation records the package tree digest and Backend ID. Activation has
no runtime side effects. Rebinding the same instance is explicit and atomic.

`ce package use` loads this record and returns a runtime description containing
the installed package root, embodiment manifest, Backend, connection
configuration, Robot Instance, and recorded digests. It detects changed or
missing package content. This description is the protocol independent input to
an explicit runtime session; merely resolving it does not touch hardware.

## Uninstall

Uninstall removes one installed name/version and its installation record. It
refuses removal while any activation references that exact package. It never
deletes external drivers, ROS workspaces, shared libraries, Python packages, or
other versions. Empty SDK owned directories may be pruned.

## CLI

```text
ce package build --package-root DIR --output FILE.cepack
ce package install --artifact FILE.cepack [--store DIR]
ce package list [--store DIR] [--json]
ce package inspect NAME@VERSION [--store DIR] [--json]
ce package activate NAME@VERSION --instance INSTANCE.yaml [--store DIR]
ce package use --instance INSTANCE_ID [--store DIR] [--json]
ce package uninstall NAME@VERSION [--store DIR]
```

Every mutating command returns a structured result suitable for audit. The CLI
uses exact versions for activation and uninstall; version ranges stay in the
existing project resolver.

## Errors and integrity

- Invalid identities, versions, digests, asset paths, archive paths, and
  symlinks fail before store mutation.
- Build writes through a temporary file and atomically replaces the output.
- Install extracts to a temporary directory, validates identity/assets/tree
  digest, then atomically installs.
- Activation and record writes are atomic.
- Inspect and use verify the current tree digest against the install record.
- Uninstall refuses active packages and paths outside the SDK store.

## Compatibility and scope

No public Robot action, Mapping Engine behavior, Backend Protocol, ROS2
Transport, Weiyi endpoint, or completion policy changes. No remote registry,
dependency installer, driver launcher, package signing, or automatic hardware
startup is introduced.

## Acceptance

The clean room Weiyi runtime package can be built, installed, listed,
inspected, activated, and resolved for use in a temporary store without ROS2
being sourced. A second version can coexist. Active packages cannot be
uninstalled. After removing the activation, uninstall removes only SDK owned
package and record files. Existing tests and onboarding workflows continue to
pass.
