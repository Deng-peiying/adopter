# 跨本体具身智能 SDK 整体方案

**文档版本：** v0.1-draft  
**目标版本：** SDK v0.1  
**状态：** 技术设计草案  
**核心策略：** EE-first，非 EE-centric

## 1. 摘要

本方案定义一套面向多种机器人本体的统一软件基础设施，使算法开发者能够使用统一的硬件 API、状态模型和 Policy Protocol，在不同机器人上运行、评测和部署具身策略。

v0.1 聚焦最容易跨本体复用的 **EE Policy**，尤其是 `ee_delta` 控制模式；但底层模型、能力描述、动作协议和 Runtime 不把“动作等于末端位姿”作为系统根假设，从设计上预留：

- Joint Policy
- 移动底盘 / Base Policy
- 双臂 / Bimanual Policy
- Whole-body Policy
- 多模态观测和复杂控制器

整体产品不是单纯的机器人控制 SDK，而是由以下部分共同构成的跨本体运行基础设施：

```text
Policy / Skill / Application
              │
              ▼
Cross-Embodiment Runtime
  Compatibility / Mapping / Loop / Safety
              │
              ▼
Unified Robot SDK
  Robot / Device / State / Command API
              │
              ▼
Robot Adapter
  厂商 SDK / 网络协议 / 实时驱动 / 仿真后端
              │
              ▼
真实机器人、传感器、执行器或仿真环境
```

## 2. 产品定位与设计原则

### 2.1 产品定位

平台定位为：

> 连接机器人本体、传感器、策略、技能、仿真和应用的跨本体具身智能软件基础设施。

它解决的不是单一机器人的“如何发控制指令”，而是：

1. 用统一 API 描述和控制不同机器人。
2. 用统一状态和观测协议向 Policy 提供输入。
3. 根据本体能力自动检查 Policy 是否可运行。
4. 将 Policy 的抽象 Action 映射到具体本体的控制模式。
5. 在执行过程中提供时钟、生命周期、安全、错误恢复和可观测性。

### 2.2 设计原则

#### 原则一：EE-first，而非 EE-centric

第一版优先支持 EE Policy，但系统中的根抽象应是 `ActionSpec`、`Capability`、`ControlMode` 和 `PolicyProtocol`，而不是固定的七维末端动作。

#### 原则二：能力优先于类型继承

机器人不是由一个巨大且难以扩展的 `Robot` 子类定义，而是由一组设备和能力组合而成：机械臂、末端执行器、相机、底盘、IMU、力传感器等均以组件形式存在。

#### 原则三：稳定抽象，后端可替换

SDK 对上提供稳定接口，对下允许接入厂商 SDK、网络协议、ROS、仿真器或自研驱动。上层不应依赖具体厂商的通信细节。

#### 原则四：显式语义，拒绝隐式约定

坐标系、单位、关节顺序、旋转表示、控制模式、频率、时间戳和安全限制都必须在 Schema 或 Manifest 中显式表达。

#### 原则五：运行前检查，运行中保护

Runtime 应在启动前发现能力不匹配，在运行中持续执行边界检查、时间检查、状态检查和急停逻辑。

#### 原则六：仿真与真实设备共享接口

仿真机器人、录制回放机器人和真实机器人都应实现同一套 Unified Robot SDK 接口，以支持测试、Benchmark 和 sim-to-real。

#### 原则七：协议可版本化

Observation、Action、Manifest 和 Adapter API 均需要携带版本或可解析的 Schema 标识，避免未来扩展破坏现有 Policy。

## 3. 总体架构

### 3.1 分层架构

```text
┌─────────────────────────────────────────────────────────┐
│ Application Layer                                       │
│ 任务应用 / Skill / 数据采集 / Benchmark / 部署工具      │
├─────────────────────────────────────────────────────────┤
│ Policy Layer                                            │
│ Policy / Policy Bundle / Policy Protocol                │
├─────────────────────────────────────────────────────────┤
│ Cross-Embodiment Runtime                               │
│ Compatibility / Observation Mapping / Action Mapping    │
│ Scheduling / Safety / Lifecycle / Logging               │
├─────────────────────────────────────────────────────────┤
│ Unified Robot SDK                                      │
│ Robot / Device / Capability / State / Command / Events  │
├─────────────────────────────────────────────────────────┤
│ Adapter Layer                                           │
│ Vendor Adapter / Network Adapter / Sim Adapter / Replay │
├─────────────────────────────────────────────────────────┤
│ Hardware / Simulator                                    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 SDK 与 Runtime 的关系

| 模块 | 核心问题 | 主要职责 | 不负责的事情 |
|---|---|---|---|
| Unified Robot SDK | “如何统一操作机器人？” | 设备访问、状态读取、命令发送、能力查询 | Policy 如何组织执行、观测动作如何适配 |
| Cross-Embodiment Runtime | “一个 Policy 如何在具体本体上正确运行？” | 生命周期、调度、映射、兼容性、安全、错误处理 | 厂商协议细节、具体硬件驱动实现 |
| Robot Adapter | “如何把具体硬件接入 SDK？” | 厂商 SDK、通信、单位转换、实时线程、硬件故障 | Policy 逻辑和跨本体映射策略 |
| Embodiment Manifest | “这个本体有什么能力和约束？” | 结构化描述设备、坐标系、关节、限制和能力 | 动态控制逻辑、厂商通信实现 |
| Policy Protocol | “Policy 需要什么输入、输出什么动作？” | Observation、Action、Spec、版本、时序语义 | 直接控制硬件、替代 Adapter |

## 4. 核心对象模型

### 4.1 Robot / Device / Capability

采用组合模型：

```text
Robot
├── Device: Arm("left_arm")
│   ├── Capability: StateProvider
│   ├── Capability: EEController
│   └── Capability: JointController
├── Device: Gripper("left_gripper")
│   ├── Capability: GripperController
│   └── Capability: StateProvider
├── Device: Camera("front_camera")
│   └── Capability: ImageProvider
├── Device: Base("mobile_base")
│   ├── Capability: BaseController
│   └── Capability: OdometryProvider
└── Device: FT Sensor("wrist_ft")
    └── Capability: ForceTorqueProvider
```

`Robot` 表示一个可部署的本体实例；`Device` 表示物理或逻辑设备；`Capability` 表示设备可提供的能力。能力可以由多个设备共同实现，也可以由一个设备提供多个能力。

### 4.2 推荐能力分类

```text
StateProvider          读取状态
Commandable            接收命令
JointStateProvider     读取关节状态
JointController        关节控制
EEStateProvider        读取末端状态
EEController           末端控制
GripperController      夹爪控制
ImageProvider          图像
DepthProvider          深度
PointCloudProvider     点云
ForceTorqueProvider    力/力矩
IMUProvider            IMU
BaseController         底盘控制
OdometryProvider       里程计
SafetyMonitor          安全状态和急停
TimeProvider           设备时钟或同步时钟
```

## 5. Unified Robot SDK

### 5.1 SDK 边界

Unified Robot SDK 是面向开发者的统一硬件抽象层，提供：

- 连接、启动、停止和资源释放。
- Robot、Device、Capability 查询。
- 统一状态读取。
- 统一命令接口。
- 设备和能力发现。
- 时间戳和时钟访问。
- 错误、事件和安全状态访问。

SDK 不直接规定 Policy 的输入输出，也不负责在每个循环中决定先读哪些传感器、如何做 Policy 推理或如何把策略动作映射到目标本体。

### 5.2 统一控制 API

```python
robot = connect("ur5e", config="robot.yaml")

robot.lifecycle.start()

state = robot.state.read()
robot.ee("right_arm").command(
    mode="ee_delta",
    translation=[0.01, 0.0, 0.0],
    rotation=[0.0, 0.0, 0.02],
    frame="base",
)

robot.gripper("right_gripper").command(
    mode="position",
    value=0.8,
)

robot.lifecycle.stop()
robot.close()
```

推荐同时提供面向能力的 API 和底层统一命令 API：

```python
robot.ee("right_arm").move_to(pose)
robot.joints("right_arm").move_to(q)

robot.command(Command(
    target="right_arm",
    mode="ee_delta",
    payload=action,
))
```

### 5.3 Control Mode 语义

控制模式必须区分“动作空间类型”和“底层执行实现”：

| 类别 | 示例 | 语义 |
|---|---|---|
| EE | `ee_pose` | 目标末端位姿 |
| EE | `ee_delta` | 相对当前或指定参考位姿的增量 |
| EE | `ee_velocity` | 末端速度/角速度 |
| Joint | `joint_position` | 目标关节位置 |
| Joint | `joint_delta` | 关节位置增量 |
| Joint | `joint_velocity` | 关节速度 |
| Joint | `joint_torque` | 关节力矩 |
| Base | `base_velocity` | 平面底盘速度 |
| Gripper | `gripper_position` | 夹爪位置或开合比例 |
| Whole-body | `whole_body_target` | 多设备联合动作 |

每种模式必须定义：目标对象、维度、单位、参考坐标系、时间语义、约束和超时行为。

## 6. Embodiment Manifest

### 6.1 作用

Manifest 是对一个机器人实例或机器人型号的机器可读描述，供 SDK、Runtime、工具链和 Compatibility Check 使用。它描述“本体有什么”和“本体允许什么”，不描述具体 Policy 如何实现。

### 6.2 Manifest 必备内容

- Manifest schema 版本。
- 本体标识、厂商、型号和实例信息。
- 设备树。
- 关节名称、顺序、类型、限制和单位。
- 末端执行器与工具坐标系。
- 坐标系树和默认参考坐标系。
- 控制模式及其频率、延迟和约束。
- 传感器信息和图像规格。
- 安全能力和急停状态。
- Adapter 名称及版本。

### 6.3 YAML 示例

```yaml
schema_version: "embodiment/v0.1"

embodiment:
  id: "example.ur5e.right_arm"
  name: "UR5e Right Arm"
  vendor: "example"
  model: "ur5e"
  instance_id: "lab_a_01"

frames:
  world: world
  base: base
  ee: tool0
  default_action_frame: base

devices:
  - id: right_arm
    type: arm
    joints:
      - name: shoulder_pan
        canonical_name: arm.joint.0
        type: revolute
        limits: {position: [-6.28, 6.28], velocity: 3.14, effort: 150}
      - name: shoulder_lift
        canonical_name: arm.joint.1
        type: revolute
        limits: {position: [-6.28, 6.28], velocity: 3.14, effort: 150}
      - name: elbow
        canonical_name: arm.joint.2
        type: revolute
      - name: wrist_1
        canonical_name: arm.joint.3
        type: revolute
      - name: wrist_2
        canonical_name: arm.joint.4
        type: revolute
      - name: wrist_3
        canonical_name: arm.joint.5
        type: revolute
    end_effectors:
      - id: tool0
        frame: tool0
        capabilities: [ee_state, ee_controller]
    capabilities:
      - joint_state
      - joint_position
      - ee_state
      - ee_pose
      - ee_delta

  - id: right_gripper
    type: gripper
    capabilities: [gripper_state, gripper_position]
    range: [0.0, 1.0]

  - id: front_camera
    type: camera
    capabilities: [rgb]
    image:
      width: 640
      height: 480
      fps: 30
      encoding: rgb8

control:
  supported_modes:
    - type: ee_delta
      target: right_arm
      frame: base
      translation_unit: meter
      rotation_representation: axis_angle
      max_translation_delta: [0.05, 0.05, 0.05]
      max_rotation_delta: [0.2, 0.2, 0.2]
      frequency_hz: 20
      command_timeout_ms: 150
    - type: joint_position
      target: right_arm
      joint_order: [shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]
      frequency_hz: 100

safety:
  requires_enable: true
  supports_estop: true
  workspace:
    frame: base
    min: [-0.8, -0.8, 0.0]
    max: [0.8, 0.8, 1.2]

adapter:
  id: example_ur
  version: "0.1.0"
```

## 7. Policy Protocol

### 7.1 协议边界

Policy Protocol 规定 Policy 与 Runtime 之间的契约：

```text
Observation → Policy → Action
```

它应回答：

- Policy 需要哪些观测字段？
- 每个字段的形状、单位、坐标系和时间语义是什么？
- Policy 输出哪一种 ActionSpec？
- 推理频率和最大延迟是多少？
- 缺失字段如何处理？
- Policy 是否允许批量输入、历史帧或异步输入？

### 7.2 RobotState Schema

RobotState 是 SDK 面向硬件的完整状态，不等同于某个 Policy 的 Observation。

```python
@dataclass
class RobotState:
    timestamp: Timestamp
    sequence_id: int
    joint_positions: dict[str, float] | None
    joint_velocities: dict[str, float] | None
    joint_efforts: dict[str, float] | None
    ee_poses: dict[str, Pose] | None
    ee_twists: dict[str, Twist] | None
    grippers: dict[str, GripperState] | None
    base_pose: Pose | None
    base_twist: Twist | None
    force_torques: dict[str, Wrench] | None
    safety: SafetyState
    device_status: dict[str, DeviceStatus]
```

状态字段允许为 `None`，表示本体不提供该能力；不应通过填充零值伪造不存在的传感器数据。

### 7.3 Observation Schema

Observation 是经过 Runtime 选择、同步、变换和归一化后提供给 Policy 的输入。

```python
@dataclass
class Observation:
    schema: str
    timestamp: Timestamp
    fields: dict[str, ObservationField]
    source_state_sequence: int

@dataclass
class ObservationField:
    value: Any
    dtype: str
    shape: tuple[int, ...] | None
    unit: str | None
    frame: str | None
    valid: bool
    age_ms: float
```

Observation 可以包含：

```text
rgb.front
depth.front
robot.ee_pose.right_arm
robot.gripper.right
robot.joint_position.right_arm
robot.joint_velocity.right_arm
task.language
task.goal_pose
```

### 7.4 Action 与 ActionSpec

`Action` 是一次具体输出；`ActionSpec` 描述输出空间和语义。

```python
@dataclass
class ActionSpec:
    type: str                 # ee_delta / joint_position / ...
    target: str
    frame: str | None
    dimension: int | None
    units: dict[str, str]
    bounds: dict[str, Any]
    frequency_hz: float
    horizon: int = 1

@dataclass
class Action:
    spec: ActionSpec
    timestamp: Timestamp
    values: Any
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

## 8. v0.1 EE Policy 协议

### 8.1 支持范围

v0.1 支持：

- 单臂 EE Policy。
- 可选 RGB 图像输入。
- 可选 EE Pose 和夹爪状态输入。
- `ee_delta` 和可选 `ee_pose` 输出。
- 可选标量夹爪动作。
- 固定频率或由 Runtime 驱动的 step 模式。

v0.1 暂不承诺：

- 多臂同步控制。
- 复杂 whole-body 优化。
- 任意 joint torque 控制。
- 自动解决不可逆的本体差异。

### 8.2 EE Observation Contract

```yaml
observation_spec:
  schema: "policy-observation/ee/v0.1"
  fields:
    - name: rgb.front
      type: image
      shape: [3, 224, 224]
      dtype: float32
      normalization: imagenet
      required: true
    - name: robot.ee_pose.right_arm
      type: pose
      frame: base
      position_unit: meter
      rotation_representation: quaternion_xyzw
      required: true
    - name: robot.gripper.right
      type: scalar
      range: [0.0, 1.0]
      required: false
```

### 8.3 EE Action Contract

```yaml
action_spec:
  schema: "policy-action/ee/v0.1"
  type: ee_delta
  target: right_arm
  frame: base
  translation:
    representation: xyz
    unit: meter
    bounds: [-0.05, 0.05]
  rotation:
    representation: axis_angle
    unit: radian
    bounds: [-0.2, 0.2]
  gripper:
    type: scalar
    range: [0.0, 1.0]
  frequency_hz: 20
```

推荐使用结构化 Action，而不是只传一个无语义数组：

```python
EEAction(
    translation=np.array([dx, dy, dz]),
    rotation_axis_angle=np.array([rx, ry, rz]),
    gripper=0.7,
)
```

内部可以转换成张量，但在协议边界处必须保留语义。

## 9. Cross-Embodiment Runtime

### 9.1 Runtime 职责

Runtime 是 Policy 的执行器和跨本体适配层，负责：

1. 加载 Policy Bundle 和 Manifest。
2. 检查协议版本与本体能力。
3. 建立 Observation Mapping。
4. 启动设备、相机、时钟和安全监控。
5. 按指定频率读取并同步观测。
6. 调用 Policy。
7. 校验、变换和限幅 Action。
8. 发送到 SDK 能力接口。
9. 处理超时、异常、急停和安全降级。
10. 记录运行指标和可复现实验信息。

### 9.2 执行流程

```text
加载 Policy Bundle
        │
加载 Embodiment Manifest
        │
解析 ObservationSpec / ActionSpec
        │
Compatibility Check
        │
创建 Observation Mapper / Action Mapper
        │
连接 Robot Adapter
        │
执行 enable / calibrate / warmup
        │
┌───────┴─────────────────────┐
│ Runtime Loop                 │
│ 读取 RobotState              │
│ 同步传感器与时间戳            │
│ 构造 Observation              │
│ policy.step(observation)     │
│ 校验 Action                   │
│ 坐标变换、限幅、安全检查       │
│ 调用 SDK Capability           │
│ 记录 latency / status         │
└─────────────────────────────┘
        │
停止、制动、释放、保存运行摘要
```

### 9.3 Runtime 状态机

```text
CREATED
  ↓ load
LOADED
  ↓ validate
VALIDATED
  ↓ connect
CONNECTED
  ↓ enable
READY
  ↓ start
RUNNING
  ├─ pause → PAUSED → resume → RUNNING
  ├─ fault → FAULT
  └─ stop → STOPPING → STOPPED
```

### 9.4 Runtime 伪代码

```python
runtime = Runtime(
    policy=policy,
    robot=robot,
    policy_bundle="policies/pick_v1",
)

report = runtime.validate()
report.raise_if_incompatible()

with runtime:
    runtime.start()
    while runtime.running:
        observation = runtime.observe()
        action = policy.step(observation)
        runtime.apply(action)
```

## 10. Compatibility Check

### 10.1 检查目标

Compatibility Check 在运行前判断 Policy 与目标本体是否可以安全运行。结果应区分：

- `compatible`：可以直接运行。
- `compatible_with_mapping`：需要已声明且可验证的映射。
- `incompatible`：缺少必要能力或语义不匹配。
- `unsafe`：虽然字段存在，但违反安全约束。

### 10.2 检查维度

| 维度 | 示例 |
|---|---|
| 协议版本 | Policy Protocol v0.1 与 Runtime 支持范围 |
| 观测字段 | RGB、EE Pose、Gripper 是否存在 |
| 数据形状 | 分辨率、通道数、张量布局 |
| 单位 | meter、radian、degree、normalized |
| 坐标系 | base、world、camera、tool |
| 旋转表示 | quaternion、axis-angle、rotation matrix |
| 动作模式 | `ee_delta` 是否被目标设备支持 |
| 频率 | Policy 20 Hz 与控制器可否满足 |
| 关节语义 | joint policy 的 canonical joint name 是否可映射 |
| 限制 | 工作空间、速度、加速度、力矩、夹爪范围 |
| 安全 | 急停、enable、看门狗、状态监控 |

### 10.3 检查结果示例

```python
CompatibilityReport(
    status="compatible_with_mapping",
    checks=[
        Check("rgb.front", "mapped", "camera.front -> policy.front"),
        Check("ee_pose", "passed", "base frame available"),
        Check("rotation", "mapped", "quaternion -> axis_angle"),
        Check("frequency", "warning", "policy 20Hz, adapter 18-20Hz"),
    ],
    blocking_issues=[],
    warnings=["camera timestamp jitter above target"],
)
```

## 11. 坐标系、Joint Naming 与语义规范

### 11.1 坐标系规范

系统至少需要区分：

- `world`：环境或实验室固定坐标系。
- `base`：机器人基座坐标系。
- `camera_x`：传感器坐标系。
- `ee` / `tool`：末端或工具坐标系。
- `object_x`：任务对象坐标系。

所有 Pose 和 Twist 必须带 `frame`。禁止在跨模块传递裸数组并依赖上下文猜测坐标系。

### 11.2 EE Delta 语义

`ee_delta` 必须明确：

- 增量是在 `base`、`world` 还是 `ee` frame 中表达。
- 平移是位置增量还是目标速度。
- 旋转是 axis-angle 增量还是欧拉角增量。
- 增量是应用于当前状态还是上一条目标。
- 单次动作的时间窗口和插值方式。

v0.1 默认建议：

```text
translation: base frame, meter, position delta
rotation: base frame, axis-angle, radian delta
gripper: normalized scalar [0, 1]
command semantics: apply to current measured EE pose
```

### 11.3 Joint Naming

同时保留两种名字：

- `native_name`：厂商或本体原始名称。
- `canonical_name`：SDK 内部稳定名称。

例如：

```text
native_name: shoulder_pan_joint
canonical_name: arm.right.joint.0
```

Joint Policy 不应依赖不同机器人恰好相同的原始命名。映射必须显式列出关节顺序、方向、零位偏移和单位。

## 12. 错误、安全与生命周期

### 12.1 错误分类

```text
ConfigurationError       配置或 Manifest 错误
CompatibilityError       Policy 与本体不兼容
ConnectionError          通信连接失败
DeviceError              设备故障
CommandRejected          控制器拒绝命令
CommandTimeout           命令超时
ObservationStale         观测过期
PolicyError              Policy 推理异常
SafetyViolation          超出安全约束
EmergencyStop            急停触发
LifecycleError           生命周期状态错误
```

每个错误应包含：错误码、时间戳、设备、可恢复性、建议动作和原始后端错误。

### 12.2 必备安全机制

- 启动前 `enable` 和安全状态检查。
- 动作范围、速度和加速度限幅。
- 工作空间限制。
- Policy 输出 NaN/Inf 检测。
- 观测过期和时间戳倒退检测。
- Command watchdog。
- 通信中断后的安全动作。
- 急停状态传播。
- Policy 异常时停止或保持安全位姿。
- 真实机器人运行前 dry-run、低速模式和人工确认。

### 12.3 生命周期约束

```python
with connect(...) as robot:
    robot.lifecycle.configure()
    robot.lifecycle.connect()
    robot.lifecycle.enable()
    robot.lifecycle.start()
    ...
    robot.lifecycle.stop()
    robot.lifecycle.disable()
```

Runtime 不应绕过 SDK 直接操作 Adapter；所有停止和释放操作都必须幂等。

## 13. 插件与 Adapter 机制

### 13.1 Adapter 接口

```python
class RobotAdapter(Protocol):
    adapter_id: str
    version: str

    def load_manifest(self) -> EmbodimentManifest: ...
    def connect(self, config: AdapterConfig) -> None: ...
    def disconnect(self) -> None: ...
    def get_state(self) -> RobotState: ...
    def send_command(self, command: Command) -> CommandResult: ...
    def subscribe_events(self, callback: EventCallback) -> Subscription: ...
    def health(self) -> HealthReport: ...
```

### 13.2 Adapter 类型

建议至少支持：

```text
vendor/<vendor>/<model>       厂商硬件
network/<protocol>            网络控制协议
simulation/<engine>           仿真器
replay/<format>               录制回放
mock/<name>                   单元测试
```

### 13.3 注册机制

```python
@register_adapter("example_ur")
class ExampleURAdapter(RobotAdapter):
    ...

robot = connect("example_ur", endpoint="192.168.1.10")
```

Adapter 应通过 entry points 或显式注册发现，不应让核心包依赖所有厂商 SDK。硬件依赖应放入可选 extras：

```text
cross_embodiment[ur]
cross_embodiment[franka]
cross_embodiment[unitree]
cross_embodiment[sim]
```

## 14. Python 包目录建议

```text
cross_embodiment/
├── pyproject.toml
├── README.md
├── src/cross_embodiment/
│   ├── __init__.py
│   ├── api.py                 # 面向用户的简化入口
│   ├── sdk/
│   │   ├── robot.py
│   │   ├── device.py
│   │   ├── capability.py
│   │   ├── lifecycle.py
│   │   ├── state.py
│   │   └── command.py
│   ├── runtime/
│   │   ├── runtime.py
│   │   ├── scheduler.py
│   │   ├── observation.py
│   │   ├── action.py
│   │   ├── compatibility.py
│   │   ├── safety.py
│   │   └── lifecycle.py
│   ├── protocol/
│   │   ├── observation.py
│   │   ├── action.py
│   │   ├── policy.py
│   │   └── schemas/
│   ├── manifest/
│   │   ├── model.py
│   │   ├── loader.py
│   │   └── validator.py
│   ├── adapters/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── mock.py
│   │   └── ...
│   ├── transforms/
│   │   ├── frames.py
│   │   ├── rotations.py
│   │   ├── joints.py
│   │   └── units.py
│   ├── errors.py
│   └── logging.py
├── adapters/
│   ├── example_ur/
│   ├── franka/
│   └── unitree/
├── manifests/
├── examples/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── conformance/
│   └── benchmark/
└── docs/
```

## 15. 核心类和接口伪代码

```python
class Robot:
    manifest: EmbodimentManifest

    def state(self) -> RobotState: ...
    def devices(self) -> list[Device]: ...
    def capability(self, name: str, target: str) -> Capability: ...
    def command(self, command: Command) -> CommandResult: ...
    def lifecycle(self) -> LifecycleController: ...


class Policy(Protocol):
    def observation_spec(self) -> ObservationSpec: ...
    def action_spec(self) -> ActionSpec: ...
    def reset(self, context: EpisodeContext) -> None: ...
    def step(self, observation: Observation) -> Action: ...


class ObservationMapper:
    def build(self, state: RobotState, sensors: SensorSnapshot) -> Observation: ...


class ActionMapper:
    def map(self, action: Action, state: RobotState) -> list[Command]: ...


class CompatibilityChecker:
    def check(
        self,
        policy: Policy,
        manifest: EmbodimentManifest,
    ) -> CompatibilityReport: ...


class Runtime:
    def validate(self) -> CompatibilityReport: ...
    def start(self) -> None: ...
    def observe(self) -> Observation: ...
    def apply(self, action: Action) -> list[CommandResult]: ...
    def stop(self, reason: str = "user") -> None: ...
```

## 16. EE Policy 运行示例

```python
from cross_embodiment import connect, Runtime
from my_policy import PickPolicy

robot = connect(
    adapter="example_ur",
    manifest="manifests/ur5e_right_arm.yaml",
    endpoint="192.168.1.10",
)

policy = PickPolicy.load("policies/pick_v1")

runtime = Runtime(
    robot=robot,
    policy=policy,
    control_frequency_hz=20,
    safety_profile="conservative",
)

report = runtime.validate()
if report.has_blocking_issues:
    raise RuntimeError(report.summary())

try:
    runtime.start()
    runtime.run(max_seconds=60)
finally:
    runtime.stop(reason="example_finished")
    robot.close()
```

Policy 本身只依赖协议，不依赖具体机器人：

```python
class PickPolicy:
    def observation_spec(self):
        return ObservationSpec.from_yaml("pick_observation.yaml")

    def action_spec(self):
        return ActionSpec(
            type="ee_delta",
            target="right_arm",
            frame="base",
            frequency_hz=20,
        )

    def step(self, obs):
        image = obs["rgb.front"]
        ee_pose = obs["robot.ee_pose.right_arm"]
        output = self.model(image, ee_pose)
        return EEAction.from_model_output(output)
```

## 17. 未来 Joint Policy 扩展示例

### 17.1 Joint Policy Manifest

```yaml
policy:
  protocol: "policy/v0.2"
  action_space:
    type: joint_position
    target: right_arm
    joint_names:
      - arm.joint.0
      - arm.joint.1
      - arm.joint.2
      - arm.joint.3
      - arm.joint.4
      - arm.joint.5
    unit: radian
    semantics: absolute_target
    frequency_hz: 50
```

### 17.2 Joint Policy 运行逻辑

```python
class JointPolicy:
    def action_spec(self):
        return ActionSpec(
            type="joint_position",
            target="right_arm",
            dimension=6,
            units={"position": "radian"},
            frequency_hz=50,
        )

    def step(self, observation):
        q = self.model(observation["robot.joint_position.right_arm"])
        return JointPositionAction(
            target="right_arm",
            joint_names=self.joint_names,
            positions=q,
        )
```

Runtime 可以复用相同生命周期和安全链路，只替换：

```text
Observation Mapper
ActionSpec
Action Mapper
Control Capability
```

这正是“EE-first、非 EE-centric”的关键：新增 Joint Policy 不需要重写 Robot、Adapter、Manifest、Runtime 生命周期和安全框架。

### 17.3 后续扩展方向

```text
Base Policy
  action: base_velocity(vx, vy, wz)

Bimanual Policy
  action: {left_ee_delta, right_ee_delta, synchronization}

Whole-body Policy
  action: joint_position + base_velocity + end-effector targets

Hierarchical Policy
  high-level skill → Runtime → low-level controller
```

## 18. 测试与 Benchmark

### 18.1 测试层次

1. **Schema Test**：Manifest、Observation、Action 的序列化与校验。
2. **Unit Test**：坐标变换、旋转转换、单位转换、joint mapping、限幅。
3. **Adapter Conformance Test**：每个 Adapter 是否满足统一接口和生命周期语义。
4. **Mock Integration Test**：Policy + Runtime + Mock Robot 闭环运行。
5. **Simulation Test**：仿真器中的任务成功率和控制稳定性。
6. **Hardware-in-the-loop Test**：真实控制器、通信和安全链路。
7. **Regression Test**：同一 Policy 在多个 Manifest 上的行为变化。

### 18.2 Adapter Conformance 必测项目

- Manifest 可加载且字段完整。
- connect/disconnect 幂等。
- state 时间戳单调递增。
- command 超时可检测。
- 非法动作被拒绝。
- 急停状态可读且能阻断命令。
- 设备断连后能返回明确错误。
- 所有声明的 capability 都可查询。

### 18.3 Runtime Benchmark 指标

```text
observation latency
policy inference latency
action mapping latency
command round-trip latency
control loop jitter
timestamp skew
stale observation rate
command rejection rate
safety intervention count
task success rate
cross-embodiment transfer gap
```

### 18.4 推荐 Benchmark 场景

- 到达指定 Pose。
- 推、拉、抓取和放置。
- 不同相机分辨率和视角。
- 不同控制频率。
- 不同自由度和夹爪类型。
- 观测延迟、丢帧和通信抖动。
- 仿真到真实迁移。

Benchmark 输出应包含 Policy 版本、Manifest hash、Adapter 版本、Runtime 版本、随机种子、硬件信息和完整运行日志。

## 19. 版本路线图

### v0.1：EE-first 基础闭环

- Unified Robot SDK 基础接口。
- Robot / Device / Capability 模型。
- Manifest v0.1。
- RobotState、Observation、Action、ActionSpec。
- 单臂 EE Policy。
- `ee_delta`，可选 `ee_pose`。
- RGB + EE Pose + Gripper 观测。
- Runtime 生命周期、Compatibility Check 和安全限幅。
- Mock Adapter、至少一个真实 Adapter、一个仿真 Adapter。

### v0.2：多设备与 Joint 基础能力

- Joint State 完整支持。
- `joint_position` 和 `joint_delta`。
- Joint naming 与 canonical mapping。
- 多相机和时间同步增强。
- Bimanual Manifest 表达。
- 更完整的回放和数据采集接口。

### v0.3：移动与双臂

- `base_velocity`。
- Bimanual Policy。
- 多设备同步调度。
- 任务级 Skill API。
- 仿真、真实设备和回放的统一 Benchmark。

### v1.0：跨本体生产级平台

- 稳定的协议兼容策略。
- Whole-body Policy 基础能力。
- 版本化 Policy Bundle 和模型注册。
- 可观测性、远程部署和运行审计。
- 丰富 Adapter 生态及 Adapter Conformance 认证。

## 20. 关键决策与非目标

### 20.1 当前关键决策

1. v0.1 只实现 EE Policy，但所有协议采用可扩展 ActionSpec。
2. SDK 和 Runtime 在概念与代码边界上分离，即使 Python 包可以统一分发。
3. RobotState 是完整硬件状态；Observation 是面向 Policy 的投影。
4. 所有跨模块数据都显式携带单位、坐标系、时间戳和版本。
5. 采用 Robot + Device + Capability 组合模型，而不是按机器人型号堆叠继承树。
6. Adapter 是可插拔后端，厂商依赖不进入核心包。

### 20.2 v0.1 非目标

- 自动把任意 Policy 强行迁移到任意机器人。
- 隐式解决不同本体的动力学、可达性和任务语义差异。
- 在核心 SDK 中内置所有厂商协议。
- 在没有安全边界和人工确认的情况下直接支持高风险真实机器人运行。

## 21. 最终建议

实现顺序建议为：

```text
1. Manifest + RobotState + Capability
2. Mock Adapter + Conformance Test
3. Unified Robot SDK 控制闭环
4. EE Observation / Action Protocol
5. Runtime + Compatibility Check
6. 一个真实 Adapter
7. 仿真 Adapter + Benchmark
8. Joint State / Joint Policy 扩展
```

最需要避免的技术债是把以下假设写死在根接口中：

```text
action 永远是 7 维数组
机器人永远只有一条机械臂
末端永远叫 ee
关节顺序可以靠数组位置猜测
所有位姿都在 base 坐标系
所有相机都输出同样的图像格式
Policy 可以直接调用厂商 SDK
```

如果 v0.1 能稳定完成“同一个 EE Policy 在两个不同本体或仿真后端上运行”，并且运行前能明确解释兼容性、运行中能保证安全边界，那么这套 SDK 就具备继续扩展 Joint、Base、Bimanual 和 Whole-body Policy 的正确基础。
