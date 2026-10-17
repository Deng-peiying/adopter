# Weiyi right-arm generated-package L3 runbook

This runbook validates one package generated from the isolated `robot_launch`
asset scan. It never resolves a package from the local registry and does not
use the existing Weiyi Hardware Package as a runtime fallback.

## Preconditions and evidence boundary

L1 and L2 completed without sending a motion command. Gate D and its 638-record
evidence replay are archived under:

```text
<evidence-root>/weiyi-right-arm-20261015-gate-d
provider transcript sha256:4855dfe2450f15e913fdc7b1b508224314c9c6dd86c818703f5938bdca564f2b
```

The DeepSeek candidate maps the endpoints, interfaces, fields, joint order,
units, MoveJ constants, result decoding, and right-arm limits. It deliberately
leaves three operator Runtime Completion Policy values unresolved. Gate E uses
the following previously live-validated policy without presenting it as a
vendor declaration:

| Policy | Operator-confirmed value |
| --- | ---: |
| Action timeout | 90 s |
| Arrival tolerance | 0.015 rad |
| Settle window | 1.0 s |

These values do not change the requested joint target. They only define how
the runtime waits for and verifies completion. The command below preserves the
candidate and its interface evidence, writes a separate policy record, creates
`hardware-package-runtime`, and sends no ROS request:

```bash
: "${GATE_D_RUN_ROOT:?set GATE_D_RUN_ROOT to the sealed Gate D run directory}"

ce onboard confirm-policy \
  --run-root "$GATE_D_RUN_ROOT" \
  --timeout-s 90 \
  --arrival-tolerance-rad 0.015 \
  --settle-window-s 1.0 \
  --source previously_live_validated_runtime_policy \
  --operator robot \
  --reference "2026-10-13 Weiyi right-arm public SDK measured-arrival validation" \
  --json
```

The sealed runtime package used below is:

```text
<evidence-root>/weiyi-right-arm-20261015-gate-e/hardware-package-runtime
candidate package sha256:2ca45703f74a3005a5d57cf5d8d23aca255cb2dadf3140e3064f92acbe0d846c
runtime policy sha256:786ad9bf3f18691bd3670f25046f1ec1c7828a5ed09aec320a3a06ba99a0207e
runtime mapping sha256:f9bbd83f1c7de63869a912f0cf2bea08a140b0d5de14bc7b5eec4f569a3a7b17
runtime package sha256:ab9eeeba9e81aed0ae295da003372300e05f3fd4efeda84dddf9fbfad94befaf
```

Gate E / L3 passed on 2026-10-16 after successful read-only preflight and
explicit onsite authorization. The sealed evidence is under
`onboarding-evidence/weiyi-right-arm-20261015-gate-e/`; the commands below are
retained as the reproducible procedure.

## Terminal 1: start the vendor runtime

```bash
: "${VENDOR_RUNTIME_ROOT:?set VENDOR_RUNTIME_ROOT to the installed Weiyi runtime}"
cd "$VENDOR_RUNTIME_ROOT"
conda deactivate 2>/dev/null || true
source setup.sh
ros2 launch robot_bringup dual_arm_hand.launch.py
```

Driver launch and right-arm enable are separate Weiyi lifecycle operations.
Keep Terminal 1 running. After every driver launch or restart, and before any
SDK, Agent, Calibration, or L3 motion entry point, run the separate enable
operation in another terminal:

```bash
: "${VENDOR_RUNTIME_ROOT:?set VENDOR_RUNTIME_ROOT to the installed Weiyi runtime}"
cd "$VENDOR_RUNTIME_ROOT"
conda deactivate 2>/dev/null || true
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=0
source setup.sh

ros2 service call /wy_robot1/right_arm_set_power \
  arm_control_interface/srv/SetPower "{power_enable: true}"

timeout 10s ros2 topic echo /wy_robot1/right_arm_state --once
```

Do not assume that launching the driver enables the arm. The state must be
fresh, contain seven joint angles, report fault code `0`, and report mode `104`
before an SDK motion is considered. Mode `101` is not accepted as ready by the
generated package and must not proceed to authorization.

## Terminal 2: read-only generated-package preflight

This command sets `control_enabled=False`, reads `Robot.get_joint_state()`,
and writes an execution record with `commands: []` and `motion_sent: false`.
It accepts only an explicit package directory; it does not search a registry,
cache, project, or default package location.

```bash
: "${VENDOR_RUNTIME_ROOT:?set VENDOR_RUNTIME_ROOT to the installed Weiyi runtime}"
: "${GATE_E_PACKAGE_ROOT:?set GATE_E_PACKAGE_ROOT to the sealed runtime package}"
conda deactivate 2>/dev/null || true
source "$VENDOR_RUNTIME_ROOT/setup.sh"
export ROS_LOG_DIR=/tmp/ce-onboarding/ros-log
mkdir -p "$ROS_LOG_DIR"

ce onboard preflight \
  --package-root "$GATE_E_PACKAGE_ROOT" \
  --device right_arm \
  --output /tmp/ce-onboarding/weiyi-right-arm-20261015-gate-e-preflight.json \
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
cat > /tmp/ce-onboarding/weiyi-right-arm-20261015-gate-e-target.yaml <<'YAML'
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
: "${VENDOR_RUNTIME_ROOT:?set VENDOR_RUNTIME_ROOT to the installed Weiyi runtime}"
: "${GATE_E_PACKAGE_ROOT:?set GATE_E_PACKAGE_ROOT to the sealed runtime package}"
conda deactivate 2>/dev/null || true
source "$VENDOR_RUNTIME_ROOT/setup.sh"
export ROS_LOG_DIR=/tmp/ce-onboarding/ros-log
mkdir -p "$ROS_LOG_DIR"

ce onboard accept-l3 \
  --package-root "$GATE_E_PACKAGE_ROOT" \
  --device right_arm \
  --target /tmp/ce-onboarding/weiyi-right-arm-20261015-gate-e-target.yaml \
  --operator robot \
  --output /tmp/ce-onboarding/weiyi-right-arm-20261015-gate-e-execution.json
```

The command performs another read-only preflight and prints the exact package,
mapping, backend, current state, and full probe target. After trimming terminal
whitespace, anything other than `EXECUTE L3` cancels with no motion command.

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

## Recorded Gate E result

The 2026-10-16 onsite run loaded package tree
`b917fd226eec6771605034ffe0f518df33fadb805c1aeec1b9ae2b12ef1161e2`
and mapping
`f9bbd83f1c7de63869a912f0cf2bea08a140b0d5de14bc7b5eec4f569a3a7b17`.
The read-only preflight reported mode `104`, fault code `0`, and a fresh
seven-joint state.

The authorized round trip produced:

| Operation | Result | Backend status | Vendor code | Arrival | Maximum error |
| --- | --- | ---: | ---: | --- | ---: |
| probe | succeeded | 4 | 0 | confirmed | 0.000203252424 rad |
| return | succeeded | 4 | 0 | confirmed | 0.000142851961 rad |

Both measured state timestamps were newer than the pre-dispatch sample. The
adapter did not supply an optional `CommandResult.command_id`, so the evidence
preserves it as `null` and does not invent an identifier. The authoritative
records are `e4-live-preflight.json`, `e5-l3-execution.json`, and
`gate-e-acceptance-report.json` in the Gate E evidence directory.
