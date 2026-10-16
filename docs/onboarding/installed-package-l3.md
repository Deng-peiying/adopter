# Installed Hardware Package L3 path

The L3 commands can load either an explicit generated package directory or an
activated package from the immutable SDK Package Store. The installed path is:

```text
ce package install
  -> ce package activate
  -> ce package use / PackageLifecycle.resolve_use()
  -> ce onboard preflight --store ... --instance ...
  -> existing connect() and Robot.get_joint_state()
  -> ce onboard accept-l3 --store ... --instance ...
  -> existing Robot.move_joints() probe and return
```

The installed path validates the install record, package tree digest,
activation digest, selected Backend, embodiment manifest, and Mapping asset
before constructing the existing mapped ROS2 Adapter. It does not search the
legacy Registry or a generated package directory.

## Commands

```bash
ce package install --artifact robot.cepack --store "$STORE" --json
ce package activate vendor/model@1.0.0 \
  --instance instance.yaml --store "$STORE" --json
ce package use --instance lab/right-arm --store "$STORE" --json

ce onboard preflight \
  --store "$STORE" \
  --instance lab/right-arm \
  --device right_arm \
  --output preflight.json \
  --json

ce onboard accept-l3 \
  --store "$STORE" \
  --instance lab/right-arm \
  --device right_arm \
  --target target.yaml \
  --operator operator-name \
  --output l3-execution.json
```

Install, activate, and use only read and write package files. Preflight opens
the configured Backend with control disabled and sends no motion. `accept-l3`
prints the full live state and target, then requires the exact onsite input
`EXECUTE L3` before reloading the same activated Store package with control
enabled. The execution record includes `load_source=installed_activation`, the
Robot Instance ID, installed package digest, Store package path, Mapping path
and digest, Action terminal results, vendor return code, measured state, and
joint error.
