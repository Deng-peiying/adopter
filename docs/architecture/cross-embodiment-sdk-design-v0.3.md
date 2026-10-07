# 跨本体具身智能 SDK 整体方案

**文档版本：** v0.3-draft  
**目标版本：** SDK v0.1 → Platform v1.0  
**状态：** 技术设计草案  
**核心策略：** EE-first，非 EE-centric；Package-first，Adapter-not-package

---

## 1. 摘要

本方案定义一套面向多种机器人本体的统一软件基础设施，使算法开发者能够使用统一的硬件 API、状态模型和 Policy Protocol，在不同机器人上运行、评测和部署具身策略。

v0.1 聚焦最容易跨本体复用的 **EE Policy**，尤其是 `ee_delta` 控制模式；但底层模型、能力描述、动作协议和 Runtime 不把“动作等于末端位姿”作为系统根假设，从设计上预留：

- Joint Policy
- Base Policy
- Bimanual Policy
- Whole-body Policy
- 多模态观测
- 多设备同步
- 高频控制与实时 Runtime
- 仿真 / 回放 / 真机统一执行

相比早期设计，本版本新增一个核心抽象：

> **Hardware Package / Embodiment Package 是硬件接入后的最小可安装、可发现、可版本化、可启动和可复现单元；Adapter 只是 Hardware Package 内的一种控制实现。**

这一设计用于解决现实中的硬件生态差异：

- 有的厂商只提供 Python SDK；
- 有的厂商提供 ROS / ROS2 Driver；
- 有的厂商只提供 C++ 动态库、头文件或二进制 Driver；
- 有的厂商公开 URDF / Xacro；
- 有的厂商提供 USD / MJCF / mesh / STEP；
- 有的厂商把机器人描述、控制、夹爪、相机和标定拆在多个仓库中；
- 有的厂商提供 TCP、CAN、串口、共享内存或专有实时协议；
- 同一型号在不同 OS、CPU 架构、ROS 版本下可能需要不同 Backend。

因此系统不强制厂商资产统一为单一文件格式，而是采用：

> **原始资产保留 + 语义统一 + Backend 可替换 + Package 可解析**

的设计。

---

## 2. 产品定位

### 2.1 最终定位

平台定位为：

> **连接机器人本体、硬件资产、传感器、策略、技能、仿真、部署与运行数据的跨本体具身智能基础设施。**

它解决的不只是“如何给机器人发指令”，而是完整回答：

1. 一个机器人型号由哪些代码、模型、驱动和资源构成？
2. 这些资源如何被安装、发现、解析和启动？
3. 如何用统一 API 控制不同厂商的硬件？
4. 如何用统一状态和观测协议向 Policy 提供输入？
5. 如何判断一个 Policy 是否能在某台机器人上运行？
6. 如何把抽象 Action 映射为具体机器人命令？
7. 如何复现实验时的软件、Adapter、模型和资产版本？
8. 如何让 Coding Agent 自动生成和维护新的硬件接入包？
9. 如何将 Package 模式扩展成平台模式并形成 Robot / Policy / Data 生态？

---

## 3. 核心设计原则

### 3.1 EE-first，而非 EE-centric

第一版只优先实现 EE Policy，但系统中的根抽象必须是：

- `ActionSpec`
- `ObservationSpec`
- `Capability`
- `ControlMode`
- `PolicyProtocol`

而不是固定七维末端动作。

### 3.2 Package-first，而非 Adapter-first

Adapter 不是完整的硬件交付单元。

完整硬件接入应表示为：

```text
Hardware Package
├── Package Manifest
├── Embodiment Manifest
├── Adapter / Backend
├── Vendor Runtime
├── Robot Model Assets
├── Launch / Startup
├── Default Config
├── Validation / Tests
├── License / Metadata
└── Optional Derived Assets
```

### 3.3 原始资产保留，语义统一

不要求所有厂商把硬件模型转换成唯一格式。

允许：

```text
URDF
Xacro
USD
MJCF
SDF
STL / OBJ / DAE
STEP
JSON
YAML
ROS Package
Vendor Python SDK
C++ .so / .dll
Binary Driver
```

平台统一的是：

- 资产是什么；
- 资产的用途是什么；
- 如何加载；
- 如何解析；
- 哪个 Backend 使用它；
- 该本体具备什么 Capability；
- 如何启动；
- 如何测试。

### 3.4 能力优先于机器人类型继承

采用：

```text
Robot
├── Device
│   └── Capability
```

而不是依赖大型机器人继承树。

### 3.5 Stable Core，Replaceable Backend

上层 API 稳定，下层可为：

- Python Vendor SDK
- ROS2
- C++ Native Driver
- Network Protocol
- Remote Driver
- Simulator
- Replay Backend

### 3.6 ROS 是 Backend，不是平台根依赖

ROS / ROS2 是重要兼容生态，但不作为统一 SDK 的唯一基础。

### 3.7 Model 与 Instance 分离

`xArm7` 是 Robot Model。

实验室中 IP 为 `192.168.x.x`、安装特定夹爪、带特定相机外参的那台 xArm7 是 Robot Instance。

### 3.8 显式语义

以下信息禁止依赖隐式约定：

- 坐标系
- 单位
- joint 顺序
- joint 方向
- 零位
- rotation representation
- action semantics
- control frequency
- timestamp
- timeout
- workspace
- safety limit
- backend requirements

### 3.9 可版本化、可锁定、可复现

Hardware Package、Policy Package、Manifest、Adapter、Runtime、Schema 都必须支持版本。

项目必须可生成 lock file。

---

# 4. 总体架构

```text
┌────────────────────────────────────────────────────────────────┐
│ Application / Skill / Benchmark / Data Collection             │
├────────────────────────────────────────────────────────────────┤
│ Policy Layer                                                   │
│ Policy Package / Policy Protocol / ObservationSpec / ActionSpec│
├────────────────────────────────────────────────────────────────┤
│ Cross-Embodiment Runtime                                       │
│ Compatibility / Mapping / Scheduler / Safety / Lifecycle       │
├────────────────────────────────────────────────────────────────┤
│ Unified Robot SDK                                              │
│ Robot / Device / Capability / State / Command                  │
├────────────────────────────────────────────────────────────────┤
│ Adapter Contract                                               │
│ Python / ROS2 / Native / Remote / Sim / Replay                │
├────────────────────────────────────────────────────────────────┤
│ Hardware Package Layer                                         │
│ Assets / Backend / Manifest / Launch / Config / Tests           │
├────────────────────────────────────────────────────────────────┤
│ Vendor Runtime / Driver / Native SDK / ROS / Protocol          │
├────────────────────────────────────────────────────────────────┤
│ Physical Robot / Sensor / Gripper / Simulator                  │
└────────────────────────────────────────────────────────────────┘
```

---

# 5. 核心概念边界

| 概念 | 回答的问题 | 典型内容 |
|---|---|---|
| Hardware Package | “这个硬件集成整体包含什么，怎么安装和启动？” | assets、backend、manifest、launch、config、tests |
| Robot Adapter | “如何把具体后端映射为统一 API？” | 状态读取、命令发送、单位/坐标转换 |
| Embodiment Manifest | “这个本体有什么能力和约束？” | joints、frames、devices、capabilities、limits |
| Robot Instance | “这一台具体机器在哪里、装了什么、校准如何？” | IP、serial、camera extrinsic、tool、local config |
| Unified Robot SDK | “开发者如何统一操作机器人？” | state、command、lifecycle、device API |
| Runtime | “Policy 如何在具体机器人上运行？” | compatibility、mapping、loop、safety |
| Policy Package | “模型需要什么输入、输出什么动作、如何加载？” | weights、code、spec、runtime requirements |
| Project | “这次应用使用哪些 Robot / Policy / Config？” | dependency、instance、policy、task |
| Registry | “包和资源在哪里、有哪些版本？” | package metadata、digest、platform variant |
| Lock File | “这次运行精确使用了哪些版本？” | versions、digests、backend、asset hash |

---

# 6. Hardware Package / Embodiment Package

## 6.1 定义

Hardware Package 是某个机器人、夹爪、相机或其他硬件进入生态后的标准交付单元。

推荐命名：

```text
vendor/model
```

例如：

```text
ufactory/xarm7
robotiq/2f85
intel/realsense_d405
franka/fr3
agilex/piper
```

---

## 6.2 推荐目录结构

```text
ufactory.xarm7/
├── package.yaml
├── embodiment.yaml
├── adapters/
│   ├── python/
│   │   ├── adapter.py
│   │   └── requirements.txt
│   ├── ros2/
│   │   ├── backend.yaml
│   │   └── launch/
│   └── native/
│       ├── backend.yaml
│       └── bin/
├── assets/
│   ├── urdf/
│   ├── xacro/
│   ├── usd/
│   ├── mjcf/
│   ├── meshes/
│   ├── collision/
│   ├── kinematics/
│   └── calibration_templates/
├── launch/
│   ├── direct.py
│   ├── ros2.launch.py
│   └── simulator.py
├── config/
│   ├── default.yaml
│   └── safety.yaml
├── tests/
│   ├── schema/
│   ├── conformance/
│   ├── mock/
│   └── hardware/
├── licenses/
└── README.md
```

---

## 6.3 Package Manifest

`package.yaml` 描述“包是什么以及如何使用”。

示例：

```yaml
schema_version: "hardware-package/v0.1"

package:
  name: "ufactory/xarm7"
  version: "1.2.0"
  vendor: "UFACTORY"
  model: "xArm7"
  type: "robot_arm"

embodiment_manifest: "embodiment.yaml"

assets:
  kinematic_model:
    - format: "urdf"
      path: "assets/urdf/xarm7.urdf"

    - format: "xacro"
      path: "assets/xacro/xarm7.urdf.xacro"

  visual_model:
    - format: "mesh_collection"
      path: "assets/meshes/"

  collision_model:
    - format: "urdf"
      path: "assets/urdf/xarm7.urdf"

backends:
  - id: "python_direct"
    type: "python"
    entrypoint: "adapters.python.adapter:XArmAdapter"
    platforms:
      - os: "linux"
        arch: "amd64"
      - os: "linux"
        arch: "arm64"

  - id: "ros2_humble"
    type: "ros2"
    package: "xarm_api"
    launch: "xarm7.launch.py"
    requirements:
      ros_distro: "humble"

  - id: "native"
    type: "native"
    executable: "adapters/native/bin/xarm_driver"
    platforms:
      - os: "linux"
        arch: "amd64"

defaults:
  backend: "python_direct"
  config: "config/default.yaml"

validation:
  conformance: "tests/conformance/"
```

---

# 7. Asset 管理设计

## 7.1 Asset Slot

平台不要求统一文件格式，而是定义统一用途。

推荐 slot：

```text
kinematic_model
visual_model
collision_model
dynamic_model
controller_config
sensor_model
calibration_template
simulation_model
vendor_runtime
documentation
```

---

## 7.2 Asset Variant

同一个用途允许多个 representation：

```yaml
assets:
  kinematic_model:
    - format: urdf
      path: assets/urdf/xarm7.urdf

    - format: usd
      path: assets/usd/xarm7.usd

    - format: mjcf
      path: assets/mjcf/xarm7.xml
```

Runtime 或 simulator 根据自身能力选择。

例如：

```text
MoveIt      → URDF
Isaac Sim   → USD
MuJoCo      → MJCF
SDK Core    → Parsed Joint/Frame Metadata
```

---

## 7.3 Source Asset 与 Derived Asset

建议区分：

```text
Source Asset
    ↓
Asset Importer / Converter
    ↓
Derived Asset
```

例如：

```text
Xacro
  ↓ resolve
URDF

URDF
  ↓ importer
USD

STEP
  ↓ mesh pipeline
STL / collision mesh
```

原则：

> Derived Asset 可以重新生成，Source Asset 应保留。

---

# 8. Backend / Adapter 体系

## 8.1 Adapter Contract

```python
class RobotAdapter(Protocol):
    adapter_id: str
    version: str

    def connect(self, config) -> None: ...
    def disconnect(self) -> None: ...

    def get_state(self) -> RobotState: ...

    def send_command(
        self,
        command: Command,
    ) -> CommandResult: ...

    def health(self) -> HealthReport: ...

    def subscribe_events(
        self,
        callback,
    ) -> Subscription: ...
```

Adapter 只负责：

- Vendor API → Unified Robot API；
- 单位转换；
- Frame / joint mapping；
- 状态转译；
- 控制命令映射；
- Backend error → platform error；
- Backend 生命周期映射。

Adapter 不负责：

- Policy 推理；
- Cross-embodiment mapping；
- Policy compatibility；
- Application logic。

---

## 8.2 Backend 类型

第一版建议支持：

```text
python
ros2
native
remote
simulation
replay
mock
```

未来可扩展：

```text
grpc
dds
can
serial
shared_memory
realtime_native
```

---

# 9. Driver Host

## 9.1 为什么需要 Driver Host

如果所有 Adapter 都运行在主 Python 进程中，会遇到：

- C++ ABI 问题；
- ROS 环境污染；
- Python dependency conflict；
- Vendor SDK crash 导致 Runtime 一起退出；
- 不同 Python 版本；
- 高速控制；
- 实时线程；
- 设备资源隔离。

因此推荐：

```text
Unified Robot SDK
        │
        ▼
Driver Protocol
        │
 ┌──────┼───────────┐
 ▼      ▼           ▼
Python  ROS Host    Native Host
Host
 │      │           │
Vendor  ROS2       C++ SDK
SDK
```

---

## 9.2 v0.1 实现策略

v0.1：

- Python SDK 可 in-process；
- ROS2 / Native 支持 out-of-process；
- IPC 优先简单可靠。

可选：

```text
Unix Domain Socket
ZeroMQ
gRPC
```

---

## 9.3 后续实时扩展

对于：

```text
500 Hz
1 kHz
Torque Control
Whole-body Control
```

可增加：

```text
shared memory
native realtime process
RT-preempt
C++ / Rust Runtime
```

不改变上层 Python API。

---

# 10. Package Registry 与 Resource Index

## 10.1 Local Registry

SDK 本地维护：

```text
~/.cross_embodiment/
├── packages/
├── cache/
├── registry/
├── runtimes/
└── environments/
```

需要支持：

```python
registry.find("hardware", "ufactory/xarm7")
registry.find("gripper", "robotiq/2f85")
registry.find("policy", "company/pick_v1")
```

---

## 10.2 Package Resolver

输入：

```yaml
package: ufactory/xarm7
version: "^1.2"
```

Resolver 负责：

```text
版本解析
↓
平台 / OS / Arch 检查
↓
Backend Variant 选择
↓
依赖解析
↓
Asset 下载
↓
Runtime 安装
↓
Digest 校验
```

---

## 10.3 OCI 风格 Artifact

长期建议 Registry 底层采用 OCI-compatible artifact storage。

一个 package 可以拥有：

```text
Manifest
├── common assets
├── linux/amd64 backend
├── linux/arm64 backend
├── ros2-humble backend
└── sim backend
```

并通过 digest 唯一标识。

---

# 11. Robot Model 与 Robot Instance

## 11.1 Robot Model

Robot Model 来源于 Hardware Package：

```text
ufactory/xarm7@1.2.0
```

描述：

- 结构；
- joint；
- capability；
- control modes；
- 默认 asset；
- backend；
- 通用 limits。

---

## 11.2 Robot Instance

一台实际机器：

```yaml
schema_version: "robot-instance/v0.1"

instance:
  id: "lab/xarm7_01"

robot:
  package: "ufactory/xarm7"
  version: "1.2.0"

backend:
  preferred: "python_direct"

connection:
  ip: "192.168.1.232"

components:
  gripper:
    package: "ufactory/xarm_gripper"
    version: "1.0.0"

calibration:
  camera_to_base:
    file: "calibration/xarm7_01_camera.yaml"

tool:
  tcp:
    file: "calibration/tool_tcp.yaml"

overrides:
  speed_limit: 0.3
```

Instance 只保存这台机器特有的信息。

---

# 12. Project 模型

## 12.1 Project 是单项目运行入口

一个项目：

```text
pick_demo/
├── project.yaml
├── embodiment.lock
├── robots/
│   └── arm_01.yaml
├── policies/
├── configs/
├── tasks/
└── main.py
```

---

## 12.2 project.yaml

```yaml
schema_version: "project/v0.1"

robots:
  arm:
    package: "ufactory/xarm7"
    version: "^1.2"
    instance: "robots/arm_01.yaml"

policy:
  package: "company/pick_policy"
  version: "0.3.1"

runtime:
  control_frequency_hz: 20
  safety_profile: "conservative"

task:
  entrypoint: "main:run"
```

---

# 13. 单项目安装与启动闭环

## 13.1 ce install

```bash
ce install
```

执行：

```text
读取 project.yaml
        ↓
解析 Hardware / Policy dependency
        ↓
解析版本
        ↓
选择当前系统 backend variant
        ↓
下载 package / asset
        ↓
准备 Python / ROS / native runtime
        ↓
校验 digest
        ↓
生成 embodiment.lock
```

---

## 13.2 ce validate

```bash
ce validate
```

检查：

```text
Package Schema
Backend Availability
Robot Instance Config
Asset Integrity
Manifest
Connection Requirements
Policy Compatibility
Safety Config
```

---

## 13.3 ce up

```bash
ce up
```

执行：

```text
读取 lock file
      ↓
启动 Driver Host
      ↓
加载 Backend
      ↓
连接 Hardware
      ↓
加载 Embodiment Manifest
      ↓
加载 Instance Config
      ↓
注册 Capability
      ↓
Health Check
      ↓
Robot READY
```

---

## 13.4 ce run

```bash
ce run
```

执行：

```text
Robot READY
    ↓
Policy Package Load
    ↓
Compatibility Check
    ↓
Observation Mapping
    ↓
Action Mapping
    ↓
Runtime Loop
    ↓
Logging / Metrics
```

---

## 13.5 ce down

```bash
ce down
```

执行：

```text
停止 Policy
↓
Runtime safe stop
↓
Disable Robot
↓
Stop Driver Host
↓
释放资源
```

---

# 14. Lock File 与实验复现

推荐：

```text
embodiment.lock
```

示例：

```yaml
lock_version: "v0.1"

hardware:
  ufactory/xarm7:
    version: "1.2.3"
    digest: "sha256:xxxx"

    backend:
      id: "python_direct"
      version: "0.4.2"
      digest: "sha256:xxxx"

    assets:
      kinematic_model:
        digest: "sha256:xxxx"

      visual_model:
        digest: "sha256:xxxx"

policy:
  company/pick_policy:
    version: "0.3.1"
    digest: "sha256:xxxx"

runtime:
  version: "0.1.0"
```

目的：

> 一次实验不仅记录模型版本，也记录完整硬件软件资产版本。

---

# 15. Robot / Device / Capability 模型

```text
Robot
├── Device: Arm("right_arm")
│   ├── JointStateProvider
│   ├── JointController
│   ├── EEStateProvider
│   └── EEController
├── Device: Gripper("right_gripper")
│   ├── GripperStateProvider
│   └── GripperController
├── Device: Camera("wrist_camera")
│   └── ImageProvider
├── Device: FT Sensor("wrist_ft")
│   └── ForceTorqueProvider
└── SafetyMonitor
```

推荐 Capability：

```text
StateProvider
JointStateProvider
JointController
EEStateProvider
EEController
GripperController
ImageProvider
DepthProvider
PointCloudProvider
ForceTorqueProvider
IMUProvider
BaseController
OdometryProvider
SafetyMonitor
TimeProvider
```

---


# 16. Canonical Capability Catalog

## 16.1 目的

为了避免每次接入新硬件时都依赖人工或 Coding Agent 通读全部厂商资料并自由判断能力，平台定义一份固定的 **Canonical Capability Catalog**。

Hardware Onboarding 的任务不再是“判断这个机器人能做什么”，而是：

> **针对标准 Capability Checklist 逐项检查，并给出明确状态、证据、语义、性能与验证结果。**

Capability Catalog 只描述**原子硬件能力**，不描述任务级能力。

例如：

```text
ee_velocity        ✓ 原子能力
joint_position     ✓ 原子能力
rgb                ✓ 原子能力

pick_object        ✗ 任务能力
open_drawer        ✗ 任务能力
```

复杂能力应由原子 Capability 组合得到。

## 16.2 Capability 状态

每个标准 Capability 固定使用以下状态之一：

```text
native
derived
unsupported
unknown
```

含义：

- `native`：厂商 API / Driver 原生提供。
- `derived`：由 Adapter / Runtime 基于其他已验证能力组合实现。
- `unsupported`：已有足够证据确认无法提供。
- `unknown`：当前资料不足，尚不能确认。

禁止使用模糊的 `true / false` 代替以上状态。

## 16.3 v0.1 基础 Capability Checklist

### Lifecycle

```text
connect
disconnect
enable
disable
reset
stop
```

### State

```text
joint_position_state
joint_velocity_state
joint_effort_state
ee_pose_state
ee_velocity_state
gripper_state
robot_mode_state
error_state
```

### Joint Control

```text
joint_position
joint_delta
joint_velocity
joint_torque
```

### EE Control

```text
ee_pose
ee_delta
ee_velocity
```

### Gripper

```text
gripper_open_close
gripper_position
gripper_velocity
gripper_force
```

### Sensor

```text
rgb
depth
pointcloud
force_torque
imu
```

### IO

```text
digital_io
analog_io
tool_io
```

### Timing / Streaming

```text
state_streaming
streaming_control
timestamp
command_frequency
state_frequency
```

### Safety

```text
estop_state
protective_stop_state
joint_limit
velocity_limit
workspace_limit
watchdog
```

Catalog 应版本化，例如：

```text
capability-catalog/v0.1
capability-catalog/v0.2
```

## 16.4 Capability 记录格式

Capability 不只记录“是否支持”，还必须记录：

```yaml
ee_velocity:
  status: native

  implementation:
    type: native

  evidence:
    api: "set_cartesian_velocity"
    source: "vendor_sdk"
    reference: "vendor_api_doc"

  semantics:
    frame: base
    linear_unit: m/s
    angular_unit: rad/s

  performance:
    max_frequency_hz: 100

  validation:
    status: passed
    test: "ee_velocity_conformance"
```

对于派生能力：

```yaml
ee_delta:
  status: derived

  implementation:
    type: derived
    based_on:
      - ee_pose_state
      - joint_position
      - kinematics

  performance:
    max_frequency_hz: 50

  validation:
    status: passed
```

## 16.5 Capability 的确定流程

最终 Capability 由三部分共同确定：

```text
Vendor API / Driver / Assets
            ↓
识别 Native Capability
            ↓
分析可构造的 Derived Capability
            ↓
Conformance Test
            ↓
Validated Capability Manifest
```

原则：

> **Manifest 中声明的是当前 Hardware Package + 当前 Backend 下真实可用且经过验证的能力，而不是机器人理论上可能具备的能力。**

因此同一个 Robot Model 在不同 Backend 下可以拥有不同 Capability Profile。

## 16.6 Coding Agent 检查流程

Coding Agent 必须按照固定 Checklist 执行，而不是自由总结能力：

```text
读取 Vendor SDK / API / ROS / Asset
                ↓
加载 Canonical Capability Catalog
                ↓
针对每个 Capability 逐项搜索证据
                ↓
native / derived / unsupported / unknown
                ↓
记录 evidence
                ↓
生成 Adapter / Mapping
                ↓
生成 Capability Profile
                ↓
运行 Conformance Test
                ↓
更新 validation status
                ↓
输出最终 Embodiment Manifest
```

Coding Agent 对每项 Capability 至少回答：

```text
1. 是否存在？
2. Native 还是 Derived？
3. 对应哪个 Vendor API？
4. 输入输出语义是什么？
5. 单位是什么？
6. Frame 是什么？
7. 最大或推荐控制频率是多少？
8. 有哪些限制？
9. 是否通过 Conformance Test？
```

## 16.7 Derived Capability 原则

Adapter 可以通过已有底层能力派生新的 Capability，但不能突破底层控制能力。

例如：

```text
高频 joint_position
+
Forward / Inverse Kinematics
+
ee_pose_state
        ↓
derived ee_pose / ee_delta
```

但如果厂商只提供低频阻塞式：

```text
move_to(pose)
```

则不能将其声明为真正的：

```text
streaming ee_delta
```

所有 Derived Capability 必须显式记录：

```text
based_on
max_frequency_hz
latency
constraints
validation
```

## 16.8 Conformance Test 与 Capability Catalog 对齐

每个 Capability 应拥有对应标准测试，例如：

```text
joint_position
    → joint_position_conformance

ee_delta
    → ee_delta_conformance

state_streaming
    → state_streaming_conformance

watchdog
    → watchdog_conformance
```

最终能力清单由测试结果反向确认：

```text
Declared Capability
        ↓
Conformance Test
        ↓
passed
        ↓
Validated Capability
```

如果测试失败，则该能力不得作为可用能力提供给 Runtime 的 Compatibility Check。


# 17. Embodiment Manifest

Manifest 描述：

> “这个本体有什么，以及这些能力是什么语义。”

不描述：

- Package 安装；
- Vendor dependency；
- Driver 启动；
- Policy logic。

核心字段：

```text
schema_version
embodiment
devices
joints
frames
capabilities
control_modes
sensors
limits
safety
```

示例：

```yaml
schema_version: "embodiment/v0.2"

embodiment:
  model: "xarm7"
  vendor: "ufactory"
  type: "single_arm"

frames:
  world: "world"
  base: "base_link"
  ee: "tool0"

devices:
  - id: "right_arm"
    type: "arm"

    joints:
      - native_name: "joint1"
        canonical_name: "arm.right.joint.0"
        type: "revolute"

      - native_name: "joint2"
        canonical_name: "arm.right.joint.1"
        type: "revolute"

    capabilities:
      - joint_state
      - joint_position
      - ee_state
      - ee_pose
      - ee_delta

control_modes:
  - type: "ee_delta"
    target: "right_arm"
    frame: "base_link"
    translation_unit: "meter"
    rotation_representation: "axis_angle"
    frequency_hz: 20

  - type: "joint_position"
    target: "right_arm"
    unit: "radian"
    frequency_hz: 100
```

---

# 18. Unified Robot SDK

SDK 面向开发者提供稳定接口。

```python
robot = connect("arm")

robot.lifecycle.start()

state = robot.state.read()

robot.ee("right_arm").command(
    mode="ee_delta",
    translation=[0.01, 0.0, 0.0],
    rotation=[0.0, 0.0, 0.02],
    frame="base",
)

robot.gripper("right_gripper").open()

robot.lifecycle.stop()
```

SDK 不暴露：

```text
XArmAPI
ROS Topic
RTDE
CAN Frame
Vendor socket
C++ handle
```

---

# 19. RobotState

RobotState 是完整硬件状态，不等于 Policy Observation。

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

    force_torques: dict[str, Wrench] | None

    safety: SafetyState
    device_status: dict[str, DeviceStatus]
```

不存在的状态使用 `None`，禁止伪造零值。

---

# 20. Policy Package 与 Policy Protocol

## 19.1 Policy Package

建议 Policy 也使用 package 化：

```text
company.pick_policy/
├── package.yaml
├── policy.yaml
├── model/
├── code/
├── preprocessing/
├── requirements/
└── tests/
```

---

## 19.2 Policy Protocol

```text
Observation
    ↓
Policy
    ↓
Action
```

Policy 声明：

- 需要哪些 observation；
- shape；
- dtype；
- frame；
- unit；
- action space；
- frequency；
- latency budget；
- horizon；
- optional / required fields。

---

# 21. v0.1 EE Policy

v0.1 支持：

- 单臂；
- RGB；
- EE Pose；
- Gripper State；
- `ee_delta`；
- 可选 `ee_pose`；
- 可选 Gripper Action。

推荐 Action：

```python
EEAction(
    translation=[dx, dy, dz],
    rotation_axis_angle=[rx, ry, rz],
    gripper=0.7,
)
```

Policy Spec：

```yaml
action_spec:
  type: ee_delta
  target: right_arm
  frame: base

  translation:
    unit: meter

  rotation:
    representation: axis_angle
    unit: radian

  frequency_hz: 20
```

---

# 22. Future Joint Policy

Joint Policy 只需要新增：

```text
Joint ActionSpec
Joint Observation
Joint Mapping
Joint Executor
```

示例：

```yaml
action_spec:
  type: joint_position
  target: right_arm

  joints:
    - arm.right.joint.0
    - arm.right.joint.1
    - arm.right.joint.2
    - arm.right.joint.3
    - arm.right.joint.4
    - arm.right.joint.5
    - arm.right.joint.6

  unit: radian
  frequency_hz: 50
```

Runtime 生命周期、Hardware Package、Driver Host、SDK、Registry、Project 均无需重构。

这就是：

> **EE-first，但不是 EE-centric。**

---

# 23. Cross-Embodiment Runtime

Runtime 负责：

1. 加载 Project；
2. 加载 Robot Instance；
3. 加载 Policy Package；
4. 读取 Embodiment Manifest；
5. Compatibility Check；
6. 创建 Observation Mapper；
7. 创建 Action Mapper；
8. 启动硬件；
9. 执行 Policy Loop；
10. 运行 Safety；
11. 记录日志和 metrics；
12. 安全停止和释放资源。

执行流程：

```text
Project
   ↓
Robot Instance + Hardware Package
   ↓
Driver / Adapter
   ↓
Robot READY
   ↓
Policy Package
   ↓
Compatibility Check
   ↓
Observation Mapping
   ↓
Policy
   ↓
Action Mapping
   ↓
Safety
   ↓
Unified Robot SDK
   ↓
Hardware
```

---

# 24. Compatibility Check

推荐结果：

```text
Native
Adaptable
Partially Compatible
Incompatible
Unsafe
```

检查：

- Policy Protocol；
- Observation；
- Action；
- Frame；
- Unit；
- Rotation；
- Frequency；
- Sensor；
- Gripper；
- Workspace；
- Latency；
- Backend；
- Device；
- Safety；
- Joint mapping。

---

# 25. Coding Agent 驱动的 Hardware Onboarding

## 24.1 输入

Coding Agent 获得：

```text
Vendor SDK
Vendor Documentation
Sample Code
URDF / Model Asset
RobotAdapter Contract
Hardware Package Schema
Embodiment Manifest Schema
Reference Package
Conformance Tests
```

---

## 24.2 自动流程

```text
Vendor Assets
      ↓
Asset Classification
      ↓
SDK / API Understanding
      ↓
Backend Selection
      ↓
Generate Hardware Package
      ↓
Generate Adapter
      ↓
Generate Embodiment Manifest
      ↓
Generate Tests
      ↓
Static Validation
      ↓
Mock / Simulator Test
      ↓
Human Review
      ↓
Real Hardware Test
      ↓
Certified Package
```

---

## 24.3 Coding Agent 不应自由设计接口

Agent 的任务不是：

> “给这个机器人写一套控制系统。”

而是：

> “把厂商已有能力映射到固定 Hardware Package Contract 和 Adapter Contract。”

这样才能规模化。

---

# 26. Package 模式

Package Mode 面向：

- 机器人算法开发者；
- 实验室；
- 本地真机部署；
- 需要自主开发 Adapter 的团队。

包含：

```text
Unified Robot SDK
Hardware Package System
Package Resolver
Local Registry
Adapter Framework
Driver Host
EE Policy Protocol
Runtime
CLI
Validation Tool
Official Packages
Reference Adapters
```

典型流程：

```text
ce init
↓
ce add robot ufactory/xarm7
↓
ce install
↓
ce validate
↓
ce up
↓
ce run
```

---

# 27. 平台模式

Platform Mode 在 Package Mode 之上增加 Control Plane。

```text
┌──────────────────────────────────────────────┐
│ Developer Portal                             │
├──────────────────────────────────────────────┤
│ Robot Registry                               │
│ Hardware Package Registry                    │
│ Policy Registry                              │
│ Adapter Registry                             │
│ Capability Database                          │
│ Compatibility Database                       │
├──────────────────────────────────────────────┤
│ Hardware Onboarding Agent                    │
│ Policy Onboarding Agent                      │
│ Auto Validation                              │
│ Certification                                │
├──────────────────────────────────────────────┤
│ Deployment                                   │
│ Fleet / Device Management                    │
│ Monitoring                                   │
│ Logs / Metrics                               │
├──────────────────────────────────────────────┤
│ Dataset / Benchmark / Performance Matrix     │
└──────────────────────────────────────────────┘
```

---

# 28. 平台模式下的硬件接入

```text
Create Robot Model
      ↓
Upload / Link Vendor Assets
      ↓
Hardware Onboarding Agent
      ↓
Generate Hardware Package
      ↓
Generate Adapter
      ↓
Generate Manifest
      ↓
Cloud Static Test
      ↓
Local Hardware Validation
      ↓
Certification
      ↓
Publish Package
      ↓
Robot Registry
```

---

# 29. 平台模式下的模型接入

```text
Upload Policy
      ↓
Generate Policy Package
      ↓
Parse Observation / Action Spec
      ↓
Compatibility Matrix
      ↓
Select Robot
      ↓
Generate Deployment Bundle
      ↓
Deploy
      ↓
Run
      ↓
Collect Metrics
```

---

# 30. Policy × Embodiment Performance Matrix

长期核心资产：

```text
              Franka   UR5   xArm7   Piper   Humanoid
Policy A        92%     87%    90%     82%       -
Policy B        88%     81%    86%     79%       -
Policy C        94%     91%    92%     84%      61%
```

不仅记录 success rate，还应记录：

```text
latency
jitter
workspace failure
gripper failure
safety intervention
observation drop
mapping type
backend
runtime version
hardware package version
```

---

# 31. 测试体系

## 30.1 Package Schema Test

验证：

- package.yaml；
- asset slot；
- backend；
- manifest；
- dependencies；
- platform variant。

## 30.2 Adapter Conformance Test

验证：

- connect/disconnect；
- state；
- joint；
- EE；
- gripper；
- error；
- timeout；
- lifecycle；
- safety；
- frequency。

## 30.3 Asset Test

验证：

- URDF / model 可解析；
- mesh path；
- frame；
- joint；
- hash；
- optional derived asset。

## 30.4 Runtime Integration Test

```text
Policy
+
Mock Robot
+
Runtime
```

## 30.5 Real Hardware Test

逐步：

```text
read-only
↓
low speed
↓
single command
↓
servo
↓
policy loop
```

---

# 32. CLI 建议

```bash
ce init

ce package search xarm

ce add robot ufactory/xarm7

ce install

ce validate

ce robot list

ce robot inspect arm

ce up

ce status

ce run

ce logs

ce benchmark

ce down
```

Adapter 开发：

```bash
ce hardware init my_vendor/my_robot

ce hardware import ./vendor_sdk

ce hardware validate

ce hardware test --mock

ce hardware test --robot lab_robot

ce hardware pack

ce hardware publish
```

---

# 33. Python 包结构

```text
cross_embodiment/
├── sdk/
│   ├── robot.py
│   ├── device.py
│   ├── capability.py
│   ├── state.py
│   ├── command.py
│   └── lifecycle.py
│
├── runtime/
│   ├── runtime.py
│   ├── scheduler.py
│   ├── compatibility.py
│   ├── observation.py
│   ├── action.py
│   └── safety.py
│
├── package/
│   ├── manifest.py
│   ├── resolver.py
│   ├── registry.py
│   ├── lock.py
│   ├── assets.py
│   └── platform.py
│
├── hardware/
│   ├── embodiment.py
│   ├── instance.py
│   └── capability.py
│
├── driver/
│   ├── protocol.py
│   ├── python_host.py
│   ├── ros_host.py
│   └── native_host.py
│
├── adapters/
│   ├── base.py
│   └── registry.py
│
├── policy/
│   ├── protocol.py
│   ├── package.py
│   ├── observation.py
│   └── action.py
│
├── transforms/
│   ├── frames.py
│   ├── rotations.py
│   ├── units.py
│   └── joints.py
│
└── cli/
```

---

# 34. 生命周期

推荐统一状态：

```text
UNINSTALLED
   ↓
INSTALLED
   ↓
CONFIGURED
   ↓
CONNECTED
   ↓
ENABLED
   ↓
READY
   ↓
RUNNING
   ├── PAUSED
   ├── FAULT
   └── STOPPED
```

Package Manager 负责：

```text
UNINSTALLED → INSTALLED
```

Hardware / SDK 负责：

```text
INSTALLED → READY
```

Runtime 负责：

```text
READY → RUNNING
```

---

# 35. 错误体系

```text
PackageError
AssetError
DependencyError
BackendUnavailable
ConfigurationError
CompatibilityError
ConnectionError
DeviceError
CommandRejected
CommandTimeout
ObservationStale
PolicyError
DriverCrash
SafetyViolation
EmergencyStop
LifecycleError
```

错误必须包含：

- code；
- timestamp；
- package；
- backend；
- device；
- recoverable；
- suggested action；
- native error。

---

# 36. 安全

v0.1 至少提供：

- enable 状态检查；
- workspace limit；
- velocity limit；
- acceleration limit；
- action clipping；
- NaN / Inf；
- stale observation；
- timeout；
- watchdog；
- communication loss；
- emergency stop propagation；
- low-speed test mode；
- dry-run；
- manual confirmation。

---

# 37. 推荐的第一批 Reference Hardware Packages

为验证 Package / Backend / Asset 设计，不应该只选择接口相似的机械臂。

推荐：

### 1. UFACTORY xArm7

目的：

- Python SDK；
- EE；
- Joint；
- Gripper；
- URDF / ROS；
- 作为 Reference Adapter。

### 2. AgileX Piper

目的：

- CAN；
- Python SDK；
- URDF；
- 验证不同底层通信。

### 3. JAKA / FAIRINO

目的：

- 工业 SDK；
- 单位、状态机、控制语义差异；
- 验证 Manifest 与 normalization。

### 4. DOBOT

目的：

- Coding Agent 自动生成 Adapter / Hardware Package。

### 5. Franka

目的：

- C++；
- 高频控制；
- Driver Host；
- native realtime backend。

---

# 38. 开发路线图

## v0.1 — Package + EE 基础闭环

必须完成：

```text
Hardware Package v0.1
Package Manifest
Embodiment Manifest
Robot Instance
Local Registry
Package Resolver
Lock File
Python Backend
Adapter Contract
Unified Robot SDK
EE Policy Protocol
Runtime
Mock Adapter
xArm Reference Package
Project CLI
```

目标：

> 同一个 EE Policy 可在两个不同 Hardware Package 上运行。

---

## v0.2 — 多 Backend + Joint 基础

新增：

```text
ROS2 Backend
Native Driver Host
Joint Policy
Joint Mapping
Multi-camera
Replay Package
Simulation Package
Remote Backend
```

---

## v0.3 — 平台化

新增：

```text
Cloud Package Registry
Robot Registry
Policy Registry
Hardware Onboarding Agent
Certification
Compatibility Database
Remote Deployment
Monitoring
```

---

## v1.0 — 跨本体开发与部署平台

新增：

```text
Bimanual
Mobile Manipulation
Whole-body
Fleet
Skill
Dataset
Benchmark
Performance Matrix
Automated Adaptation
Marketplace
```

---

# 39. 当前最关键的架构决策

### 决策 1

**Adapter 不是安装单位，Hardware Package 才是。**

### 决策 2

**原始资产不强制统一格式，统一 Asset Role 和语义。**

### 决策 3

**ROS 是 Backend，不是平台根依赖。**

### 决策 4

**复杂 Vendor Runtime 通过 Driver Host 隔离。**

### 决策 5

**Robot Model、Robot Instance、Project 必须分离。**

### 决策 6

**Project 必须支持 dependency resolution 与 lock file。**

### 决策 7

**Coding Agent 面向固定 Contract 生成 Package，而不是自由设计 Driver。**

### 决策 8

**v0.1 继续坚持 EE-first，但 Package / Runtime / SDK 不依赖 EE 假设。**

---

# 40. 最终闭环

```text
               Vendor Hardware
                     │
             SDK / ROS / C++ / Asset
                     │
                     ▼
          Hardware Onboarding Agent
                     │
                     ▼
              Hardware Package
                     │
       ┌─────────────┴──────────────┐
       ▼                            ▼
 Embodiment Manifest            Backend
       │                            │
       └─────────────┬──────────────┘
                     ▼
                Robot Instance
                     │
                     ▼
                   Project
                     │
               Package Resolver
                     │
                     ▼
                Driver Host
                     │
                     ▼
             Unified Robot SDK
                     │
                     ▼
          Cross-Embodiment Runtime
                     │
                     ▼
                  Policy
                     │
                     ▼
             Execution Data
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
 Adapter Improvement      Policy Improvement
          │                     │
          └──────────┬──────────┘
                     ▼
                  Platform
```

---

# 41. 最终产品形态

## Package Mode

> 一个本地跨本体机器人开发框架。

用户获得：

```text
Unified Robot SDK
Hardware Package System
Adapter Framework
Driver Host
Runtime
Policy Protocol
CLI
Official Packages
Reference Adapters
Validation Tool
```

核心体验：

```text
ce add
ce install
ce up
ce run
```

---

## Platform Mode

> 一个基于 Package 标准构建的跨本体开发、适配、部署和数据生态。

平台进一步提供：

```text
Robot Hub
Hardware Package Registry
Policy Hub
Adapter / Backend Registry
Hardware Onboarding Agent
Compatibility Engine
Deployment
Monitoring
Benchmark
Dataset
Performance Matrix
Certification
Marketplace
```

最终目标不是：

> “支持很多机器人。”

而是：

> **让新的硬件、新的模型和新的应用都能够以标准资产形式进入同一运行体系，并通过 Runtime 在不同本体之间复用、验证和部署。**

# 42. 用户项目目录结构

用户项目应保持轻量，只保存“这次项目要使用什么”，而不直接承载厂商 SDK、URDF、Adapter 等硬件通用资产。

推荐结构：

```text
pick_demo/
├── project.yaml              # 项目入口：Robot / Policy / Runtime / Task
├── embodiment.lock           # 锁定 Hardware / Policy / Runtime 精确版本
│
├── robots/                   # Robot Instance 配置
│   ├── arm.yaml
│   └── camera.yaml
│
├── policies/                 # 本地 Policy，可选
│   └── pick_policy/
│       ├── policy.yaml
│       ├── model/
│       └── code/
│
├── tasks/                    # 任务逻辑
│   └── pick.py
│
├── configs/                  # 项目级配置
│   ├── runtime.yaml
│   └── safety.yaml
│
├── calibration/              # 仅属于当前设备实例的标定
│   ├── camera_to_base.yaml
│   └── tool_tcp.yaml
│
├── data/                     # 可选：运行数据
├── logs/                     # 运行日志
├── tests/                    # 项目级测试
└── README.md
```

## 42.1 Project 与 Hardware Package 的边界

项目中不直接放：

```text
Vendor SDK
URDF / Xacro / USD / Mesh
Adapter
Driver
通用控制配置
```

这些属于 Hardware Package。

项目只通过依赖引用：

```yaml
robots:
  arm:
    package: "ufactory/xarm7"
    version: "^1.2"
    instance: "robots/arm.yaml"
```

因此：

```text
Project
├── 这次使用什么 Robot / Policy
├── 具体 Robot Instance 怎么连接
├── 运行什么 Task
├── 项目自己的标定
└── 项目自己的 Runtime / Safety 配置

Hardware Package
├── 机器人型号本身的资产
├── Adapter / Backend
├── Vendor Runtime
├── Embodiment Manifest
└── Conformance Tests
```

这样同一个 Hardware Package 可以被多个项目复用。

---

# 43. SDK 源码仓库结构

核心 SDK 仓库只维护稳定标准、运行基础设施与公共工具，不直接包含具体厂商实现。

推荐结构：

```text
cross-embodiment-sdk/
├── pyproject.toml
├── README.md
├── LICENSE
│
├── src/cross_embodiment/
│   ├── __init__.py
│   ├── api.py
│   │
│   ├── sdk/                    # Unified Robot SDK
│   │   ├── robot.py
│   │   ├── device.py
│   │   ├── capability.py
│   │   ├── state.py
│   │   ├── command.py
│   │   └── lifecycle.py
│   │
│   ├── runtime/                # Cross-Embodiment Runtime
│   │   ├── runtime.py
│   │   ├── scheduler.py
│   │   ├── compatibility.py
│   │   ├── observation.py
│   │   ├── action.py
│   │   └── safety.py
│   │
│   ├── protocol/               # Policy / Observation / Action 协议
│   │   ├── policy.py
│   │   ├── observation.py
│   │   ├── action.py
│   │   └── schemas/
│   │
│   ├── hardware/               # 硬件语义模型
│   │   ├── embodiment.py
│   │   ├── instance.py
│   │   ├── capability_catalog.py
│   │   └── manifest.py
│   │
│   ├── package/                # Package 管理
│   │   ├── manifest.py
│   │   ├── resolver.py
│   │   ├── registry.py
│   │   ├── assets.py
│   │   └── lock.py
│   │
│   ├── adapter/                # Adapter 标准，不放具体厂商实现
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── conformance.py
│   │
│   ├── driver/                 # Backend / Driver Host
│   │   ├── protocol.py
│   │   ├── python_host.py
│   │   ├── ros2_host.py
│   │   └── native_host.py
│   │
│   ├── transforms/
│   │   ├── frames.py
│   │   ├── rotations.py
│   │   ├── joints.py
│   │   └── units.py
│   │
│   ├── errors.py
│   └── logging.py
│
├── cli/                        # ce install / validate / up / run / down
│
├── schemas/                    # YAML / JSON Schema
│   ├── hardware-package/
│   ├── embodiment/
│   ├── robot-instance/
│   ├── policy/
│   └── project/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── conformance/
│   └── mock/
│
├── examples/
└── docs/
```

## 43.1 核心 SDK 与厂商包分离

具体厂商实现不建议直接放进核心 SDK 仓库。

可以维护独立 Hardware Package 仓库：

```text
hardware-packages/
├── ufactory-xarm/
├── agilex-piper/
├── jaka/
└── dobot/
```

也可以进一步拆成独立发布包：

```text
ce-hardware-ufactory-xarm
ce-hardware-agilex-piper
ce-hardware-jaka
ce-hardware-dobot
```

核心 SDK 只维护：

```text
标准
Schema
Runtime
Package System
Adapter Contract
Driver Host
CLI
Conformance Test
```

Hardware Package 生态负责：

```text
Vendor SDK
Adapter
Robot Assets
Backend
Vendor-specific Config
Hardware Tests
```

## 43.2 三类目录边界

最终应明确区分：

```text
SDK Repository
    = 平台标准与运行基础设施

Hardware Package Repository
    = 某个硬件型号如何被平台支持

User Project
    = 这次具体应用如何组合 Robot + Policy + Task
```

这三个层次应保持独立，避免随着支持厂商数量增加而污染核心 SDK 或用户项目。
