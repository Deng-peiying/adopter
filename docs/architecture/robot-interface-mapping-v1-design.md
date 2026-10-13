# 厂商中立的机器人接口与映射设计

**状态：** 基于 SDK v0.3 和 2026-10-12 右臂会话形成的设计草案。  
**范围：** 稳定的公共语义、可移植绑定和可复用的传输执行器。

## 边界

稳定的公共接口由 `Robot`、`Device`、`Action`、`RobotState`、`Capabilities` 和 `CommandResult` 构成。`move_joints`、`stop_motion` 等功能名称，是构建在类型化 Action 之上的易用 SDK/LLM 工具；它们既不是 ROS 端点名称，也不是第二套机器人控制协议。公共 Schema 中不得出现厂商名称、消息包、CAN 端口或关节数组顺序。

每个 Hardware Package 都要为其具体设备提供接口映射和证据。纯 Mapping Engine 负责校验绑定、排序与单位转换、命令编译和结果解码；Backend Transport 只执行端点通信。当前 `MappedRos2Adapter` 作为薄运行时组合这两部分。只有当映射 Schema 无法表达某个厂商的传输方式或控制生命周期时，才需要协议插件。厂商原始驱动仍作为外部依赖存在；厂商端点名称、消息字段和关节顺序不会出现在 Robot API 或 Demo 代码中。

## 公共操作

| 函数 | 规范请求 | 规范响应 |
|---|---|---|
| `get_capabilities` | 机器人/设备过滤条件 | 支持状态、Schema、限制、频率和证据等级 |
| `get_joint_state` | 设备 ID | 具名实测关节、源时间戳、有效性和单位 |
| `move_joints` | 设备 ID、以弧度表示的完整具名绝对目标 | 命令 ID 和执行状态/结果 |
| `get_end_effector_pose` | 设备 ID | 位姿、明确的坐标系和源时间戳 |
| `move_end_effector` | 设备 ID、位姿和坐标系 | 命令 ID 和执行状态/结果 |
| `set_hand` | 设备 ID、具名关节或经过标定的预设 | 命令 ID 和执行状态/结果 |
| `set_enabled` | 设备 ID、布尔值 | 请求响应，随后是经过验证的设备模式 |
| `stop_motion` | 设备 ID | 停止/取消确认，以及作用范围和结果 |

只有具备已验证绑定的能力，才可以提供给应用或 LLM。接口构件只能证明存在潜在的绑定，并不能证明该能力已经启用。`stop_motion` 绝不等同于硬件急停。

## 绑定 Schema

`interface-mapping/v1` 将每条绑定明确分为四类：

- `semantic`：规范操作、设备、规范关节顺序和单位；
- `transport`：Backend 类型、调用种类、端点、接口类型和动作超时；
- `encode` / `decode`：规范载荷和厂商字段之间的明确转换；
- `result` / `completion`：厂商结果码、说明字段以及实测到位判据。

一条绑定记录需标识：规范操作和设备；传输方式（`ros2_topic`、`ros2_service`、`ros2_action` 或已注册插件）；准确的端点和消息类型；请求字段映射；明确的关节顺序、单位和坐标系；前置条件和控制模式；结果与反馈字段；超时/取消行为；证据引用；以及验证阶段。字段转换使用规模较小的类型化注册表，包括恒等转换、具名顺序映射、经过标定的标量转换和经过验证的坐标系转换。映射文件不得包含任意 Python 表达式。

当源 API 要求特定生命周期时，一项绑定可以包含多个有序的协议步骤。`move_joints` 操作不会隐式给硬件上电：`set_enabled` 仍需显式调用，而运动绑定会检查当前的启用状态/模式以及新鲜的实测状态。Topic 发布最多只能返回 `submitted`；Action 可以返回 `accepted`、`running` 和终态结果。执行器必须保留这些差异、后端错误码，以及取消或超时带来的不确定性。

首个右臂绑定标识了已观测到的 `/wy_robot1/right_arm_move_action` 端点、其 `arm_control_interface/action/ArmMove` 类型、`move_type=MoveJ`，以及从七个具名绝对弧度目标到有序 `joint_angles` 字段的映射。该绑定要求新鲜的 `arm_mode=104` 状态且无故障。生成的 Action 还要求 `cart_pose[6]`；测试过的 MoveJ 目标使用了六个零。经 SDK 路径执行的探测和返回均以 Action 状态 4/代码 0 完成，并获得了新鲜的实测到位状态。该字段在其他模式下的解释和 Action 取消行为仍未确认。

能力发现将目录中的 `native`/`derived`/`unsupported`/`unknown` 分类，与绑定验证和当前设备健康状态结合起来。即使清单声明某项能力存在，只要运行时缺失或状态过期，也不得下发命令。SDK 对直接调用者、Runtime Policy 和 LLM 工具执行相同的保护；原始 `Command` 无法绕过该保护。

## 首个硬件映射与证据门槛

| 操作 | 当前证据 | 开放前的门槛 |
|---|---|---|
| 右臂关节状态 | 在线公共接口 `Robot.get_joint_state()` 报告了七个实测角度、源时间戳、`arm_mode=104` 和故障码 0 | 已在测试过的在线配置中通过；映射路径会拒绝过期/Standby 状态 |
| 右臂 `move_joints` | 在线公共接口 `Robot.move_joints()` 的探测与返回均报告 Action 状态 4/代码 0，并获得新鲜的实测到位状态；误差分别为 `0.000147` 和 `0.000145` rad | 已针对两个测试过的绝对目标通过；任意路径、时序和取消行为尚未确立 |
| 右臂 `set_enabled` | 在线 SetPower 端点以及随后的 Idle 模式 104 | 需要服务响应和新鲜的 Idle 转换；报告上电失败 |
| 右臂 `stop_motion` | 只有 `StopMove.srv` 构件；未观测到在线端点 | 确定可调用端点，或验证 Action 取消行为 |
| 末端执行器位姿/控制 | 非零的 `arm_pose[6]` 状态；约定/坐标系未知 | 转换为规范 Pose 前，确认单位、姿态顺序和坐标系 |
| 右手状态/控制 | ROS 节点已打开 CAN；版本号/序列号回复无效 | 验证物理回复、关节顺序和实测数据有效性 |

## 端到端执行路径

`LLM 工具或 Policy -> Robot Action -> 能力与安全检查 -> 绑定计划 -> 传输执行器 -> 驱动 -> 反馈/结果 -> RobotState 和 CommandResult`。LLM 选择受限的语义动作，绝不发送原始 ROS 消息或高频伺服设定点。确定性的 Runtime 负责验证、下发、故障处理和结果报告。

## 具名任务层

`raise_hand` 和 `handshake` 是构建在通用关节和位姿操作之上的任务名称。每个任务都需要特定于本体的动作流程或运动规划器：不能假设同样的七个数值在另一台机器人上也表示举手。任务条目声明所需能力，并且只调用 `get_joint_state()`、`move_joints()` 等公共 `Robot` 方法。任务的姿态、轨迹、工具坐标系和完成条件随机器人包或兼容的任务包一同提供。LLM 选择任务及其允许的参数，而不生成 ROS 消息。在添加这些任务流程之前，首先要验证右臂关节路径这一基础操作。

## 实现顺序

1. 在 SDK 中固定公共操作 Schema 和结果词汇；移除原始 `Command` 的安全绕过路径，并按设备管理状态新鲜度。
2. 定义并验证映射 Schema；加载器应拒绝未知转换、缺失字段、不支持的模式以及相互矛盾的能力声明。
3. 实现可复用的 ROS 2 Action/Topic Transport 和离线生命周期测试。厂商特定兼容路径的映射替代方案通过公共 API 验收路径后，移除这些兼容路径。
4. 在 Hardware Package 中表示由证据支持的右臂绑定；继续禁用尚未确认的位姿、停止和灵巧手能力。在声明在线右臂控制能力之前，验证一次受限的物理操作。
5. 在接入真实的第二种通信机制时，依据已稳定的 `BackendTransport` 协议实现相应 Transport，并继续保持 Robot API 与 Mapping Engine 不变。
6. 将任务流程连接到类型化 Robot 客户端，然后添加 LLM 工具；这些工具的 Schema 暴露同一组经过能力过滤的操作。

截至 2026-10-13 的实现状态：公共右臂 `get_joint_state()` 和 `move_joints()`、纯 Mapping Engine、通用 Backend Transport Protocol、ROS2 Transport 以及 Hardware Package 映射均已存在。主机侧 SDK 路径通过了读取、探测和返回目标测试。随后，Demo 通过相同的公共调用完成了完整的下降/抬升/挥动/下降任务。Hardware Package 中旧有的厂商特定 Adapter 已被移除，薄 `MappedRos2Adapter` 是唯一在线控制入口。左臂、灵巧手、ROS2 Service、笛卡尔操作、Python/Native Transport 和 LLM 工具仍未验证或尚未实现。详细的源码审计记录位于 Hardware Package 的 `docs/weiyi-interface-matrix.md`。
