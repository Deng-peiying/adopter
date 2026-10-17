# Body-aware Robot Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a body-aware single Robot Agent that can execute the verified wave skill and create a new right-arm `JointGoalPlan` with deterministic KDL kinematics without exposing vendor interfaces or model-generated joint angles.

**Architecture:** The Hardware Package supplies explicit URDF and kinematic semantics assets. An optional SDK kinematics module wraps mature ROS URDF parsing and Orocos KDL. The Demo owns skills, task authorization, execution state, MCP tools, and a single-agent CLI; every motion still enters through the existing public Robot API.

**Tech Stack:** Python 3.10, PyYAML, ROS 2 Humble `urdf_parser_py`, PyKDL/Orocos KDL, MCP Python SDK, OpenAI Agents SDK, unittest.

**Spec:** `docs/superpowers/specs/2026-10-13-body-aware-robot-agent-mvp-design.md`

## Global Constraints

- Right arm only; never control or advertise the damaged left arm or hands in this MVP.
- Preserve the verified ROS 2 mapping/transport chain and all taught wave targets.
- Do not add joint step, speed, or amplitude constraints.
- Kinematics dependencies remain optional and absent from SDK core dependencies.
- `JointGoalPlan` means endpoint IK plus evidence, not collision-free or Cartesian-path validation.
- Agent and MCP code never import vendor ROS interfaces or generate joint angles.
- Task-level authorization allows bounded corrections; the model cannot authorize itself.
- Do not autonomously run live motion during implementation.

## Review Focus

- A malformed or mismatched canonical-to-URDF joint map must fail before FK/IK; Task 2 tests it.
- Missing optional KDL/URDF dependencies must leave the rest of the SDK importable; Task 2 tests it.
- An IK endpoint must never be labeled a validated path or Cartesian move; Task 3 tests serialized plan semantics.
- A correction outside the authorized goal/frame/tolerances/model digest must require new authorization; Task 5 tests containment.
- MCP timeout or process loss must not be reported as robot stop or task success; Task 6 tests execution status semantics.

---

### Task 1: Hardware kinematic assets and evidence

**Files:**
- Create: `../ce-hardware-weiyi-dual-o6/assets/kinematics/right_arm.urdf`
- Create: `../ce-hardware-weiyi-dual-o6/config/right_arm_kinematics.yaml`
- Create: `../ce-hardware-weiyi-dual-o6/docs/right-arm-kinematic-evidence.md`
- Modify: `../ce-hardware-weiyi-dual-o6/package.yaml`
- Modify: `../ce-hardware-weiyi-dual-o6/embodiment.yaml`
- Test: `../ce-hardware-weiyi-dual-o6/tests/test_kinematic_assets.py`

**Interfaces:**
- Produces: package assets `kinematic_model:urdf` and `kinematic_semantics:yaml`; canonical joint mapping; arm-local base/tip frames; explicit consistency status.
- Consumes: vendor-installed 7-axis URDF and existing verified manifest joint order.

- [ ] Write failing tests that require both digested assets, exact seven-joint canonical mapping, base/tip links present in the URDF, radian/metre units, and removal of unbacked live `ee_state` capability.
- [ ] Run `PYTHONPATH=../cross-embody-sdk/src python3.10 -m unittest tests.test_kinematic_assets -v`; expect failures for missing assets.
- [ ] Copy the vendor URDF without semantic edits, add the semantics/evidence files, update package digests, and make capability claims match implemented observation bindings.
- [ ] Run the hardware package suite and `git diff --check`; expect all tests to pass.
- [ ] Commit in the Hardware Package repository.

### Task 2: Optional KDL kinematics adapter

**Files:**
- Create: `src/cross_embodiment/kinematics/__init__.py`
- Create: `src/cross_embodiment/kinematics/types.py`
- Create: `src/cross_embodiment/kinematics/kdl.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_optional_kinematics.py`
- Test: `tests/unit/test_kdl_kinematics.py`

**Interfaces:**
- Consumes: Task 1 URDF and semantics assets through `HardwarePackage.resolve_asset_path`.
- Produces: `KinematicChain`, `IKResult`, `load_kdl_chain(...)`, `forward_kinematics(...)`, and `solve_inverse_kinematics(...)` with canonical named joints.

- [ ] Write a failing optional-import test proving `import cross_embodiment` works without importing KDL dependencies and that requesting an unavailable backend raises `DependencyError` with the required packages.
- [ ] Write failing FK/IK tests using the actual right-arm assets: exact canonical order, malformed mapping rejection, FK finite pose, IK seeded from a known state, IK-to-FK residual, and unreachable target failure.
- [ ] Run the two focused test modules and confirm failures are caused by missing kinematics APIs.
- [ ] Implement the thin `urdf_parser_py` + PyKDL adapter and typed results; keep dependencies in a `kinematics` optional extra/documented ROS dependency rather than core requirements.
- [ ] Run the focused tests and full SDK suite; expect all to pass.
- [ ] Commit in the SDK repository.

### Task 3: JointGoalPlan and evidence boundaries

**Files:**
- Create: `src/cross_embodiment/kinematics/planning.py`
- Create: `tests/unit/test_joint_goal_plan.py`
- Modify: `src/cross_embodiment/kinematics/__init__.py`

**Interfaces:**
- Consumes: Task 2 KDL APIs, `JointState`, target `Pose`, explicit position/orientation tolerances.
- Produces: `JointGoalPlan`, `JointGoalPlanner.plan(...)`, and `JointGoalPlanner.verify(...)`.

- [ ] Write failing tests that bind model digest/source timestamp/frame, preserve complete generated joints, reject missing frame/tolerance and failed IK, state `joint_space_move_to_ik_solution`, and never claim path or collision validation.
- [ ] Run `python3.10 -m unittest tests.unit.test_joint_goal_plan -v`; expect missing planner failures.
- [ ] Implement the minimal planner and verifier around Task 2; do not call Robot or ROS.
- [ ] Run focused and full SDK suites; expect all to pass.
- [ ] Commit in the SDK repository.

### Task 4: Model consistency experiment and execution gate

**Files:**
- Create: `../ce-hardware-weiyi-dual-o6/tests/fixtures/right_arm_live_samples.yaml`
- Create: `../ce-hardware-weiyi-dual-o6/tools/check_right_arm_kinematics.py`
- Modify: `../ce-hardware-weiyi-dual-o6/docs/right-arm-kinematic-evidence.md`
- Test: `../ce-hardware-weiyi-dual-o6/tests/test_kinematic_consistency.py`

**Interfaces:**
- Consumes: Tasks 1-2 assets/APIs and operator-recorded joint/ArmState samples.
- Produces: machine-readable consistency report with evidence levels and `dynamic_execution_ready` gate.

- [ ] Write failing tests for continuity over recorded wave states, independent vendor-pose sample comparison when its convention is declared, unresolved orientation/frame reporting, and a false execution gate when required evidence is missing.
- [ ] Run the focused test and confirm the report/gate APIs are absent.
- [ ] Implement the offline experiment tool and committed evidence fixture; never turn an IK-to-FK round trip into a real-model consistency pass.
- [ ] Run the tool and hardware suite, record actual findings, and set the gate from evidence rather than expectation.
- [ ] Commit in the Hardware Package repository.

### Task 5: Skill registry and task authorization

**Files:**
- Create: `../wy-dual-o6-demo/robot_app/robot_loader.py`
- Create: `../wy-dual-o6-demo/robot_skills/contract.py`
- Create: `../wy-dual-o6-demo/robot_skills/registry.py`
- Create: `../wy-dual-o6-demo/robot_skills/wave_goodbye.py`
- Create: `../wy-dual-o6-demo/skills/wave_goodbye.yaml`
- Create: `../wy-dual-o6-demo/robot_control/authorization.py`
- Modify: `../wy-dual-o6-demo/tasks/wave_goodbye.py`
- Test: `../wy-dual-o6-demo/tests/test_skill_registry.py`
- Test: `../wy-dual-o6-demo/tests/test_task_authorization.py`
- Modify: existing Demo wave tests.

**Interfaces:**
- Consumes: public `Robot`, existing wave constants, Hardware Package capabilities/model digests.
- Produces: reusable `RobotSkill`, `SkillRegistry`, unchanged CLI behavior, `TaskAuthorization`, and containment checks for correction plans.

- [ ] Write failing tests for exact wave behavior, capability-based discovery, no vendor imports, unchanged CLI plan, authorization binding fields, correction containment, and reauthorization on material change/exhaustion.
- [ ] Run focused tests and confirm missing modules fail.
- [ ] Extract the current task logic without changing targets; implement registry and task-level authorization without an agent-supplied approval boolean.
- [ ] Run Demo tests and offline wave preview; expect unchanged plan output.
- [ ] Commit in the Demo repository.

### Task 6: Execution manager and MCP service

**Files:**
- Create: `../wy-dual-o6-demo/robot_control/execution.py`
- Create: `../wy-dual-o6-demo/robot_mcp/service.py`
- Create: `../wy-dual-o6-demo/robot_mcp/server.py`
- Create: `../wy-dual-o6-demo/requirements-agent.txt`
- Test: `../wy-dual-o6-demo/tests/test_execution_manager.py`
- Test: `../wy-dual-o6-demo/tests/test_mcp_service.py`

**Interfaces:**
- Consumes: Tasks 3-5 plans, skills, authorization, Robot loader.
- Produces: single-task execution records and the ten typed MCP tools in the spec over local Streamable HTTP.

- [ ] Write failing tests for read-only tools, skill/planner selection surfaces, disabled control, single active task, command ID preservation, timeout/unknown outcome semantics, authorization containment, and absence of raw joint/ROS/stop tools.
- [ ] Run focused tests and confirm missing service/executor failures.
- [ ] Implement a deterministic service independent of MCP decorators, then thin MCP wiring; keep Agent/MCP dependencies outside SDK core.
- [ ] Run focused and full Demo suites; expect all to pass.
- [ ] Commit in the Demo repository.

### Task 7: Single Robot Agent and offline end-to-end scenarios

**Files:**
- Create: `../wy-dual-o6-demo/robot_agent/instructions.py`
- Create: `../wy-dual-o6-demo/robot_agent/cli.py`
- Create: `../wy-dual-o6-demo/tests/test_agent_contract.py`
- Create: `../wy-dual-o6-demo/docs/agent-mvp.md`
- Modify: `../wy-dual-o6-demo/README.md`

**Interfaces:**
- Consumes: Task 6 MCP server and task authorization approval/resume flow.
- Produces: one OpenAI Agents SDK CLI that selects skill or planner path, requests one task authorization, polls execution, verifies, and replans within the envelope.

- [ ] Write failing contract tests for wave skill selection, no-skill planner selection, no model-generated joints, missing-context clarification, one task approval, bounded correction without repeated approval, and material-change reauthorization.
- [ ] Run the focused test and confirm missing agent contract failures.
- [ ] Implement the single-agent instructions/CLI with explicit model argument and MCP URL; configure execution tools for human approval and leave read-only tools automatic.
- [ ] Run offline scripted scenarios, all three repository suites, compile checks, and boundary scans for vendor/ROS leakage.
- [ ] Document three-terminal startup and the two operator-supervised live experiments; do not run motion automatically.
- [ ] Commit in the Demo repository.

### Task 8: Final review and operator-run acceptance package

**Files:**
- Modify only files required by review findings.
- Create: `../wy-dual-o6-demo/docs/acceptance-results.md` after operator evidence is available.

**Interfaces:**
- Consumes: all prior tasks and live operator output.
- Produces: reviewed code, exact commands, offline evidence, and a clearly gated live acceptance record.

- [ ] Run the complete SDK, Hardware Package, and Demo suites plus `compileall` and `git diff --check` in all repositories.
- [ ] Perform a fresh whole-change code review against the spec and fix Critical/Important findings with RED-GREEN tests.
- [ ] Produce the no-motion acceptance commands and exact evidence fields for skill and dynamic-plan paths.
- [ ] If the model consistency gate is false, report the missing evidence and leave dynamic hardware execution disabled.
- [ ] After the operator supplies live outputs, record Skill A and no-Skill B results without inferring unobserved behavior.

