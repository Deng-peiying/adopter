# DeepSeek Provider / Orchestrator protocol audit

Date: 2026-10-15

This audit replaces the earlier loop of prompt changes and temporary exchange
scripts. It covers only the two scoped capabilities:
`joint_position_state` and `joint_position`.

## Frozen failure evidence

The failed runs are preserved without modification at:

- `/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-2`
- `/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-3`
- `/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-4`
- `/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-5`

`/tmp/ce-onboarding/deepseek-protocol-failure-evidence-manifest.json` records
the path, size and SHA-256 digest of each preserved artifact. The secret scan
result is stored in `/tmp/ce-onboarding/failure-secret-scan.txt`. API keys and
authorization headers are excluded from both files.

Run 2 and run 3 used a prompt-level JSON action convention. DeepSeek returned
JSON-shaped ordinary text and then a final text object. The old orchestrator
treated the final text as workflow completion even though both capabilities had
not received deterministic terminal decisions.

Run 4 and run 5 demonstrated native DeepSeek tool calling. A single assistant
response contained as many as sixteen calls. The old provider converted them
into private pending actions, discarded the native call IDs from the formal
orchestrator history, and the temporary exchange script maintained a second,
incompatible state machine. Later ordinary-text JSON was again interpreted as
an action or final answer.

## Root causes

1. The old provider returned one ad-hoc action rather than a complete provider
   turn, so zero, one and multiple native tool calls did not share one protocol.
2. Native tool-call IDs were not preserved across assistant calls and tool
   results. This made a multi-call response impossible to replay correctly.
3. The formal orchestrator did not own the complete assistant/tool message
   history. The temporary script supplied missing behavior and therefore became
   a conflicting second orchestrator.
4. Ordinary assistant text was accepted as a final onboarding result.
5. Completion depended on package conformance. A valid evidence conclusion of
   `gap`, `unsupported` or `unknown` therefore caused further model requests
   instead of ending capability assessment.
6. Values found in a vendor demo were incorrectly eligible as controller
   execution semantics. The separate execution-policy audit shows that 20 s,
   0.03 rad and 0.2 s are unconfirmed application behavior.

## Corrected protocol

`DeepSeekProvider` now returns a `ProviderTurn` containing ordinary content,
optional `reasoning_content`, and the complete tuple of native tool calls. Every
call retains its ID, name, raw argument JSON, decoded argument object and any
decode error.

The deterministic `OnboardingAgent` executes every call in the batch and
records one `ProviderToolResult` with the same call ID and name. The full batch
is appended to provider history before another model request or terminal
workflow return. Tool validation errors are normal structured results.

Thinking-mode `reasoning_content` is preserved unchanged on the assistant
message that is replayed with the corresponding tool results.

Ordinary text is retained as model output but is not a capability decision. The
orchestrator asks once for typed conclusions. A second consecutive text-only
turn stops further model requests and records unresolved capabilities as
`unknown`, but the run is marked `completed: false`. This avoids a retry loop
without treating ordinary text as successful onboarding completion.

Each scoped capability terminates independently as one of:

- `mapped`: a submitted candidate passed deterministic evidence matching;
- `gap`: relevant evidence exists but required binding or policy fields remain
  unresolved;
- `unsupported`: explicit evidence states that the capability is unsupported;
- `unknown`: the available evidence or model conclusion is insufficient.

An all-`mapped` result is eligible for executable package generation and full
L2 conformance. If both interface mappings are complete but Runtime Completion
Policy remains a recorded `gap`, the workflow can generate a non-executable
Candidate Hardware Package and run candidate conformance. Such a package has
no runtime entrypoint and is not L3-ready.

## Regression evidence

Sanitized response fixtures derived from the preserved real runs are stored in
`tests/onboarding/fixtures/deepseek_protocol/`. They cover native multi-call and
ordinary-text responses. The protocol tests additionally cover a single call,
malformed arguments, structured tool errors, terminal gaps, consecutive
text-only responses, final-batch result recording and thinking-mode reasoning
replay.

The formal model entry point is:

```text
ce onboard agent --run-root ... --platform-root ... --identity ... \
  --device right_arm \
  --capability joint_position_state --capability joint_position \
  --joint arm.right.joint.0 ... --joint arm.right.joint.6 \
  --provider deepseek --model deepseek-chat
```

It writes `agent-run.json`, `agent-capability-decisions.json`, and a sanitized
`provider-transcript.json`. The transcript contains model messages, native tool
calls and tool results; it does not contain API credentials or HTTP headers.
No temporary exchange runner participates in this path.

## Execution-policy boundary

The preserved first deterministic L2 candidate remains at
`/tmp/ce-onboarding/weiyi-right-arm-20261015-native-4`. Its package tree digest
is `ea8848c3228f16b979027b3c162911e7ad2710c128a5b8025837da038eb9ee56`.
It is historical evidence and is not rewritten.

The current extractor keeps the demo values with provenance but labels them as
unconfirmed execution policy. The matcher does not use them to satisfy
`timeout_s`, maximum per-joint `arrival_tolerance_rad`, or continuous
`settle_window_s`. Therefore the expected independent assessment is:

- `joint_position_state`: eligible for `mapped` when its complete interface
  binding is evidenced;
- `joint_position`: its interface candidate is accepted while the three
  execution policies remain a terminal `gap` until reviewed evidence or an
  explicit operator policy decision exists.

This expected gap is not a model failure and must not trigger repeated calls.

## First formal real-provider rerun

The operator ran the formal `ce onboard agent` entry point against the isolated
raw-asset run at
`/tmp/ce-onboarding/weiyi-right-arm-20261015-deepseek-formal-final`.
The provider protocol itself remained stable for 12 assistant turns and 46
native tool calls. All calls and results retained their IDs in
`provider-transcript.json`; no package or motion command was produced.

The run ended `completed: false` with both capabilities `unknown`. Seven mapping
candidates were rejected by the deterministic matcher. The final state
candidate proposed ROS transport activity (`subscribe`) as the canonical
`binding_operation`, while the platform Capability Catalog defines the
canonical operation as `joint_state`. The model context exposed the required
field name but not the catalog's allowed canonical values, so the model tried to
infer a platform constant from vendor ROS usage.

The corrected context now includes each scoped Capability's category, canonical
`binding_operations`, and semantic contract. This is platform schema exposure,
not a vendor default or a prompt-selected answer. Vendor endpoints, message
types, fields, units and policies must still be selected from evidence. The
failed real-provider run remains frozen and must not be overwritten by a later
rerun.
