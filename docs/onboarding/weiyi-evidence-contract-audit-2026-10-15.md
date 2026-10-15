# Weiyi Evidence Contract Audit — 2026-10-15

## Scope and conclusion

This audit covers only the Weiyi right-arm `joint_position_state` and
`joint_position` capabilities. No robot command was sent.

The original vendor assets are sufficient to map both interfaces. The previous
failure was caused by three platform issues:

1. the ROS2 Extractor and Matcher used different vocabulary for observed
   transport operations and canonical SDK operations;
2. interface facts and Runtime Completion Policy were treated as one all-or-
   nothing capability decision;
3. the Agent had to retype facts that deterministic extraction had already
   resolved.

The corrected result is:

| Capability | Candidate valid | Interface mapped | Completion policy complete | Status |
| --- | ---: | ---: | ---: | --- |
| `joint_position_state` | yes | yes | yes | `native` |
| `joint_position` | yes | yes | no | `unknown` because runtime policy is unresolved |

The second row is intentionally not promoted to executable. It can be emitted
as a Candidate Hardware Package and statically validated, while
`live_execution_ready` remains false.

## Shared contract

The versioned contract is declared by:

- `schemas/onboarding/evidence-contract.schema.json`
- `src/cross_embodiment/onboarding/evidence_contract.py`

The same Python contract is queried by the Matcher, deterministic candidate
builder, Generator, and Agent context. It defines candidate fields, required
facts, allowed evidence types, normalization rules, platform-owned values, and
which fields are unconfirmed runtime policy. The ROS2 Extractor emits the claim
names consumed by this contract.

No Weiyi endpoint, message type, fault path, MoveJ value, or fixed joint count
is present in the shared contract. Those values exist only in raw vendor
evidence, test fixtures, or generated output. Canonical joint names come from
the explicit onboarding scope.

## Field-level provenance

The following source locations are relative to the isolated `robot_launch`
vendor root used by the experiment.

### `joint_position_state`

| Candidate field | Source | Normalization |
| --- | --- | --- |
| `binding_operation` | `examples/caiquan_demo.py:128`, `examples/right_arm_return.py:46` | observed `subscribe` plus the catalog's single canonical operation becomes `joint_state` |
| `transport_kind` | the same `create_subscription` calls | normalized to `ros2_subscription` |
| `endpoint` | the same calls | statically resolved topic literal |
| `interface_type` | subscription import and constructor | qualified ROS2 message type |
| `positions_field` | `examples/caiquan_demo.py:144`, `examples/right_arm_return.py:78` | field read as measured joint array |
| `stamp_field` | `third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/msg/ArmState.msg:1` | shallow structural path ending in `stamp` |
| `mode_field` | `examples/caiquan_demo.py:143`, `examples/right_arm_return.py:73` | field read as arm mode |
| `ready_values` | `examples/caiquan_demo.py:170` | mode value used as ready/idle by vendor example |
| `fault_field` | `examples/right_arm_return.py:76` | numeric `arm_fault.fault_code`; `fault_type.value` is not substituted |
| `unit`, `joint_limits` | `third_party/wy_arm_sdk/install/arm_control_system/share/arm_control_system/config/dual_arm_system.yaml:77` and following joint entries | ordered vendor joint configuration |
| `ordered_joints` | explicit onboarding scope | platform canonical names; not represented as vendor names |

### `joint_position`

| Candidate field | Source | Normalization |
| --- | --- | --- |
| `binding_operation` | `examples/caiquan_demo.py:121` and action goal use | observed `send_action_goal` plus catalog canonical operation becomes `joint_position` |
| `transport_kind` | the same ActionClient construction | normalized to `ros2_action` |
| `endpoint`, `interface_type` | the same ActionClient construction | statically resolved action name and qualified type |
| `target_field`, `constants` | `examples/caiquan_demo.py:231` and adjacent goal assignments | dynamic joint array separated from constant goal fields |
| `target_unit`, `unit` | joint configuration at `third_party/wy_arm_sdk/install/arm_control_system/share/arm_control_system/config/dual_arm_system.yaml:77` | declared joint unit |
| `result_code_field`, `success_code` | `examples/caiquan_demo.py:253` and result handling | field compared with the success code |
| `result_description_field` | `third_party/wy_arm_sdk/install/arm_control_interface/share/arm_control_interface/action/ArmMove.action:9` | shallow structural description path |
| `ordered_joints` | explicit onboarding scope | platform canonical order |
| `state_binding` | mapped `joint_position_state` for this device | deterministic Adapter Runtime reference |
| `completion` | Adapter Runtime contract | terminal Action result plus fresh measured arrival |

The exact Evidence IDs and source line provenance are stored in the experiment
field matrix:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-deterministic-candidate-3/field-evidence-matrix.json`

## Runtime Completion Policy boundary

The vendor interface evidence does not declare these three values:

- `timeout_s`
- `arrival_tolerance_rad`
- `settle_window_s`

They remain structured gaps. Values seen in an old package or Demo are not
reclassified as vendor facts. A future explicit operator configuration,
platform policy, or validated test policy may resolve them with its own
provenance. Until then, the runtime package cannot be generated and live
execution is blocked.

This gives separate, auditable states:

- `candidate_valid`
- `mapping_complete`
- `execution_policy_complete`
- `offline_verified`
- `live_execution_ready`

## Deterministic L2 experiment

Run root:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-deterministic-candidate-3`

The run contains 1,368 inventoried assets and 638 evidence records. To avoid
another long full-tree rescan during contract iteration, it preserved the
frozen full evidence set and refreshed the eight relevant raw vendor files;
16 affected records were replaced. This limitation is recorded rather than
presented as a fresh full scan.

Interface coverage is 26/26 fields. Including runtime policy, state coverage is
12/12 and action coverage is 14/17, with the three policy gaps above.

The generated candidate is:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-deterministic-candidate-3/hardware-package-candidate`

The final implementation was also replayed through the public CLI at:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-deterministic-candidate-current`

After the independent review fixes, the eight raw files that supply every
required field were scanned again from source with the final Extractor. That
fresh Scanner → Evidence → Matcher → Generator → Conformance run is stored at:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-focused-raw-final-2`

It contains 8 inventoried assets and 18 evidence records. Both interface
mappings completed, the same three policy fields remained unresolved, and all
seven candidate conformance checks passed with `motion_sent: false`.

The frozen 1,368-asset/638-record Evidence set was also copied to a new replay
root and evaluated by the final Matcher and Generator without changing the
historical run:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-full-evidence-replay-final-2`

It produced the same two interface mappings, preserved exactly the three
Runtime Completion Policy gaps, generated a non-executable candidate package,
and passed the same seven candidate conformance checks.

Candidate conformance passed:

- package schema
- asset digests
- candidate mapping schema
- runtime execution blocked
- interface mapping complete
- execution policy gap recorded
- provenance isolation

The hidden, previously validated Weiyi mapping was read only after candidate
conformance. The comparison confirmed equivalent state transport/decode and
action transport/encode/result semantics. Its numeric runtime policy values
were recorded as external reference and were not copied into the candidate.

## Agent responsibility

The deterministic Scanner/Extractor/Builder assembles facts when exactly one
scoped, non-conflicting value exists. DeepSeek must inspect the candidate,
select supporting Evidence IDs, explain the Capability alignment, and record
gaps. It uses `accept_deterministic_candidate` for this review. It may use
`submit_candidate` when evidence is ambiguous or a different supported
interpretation is required.

This preserves Agent participation in semantic judgment without using the LLM
as a field-copying mechanism. `gap` and `unknown` are valid terminal decisions;
they do not trigger indefinite retries.

## Replay and test audit

The saved failed DeepSeek calls are replayed without model access. Tests cover
zero, one, and multiple tool calls; tool errors; text-only early completion;
Subscription and Action candidates; multiple evidence records; wrong endpoint,
field path, unit, joint order, and fault path; and unconfirmed completion
policy. One integration test starts from original vendor fixture files and runs
the actual Scanner, Evidence Matrix, deterministic builder, and Matcher.

Negative security assertions remain in place: the provider has no arbitrary
file or shell tool, cannot promote validation evidence, and receives no API
credential in its context.

Independent review added regressions for four evidence-association hazards:

- a transport endpoint associated with another configured device cannot be
  submitted for the scoped device;
- structural message/action paths must come from the candidate's exact
  `interface_type`;
- action result comparisons are scoped to the function constructing that
  action goal rather than copied across every ActionClient in a file;
- callbacks with the same method name in different classes retain their own
  message-field observations.

The final repository regression run reports `191 passed`. A Backend-fit gap now
also prevents the Agent run from claiming completion when no package was
generated.

## Real DeepSeek rerun status

One formal rerun was attempted through `ce onboard agent` at:

`/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-evidence-contract-final-1`

The current Codex execution sandbox rejected outbound network access before the
first model response (`Operation not permitted`, surfaced as
`openai.APIConnectionError`). Model response count and tool call count are both
zero. This is an environment failure, not a DeepSeek capability result, and is
not counted as Gate D success or failure.

The formal CLI and prepared isolated inputs remain available for one rerun in
the operator's network-enabled terminal. No temporary provider state machine is
required.

The Provider reads `DEEPSEEK_API_KEY` from the environment first and otherwise
loads the literal assignment from repository-local `.deepseek_credentials.py`.
That local file is mode `0600`, ignored by Git, parsed through `ast.literal_eval`
without executing it, and never copied into generated artifacts or transcripts.
