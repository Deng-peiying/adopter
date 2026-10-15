# Weiyi right-arm generated-package L3 runbook

This runbook validates one package generated from the isolated `robot_launch`
asset scan. It never resolves a package from the local registry and does not
use the existing Weiyi Hardware Package as a runtime fallback.

## Preconditions and evidence boundary

L1 and L2 completed without sending a motion command. The sealed independent
artifact is:

```text
/tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/hardware-package
sha256:ea8848c3228f16b979027b3c162911e7ad2710c128a5b8025837da038eb9ee56
```

The post-seal comparison found that endpoints, interfaces, fields, joint
order, units, MoveJ constants, result decoding, and right-arm limits match the
human package. Three completion policy values differ:

| Policy | Generated from raw example | Existing live-verified package |
| --- | ---: | ---: |
| Action timeout | 20 s | 90 s |
| Arrival tolerance | 0.03 rad | 0.015 rad |
| Settle window | 0.2 s | 1.0 s |

These values do not change the requested joint target, but they change when
the SDK declares the operation complete. Preserve the sealed L2 artifact.
Any reviewed L3 variant must be copied to a new directory, have updated asset
digests, pass L2 conformance again, and be named explicitly in the execution
record. Do not edit the sealed directory in place.

The read-only preflight below is permitted before that policy decision. Real
motion remains pending explicit onsite authorization.

## Terminal 1: start the vendor runtime

```bash
cd ~/文档/for_robot_dpy/robot_launch
conda deactivate 2>/dev/null || true
source setup.sh
ros2 launch robot_bringup dual_arm_hand.launch.py
```

Use the existing, operator-verified power and fault-recovery procedure. For a
normal power-on request and state check, the raw runtime exposes:

```bash
ros2 service call /wy_robot1/right_arm_set_power \
  arm_control_interface/srv/SetPower "{power_enable: true}"

timeout 10s ros2 topic echo /wy_robot1/right_arm_state --once
```

The state must be fresh, contain seven joint angles, report fault code `0`,
and report mode `104` before an L3 motion is considered.

## Terminal 2: read-only generated-package preflight

This command sets `control_enabled=False`, reads `Robot.get_joint_state()`,
and writes an execution record with `commands: []` and `motion_sent: false`.
It accepts only an explicit package directory; it does not search a registry,
cache, project, or default package location.

```bash
cd ~/文档/for_robot_dpy/.worktrees/body-aware-robot-agent-mvp/cross-embody-sdk
conda deactivate 2>/dev/null || true
source ~/文档/for_robot_dpy/robot_launch/setup.sh
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export ROS_LOG_DIR=/tmp/ce-onboarding/ros-log
mkdir -p "$ROS_LOG_DIR"

python3.10 -m cross_embodiment.cli onboard preflight \
  --package-root /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/hardware-package \
  --device right_arm \
  --output /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/l3-preflight.json \
  --json
```

Review the printed and recorded values:

- resolved package path and complete package-tree SHA-256;
- resolved mapping path and mapping SHA-256;
- backend ID and entrypoint;
- measured canonical joint state, source timestamp, mode, and fault code;
- `classification=preflight_read_only` and `motion_sent=false`.

If the command cannot read the state, classify the failure before motion as
`asset/runtime incompatible`, `mapping wrong`, or `backend wrong`. Do not
continue to Terminal 3.

## Operator-only target file

The target is not input to the generation Agent. It is prepared after L2 from
a target already exercised through the public SDK. The current acceptance
candidate changes only right joint 6 by `+0.10 rad` from the established lower
pose; the return target is captured from the fresh measured state immediately
before the probe.

Create this file outside the generated package:

```bash
cat > /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/operator-l3-target.yaml <<'YAML'
schema_version: l3-target/v0.1
evidence: previously verified right-arm public-SDK joint-6 probe
positions:
  arm.right.joint.0: -0.0033670878
  arm.right.joint.1: 1.4220001904
  arm.right.joint.2: -1.4747183164
  arm.right.joint.3: 0.2770752798
  arm.right.joint.4: -0.0200855609
  arm.right.joint.5: 0.0502848490
  arm.right.joint.6: 0.1708018420
YAML
```

This is an explicit full seven-joint absolute target. The L3 tool does not add
a step, speed, amplitude, or fallback target.

## Terminal 3: onsite operator acceptance

Run this only after Terminal 2 succeeds, the completion policy review is
resolved, the physical workspace is checked, and the onsite operator has the
existing hardware stop available.

```bash
cd ~/文档/for_robot_dpy/.worktrees/body-aware-robot-agent-mvp/cross-embody-sdk
conda deactivate 2>/dev/null || true
source ~/文档/for_robot_dpy/robot_launch/setup.sh
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export ROS_LOG_DIR=/tmp/ce-onboarding/ros-log
mkdir -p "$ROS_LOG_DIR"

python3.10 -m cross_embodiment.cli onboard accept-l3 \
  --package-root /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/hardware-package \
  --device right_arm \
  --target /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/operator-l3-target.yaml \
  --operator robot \
  --output /tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/l3-execution.json
```

The command performs another read-only preflight and prints the exact package,
mapping, backend, current state, and full probe target. Anything other than the
exact terminal response `EXECUTE L3` cancels with no motion command.

After authorization it performs exactly:

1. `Robot.move_joints("right_arm", full_probe_target)`;
2. only after terminal success and measured arrival, a second
   `Robot.move_joints("right_arm", fresh_initial_positions)`.

It does not call ROS2 directly. Each command record contains the target,
command ID when supplied by the SDK, dispatch and terminal status, ROS Action
backend status, vendor code, timestamps, measured state, maximum joint error,
and `arrival_confirmed`.

## Gate E classification

Gate E passes only when both command records report `status=succeeded`,
`arrival_confirmed=true`, and a newer measured state. Otherwise retain the
record and classify the result:

- `asset/runtime incompatible`: vendor binary/runtime cannot operate on the
  current OS, architecture, ROS environment, or dependency set;
- `mapping wrong`: endpoint, field, order, unit, or result decoding differs
  from the live driver;
- `backend wrong`: the selected transport cannot express or complete the ROS2
  interaction;
- `hardware validation failed`: the request reached the driver but the action
  failed, timed out, was rejected, or did not reach the measured target.

Do not publish, certify, merge, or push the generated package based on L1/L2
alone. A successful Weiyi L3 validates this ROS2 case only.
