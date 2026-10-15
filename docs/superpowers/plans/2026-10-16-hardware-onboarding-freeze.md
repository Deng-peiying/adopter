# Hardware Onboarding End-to-End Freeze Plan

> **For agentic workers:** Execute this documentation and evidence audit sequentially; do not change runtime behavior.

**Goal:** Convert the successful Weiyi Gate D/E experiment into a reproducible, vendor-neutral onboarding workflow and a frozen reference case.

**Architecture:** Preserve Gate D/E artifacts as immutable evidence, trace the actual implementation from source, then publish one audit report, one new-vendor operator guide, and one versioned Weiyi reference manifest. Runtime code and verified mappings remain unchanged.

**Tech Stack:** Markdown, JSON/YAML evidence, Python source inspection, SHA-256.

**Spec:** User request dated 2026-10-16 in the active Hardware Onboarding thread.

## Global Constraints

- Do not alter Unified Robot API, Mapping Engine, Ros2Transport, or verified Weiyi mapping semantics.
- Do not call DeepSeek, ROS services/actions, or send robot motion.
- Keep `feature/body-aware-robot-agent-mvp`; do not merge, push, or open a PR.
- Distinguish DeepSeek judgments, deterministic tools, Codex repairs, and operator confirmations.

## Review Focus

- Archive hashes and decisions must match the sealed Gate D/E artifacts.
- Source references must name real functions and files.
- Generic framework files must contain no hidden Weiyi endpoint/type/default.
- Runtime policy must remain operator policy rather than vendor evidence.
- Claims must remain scoped to Weiyi right-arm ROS2 state and joint-position control.

### Task 1: Verify and freeze evidence

- [x] Verify Gate D/E checksums, transcripts, decisions, policy provenance, package identity, and L3 records.
- [x] Produce a machine-readable freeze manifest linking all authoritative artifacts.

### Task 2: Trace the actual implementation

- [x] Trace inputs/outputs/functions from raw asset scanning through generated package runtime and live SDK execution.
- [x] Record source paths and line numbers from the current commit.

### Task 3: Audit responsibility boundaries and leakage

- [x] Classify DeepSeek, deterministic tooling, Codex, and operator contributions.
- [x] Search SDK Core, Evidence Contract, matcher, generator, and backend for Weiyi-specific constants.

### Task 4: Publish reusable onboarding documentation

- [x] Write a new-vendor onboarding guide with minimum assets, schemas, capability scope, backend decision rules, gates, and manual interventions.
- [x] Write and version the Weiyi Reference Onboarding Case with evidence hashes and limitations.
- [x] Write the end-to-end audit report and link all three documents from the onboarding index/README.

### Task 5: Verify the freeze

- [x] Validate JSON/YAML syntax, checksums, links, source references, clean diffs, and unchanged runtime source.
- [x] Commit documentation only; do not push or merge.
