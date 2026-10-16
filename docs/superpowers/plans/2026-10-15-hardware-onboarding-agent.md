# Hardware Onboarding Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a constrained Hardware Onboarding Agent that turns an allowed vendor asset tree plus frozen platform standards into an evidence-backed, independently generated Hardware Package for the Weiyi right arm, without reading the existing Weiyi mapping during generation.

**Architecture:** Deterministic scanners, schemas, capability matching, backend-fit checks, package generation, and conformance tests form the trusted onboarding toolchain. DeepSeek only orchestrates those typed tools and proposes evidence-linked candidates; it cannot promote evidence, invent interfaces, bypass validation, or write outside a new staging root. The existing Robot API, Mapping Engine, ROS2 Transport, and verified Weiyi runtime behavior remain unchanged.

**Tech Stack:** Python 3.10+, dataclasses, PyYAML, JSON Schema Draft 2020-12, XML/AST parsing, ROS2 interface files, optional OpenAI-compatible DeepSeek client, pytest/unittest, existing `ce` CLI and Hardware Package resolver.

**Spec:** `docs/architecture/cross-embodiment-sdk-design-v0.3.md` sections 16 and 25; `docs/architecture/robot-interface-mapping-v1-design.md`; this plan incorporates the 2026-10-15 independent-asset onboarding acceptance requirements.

## Global Constraints

- Work only on `feature/body-aware-robot-agent-mvp`; do not merge, push, create a PR, or modify `main`.
- Do not change the public `Robot` API, existing Mapping Engine semantics, ROS2 Transport behavior, or verified `wave_goodbye` parameters.
- Real acceptance covers only the working Weiyi `right_arm`; exclude the left arm, hands, bimanual synchronization, and a second vendor.
- Do not add joint step, speed, amplitude, or motion limits.
- Do not expose the existing `ce-hardware-weiyi-dual-o6` mapping, demo targets, or task logic to the generation agent.
- Vendor binaries and drivers may be referenced as external runtime assets; source rebuild is not required.
- A discovered type, symbol, or compilable source does not prove that a runtime endpoint or hardware capability works.
- Unknown units, frames, lifecycle rules, frequencies, endpoint names, and result semantics remain `unknown` until supported by evidence.
- Offline work may proceed automatically. Any real motion requires a separate operator-controlled command and explicit confirmation.
- API credentials are read from environment variables and never written to source, reports, prompts, fixtures, or generated packages.

## Review Focus

- An old Weiyi path, digest, endpoint answer, or mapping leaking into the generation context must make the isolation test fail.
- Generated capabilities whose evidence is only a message definition or binary symbol must remain discovered/unverified, not runtime verified.
- Symlink escapes, absolute paths, unreadable files, logs, caches, and multi-gigabyte binary trees must be handled without leaving the allowed roots or making inventory nondeterministic.
- Conflicting joint order, unit, endpoint, or frame evidence must produce an explicit conflict and block package generation for that capability.
- Read-only ROS graph evidence and real-motion authorization must remain separate; the onboarding CLI must never start motion as a side effect of scanning or validation.

---

## Planned File Layout

```text
cross-embody-sdk/
├── catalogs/
│   ├── capabilities/v0.1.yaml
│   └── backends/ros2_mapped_v0.1.yaml
├── schemas/
│   ├── capability/catalog.schema.json
│   ├── onboarding/asset-inventory.schema.json
│   ├── onboarding/interface-evidence.schema.json
│   ├── onboarding/capability-coverage.schema.json
│   ├── onboarding/backend-support.schema.json
│   └── mapping/interface-mapping-v1.schema.json
├── src/cross_embodiment/onboarding/
│   ├── __init__.py
│   ├── models.py
│   ├── catalog.py
│   ├── isolation.py
│   ├── inventory.py
│   ├── evidence.py
│   ├── capability.py
│   ├── backend_fit.py
│   ├── generator.py
│   ├── conformance.py
│   ├── workflow.py
│   ├── agent.py
│   ├── providers.py
│   └── extractors/
│       ├── base.py
│       ├── filesystem.py
│       ├── ros2.py
│       ├── python.py
│       ├── native.py
│       └── robot_model.py
├── tests/onboarding/
│   ├── fixtures/
│   └── test_*.py
└── docs/onboarding/
    ├── workflow.md
    ├── evidence-policy.md
    └── weiyi-independent-acceptance.md
```

Generated experiment output lives outside the source tree, for example:

```text
/tmp/ce-onboarding/weiyi-right-arm-<run-id>/
├── platform-lock.yaml
├── asset-inventory.json
├── interface-evidence.yaml
├── capability-coverage.yaml
├── missing-evidence.md
├── generation-provenance.json
└── hardware-package/
```

---

### Task 1: Freeze the platform contract and add the machine-readable Capability Catalog

**Files:**
- Create: `catalogs/capabilities/v0.1.yaml`
- Create: `schemas/capability/catalog.schema.json`
- Create: `src/cross_embodiment/onboarding/models.py`
- Create: `src/cross_embodiment/onboarding/catalog.py`
- Test: `tests/onboarding/test_capability_catalog.py`

**Interfaces:**
- Produces: `CapabilityDefinition`, `CapabilityCatalog`, `load_capability_catalog(path: Path) -> CapabilityCatalog`.
- Produces: canonical IDs with separate `binding_operations`, including `joint_position_state -> joint_state`, `joint_position -> joint_position`, and `ee_pose -> cartesian_pose`.

- [ ] **Step 1: Write failing catalog tests** for schema version, unique IDs, native/derived/unsupported/unknown status vocabulary, required units/frames/lifecycle fields, and the current operation aliases.
- [ ] **Step 2: Run `python -m pytest tests/onboarding/test_capability_catalog.py -v`** and verify missing catalog/model failures.
- [ ] **Step 3: Add `capability-catalog/v0.1`** covering the v0.3 atomic checklist while marking only `joint_position_state` and `joint_position` as required by the first Weiyi generation profile.
- [ ] **Step 4: Implement strict catalog loading**; reject unknown fields, duplicate IDs, missing semantic contracts, and boolean `supported` substitutes.
- [ ] **Step 5: Run the catalog test and existing SDK unit tests**; expect all pass and no runtime API diff.
- [ ] **Step 6: Commit** with `feat: add machine-readable capability catalog`.

### Task 2: Define onboarding evidence and coverage schemas

**Files:**
- Create: `schemas/onboarding/asset-inventory.schema.json`
- Create: `schemas/onboarding/interface-evidence.schema.json`
- Create: `schemas/onboarding/capability-coverage.schema.json`
- Create: `schemas/onboarding/backend-support.schema.json`
- Modify: `src/cross_embodiment/onboarding/models.py`
- Test: `tests/onboarding/test_onboarding_schemas.py`

**Interfaces:**
- Produces: `AssetRecord`, `EvidenceRecord`, `CapabilityAssessment`, `IntegrationStage`, `EvidenceLevel`, `MissingRequirement`.
- Integration stages are independent flags: `discovered`, `backend_expressible`, `mapped`, `offline_verified`, `runtime_read_verified`, `hardware_motion_verified`.

- [ ] **Step 1: Write failing schema tests** for valid records, missing/unknown data, conflicting evidence, and prohibition of `hardware_motion_verified` without an external execution record.
- [ ] **Step 2: Verify the tests fail** because the schemas and models are absent.
- [ ] **Step 3: Implement schemas and dataclasses** with immutable evidence IDs, relative source paths, SHA-256 digests, provenance, semantic claims, confidence boundary, and verification stage.
- [ ] **Step 4: Add status transition validation** so discovery never implies mapping or runtime verification.
- [ ] **Step 5: Run the schema tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: define onboarding evidence contracts`.

### Task 3: Add platform locking and isolation policy

**Files:**
- Create: `src/cross_embodiment/onboarding/isolation.py`
- Test: `tests/onboarding/test_isolation_policy.py`

**Interfaces:**
- Produces: `PlatformLock.capture(repo_root: Path, schema_paths: Sequence[Path]) -> PlatformLock`.
- Produces: `IsolationPolicy(vendor_roots, platform_roots, output_root, denied_roots)` with `authorize_read`, `authorize_write`, and `validate_generated_tree`.

- [ ] **Step 1: Write failing tests** for allowed vendor reads, staging-only writes, symlink escape rejection, absolute path rejection, and denial of the old Weiyi Package root.
- [ ] **Step 2: Run the isolation test and confirm failure.**
- [ ] **Step 3: Implement normalized path and symlink checks** without importing or executing vendor code.
- [ ] **Step 4: Implement `platform-lock.yaml` generation** containing SDK commit, catalog/schema digests, backend descriptor digests, Python version, OS, and architecture.
- [ ] **Step 5: Run the isolation tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: isolate onboarding inputs and outputs`.

### Task 4: Implement deterministic filesystem inventory

**Files:**
- Create: `src/cross_embodiment/onboarding/extractors/base.py`
- Create: `src/cross_embodiment/onboarding/extractors/filesystem.py`
- Create: `src/cross_embodiment/onboarding/inventory.py`
- Test: `tests/onboarding/test_filesystem_inventory.py`

**Interfaces:**
- Produces: `AssetExtractor.scan(context: ScanContext) -> list[AssetRecord]`.
- Produces: `InventoryBuilder.build(roots: Sequence[Path]) -> AssetInventory`.

- [ ] **Step 1: Write failing tests** for stable ordering, digests, source/generated/binary classification, cache/log exclusion, symlinks, unreadable files, and duplicate content.
- [ ] **Step 2: Verify the tests fail.**
- [ ] **Step 3: Implement the extractor registry and filesystem scanner** with explicit ignore configuration; do not execute files during inventory.
- [ ] **Step 4: Serialize and validate `asset-inventory.json`.**
- [ ] **Step 5: Run inventory tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: inventory vendor asset trees`.

### Task 5: Extract ROS2 packages, interfaces, launch evidence, and read-only graph evidence

**Files:**
- Create: `src/cross_embodiment/onboarding/extractors/ros2.py`
- Create: `tests/onboarding/fixtures/ros2_vendor/`
- Test: `tests/onboarding/test_ros2_extractor.py`

**Interfaces:**
- Produces: `Ros2Extractor.scan_files(context) -> list[EvidenceRecord]`.
- Produces: `RosGraphSnapshot.from_json(path: Path) -> RosGraphSnapshot`; graph capture itself is a separate explicit read-only command.

- [ ] **Step 1: Write failing tests** for package.xml, `.msg`, `.srv`, `.action`, installed IDL, launch argument/node extraction, namespace composition, empty Action feedback, and type-without-endpoint classification.
- [ ] **Step 2: Add a test proving `_move_action` binary text alone remains an endpoint candidate**, not a confirmed fully qualified endpoint.
- [ ] **Step 3: Implement pure file parsing**; do not import launch files or ROS Python modules.
- [ ] **Step 4: Implement optional graph snapshot ingestion** for topics/services/actions, types, and node names. Mark it `runtime_read_verified`, never motion verified.
- [ ] **Step 5: Run ROS2 extractor tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: extract ros2 onboarding evidence`.

### Task 6: Extract Python, native-library, and robot-model evidence

**Files:**
- Create: `src/cross_embodiment/onboarding/extractors/python.py`
- Create: `src/cross_embodiment/onboarding/extractors/native.py`
- Create: `src/cross_embodiment/onboarding/extractors/robot_model.py`
- Test: `tests/onboarding/test_language_and_model_extractors.py`

**Interfaces:**
- Python extraction uses AST only and returns modules/classes/functions/signatures without imports.
- Native extraction returns ELF platform, shared dependencies, exported symbols, public headers, and missing include references.
- Model extraction returns model format, joints, axes, limits, base/tip candidates, mesh references, and unresolved Xacro requirements.

- [ ] **Step 1: Write failing tests** proving vendor Python is not imported, missing C++ headers are reported, ELF architecture is captured, and URDF joint order/units remain evidence rather than runtime truth.
- [ ] **Step 2: Verify tests fail.**
- [ ] **Step 3: Implement Python AST and XML model extractors.**
- [ ] **Step 4: Implement an allowlisted native inspector** around `file`, `readelf`, and `nm -D -C`; record unavailable tools instead of failing the whole scan.
- [ ] **Step 5: Run extractor tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: inspect python native and model assets`.

### Task 7: Build the evidence matrix and deterministic capability matcher

**Files:**
- Create: `src/cross_embodiment/onboarding/evidence.py`
- Create: `src/cross_embodiment/onboarding/capability.py`
- Test: `tests/onboarding/test_capability_matching.py`

**Interfaces:**
- Produces: `EvidenceMatrix.build(inventory, evidence) -> EvidenceMatrix`.
- Produces: `CapabilityMatcher.assess(catalog, matrix, scope) -> CapabilityCoverage`.
- Consumes optional agent candidates only as `CapabilityCandidate(capability_id, evidence_ids, proposed_semantics)`.

- [ ] **Step 1: Write failing tests** for native, derived, unsupported, and unknown assessments; conflicting unit/order/frame evidence; and discovery/mapping/verification separation.
- [ ] **Step 2: Add Weiyi-shaped fixture tests** where `ArmState.joint_angles` and `ArmMove` are candidates, while `SetPower`, `StopMove`, and `ArmRtCtrl` remain discovered but unmapped.
- [ ] **Step 3: Implement evidence linking and conflict detection.**
- [ ] **Step 4: Implement the first profile matcher** for `joint_position_state` and `joint_position`; require explicit unit, ordered joints, endpoint/type evidence, request fields, result fields, and completion evidence.
- [ ] **Step 5: Run matching tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: match vendor evidence to canonical capabilities`.

### Task 8: Describe Backend support and compute backend fit

**Files:**
- Create: `catalogs/backends/ros2_mapped_v0.1.yaml`
- Create: `src/cross_embodiment/onboarding/backend_fit.py`
- Test: `tests/onboarding/test_backend_fit.py`

**Interfaces:**
- Produces: `BackendDescriptor` and `BackendFit.evaluate(coverage, descriptors) -> BackendFitReport`.
- The initial ROS2 descriptor truthfully supports subscriptions and actions with current mapping operations only; services and publishers produce `BackendPluginRequirement`.

- [ ] **Step 1: Write failing tests** proving ROS2 subscription/action fit passes and service/publisher/Python/native/raw-CAN requirements do not silently fit.
- [ ] **Step 2: Verify tests fail.**
- [ ] **Step 3: Implement descriptor loading and fit evaluation.**
- [ ] **Step 4: Emit a structured plugin requirement** containing missing mechanism, lifecycle semantics, evidence, and minimum tests; do not generate the plugin in the first experiment.
- [ ] **Step 5: Run backend-fit tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: evaluate onboarding backend fit`.

### Task 9: Add strict Mapping Schema and Hardware Package generation

**Files:**
- Create: `schemas/mapping/interface-mapping-v1.schema.json`
- Create: `src/cross_embodiment/onboarding/generator.py`
- Test: `tests/onboarding/test_package_generator.py`

**Interfaces:**
- Produces: `PackageGenerator.generate(coverage, evidence, backend_fit, output_root, package_identity) -> GeneratedPackage`.
- Generates `package.yaml`, `embodiment.yaml`, `config/right_arm_ros2_mapping.yaml`, asset references, digests, evidence report, and generated conformance tests.

- [ ] **Step 1: Write failing generator tests** for exact seven-joint named mapping, radian units, state decode, MoveJ goal encoding, result decoding, completion evidence, deterministic output, and refusal on conflicts/unknown required fields.
- [ ] **Step 2: Add a test ensuring generated manifests expose only scoped and mapped devices**, not all devices found in vendor assets.
- [ ] **Step 3: Implement the mapping JSON Schema to match current engine behavior**, without adding new engine operations.
- [ ] **Step 4: Implement deterministic package generation** using evidence IDs in generated metadata and no absolute vendor paths.
- [ ] **Step 5: Run generator tests and load the result with existing `load_package_manifest`, `load_manifest`, and `InterfaceMappingEngine`.**
- [ ] **Step 6: Commit** with `feat: generate evidence-backed hardware packages`.

### Task 10: Implement conformance and independent comparison runners

**Files:**
- Create: `src/cross_embodiment/onboarding/conformance.py`
- Create: `tests/onboarding/test_conformance_runner.py`
- Create: `tests/onboarding/fixtures/transport_replay/`

**Interfaces:**
- Produces: `ConformanceRunner.validate_generated_package(package_root: Path) -> ConformanceReport`.
- Produces: `IndependentEvaluator.compare(candidate_root, reference_root) -> SemanticDiff`; this evaluator runs only after generation and is never exposed to the agent.

- [ ] **Step 1: Write failing tests** for schema validation, asset digests, backend loading, state decode replay, goal encoding, result failures, timeout/cancel uncertainty, and measured-arrival behavior.
- [ ] **Step 2: Add isolation assertions** that fail when generated provenance includes denied reference files or when runtime resolution selects another package.
- [ ] **Step 3: Implement offline conformance using the existing mapping engine and fake transport.**
- [ ] **Step 4: Implement semantic comparison** for device scope, joint order, units, endpoints, fields, result codes, and completion policy; ignore formatting and file order.
- [ ] **Step 5: Run conformance tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: validate generated hardware packages`.

### Task 11: Add deterministic onboarding workflow and `ce onboard` CLI

**Files:**
- Create: `src/cross_embodiment/onboarding/workflow.py`
- Modify: `src/cross_embodiment/cli/__init__.py`
- Test: `tests/onboarding/test_onboarding_cli.py`

**Interfaces:**
- Produces: `OnboardingWorkflow.inspect`, `assess`, `generate`, and `validate`.
- CLI commands: `ce onboard inspect`, `ce onboard assess`, `ce onboard generate`, `ce onboard validate`, and `ce onboard report`.

- [ ] **Step 1: Write failing CLI tests** for explicit roots, scope, staging output, resume from artifacts, JSON output, denied old package root, and no network/ROS/motion side effects.
- [ ] **Step 2: Verify tests fail.**
- [ ] **Step 3: Implement workflow phases as restartable artifact transformations.**
- [ ] **Step 4: Implement CLI parsing and exit codes** that distinguish asset insufficiency, semantic conflict, backend gap, schema failure, and conformance failure.
- [ ] **Step 5: Run CLI tests and existing CLI tests** and expect pass.
- [ ] **Step 6: Commit** with `feat: add hardware onboarding workflow cli`.

### Task 12: Add constrained DeepSeek orchestration

**Files:**
- Create: `src/cross_embodiment/onboarding/providers.py`
- Create: `src/cross_embodiment/onboarding/agent.py`
- Modify: `pyproject.toml`
- Test: `tests/onboarding/test_onboarding_agent.py`

**Interfaces:**
- Produces: `OnboardingAgent.run(goal: OnboardingGoal, workflow: OnboardingWorkflow) -> OnboardingRunResult`.
- Provider uses `DEEPSEEK_API_KEY`, an explicit base URL, and configured model; credentials never enter prompts or artifacts.
- Agent tools expose inventory/evidence lookup, candidate submission, backend-fit query, generation, and validation. They do not expose arbitrary shell or filesystem writes.

- [ ] **Step 1: Write failing tests with a scripted model** that submits valid evidence-linked candidates, attempts unsupported promotion, invents an endpoint, requests a denied file, and retries after validator feedback.
- [ ] **Step 2: Verify tests fail.**
- [ ] **Step 3: Implement optional provider loading** so deterministic onboarding remains importable without agent dependencies.
- [ ] **Step 4: Implement typed tool orchestration and validator feedback**; only deterministic workflow code writes artifacts.
- [ ] **Step 5: Run agent tests without network** and expect pass.
- [ ] **Step 6: Commit** with `feat: orchestrate onboarding with deepseek`.

### Task 13: Run the isolated Weiyi L1/L2 experiment

**Files:**
- Create: `docs/onboarding/weiyi-independent-acceptance.md`
- Create in staging: all run artifacts and generated Hardware Package
- Do not modify: existing `ce-hardware-weiyi-dual-o6`

**Interfaces:**
- Consumes only the frozen platform contract, raw `robot_launch`, allowed runtime dependencies, and a right-arm scope file.
- Produces L1 inventory/evidence and L2 generated package/conformance reports.

- [ ] **Step 1: Create an isolation manifest** listing allowed SDK/catalog/schema roots, raw vendor roots, denied old Package/Demo roots, and a fresh staging root.
- [ ] **Step 2: Capture the platform lock and raw asset inventory.**
- [ ] **Step 3: Run L1 inspection** and confirm `ArmState`, `ArmMove`, seven right-arm joints, ROS2 runtime, URDF, platform ABI, and all missing/unknown evidence are recorded.
- [ ] **Step 4: If endpoints are not proven offline, capture a separate read-only ROS graph snapshot** with the driver running; do not send actions or call services.
- [ ] **Step 5: Run the Agent to produce candidate assessments** for only `joint_position_state` and `joint_position`.
- [ ] **Step 6: Generate the new Package and run L2 conformance.**
- [ ] **Step 7: After generation is sealed, run the independent semantic comparison** against the old Package and document every material difference without silently copying it.
- [ ] **Step 8: Commit only source/tooling/docs**, not caches, vendor runtime copies, credentials, logs, or staging artifacts, using `test: complete independent weiyi onboarding l2`.

### Task 14: Prepare and perform operator-controlled L3 acceptance

**Files:**
- Create: `docs/onboarding/weiyi-l3-runbook.md`
- Modify: generated Package metadata only after preserving the original L2 artifact digest

**Interfaces:**
- Produces: immutable `L3ExecutionRecord` containing resolved Package path/digest, mapping path/digest, backend entrypoint, state sample, command/result, action status, vendor code, and measured arrival.

- [ ] **Step 1: Write the L3 runbook** with separate driver, generated-package runtime, and operator terminals; commands must print resolved package/mapping/backend paths and digests.
- [ ] **Step 2: Add a read-only preflight command** that loads only the generated Package and calls `Robot.get_joint_state("right_arm")`.
- [ ] **Step 3: Verify there is no fallback** by temporarily making the old Package unavailable to the acceptance project and checking resolution still succeeds.
- [ ] **Step 4: Prepare one explicit full seven-joint absolute target using a previously verified target**, without exposing that target to the generation Agent.
- [ ] **Step 5: Stop before motion and obtain onsite operator authorization.**
- [ ] **Step 6: On authorization, execute exactly one SDK move and its return operation**, capturing terminal Action result and newer measured arrival for both.
- [ ] **Step 7: Classify L3 independently** as passed, asset/runtime incompatible, mapping wrong, backend wrong, or hardware validation failed.
- [ ] **Step 8: Do not commit, merge, push, or certify the generated Package until the user reviews L3 evidence.**

### Task 15: Document supported scope and future backend work

**Files:**
- Create: `docs/onboarding/workflow.md`
- Create: `docs/onboarding/evidence-policy.md`
- Modify: `README.md`

**Interfaces:**
- Documents the fixed contract, tool boundaries, L1/L2/L3 meanings, provider setup, outputs, and plugin-requirement path.

- [ ] **Step 1: Document the deterministic CLI workflow** independently of DeepSeek.
- [ ] **Step 2: Document Agent workspace/prompt boundaries** and why old mappings are denied during generation.
- [ ] **Step 3: Document evidence states and capability/integration separation.**
- [ ] **Step 4: Document current backend truth:** ROS2 subscription/action only; Python, native, raw protocol, ROS2 service/publisher remain future implementations.
- [ ] **Step 5: Add exact L1/L2 commands and link the separate L3 runbook.**
- [ ] **Step 6: Run documentation path checks and the complete offline suite.**
- [ ] **Step 7: Commit** with `docs: explain hardware onboarding workflow`.

---

## Milestone Gates

### Gate A — Platform standard ready

Tasks 1–3 complete. Catalog, evidence schemas, platform lock, and isolation rules are machine validated. No vendor scan starts before this gate.

### Gate B — Deterministic onboarding ready

Tasks 4–11 complete. The full L1/L2 workflow works without an LLM. This proves Agent failures can be separated from scanner/generator failures.

### Gate C — Agent orchestration ready

Task 12 complete. A scripted-model test proves the Agent cannot invent evidence, escape roots, or self-promote verification.

### Gate D — Weiyi L1/L2 accepted

Task 13 complete. A fresh Package is generated without old Weiyi answers and passes offline conformance. Differences are reviewed before any hardware action.

### Gate E — Weiyi L3 accepted

Task 14 completes only after explicit onsite authorization. Success proves the workflow for this Weiyi ROS2 case; it does not prove Python/C++/raw-protocol generalization.

## Explicit Non-Goals for This Plan

- Implementing ROS2 Service/Publisher, Python, Native, TCP, CAN, serial, or shared-memory Backends.
- Rebuilding the closed Weiyi driver from source.
- Generating left-arm, hand, bimanual, Cartesian, RT servo, or trajectory bindings.
- Modifying Operation Agent, MCP, Skill, calibration, FK/IK, or JointGoalPlan behavior.
- Automatically publishing or certifying generated packages.

## Final Verification Commands

```bash
cd cross-embody-sdk
python3 -m pytest tests/onboarding -v
python3 -m pytest tests/unit tests/integration tests/mock -v
python3 -m cross_embodiment.cli onboard validate \
  --run-root /tmp/ce-onboarding/weiyi-right-arm-<run-id>
```

Expected offline result: all onboarding and existing SDK tests pass; the generated Package resolves with the fixed SDK; only right-arm joint state and absolute joint position are exposed; no live command is sent.
