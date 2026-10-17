# Weiyi right-arm independent onboarding acceptance

Date: 2026-10-15  
Branch: `feature/body-aware-robot-agent-mvp`  
Run root: `/tmp/ce-onboarding/weiyi-right-arm-20261015-native-4`

## Isolation boundary

The generation input contained only the fixed SDK platform tree and the raw
`robot_launch` vendor/runtime tree. The following roots were denied until the
new L2 package had been generated, validated, and sealed:

- the existing `ce-hardware-weiyi-dual-o6` package;
- the existing `wy-dual-o6-demo` project.

The generated package did not contain credentials, cache files, runtime logs,
demo joint targets, or copies of the vendor runtime. It declares the existing
ROS2 runtime as an external dependency.

## L1 evidence result

The deterministic inventory recorded 1,368 assets. The evidence extractors
created 638 records without importing or executing vendor Python code.

Evidence used for the two scoped capabilities:

| Capability | Source evidence | Result |
| --- | --- | --- |
| `joint_position_state` | `examples/caiquan_demo.py`, `ArmState.msg`, `dual_arm_system.yaml` | Native candidate accepted |
| `joint_position` | `examples/caiquan_demo.py`, `ArmMove.action`, `dual_arm_system.yaml`, measured-arrival policy in the same example | Native candidate accepted |

The evidence establishes:

- `/wy_robot1/right_arm_state` with
  `arm_control_interface/msg/ArmState`;
- `/wy_robot1/right_arm_move_action` with
  `arm_control_interface/action/ArmMove`;
- `MoveJ`, `joint_angles`, six zero `cart_pose` values, vendor success code
  zero, and `error_description`;
- `arm_mode=104` as the ready/Idle value;
- seven right-arm vendor joints in controller order, radians, and controller
  soft limits;
- a runnable Humble/x86-64 ROS2 runtime despite incomplete driver source;
- the 7-axis URDF, meshes, headers, shared libraries, and executable driver.

The raw tree also contains `SetPower`, `StopMove`, `ArmRtCtrl`, hand, left-arm,
and other evidence. Those items remain discovered and unmapped because this
experiment only authorizes right-arm `joint_position_state` and
`joint_position`.

### Read-only graph evidence

The current managed execution environment denied the local sockets used by
`ros2 topic/action/service/node list` (`PermissionError: Operation not
permitted`). No graph evidence was fabricated. Endpoint evidence for L2 is
therefore static source usage plus type definitions, and runtime graph capture
remains pending for the operator environment. No action or service was sent.

## Agent decision boundary

The constrained `OnboardingAgent` read evidence through typed tools, submitted
two evidence-linked candidates, requested deterministic assessment and backend
fit, then invoked generation and validation. It had no shell, arbitrary read,
arbitrary write, verification-promotion, or motion tool.

This native run used the scripted provider against the same Agent API because
`DEEPSEEK_API_KEY` and the optional OpenAI-compatible client were absent from
the executing process. It proves the candidate and tool path, but it is not
reported as a live DeepSeek model call. The live provider remains a separate
environment acceptance item.

## L2 package result

Generated package:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-native-4/hardware-package`

Sealed package tree digest:

`sha256:ea8848c3228f16b979027b3c162911e7ad2710c128a5b8025837da038eb9ee56`

Conformance passed all checks:

1. package schema;
2. resolved package identity;
3. asset digests;
4. provenance isolation;
5. backend entrypoint;
6. canonical state decode;
7. full joint goal encode;
8. vendor failure-code handling;
9. timeout/cancel uncertainty;
10. terminal result plus measured arrival.

`motion_sent` remained `false` for inventory, assessment, generation, and
conformance.

## Post-seal independent comparison

Only after the L2 digest was sealed did the evaluator read the existing human
package. It found no difference in ROS2 endpoints, types, field mappings,
MoveJ constants, success-code handling, units, joint order, or right-arm joint
limits. Four material differences remain:

| Field | Independent candidate | Existing verified package | Disposition |
| --- | ---: | ---: | --- |
| Exposed devices | `right_arm` | left/right arms and hands | Expected: current scope is right arm only |
| Action timeout | 20 s | 90 s | Review before L3; do not silently copy |
| Arrival tolerance | 0.03 rad | 0.015 rad | Review before L3; do not silently copy |
| Settle window | 0.2 s | 1.0 s | Review before L3; do not silently copy |

The three timing/completion values came from raw example code. They are
execution policy, not new joint step, speed, or amplitude limits. The original
L2 artifact stays immutable so any post-comparison policy decision remains
auditable.

## Gate classification

- L1 asset/interface discovery: **passed offline**.
- L2 package generation and conformance: **passed offline**.
- Live DeepSeek orchestration: **pending environment credentials/client**.
- Read-only ROS graph capture: **pending outside the managed socket sandbox**.
- L3 real state/motion: **not run**; requires the separate runbook and explicit
  onsite operator authorization.

This result demonstrates the deterministic ROS2 onboarding path for the Weiyi
right arm. It does not claim support for Python SDK, native library, CAN/TCP,
serial, ROS2 Service/Publisher, or a second robot.
