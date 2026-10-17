# Reference Onboarding Case: Weiyi Dual O6 Right Arm v0.1

## Identity and scope

| Field | Value |
| --- | --- |
| Case ID | `weiyi-dual-o6-right-arm/v0.1` |
| Device | `right_arm` |
| Capabilities | `joint_position_state`, `joint_position` |
| Backend | `cross_embodiment.driver.ros2_mapped:MappedRos2Adapter` |
| Runtime | ROS2 Humble, Linux x86-64, Python 3.10 |
| Gate D platform lock | `6fa287b988597245c00495d7ecec36ab31244499` |
| L3 CLI/runtime revision | `43f605d` |
| Final status | Gate D completed; Gate E / L3 passed |

## Isolated inputs

The real model run could read only the reviewed raw vendor directory and the
fixed platform. These roots were denied:

- existing `ce-hardware-weiyi-dual-o6`;
- `wy-dual-o6-demo`.

The reviewed input contained:

- `examples/caiquan_demo.py`;
- `examples/right_arm_return.py`;
- `ArmMove.action`;
- `ArmState.msg`, `ArmFault.msg`, `ArmFaultType.msg`, `ArmMotionError.msg`;
- `dual_arm_system.yaml`.

The full predecessor scan contained 1,368 assets and 638 evidence records. The
reviewed final run contained 8 assets and 18 evidence records.

## DeepSeek decision record

Transcript:

```text
onboarding-evidence/weiyi-right-arm-20261015-gate-d/
  gate-d-real-1/provider-transcript.json
SHA-256: 4855dfe2450f15e913fdc7b1b508224314c9c6dd86c818703f5938bdca564f2b
```

The final transcript has 6 assistant turns and 16 native Tool Calls with
matching Tool Results. DeepSeek accepted the state candidate and recorded the
joint-position completion policy as a gap. Saved-response replay retained the
interface mapping and generated a non-executable candidate.

## Accepted interface semantics

### `joint_position_state`

- Endpoint: `/wy_robot1/right_arm_state`
- Interface: `arm_control_interface/msg/ArmState`
- Positions: `joint_angles`
- Timestamp: `header.stamp`
- Mode: `arm_mode`; ready value `104`
- Fault code: `arm_fault.fault_code`
- Unit: radian
- Vendor order: seven configured right-arm joints
- Canonical order: `arm.right.joint.0` through `.6`

### `joint_position`

- Endpoint: `/wy_robot1/right_arm_move_action`
- Interface: `arm_control_interface/action/ArmMove`
- Target: `joint_angles`
- Constants: `move_type=MoveJ`, `cart_pose=[0,0,0,0,0,0]`
- Result: `error_code.value`; success code `0`
- Description: `error_description`
- Completion: terminal result plus fresh measured arrival

## Runtime policy boundary

The vendor evidence did not establish the final execution policy. The operator
confirmed a previously live-validated configuration:

- timeout: 90 s;
- arrival tolerance: 0.015 rad;
- settle window: 1.0 s;
- source: `previously_live_validated_runtime_policy`;
- `vendor_declared: false`.

Policy SHA-256:
`786ad9bf3f18691bd3670f25046f1ec1c7828a5ed09aec320a3a06ba99a0207e`.

## Generated artifacts

| Artifact | Digest |
| --- | --- |
| Candidate package | `2ca45703f74a3005a5d57cf5d8d23aca255cb2dadf3140e3064f92acbe0d846c` |
| Candidate mapping | `540b14e082d2b3a41883ca221d479636b14afcf52787980b20b43ed6b88cfb4b` |
| Runtime mapping | `f9bbd83f1c7de63869a912f0cf2bea08a140b0d5de14bc7b5eec4f569a3a7b17` |
| Generator runtime package | `ab9eeeba9e81aed0ae295da003372300e05f3fd4efeda84dddf9fbfad94befaf` |
| L3 loaded tree | `b917fd226eec6771605034ffe0f518df33fadb805c1aeec1b9ae2b12ef1161e2` |

Candidate Conformance passed seven checks. Frozen Runtime Conformance replay
passed ten checks: schema, identity, asset digests, isolation, backend,
state decode, goal encode, vendor failure, timeout uncertainty, and measured
arrival.

## Hardware evidence

Read-only preflight:

- fresh seven-joint state;
- `arm_mode=104`;
- `fault_code=0`;
- no commands and no motion.

Authorized L3:

| Operation | Status | Backend | Vendor code | Arrival | Maximum error |
| --- | --- | ---: | ---: | --- | ---: |
| Probe | succeeded | 4 | 0 | confirmed | 0.000203252424 rad |
| Return | succeeded | 4 | 0 | confirmed | 0.000142851961 rad |

The runtime returned to the fresh pre-probe measured state. The optional SDK
`command_id` was not supplied by the adapter and remains `null`; no identifier
was fabricated.

Authoritative evidence:

```text
onboarding-evidence/weiyi-right-arm-20261015-gate-e/
  e4-live-preflight.json
  e5-l3-execution.json
  gate-e-acceptance-report.json
  runtime-conformance-recheck.json
  GATE-E-ACCEPTANCE.md
  SHA256SUMS
```

## Reproduction lifecycle detail

Weiyi Driver startup and arm power enable are separate operations. After each
Driver launch or restart, call the vendor `SetPower` service and verify mode
104 and fault code 0 before using any motion entry point.

## Valid claim

This case proves that the isolated generated package can provide canonical
right-arm joint state and absolute joint-position control on the tested Weiyi
ROS2 runtime through the unchanged Unified Robot SDK.

It is a reference case for workflow structure and evidence quality. Vendor
endpoints, types, fields, constants, joint data, policies, and lifecycle values
must be rediscovered for every new robot.

