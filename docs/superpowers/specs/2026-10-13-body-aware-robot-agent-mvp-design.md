# Body-aware Robot Agent MVP Design

## Objective

Build a single-agent MVP that controls only the verified right arm through the public Cross-Embodiment Robot API. The agent may reuse a registered skill or construct a new end-effector goal with deterministic kinematics. It never generates vendor messages or joint angles itself.

The two acceptance paths are:

1. select and execute the existing `wave_goodbye` skill;
2. without a matching skill, turn an operator-authorized end-effector goal into a `JointGoalPlan`, execute its complete seven-joint target through `Robot.move_joints()`, and verify the measured result with forward kinematics.

## Existing Baseline

The post-refactor right-arm chain has passed a live eight-stage wave test:

`Demo -> Robot API -> Adapter Runtime -> Mapping Engine -> ROS 2 Transport -> Weiyi driver -> measured JointState / CommandResult`.

All stages returned ROS action status 4, vendor code 0, measured arrival confirmation, and at most 0.00026142 rad joint error. This chain and the taught wave targets remain unchanged.

## Scope

- Right arm only.
- Preserve `Robot.get_joint_state()` and `Robot.move_joints()`.
- Preserve the mapped ROS 2 control chain and wave parameters.
- Add no custom joint step, speed, or amplitude limits.
- Keep left arm, hands, dual-arm synchronization, Cartesian vendor control, ArmRtCtrl, collision planning, Python/native transports, vision, and multi-agent systems out of scope.

## Responsibility Boundaries

- **Agent:** interpret tasks, choose skill or planning path, decompose work, call tools, observe results, and replan inside an authorized task envelope.
- **Skill:** optional reusable task knowledge. A skill calls only the public Robot API.
- **SDK:** common package assets, robot capabilities, state, actions, results, optional kinematics interfaces, and `JointGoalPlan` types.
- **Kinematics backend:** deterministic FK and IK using a mature solver. It does not communicate with hardware.
- **Mapping Engine:** deterministic standard-command to vendor-data conversion.
- **Backend Transport:** ROS 2 communication and action lifecycle.
- **Hardware Package:** URDF, canonical-to-model joint mapping, base/tip frames, model evidence, vendor mappings, and verified capabilities.

## Hardware Model Assets

Promote the vendor 7-axis URDF to an explicit `kinematic_model` asset in the Hardware Package. Add a separate kinematic semantics YAML containing:

- device ID `right_arm`;
- canonical joint to URDF joint mapping;
- `7axis_base_link` base link;
- the verified final link as tip link;
- metre/radian units;
- evidence and validation status for joint order, axes, zero convention, base frame, and tool frame.

Do not call the arm-local frame `base` or `world`. A robot-level mounting transform is unavailable and remains unconfirmed.

The current `ee_state` declaration is not backed by the adapter and must not be exposed as a live capability. Derived FK is represented separately from measured vendor state.

Execution bounds continue to come from the verified Hardware Package manifest. URDF limits are retained as model evidence and disagreements are reported; no additional intersection limit is introduced.

## Optional Kinematics Module

Kinematics is an optional SDK module. Importing the SDK without kinematics dependencies continues to work.

Use Orocos KDL through `PyKDL` for FK, Jacobian, and IK. Use the ROS `urdf_parser_py` package for URDF parsing. The SDK provides a thin vendor-neutral wrapper rather than implementing a solver.

The module exposes:

- a parsed `KinematicChain` with canonical joint order and model digest;
- FK from complete canonical named joint positions to `Pose`;
- current-state-seeded IK from a typed target `Pose` to an `IKResult`;
- a `JointGoalPlan` containing the source state timestamp, model digest, goal frame, target pose, complete joint target, solver result, residuals, and execution semantics.

IK success proves only that a candidate endpoint exists within declared joint bounds and requested residual tolerances. A `JointGoalPlan` does not claim collision-free motion, Cartesian-line motion, or full path validation. Its execution semantics explicitly state that the vendor controller performs a joint-space `MoveJ` to the IK solution.

## Model Consistency Evidence

Model consistency is a gate before dynamic plans can be executed on hardware.

Checks include:

1. static mapping evidence from URDF and driver joint order;
2. FK continuity over operator-recorded live wave joint states;
3. comparison of derived translation against vendor `ArmState.arm_pose` samples when the vendor pose convention is sufficiently established;
4. reporting unresolved orientation, mounting-frame, and tool-offset semantics without guessing;
5. a hardware package status flag that stays unverified until evidence meets the execution gate.

IK-to-FK round trips are solver tests, not evidence that the model matches the real arm.

## Skill Path

Extract the current wave implementation into a `wave_goodbye` skill with a manifest requiring right-arm `joint_state` and `joint_position`. Preserve the CLI and the verified 0.30 rad forearm rotation. The agent may choose this skill, but skills are not required for every task.

## MCP Surface

Expose only typed tools:

- `robot_get_description`
- `robot_get_capabilities`
- `robot_get_state`
- `robot_forward_kinematics`
- `robot_list_skills`
- `robot_preview_skill`
- `robot_plan_end_effector_goal`
- `robot_execute_skill`
- `robot_execute_plan`
- `robot_get_execution`

Do not expose raw ROS operations, shell execution, arbitrary joint targets, stop, emergency stop, or unverified capabilities.

The MCP server uses local Streamable HTTP so ROS and vendor stdout cannot corrupt a stdio protocol stream.

## Task-level Authorization

A motion task is authorized once after the user reviews its goal, robot, device, action class, frame, tolerances, and execution boundary. The model cannot authorize itself with a boolean argument.

The authorization envelope binds:

- robot instance;
- device `right_arm`;
- original task goal;
- skill or dynamic planning action class;
- target frame and tolerances;
- maximum number of internal correction attempts chosen for that task;
- model and hardware package digests.

Observe-Plan-Act-Verify corrections may execute without repeated prompts while they remain inside that envelope. A changed goal, device, frame, action class, tolerance, model version, or exhausted correction allowance requires new authorization.

The first MVP remains single-robot and single-task. It does not advertise software stop semantics. An MCP timeout does not imply the robot stopped.

## Natural-language Goal Resolution

- Quantified requests use the supplied values.
- Semantic requests may be resolved from explicit task context and deterministic model tools.
- If a required frame, magnitude, or completion condition cannot be derived from available evidence, the agent asks for that missing fact.
- The agent never treats language-model-generated joint angles as an executable plan.

## Execution and Verification

The deterministic execution manager owns one Robot session and permits one active motion task. Skill and dynamic plans ultimately call the public Robot API.

For a dynamic goal:

1. read fresh joint state;
2. derive current pose with FK;
3. solve IK from the measured joint seed;
4. create a `JointGoalPlan` and present its evidence boundary;
5. after task authorization, call `Robot.move_joints()` with the generated complete target;
6. require the terminal action result and measured joint arrival;
7. recompute FK from the new measured state;
8. compare measured derived pose to the authorized goal and tolerance;
9. if outside tolerance, replan from the new measured state within the existing authorization envelope.

Every execution record preserves real `CommandResult.command_id` values when supplied and uses null when the backend supplies none.

## Validation

Offline validation covers assets, joint/frame mapping, optional dependency behavior, FK fixtures, IK-to-FK residuals, unreachable goals, exact `JointGoalPlan` semantics, task authorization containment, single-task execution, MCP schemas, skill selection, planner selection, and no vendor interface leakage.

Live validation happens in two operator-supervised experiments:

1. natural language selects and runs the verified `wave_goodbye` skill;
2. a quantified arm-local end-effector goal has no matching skill, produces a KDL-backed `JointGoalPlan`, executes through `Robot.move_joints()`, and verifies final pose error from fresh measured joint state.

If model consistency or endpoint/path evidence is insufficient, the dynamic live experiment remains disabled and the report states the exact missing evidence.

