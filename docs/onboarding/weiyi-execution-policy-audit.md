# Weiyi L2 execution-policy evidence audit

Date: 2026-10-15

This audit preserves the first independent L2 result at
`/tmp/ce-onboarding/weiyi-right-arm-20261015-native-4` unchanged. Its generated
package tree digest is
`ea8848c3228f16b979027b3c162911e7ad2710c128a5b8025837da038eb9ee56`.

## Findings

The three values in that candidate came from
`robot_launch/examples/caiquan_demo.py`. They are application helper defaults,
not declarations in `ArmMove.action`, the controller configuration, or a
vendor interface contract.

| Candidate field | Raw value | Source | Actual source semantics | Disposition |
| --- | ---: | --- | --- | --- |
| Action timeout | 20 s | `movej(... timeout=20.0)` at line 220 | Python helper default used to wait for an Action server/result | Unconfirmed execution policy |
| Arrival tolerance | 0.03 rad | `wait_joint_near(... tol=0.03)` at line 196 | Euclidean norm over all seven joint errors at line 206 | Incompatible with the SDK mapping's maximum per-joint error unless an operator defines a conversion/policy |
| Settle window | 0.2 s | `wait_joint_near(... settle=0.2)` at line 196 | One sleep after the first threshold crossing at lines 208-213 | Not evidence of a continuous stable-arrival window |

Calls in the same demo override the timeout with 5 seconds and sometimes use a
0.15 second settle sleep. This confirms that the values are demo behavior, not
fixed controller semantics.

The existing human package uses 90 seconds, 0.015 rad, and 1.0 second. Those
values are a hidden comparison baseline and are not copied into a newly
onboarded package without an independent source or an explicit operator policy
decision.

## Toolchain correction

The ROS2 static extractor still preserves the values and source provenance, but
labels them `execution_policy_status: unconfirmed`. The capability matcher does
not accept unconfirmed application policies as evidence for the standard
`joint_position` completion contract.

As a result:

- discovery of `ArmMove`, its endpoint, fields, constants, result code, joint
  order, unit, and limits remains valid;
- `joint_position_state` can still be classified from the independent raw
  assets;
- `joint_position` remains incomplete until timeout, maximum per-joint arrival
  tolerance, and continuous settle-window policies have a reviewed source;
- generation and L3 motion are blocked while those required policies remain
  unresolved.

This is an evidence correction. It does not alter the SDK Robot API, Mapping
Engine, ROS2 Transport, old Hardware Package, or the preserved first L2 run.
