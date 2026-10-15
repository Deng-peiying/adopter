# New Vendor Hardware Onboarding Runbook

This runbook starts with raw vendor assets and ends with an explicitly loaded,
operator-accepted Hardware Package. It does not use an existing package from
the target vendor as an answer source.

## 1. Choose a narrow capability scope

Declare only the capabilities needed for the first experiment. For the current
platform baseline:

```yaml
# scope.yaml
device_id: arm
capability_ids:
  - joint_position_state
  - joint_position
ordered_joints:
  - arm.joint.0
  - arm.joint.1
  # Continue in canonical order for the actual device.
```

Canonical names come from the platform integration scope. Vendor names and
array order must come from vendor evidence and be mapped explicitly.

## 2. Prepare the vendor asset directory

A suggested layout is:

```text
vendor-assets/
├── docs/                 # interface and lifecycle documentation
├── examples/             # real state/command examples
├── interfaces/           # .msg/.srv/.action, Python stubs, headers, IDL
├── config/               # joint order, units, limits, controller config
├── launch/               # launch and runtime configuration
├── runtime/              # permitted binaries/libraries and dependency data
└── models/               # optional URDF/Xacro/MJCF/USD/meshes
```

The physical layout may differ. The required facts are:

| Fact | Minimum useful source |
| --- | --- |
| State mechanism | subscription/callback usage, SDK getter, protocol response, or runtime capture |
| Command mechanism | action/client usage, SDK call, ABI function, or protocol request |
| Interface fields | message/action definition, signature/header, or authoritative protocol schema |
| Joint order and units | controller configuration or explicit vendor documentation |
| Limits | device-scoped configuration or documented limits |
| Result/fault semantics | checked vendor result fields and success/failure codes |
| Runtime | executable/library, OS/architecture, dependencies, launch sequence, permissions |

Compiled binaries and incomplete source are acceptable when the external
runtime is runnable and its public interface is evidenced. Source availability
is not itself a capability requirement.

## 3. Record platform and package identity

```yaml
# package-identity.yaml
package_name: vendor/model_generated
version: 0.1.0
vendor: vendor
model: model
device_id: arm
embodiment_type: single_arm
backend_id: ros2_mapped
backend_entrypoint: cross_embodiment.driver.ros2_mapped:MappedRos2Adapter
ros_distro: humble
os: linux
arch: x86_64
```

Choose a backend only after checking the real communication mechanism.

## 4. Create an isolated run

```bash
ce onboard inspect \
  --vendor-root /absolute/path/to/vendor-assets \
  --platform-root /absolute/path/to/cross-embody-sdk \
  --run-root /absolute/path/to/onboarding-run \
  --denied-root /absolute/path/to/old-vendor-package \
  --json
```

Review `asset-inventory.json`, `interface-evidence.yaml`, `platform-lock.yaml`,
and `isolation-manifest.yaml`. Missing/unknown assets remain explicit. Do not
place an existing vendor mapping inside an allowed root.

## 5. Build and validate deterministic candidates

```bash
ce onboard derive-candidates \
  --run-root /absolute/path/to/onboarding-run \
  --scope /absolute/path/to/scope.yaml \
  --json
```

For each capability, check these states separately:

- `candidate_valid`
- `interface_mapped`
- `execution_policy_complete`
- evidence IDs and field-level provenance
- conflicts and missing fields

Do not convert application defaults into vendor facts.

## 6. Run model-assisted semantic review

Use the formal typed-tool entry point after inspection and deterministic
assembly:

```bash
ce onboard agent \
  --run-root /absolute/path/to/onboarding-run \
  --platform-root /absolute/path/to/cross-embody-sdk \
  --identity /absolute/path/to/package-identity.yaml \
  --device arm \
  --capability joint_position_state \
  --capability joint_position \
  --joint arm.joint.0 \
  --joint arm.joint.1 \
  --provider deepseek \
  --model deepseek-chat \
  --json
```

Repeat `--joint` for the complete ordered device. The model may call only the
typed onboarding tools. Preserve `provider-transcript.json`, Tool Call IDs,
Tool Results, decisions, and rejections. Every scoped capability must end as
`mapped`, `gap`, `unsupported`, or `unknown`.

## 7. Generate a candidate package

When interface mappings are complete even if completion policy remains open:

```bash
ce onboard generate-candidate \
  --run-root /absolute/path/to/onboarding-run \
  --identity /absolute/path/to/package-identity.yaml \
  --json

ce onboard validate-candidate \
  --run-root /absolute/path/to/onboarding-run \
  --json
```

The candidate must remain non-executable and record all unresolved policy.
Failure at this stage means evidence, mapping, backend fit, schema, or
isolation is incomplete. It is not a reason to fill defaults silently.

## 8. Decide whether the existing backend fits

| Vendor interface | Current decision |
| --- | --- |
| ROS2 subscription state plus action goal | Use `ros2_mapped` when lifecycle/result semantics fit |
| ROS2 service, publisher, or streaming-only command | Extend/register a backend before claiming support |
| Python SDK only | Implement a Python Backend plugin/host |
| C/C++ headers and shared library | Implement a native host/plugin with explicit ABI/runtime checks |
| TCP/CAN/serial/shared memory | Implement a protocol Backend from authoritative documentation |
| Model assets only | State/control unsupported; model may support later derived kinematics only |

Backend work is code and requires its own tests and live validation. The
Onboarding Agent may produce a plugin requirement; it must not claim a missing
backend already exists.

## 9. Confirm Runtime Completion Policy separately

If timeout, arrival tolerance, or settle window is not vendor-declared, an
operator may confirm a reviewed policy with an honest source:

```bash
ce onboard confirm-policy \
  --run-root /absolute/path/to/onboarding-run \
  --timeout-s VALUE \
  --arrival-tolerance-rad VALUE \
  --settle-window-s VALUE \
  --source operator_configured_or_validated_test_policy \
  --operator NAME \
  --reference "review record" \
  --json
```

This step promotes the sealed candidate to a runtime package. It must not
rewrite vendor evidence or model decisions.

## 10. Run offline Conformance

Verify at least:

- package schema and asset digests;
- explicit package identity and provenance isolation;
- backend entrypoint;
- state decoding and goal encoding;
- vendor failure handling;
- timeout uncertainty;
- measured-arrival behavior.

Offline success means the contract is internally executable. It is not live
hardware evidence.

## 11. Run read-only preflight

Start the vendor runtime using its documented lifecycle. Enabling power may be
a separate vendor step. Then explicitly load only the generated package:

```bash
ce onboard preflight \
  --package-root /absolute/path/to/onboarding-run/hardware-package-runtime \
  --device arm \
  --output /absolute/path/to/preflight.json \
  --json
```

Require a fresh state, correct device dimension/order/unit, expected readiness,
zero or understood fault state, the printed package/mapping/backend paths and
digests, `commands: []`, and `motion_sent: false`.

## 12. Run one controlled L3 acceptance

Prepare a complete, previously reviewed absolute target outside the package.
The target must not come from the generation model. With an onsite operator:

```bash
ce onboard accept-l3 \
  --package-root /absolute/path/to/onboarding-run/hardware-package-runtime \
  --device arm \
  --target /absolute/path/to/l3-target.yaml \
  --operator NAME \
  --output /absolute/path/to/l3-execution.json
```

Proceed only when the previewed current state and target are correct. The
operator types `EXECUTE L3`. Pass only if the probe and return both have a
successful terminal result, an acceptable vendor result, and fresh measured
arrival.

## 13. Freeze the case

Archive:

- platform lock and source revision;
- inventory, evidence, candidates, coverage, backend fit;
- provider transcript, decisions, and replay result;
- candidate and runtime packages;
- policy record and source;
- Conformance reports;
- preflight and L3 execution records;
- SHA-256 manifest;
- a scope-limited conclusion and unresolved gaps.

Never update an accepted package in place. A material mapping, policy, backend,
or dependency change creates a new case version and requires new validation.

