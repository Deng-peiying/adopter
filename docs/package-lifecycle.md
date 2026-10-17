# Hardware Package Lifecycle

The package lifecycle turns an Onboarding output directory into an immutable,
installed Hardware Package. It is independent of ROS2, Python SDKs, native
libraries, CAN, and other transport choices.

## Commands

```bash
ce package build \
  --package-root ./hardware-package-runtime \
  --output ./weiyi-right-arm-0.1.0.cepack \
  --json

ce package install \
  --artifact ./weiyi-right-arm-0.1.0.cepack \
  --store ~/.cross_embodiment \
  --json

ce package list --store ~/.cross_embodiment --json
ce package inspect weiyi/dual_o6@0.1.0 --store ~/.cross_embodiment --json

ce package activate weiyi/dual_o6@0.1.0 \
  --instance ./robot-instance.yaml \
  --store ~/.cross_embodiment \
  --json

ce package use \
  --instance lab/right-arm-01 \
  --store ~/.cross_embodiment \
  --json

ce package deactivate \
  --instance lab/right-arm-01 \
  --store ~/.cross_embodiment \
  --json

ce package uninstall weiyi/dual_o6@0.1.0 \
  --store ~/.cross_embodiment \
  --json
```

`CROSS_EMBODIMENT_STORE` sets the default store when `--store` is omitted.

## Safety behavior

The package commands do not import Backend entrypoints, source ROS setup files,
create ROS nodes, connect to drivers, start processes, enable devices, or send
commands. `activate` only stores an immutable package binding for one Robot
Instance. `use` resolves and validates that binding into a runtime description;
it reports `hardware_connected: false`.

Starting a driver, enabling a device, opening a Robot session, and permitting
control remain separate explicit runtime operations. Package installation never
performs them.

## Application runtime boundary

After activation, an application can open the installed instance through the
public `Robot.from_instance()` factory:

```python
from cross_embodiment import Robot

with Robot.from_instance(
    "lab/right-arm-01",
    store="/path/to/store",
    allow_motion=False,
) as robot:
    state = robot.get_joint_state("right_arm")
```

Factory construction validates the immutable Store package and constructs its
declared Backend without connecting it. Context entry explicitly connects to
an already running Driver. The default `allow_motion=False` permits state reads
and blocks every public Action before dispatch.

Driver Lifecycle remains an independent extension boundary. A future package
may declare an audited external process, managed child process, or managed
service and expose explicit `status/start/stop/health` operations. The current
factory does not start or stop a Driver, and `Robot.connect()` does not enable a
physical device.

## Store layout

```text
STORE/
├── packages/hardware/<namespace>/<name>/<version>/
├── records/hardware/<namespace>/<name>/<version>.json
└── activations/<instance-id>/
    ├── activation.json
    └── instance.yaml
```

Package contents are immutable for a given name and version. Several vendors
and versions can coexist. An install record captures the package tree digest,
artifact digest, Backend descriptors, Backend requirements, validation data,
and installation time.

Backend requirements describe external prerequisites. The SDK does not own or
delete vendor drivers, ROS workspaces, shared libraries, system packages, or
Python environments. Uninstall removes only the SDK managed package and record,
and refuses an exact version referenced by an activation.

## Onboarding handoff

Onboarding generates a Candidate Package and, after Runtime Completion Policy
confirmation, a Runtime Package. Build the Runtime Package directory into a
`.cepack`, then install and activate it. Candidate Packages that intentionally
lack a runtime Backend or completion policy remain unsuitable for a live Robot
session even though their interface mapping can pass static conformance.

The older project flow remains supported. `ce install --project ...` resolves a
catalog and writes `embodiment.lock`; `ce up` is still the explicit runtime
boundary. The package lifecycle adds direct artifact management and does not
change those commands.
