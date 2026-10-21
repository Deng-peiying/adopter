# 跨本体具身智能 SDK 整体设计 v0.4

**文档版本：** v0.4  
**状态：** 正式设计基线；不代表全部设计已实现或通过实机验收  
**日期：** 2026-10-21  
**基础来源：** [v0.3 整体方案](cross-embodiment-sdk-design-v0.3.md)与 [v0.4 设计依据草案](v0.4-draft.md)  
**配套实施：** [v0.4 Implementation](../implementation/cross-embodiment-sdk-implementation-v0.4.md)  
**核心策略：** EE-first；Package-first；包内 Adapter 实现厂商语义，SDK 提供通用契约与机制。

本文是包含既有整体方案的独立可读版本，不是对 v0.3 的增量补丁。冲突章节已在原位置替换；未冲突的产品与平台设计继续保留。第 1—43 节规定整体设计，第 44 节区分基础交付、实施差距与继承关系。

SDK 文档版本、Python 发行版本、Schema 版本和硬件包版本相互独立，不能因为本文升级而将当前发行包或硬件包统称为 0.4。长期规划和概念示例不自动变成当前可调用 API；以 implementation 的交付状态和实际实现为准。

---

## 1. 摘要

本方案定义面向多种机器人本体的统一软件基础设施，使应用和策略使用统一硬件接口、状态模型和 Policy Protocol，在不同机器人上运行、评测和部署。

v0.4 在 v0.3 整体方案上正式确定以下边界：

1. **Hardware Package 是型号级交付单元。** 具体 Adapter 与厂商 SDK、接口类型、驱动、配置、模型和验证材料一起交付。
2. **SDK 提供通用契约和基础设施。** 厂商端点、报文、单位和关节转换、状态码、使能和完成条件由包内 Adapter 实现。
3. **构造即配置，连接显式。** `Robot.__init__()` 内部调用 `Lifecycle.configure()`；不公开 `Robot.configure()`；构造不启动通信或改变硬件。
4. **连接、使能、就绪分开。** `Robot.connect()` 仅连接；`robot.lifecycle.enable()` / `disable()` 负责显式硬件操作及确认。
5. **关闭不等于停用或停止运动。** `Robot.close()` 释放连接和拥有的资源；停止运动是独立能力。
6. **保留运行时跨本体转换。** 删除 SDK 的厂商 YAML 映射执行引擎，不删除用于 Policy、坐标、运动学和跨本体适配的 Runtime 映射。
7. **不保留旧 SDK 转发兼容层。** 旧硬件包通过迁移、发布新版本进入新契约。

整体仍坚持 EE-first，而不是把末端动作作为所有本体的根假设。Joint、Base、Bimanual、Whole-body、多模态观测、仿真、回放和实时控制继续作为能力驱动的扩展方向。

保留 v0.3 的产品范围：Package / Asset / Registry / Model / Instance / Project / Lock、统一硬件与 Policy 协议、Runtime、Onboarding、测试、平台模式和性能矩阵。v0.4 的规范不表示上述全部功能已经实现；实施边界和差距见第 44 节及配套 implementation。

厂商交付形式可以是 Python/C++ SDK、ROS、二进制或网络/总线协议。模型和接口形式按目标能力选择，不把 ROS、URDF 或完整驱动源码作为所有本体的统一前提。

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


### 3.10 v0.4 的实现归属

统一接口由 SDK 定义；厂商语义由包内 Adapter 实现。配置无硬件副作用，连接、使能和运动显式，通信成功与物理效果分开确认。

## 4. 总体架构

```text
Application / Skill / Benchmark / Data Collection
                         │
Policy Package / Policy Protocol / ObservationSpec / ActionSpec
                         │
Cross-Embodiment Runtime：兼容性、策略映射、调度、通用安全
                         │
Unified Robot SDK：Robot ──组合── Lifecycle
                         │
RobotAdapter 契约
                         │
Hardware Package：具体 Adapter + 映射代码 + 厂商资产 + 配置 + 测试
                         │ 按需组合
SDK 通用机制：Transport / Driver Host / Environment / ProcessSupervisor
                         │
Vendor SDK / ROS Driver / Native Library / Network / Bus / Simulator
                         │
Robot / Sensor / Gripper
```

这是职责图，不表示所有模块在同一进程。当前可用的基础隔离为“应用侧纯 Python Adapter + 子进程 Transport”；完整 Adapter Host 是后续隔离里程碑，见第 9 节。

SDK 不按厂商增加控制器实现。只有现有统一协议缺少某种可复用能力时，才扩展 Core；具体机器人的报文、模式和值不进入 Core。

---

## 5. 核心概念边界

| 概念 | 回答的问题 | 责任 |
|---|---|---|
| Hardware Package | 型号如何被接入和交付？ | 具体 Adapter、原始资产、默认配置、启动方案、证据和测试 |
| Robot | 应用如何操作某个实例？ | 能力查询、状态、动作和便捷连接入口 |
| Lifecycle | 操作顺序和资源状态如何管理？ | 配置、连接、使能、停用、关闭的调度与本地记录 |
| Adapter | 厂商行为如何变为统一语义？ | 协议映射、资产选择、生命周期落实、故障与结果解释 |
| Transport | 如何完成通信？ | 订阅、请求、响应、反馈、超时和通信级结果 |
| Driver Host | 厂商运行环境如何承载？ | 子环境、IPC、后端执行及资源所有权；不决定厂商语义 |
| Embodiment Manifest | 本体具备哪些能力与约束？ | devices、joints、frames、控制模式、单位、限位与能力依据 |
| Robot Instance | 这台具体设备如何配置？ | 实例 ID、连接参数、组件、标定和实例级覆盖 |
| Runtime | Policy 如何运行于该本体？ | 兼容性、观测/动作转换、调度、安全和实验记录 |
| Policy Package | 模型需要和输出什么？ | 模型资产、运行依赖、观测与动作契约 |
| Project | 本次应用如何组合资源？ | Robot、Policy、Task、运行配置与依赖 |
| Registry / Store | 包和版本在哪里？ | 发现、安装、摘要校验和激活记录 |
| Lock File | 一次运行具体用了什么？ | 精确版本、摘要、Backend、资产和运行配置 |

Robot 与 Lifecycle 采用组合关系，生命周期本地状态只由 Lifecycle 管理。Adapter 保存真实通信和设备状态；本地“调用过 enable”不能作为硬件已使能的证明。

---

## 6. Hardware Package / Embodiment Package

### 6.1 定义

Hardware Package 是机器人、夹爪、相机等硬件型号进入生态后的最小可安装、可发现、可版本化和可复现交付单元。建议身份采用 `vendor/model`，例如 `ufactory/xarm7`、`robotiq/2f85`、`intel/realsense_d405`、`franka/fr3`、`agilex/piper`。

Adapter 是包内的具体实现，不是独立于厂商资产的完整交付。包可以引用可安装的系统依赖，但必须声明版本、平台和检查方式，不能默默依赖开发者电脑上的路径。

### 6.2 推荐目录结构

```text
ce-hardware-vendor-model/
├── package.yaml
├── embodiment.yaml
├── adapters/
│   ├── python/                 # 每种后端包含具体 Adapter
│   │   ├── adapter.py
│   │   ├── mapping.py          # 可选拆分：厂商语义转换
│   │   ├── driver.py           # 可选拆分：环境、资产与启动方案
│   │   └── requirements.txt
│   ├── ros2/
│   │   ├── adapter.py
│   │   ├── mapping.py
│   │   ├── driver.py
│   │   └── backend.yaml
│   └── native/                # Python 包装器或 Host 入口
├── vendor/                    # 原始接口、运行时、库、头文件和来源说明
├── assets/                    # URDF/Xacro/USD/MJCF/mesh 等按需保留
├── launch/
├── config/
│   ├── connection.yaml
│   └── safety.yaml
├── examples/                  # Instance 配置与最小应用示例
├── tests/                     # 映射、契约、mock、授权硬件验证
├── validation/
├── provenance/
├── licenses/
└── README.md
```

`mapping.py`、`driver.py` 是推荐组织，不要求每个包机械地拆成相同文件。资产可以保留厂商原始目录，只需清单中的路径和摘要准确；不为统一外观移动资产或破坏厂商引用。

### 6.3 Package Manifest

下面是 Python Adapter 入口模式的包清单示例；ROS/Native 也由包内入口组合通用工具，不直接指向 SDK 内置厂商适配器。

```yaml
schema_version: hardware-package/v0.1
package:
  name: vendor/model
  version: 1.0.0
  vendor: vendor
  model: model
  type: robot
embodiment_manifest: embodiment.yaml
assets:
  adapter_code:
    - format: directory
      path: adapters
      source: true
      # 发布时必须填写真实 digest: sha256:...
  vendor_runtime:
    - format: directory
      path: vendor
      source: true
  kinematic_model:
    - format: urdf
      path: assets/robot.urdf
      source: true
backends:
  - id: python_direct
    type: python
    entrypoint: adapters.python.adapter:VendorAdapter
    platforms:
      - os: linux
        arch: x86_64
    requirements:
      python: '>=3.10'
  - id: ros2_humble
    type: python
    entrypoint: adapters.ros2.adapter:VendorRos2Adapter
    requirements:
      ros_distro: humble
      python: '3.10'
defaults:
  backend: python_direct
  config: config/connection.yaml
```

示例省略真实文件摘要，不可原样作为发布包。模型 slot 按能力选择；没有模型不自动阻止只需通信和状态的能力。Native 的二进制、外部 ROS package 和 launch 文件可作为资产或包内后端描述保留，但不得绕过 Adapter 契约。

Adapter 代码、环境和启动脚本、影响语义的配置均须纳入完整性校验。已安装版本保持不可变；修改后发布新版本，再显式安装并激活。

---

## 7. Asset 管理设计

### 7.1 Asset Slot

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

### 7.2 Asset Variant

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

### 7.3 Source Asset 与 Derived Asset

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


### 7.4 可执行代码与运行配置资产

Adapter 代码、启动/环境脚本和影响行为的配置与厂商资源一起参与摘要和版本管理；安装后不可变。日志、缓存和运行输出不得写回安装包。模型不是每种本体的必需资产，按所声明能力验证。

## 8. Backend / Adapter 体系

### 8.1 Adapter Contract

```python
class RobotAdapter(Protocol):
    adapter_id: str
    version: str

    def load_manifest(self) -> EmbodimentManifest: ...
    def configure(self) -> None: ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def enable(self) -> None: ...
    def disable(self) -> None: ...
    def capabilities(self) -> dict[str, Any]: ...
    def supports_action(self, action_type: str, device_id: str) -> bool: ...
    def get_state(self) -> RobotState: ...
    def get_joint_state(self, device_id: str) -> JointState: ...
    def send_command(self, command: Command) -> CommandResult: ...
    def health(self) -> HealthReport: ...
```

方法签名以此处为基线。无关节的本体对 `get_joint_state()` 明确报告不支持，不能构造虚假的关节。缺少某种生命周期操作时也必须明确报告，不能空实现并返回成功。

包内 Python Adapter 构造基线为：

```python
VendorAdapter(
    manifest,
    connection=connection,
    control_enabled=False,
    dry_run=False,
)
```

实例工厂提供经验证的 `package_root` 和合并后的连接选项；`AdapterContext` 解析包资源并拒绝路径越界。运行目录与日志写入用户 state/runtime 区域，不修改已安装包。

`configure()` 只校验、定位资源、准备参数和环境描述。厂商 SDK 若导入即触发设备操作，应延迟到连接阶段并在 Host 中加载。`connect()` 不接收第二份独立 config，避免配置来源分叉。

### 8.2 厂商语义由包内实现

Adapter 负责 Vendor API 到统一 API 的转换、关节和坐标映射、单位/方向/零位、状态有效性、生命周期请求、故障解释、能力暴露及执行与实测确认。它可以组合 Transport、进程和状态辅助工具。

Adapter 不负责 Policy 推理、Policy compatibility、跨本体策略映射或应用任务逻辑。SDK 不提供一个承载全部厂商行为的巨型 BaseAdapter，也不通过统一 YAML 执行引擎强行表达所有厂商状态机。

YAML 可保存端点、参数和证据。`InterfaceMappingEngine`、`MappedRos2Adapter` 和旧入口转发不属于 v0.4 架构；包内可执行代码才是具体映射实现。

### 8.3 Backend 与通信类型

Backend 表示包声明的一套实现和环境选择，可以组合 Python SDK、ROS 2、Native、网络/总线、Remote、Simulation、Replay 或 Mock。Backend ID 是实现身份，`ros2` 等通信标签不替代包内入口。

新增协议通常新增硬件包即可。只有统一动作或状态契约缺少通用语义时才扩展 Core；不将某个厂商的 Type/Command、状态数值或设备 IP 放入 Core。

### 8.4 通信结果与动作结果

Transport 的 `TransportRequest / TransportEvent / TransportResult` 只表达通信请求、状态事件和通信结果。ROS 服务传输成功、UDP 发出、Action accepted、Action terminal、厂商成功码、实测到位是不同事实。

Adapter 返回 `CommandResult` 时分别填写 `status`、`dispatched`、`accepted`、`backend_code`、`arrival_confirmed`、`final_joint_state`、`max_joint_error_rad` 等适用字段。未知字段保持 `None`；无法确认物理执行时返回明确的未确认结果，不能标记动作完成。

---

## 9. Driver Host

### 9.1 隔离目标

Host 用于隔离 Python 版本、厂商依赖、ROS 类型与原生库 ABI、崩溃和运行资源；不是厂商控制策略的拥有者。应用侧环境不手动 source 厂商脚本，不注入厂商 `sys.path`、`PYTHONPATH` 或 `LD_LIBRARY_PATH`。

```text
应用独立环境
  Robot / Lifecycle / Runtime
           │ 统一协议
           ▼
Host 后端环境（目标结构）
  包内具体 Adapter
    ├── 通信机制
    ├── 厂商 SDK / 类型 / 原生库
    └── Driver 启动方案 → 通用进程工具
```

### 9.2 基础隔离与完整 Adapter Host 分阶段

| 形态 | 执行位置 | 范围 |
|---|---|---|
| 纯 Python inline Adapter | 应用侧运行无副作用的包内映射代码 | 显式选择，依赖与应用兼容；不承诺崩溃隔离 |
| Transport Host | Adapter 在应用侧，通信和厂商类型在子进程 | 当前基础实现；不能称为完整 Adapter IPC |
| 完整 Adapter Host | Adapter 及其厂商依赖在 Host，应用持有代理 | 后续独立里程碑；需补协议、代理和故障语义 |

v0.4 基础交付以明确标注的 Transport 隔离为界；完整 Adapter Host 的方向保留，不将它写成当前已完成能力。对必须在导入时加载冲突库的 Adapter，基础形态不足时须拒绝运行或明确要求完整 Host，不能偷偷污染应用环境。

### 9.3 环境准备与进程所有权

初始化准备 `EnvironmentSpec`、资源路径和启动参数；到连接阶段才在独立 shell 中解析 setup scripts 并构造子进程 env。优先固定解释器路径和依赖版本。

- `external`：接入已有 Driver，不拥有、不终止其进程。
- `managed`：由本实例启动 Driver，记录进程组和所有权，仅清理所拥有的资源。

`driver_mode`、`host_python`、超时等为包后端连接选项，按包声明校验，不能把 ROS 相关选项注入每种硬件。setup 脚本来自经摘要校验的包；进程隔离不等于容器、安全沙箱或硬实时保证。

### 9.4 IPC 基础约束

基础 Transport Host 采用带请求 ID 的 JSON 行消息和异步事件；控制通道与厂商 stdout/native 日志分离。字段只使用可序列化数据，时间戳统一编码；ROS sequence、固定长度数组、NumPy 标量和数组须转为普通数据。

RPC 必须有超时、关联 ID、明确关闭行为和错误传递。Host 在请求写出前已死亡时不得声称已派发；写出后失联只能报告结果未知。超时不能自动重发非幂等硬件操作，也不证明物理运动停止。

完整 Adapter Host 需覆盖 configure/connect/enable/disable/state/capabilities/command/health/disconnect，与 Transport RPC 分别版本化；在该里程碑中冻结消息 schema。当前不能将仅有 connect/execute/ready 的 Transport worker 当作完整 Adapter Host。

### 9.5 实时扩展

500 Hz、1 kHz、力矩或 Whole-body 控制可采用共享内存、原生实时进程、RT-preempt、C++/Rust Runtime。具体后端应声明可验证的频率与延迟；不以 Python API 不变推导实时性能已经具备。

---

## 10. Package Registry 与 Resource Index

### 10.1 Local Registry

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

### 10.2 Package Resolver

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

### 10.3 OCI 风格 Artifact

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


### 10.4 基础 Store 与实例激活

当前基础本地布局包含 `packages/hardware/`、`records/hardware/`、`activations/`；激活记录绑定实例、包版本/摘要、后端和配置。Registry 发现与 Store 安装角色分开，OCI 仍为长期分发方向。安装/激活只处理资产与配置，不连接硬件。

## 11. Robot Model 与 Robot Instance

### 11.1 Robot Model

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

### 11.2 Robot Instance

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

## 12. Project 模型

### 12.1 Project 是单项目运行入口

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

### 12.2 project.yaml

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

## 13. 单项目安装与启动闭环

### 13.1 ce install

读取 `project.yaml`，解析 Hardware / Policy 依赖与平台 Variant，下载或定位包、检查摘要、准备后端环境、生成 `embodiment.lock`。此过程不启动硬件、不上电。

### 13.2 ce validate

校验 Package Schema、Manifest、Instance、资产摘要、包内 Adapter 入口、平台依赖、策略兼容和安全配置。动态预检或实机验证必须单独标识，不能由静态校验暗中触发。

### 13.3 ce up

v0.4 目标语义：读取 lock、Instance 和 Manifest，构造已配置 Robot，再连接 Host / Adapter / Driver 并获取有效状态。**默认只到 CONNECTED，不隐式 enable，也不把 CONNECTED 报为运动 READY。**

应用自行调用 `robot.lifecycle.enable()`；CLI 自动化仅在独立显式选项 `ce up --enable` 下执行使能并确认。该选项属于待落地目标，不表示当前 CLI 已支持。`allow_motion` / `control_enabled` 是运动授权，不等价于使能操作。

### 13.4 ce run

加载 Policy、完成 Compatibility Check、创建观测与动作转换并运行任务。运动任务启动前必须满足实例的控制授权和目标能力的 READY 条件；不在配置或任务导入过程中隐式使能。

### 13.5 ce down

保留 v0.3 的受控关闭意图，但分步报告结果：

```text
停止 Policy 下发，拒绝新动作
    → 若运行过运动，调用已声明的运动停止能力并确认
    → 显式 disable，并按厂商状态确认
    → close，断开连接并清理所拥有的 Host / Driver
```

停止、停用不支持、失败或结果未知时，命令返回非零并记录具体阶段；不能仅因资源清理完成而报告安全停机。必要的最终资源清理仍需执行，报告应保留未确认的硬件状态。

`ce down --disconnect-only` 是只释放连接与拥有资源的目标入口，不声称停止或下电；该选项同样需要 implementation 落地。Python `close()` 对应这个资源语义，不等同于完整 `ce down`。

### 13.6 已安装实例的直接使用路径

```bash
ce package build --package-root ./ce-hardware-vendor-model --output ./robot.cepack --json
ce package install --artifact ./robot.cepack --json
ce package activate vendor/model@1.0.0 --instance ./robot.instance.yaml --json
```

随后通过 `Robot.from_instance(instance_id)` 构造断开状态句柄。安装、激活和配置均不触发硬件连接；`connect()` 才开始实际接入。Project 依赖路径与已激活实例路径须共享包验证、后端选择和生命周期契约，不能维护两套相互冲突的启动语义。

---

## 14. Lock File 与实验复现

项目使用 `embodiment.lock` 固定解析结果，一次实验应能追溯硬件软件资产、Policy 和 Runtime 的精确版本。

### 14.1 基础锁文件结构

v0.4 基础结构沿用 `lock_version: v0.1`：Backend 为包内后端 ID，资产按 slot 保存 Variant 列表。以下摘要为结构示意的占位值，实际文件由 Resolver 计算生成，不能复制为真实发布结果。

```yaml
lock_version: v0.1
hardware:
  vendor/model:
    version: 1.0.0
    manifest: package.yaml
    digest: sha256:PACKAGE_TREE_DIGEST
    backend: python_direct
    assets:
      kinematic_model:
        - format: urdf
          path: assets/robot.urdf
          source: true
          digest: sha256:ASSET_DIGEST
```

包树摘要覆盖具体 Adapter、后端描述和运行资产；资产摘要与整个包的摘要各自校验，不能混用计算规则。包内 Backend 没有独立发布时，不虚构一个独立后端版本替代包版本。

### 14.2 完整实验记录

保留 v0.3 的完整复现要求：除硬件外，记录 Policy 包版本/摘要、Runtime 版本、所选 Backend、模型/标定资产和实例配置。可以通过扩展锁文件或关联运行记录表达；新增结构必须版本化并由对应读取器验证。

当前 Resolver 写出的基础 lock 主要是 hardware，尚不应宣称 Policy 和 Runtime 的完整锁定已经完成。v0.3 中 Backend 内嵌独立 version/digest 对象的概念示例不作为当前 `backend: <id>` 的第二套格式保留。

---

## 15. Robot / Device / Capability 模型

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

## 16. Canonical Capability Catalog

### 16.1 目的

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

### 16.2 Capability 状态

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

### 16.3 v0.1 基础 Capability Checklist

#### Lifecycle

```text
connect
disconnect
enable
disable
reset
stop
```

#### State

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

#### Joint Control

```text
joint_position
joint_delta
joint_velocity
joint_torque
```

#### EE Control

```text
ee_pose
ee_delta
ee_velocity
```

#### Gripper

```text
gripper_open_close
gripper_position
gripper_velocity
gripper_force
```

#### Sensor

```text
rgb
depth
pointcloud
force_torque
imu
```

#### IO

```text
digital_io
analog_io
tool_io
```

#### Timing / Streaming

```text
state_streaming
streaming_control
timestamp
command_frequency
state_frequency
```

#### Safety

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

### 16.4 Capability 记录格式

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

### 16.5 Capability 的确定流程

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

### 16.6 Coding Agent 检查流程

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

### 16.7 Derived Capability 原则

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

### 16.8 Conformance Test 与 Capability Catalog 对齐

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

## 17. Embodiment Manifest

Manifest 描述本体的设备、能力、单位、坐标、控制约束和安全要求，不描述包安装、厂商依赖、Driver 启动或 Policy 实现。不同本体只声明适用字段。

v0.4 基础存储沿用 `embodiment/v0.2`，控制声明放入 `control.supported_modes`，不再并列维护顶层 `control_modes` 的另一套权威解释。

```yaml
schema_version: embodiment/v0.2
embodiment:
  model: example_arm
  vendor: example
  type: single_arm
  dof: 2
frames:
  world: world
  base: base_link
  ee: tool0
devices:
  - id: right_arm
    type: arm
    capabilities: [joint_state, joint_position]
    joints:
      - canonical_name: arm.right.joint.0
        type: revolute
        unit: radian
        limits: [-1.0, 1.0]
      - canonical_name: arm.right.joint.1
        type: revolute
        unit: radian
        limits: [-1.0, 1.0]
control:
  supported_modes:
    - type: joint_position
      target: right_arm
      dimension: 2
      unit: radian
safety:
  requires_enable: true
  max_state_age_ms: 1000
```

该示例仅声明两轴关节能力；不得由此推导已有 EE、传感器或实时控制能力。EE 模式还需声明 frame、translation unit、rotation representation 和频率；关节模式须有完整 canonical 名称与限位。厂商字段和原始关节顺序在包内映射中解释。

规范 Capability Catalog 中的能力 ID 与现有设备能力 token（例如 `joint_position_state` / `joint_state`）须有显式、可测试的对照，不能靠名称相近自动认定一致。完成这一对齐之前不得将两个名字当成不同已验证能力重复计数。

---

## 18. Unified Robot SDK

### 18.1 应用入口

```python
from cross_embodiment import Robot

robot = Robot.from_instance("lab/arm-01", allow_motion=False)
# 返回前已执行内部 configure；尚未连接、使能或发送运动。
try:
    robot.connect()
    print(robot.capabilities())
    state = robot.get_joint_state("right_arm")
    print(state.status, state.positions)
finally:
    robot.close()
```

`Robot.from_instance(instance_id, store=None, allow_motion=False)` 从已激活实例解析精确包、后端与配置。`instance_id` 是实例身份，不是型号、IP 或 ROS 节点名。

### 18.2 Robot 与 Lifecycle

`Robot.__init__()` 创建 Lifecycle 并调用其内部 `configure()`；配置错误直接终止构造。不新增公开 `Robot.configure()`。`Robot.connect()` / `close()` 只委托给 Lifecycle，不另存一份连接或使能状态。

对应用提供：`state()`、`observe()`、`capabilities()`、`get_joint_state(device_id)`、`command(Action)`、`move_joints(device_id, positions)`。便捷 Device / EE / Gripper API 继续作为整体规划，只有实现与声明匹配时才开放。

`robot.lifecycle.enable()` / `disable()` 要求已连接。每次调用交由 Adapter 检查真实状态；是否可以在已达目标状态时直接确认，由该 Adapter 的已验证幂等语义决定。不能仅修改本地布尔值。

### 18.3 动作与结果

`Robot.command()` 接受统一 `Action`，拒绝应用直接传入后端内部 `Command`。通用安全检查在转换和下发前执行；完整绝对关节目标包含目标设备的全部 canonical 关节，不允许缺失关节被填零。

`move_joints()` 返回单个 `CommandResult`。调用者按能力检查执行状态和实测确认，不能用 `accepted` 或 `dispatched` 判断到位。相对动作以有效实测基准计算，初始化占位值不能作为当前位置；真实全零姿态也不能被平台一概判为无效，应依赖数据有效性证据。

### 18.4 生命周期边界

`allow_motion=True` 只授权运动下发，不能替代硬件 enable 或 READY。`with robot:` 相当于显式 connect，退出时 close，不隐式上电或下电。

v0.3 示例中的 `lifecycle.start()` 与含混的 `lifecycle.stop()` 不作为 v0.4 公共 API 保留；已存在的 stop 复合实现需要在 implementation 中移除并迁移调用点。停止运动通过单独声明的 `stop` 动作能力执行，见第 34 节。

厂商 SDK 对象、Topic、CAN Frame、Socket 和 Native handle 不进入统一应用接口。

---

## 19. RobotState 与实测状态

RobotState 表达硬件状态，不等于 Policy Observation。基础类型位于 `protocol/types.py`：

```python
@dataclass
class RobotState:
    timestamp: datetime
    sequence_id: int
    joint_positions: dict[str, float] | None
    joint_velocities: dict[str, float] | None
    joint_efforts: dict[str, float] | None
    ee_poses: dict[str, Pose] | None
    grippers: dict[str, float] | None
    safety: SafetyState
    device_status: dict[str, str]

@dataclass(frozen=True)
class JointState:
    device_id: str
    positions: dict[str, float]
    source_timestamp: datetime | None
    received_at: datetime
    status: str
    details: dict[str, Any]
```

后续可扩展 ee_twists、force_torques、Base/Odometry、IMU 和其他状态，但不能把预留字段写成已提供的传感器反馈。

状态必须区分实测与目标、缺失与零值、来源时间与本地接收时间。不存在的状态用 `None` 或明确缺失状态表达；禁止用命令值、初始化缓存或构造时间伪造实测反馈。

JointState 的基础状态包括 `ready`、`not_ready`、`stale`、`fault`、`timestamp_unconfirmed`；未知来源时间保持 `None`，不能补当前时间使其看起来新鲜。序号和时间戳应能识别缓存重复、乱序和过期。

控制模式 ready 不自动保证位置值有效。Adapter 应根据厂商有效位、初始化状态、反馈来源和时间关系建立有效性判断；证据不足时将能力限制为未确认，应用可增加更保守的运动基准检查。

`SafetyState.enabled/estop/fault` 是从已知设备状态得到的结果；未知或未验证的急停、下电能力必须在 Capability Profile 中明确记录，不能把缺少反馈解释为已确认安全。

---

## 20. Policy Package 与 Policy Protocol

### 20.1 Policy Package

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

### 20.2 Policy Protocol

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

## 21. EE Policy 基础规范

延续早期 EE-first 的基础目标范围：

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

## 22. Joint Policy 与其他动作空间

保留 v0.3 的 Joint Policy 扩展方向：Joint ActionSpec、Joint Observation、Joint Mapping 和执行器复用既有 Package、Instance、Registry、Host 和 Runtime 体系。

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

这是目标协议示例，实际可用频率必须由具体后端的验证记录支持。不得把低频阻塞 MoveJ 包装成高频关节伺服。

Base、Bimanual、Whole-body 等动作空间在统一契约缺失时扩展 SDK；厂商通信实现仍在包内。归一化输入与物理速度需要不同单位声明，不能在没有映射依据时当作 m/s 或 rad/s。M20 的机身运动及其归一化接口仍处于讨论，不属于本次 v0.4 基础能力冻结范围。

---

## 23. Cross-Embodiment Runtime

Runtime 负责加载 Project、Robot Instance、Policy、Manifest，完成 Compatibility Check、Observation Mapping、Action Mapping、调度、安全约束和日志指标。

```text
Project + Lock
    → Instance + Hardware Package
    → 构造 Robot（内部 configure）
    → 显式 connect → CONNECTED
    → 校验 Policy / Capability / Unit / Frame / Timing
    → 显式授权与 enable → 按目标能力确认 READY
    → Observation Mapping → Policy → Canonical Action
    → 通用 Safety → Runtime Action Mapping → 包内 Adapter
    → 厂商命令与反馈 → 统一结果 / 数据记录
```

Runtime 的 Mapping 是策略到本体的转换，不是厂商报文解释器。坐标、关节空间、运动学和策略动作转换继续保留；SDK 不因删除 `mapping/engine.py` 而删除 `runtime/mapping.py`。

任务停止时先停止新命令和调度，再依照已声明的运动停止/停用能力处理硬件，最后释放资源。任何未确认状态需要记录，不能把进程退出当成物理停止。

---

## 24. Compatibility Check

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

## 25. Coding Agent 驱动的 Hardware Onboarding

### 25.1 输入材料

厂商材料按目标能力收集，可为 SDK、二进制、动态库、协议说明或 ROS 包。通用最小输入包括：

| 材料 | 需要明确的信息 |
|---|---|
| 控制入口与依赖 | 连接、发送、反馈方式；OS/CPU/语言版本、库与权限 |
| 接口语义 | 参数、单位、坐标、返回值、错误码、同步/异步和超时 |
| 生命周期 | 初始化、连接、使能、停用、故障恢复、断开与状态转换 |
| 实测反馈 | 实测/目标/缓存/占位值的区别，来源时间、频率和有效性 |
| 本体配置 | 设备与关节名称、顺序、方向、零位、限位；按能力补模型和标定 |
| 完成与停止 | 接收、执行、到位、停止、取消和通信中断后的行为 |
| 示例与版本 | 与实际硬件和固件匹配的最小可运行示例、依赖和许可 |

平台输入还包括 RobotAdapter Contract、Package/Manifest Schema、Capability Catalog、Reference Package 和 Conformance Tests。URDF、源码和 ROS 均按能力需要提供，不是所有本体的统一门槛。

### 25.2 生成与验证流程

```text
Vendor Assets → Inventory / Evidence → Capability Checklist
    → Backend Selection → Package-owned Adapter / Manifest / Tests
    → Static Validation → Offline / Simulator Test
    → Human Review → Separately authorized Hardware Test
    → 可追溯的验证记录与包发布
```

Mapping YAML 是证据或包内配置，不能作为 SDK 执行厂商控制语义的入口。生成的 Adapter 必须包含实际编解码与验证逻辑，或明确标为不可运行骨架。

当前生成工具只产出安全骨架：connect/enable/state/command 等未实现时抛出明确错误，`supports_action()` 为 false，`health()` 不报告 ready。骨架生成成功、静态契约通过或 dry-run 通过不等于具备硬件运行能力。

### 25.3 Agent 的边界

Agent 将厂商已有能力映射到固定契约，不自由发明状态码、单位、使能/下电语义或停止效果。资料不足时记录 unknown 与证据缺口；只在已有证据足够的模板范围生成可执行映射。

能力验证分别记录静态检查、离线、仿真、只读硬件和授权运动结果。测试失败、环境不满足和未执行必须分别报告；不自动将历史版本实机结果继承给新包。

---

## 26. Package 模式

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

## 27. 平台模式

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

## 28. 平台模式下的硬件接入

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

## 29. 平台模式下的模型接入

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

## 30. Policy × Embodiment Performance Matrix

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

## 31. 测试体系

### 31.1 Package Schema 与入口测试

覆盖 package.yaml、Manifest、Instance、Backend/平台选择、依赖、lock、版本和摘要。包入口必须位于包根内；相同模块名的不同包不能互相覆盖；拒绝旧 SDK 入口与路径越界。

### 31.2 Adapter Conformance Test

按声明能力测试 configure、connect/disconnect、enable/disable、state、joint/EE/gripper、health、错误、超时和频率。配置阶段监测进程、Socket、ROS、导入路径及环境副作用；不支持的方法必须明确失败。

### 31.3 Asset Test

按实际声明校验模型、mesh 引用、Frame、Joint、原始/派生资源及 digest；没有声明的模型不作为所有包的统一必需条件。厂商原始资产保留来源与许可信息。

### 31.4 Runtime 与 Host 集成测试

使用 Policy + Mock Robot + Runtime、假通信服务和受控子进程，不接硬件。覆盖状态过期/乱序/重复、非有限值、完整关节目标、幂等与失败回滚、Host 崩溃、日志污染、JSON 数组转换、超时、派发与未知结果、外部进程所有权。

### 31.5 Real Hardware Test

逐步执行只读、低速单命令、伺服和 Policy loop；每步单独授权并确认条件。软件接收成功、控制器模式和实测数据有效性分别验证。当前 WY 现场记录不能扩展为所有后端或所有能力的认证。

### 31.6 最低发布门槛

- 初始化不启动硬件；重复配置和连接不重复创建资源。
- connect 不隐式 enable；失败连接清理部分资源并可恢复。
- enable/disable 失败不记录成功；未知停用/停止不伪报。
- 新鲜度、命名、单位、限位和授权约束在下发前生效。
- close 不调用停用；只清理拥有的资源，不报告物理停止。
- 骨架不能通过运行能力预检；所有测试结果按包版本、环境和验证层级记录。

---

## 32. CLI

### 32.1 当前入口与目标语义

已存在的命令族包括 `ce install/validate/up/run/down/status`、`ce package` 和 `ce onboard`；具体子参数应以实现和 `--help` 为准。v0.4 的启动、关闭目标语义见第 13 节；其中 `--enable`、`--disconnect-only` 需实施后才能作为可运行命令展示。

```bash
ce package build --package-root ./hardware-package --output ./robot.cepack --json
ce package install --artifact ./robot.cepack --json
ce package activate vendor/model@1.0.0 --instance ./robot.instance.yaml --json
```

### 32.2 保留的整体 CLI 规划

保留 v0.3 的 Project 初始化、资源搜索/添加、机器人发现、日志、Benchmark、硬件包导入/校验/测试/发布等交互方向，包括 `ce init`、`ce add`、`ce robot`、`ce logs`、`ce benchmark`、`ce hardware` 等。

这些是产品规划，不保证当前命令已经存在，也不要求维护两套重复包管理命令。后续统一到 `ce package` / `ce onboard` 等正式命令族时应明确替代关系。

---

## 33. Python 包结构

采用标准 src layout：发行包由 `pyproject.toml` 管理，Python 导入包为 `src/cross_embodiment/`。

```text
src/cross_embodiment/
├── sdk/
│   ├── robot.py              # 应用句柄与统一动作入口
│   └── lifecycle.py          # 配置/连接/使能/关闭调度
├── protocol/
│   ├── types.py              # Action、Command、State、Result
│   └── policy.py
├── adapter/
│   ├── protocol.py           # RobotAdapter
│   ├── context.py            # 经验证包资源访问
│   ├── health.py
│   └── mock.py
├── transport/
│   ├── protocol.py           # TransportRequest/Event/Result
│   └── ros2.py               # 通用 ROS 2 机制，按需延迟导入
├── driver_host/
│   ├── environment.py
│   ├── process.py
│   ├── transport.py          # 当前 Transport Host 客户端
│   └── worker.py             # 当前 Transport worker
├── package/
│   ├── manifest.py
│   ├── assets.py
│   ├── artifact.py
│   ├── lifecycle.py
│   ├── registry.py
│   ├── resolver.py
│   ├── lock.py
│   ├── project.py
│   └── loader.py             # 只加载包内入口
├── hardware/
│   ├── manifest.py
│   └── instance.py
├── runtime/
│   ├── installed.py
│   ├── runtime.py
│   ├── mapping.py            # 保留跨本体/Policy 动作转换
│   └── safety.py
├── kinematics/
├── transforms/
├── onboarding/
│   ├── extractors/
│   ├── templates/
│   ├── platform/
│   └── ...                   # inventory/evidence/generator/conformance
├── cli/
└── errors.py
```

这是 v0.4 基础结构；后续 Device facade、Scheduler、Compatibility、传感器和完整 Adapter Host 按能力新增，不能将目录示意视为已有实现。

删除 `adapter/base.py`、旧 `backend/`、旧 `driver/`、`mapping/engine.py` 及其转发入口；不维护同义别名。厂商实现独立放在各 Hardware Package。

---

## 34. 生命周期

### 34.1 资源阶段与设备状态

```text
UNINSTALLED → INSTALLED                 # 包管理
                  ↓ 构造 Robot
              CONFIGURED               # 仅配置
                  ↓ 显式 connect
              CONNECTED                # 有效通信，可尚未使能
                  ↓ 显式 enable + 实测确认
              ENABLED
                  ↓ 目标能力全部前置条件成立
              READY → RUNNING          # Runtime 任务阶段
                        ├── PAUSED
                        └── FAULT
```

真实硬件状态可被外部操作改变，不是只能单向前进的本地枚举。CONNECTED、ENABLED 和 READY 必须分别判断；本地配置/连接标志只记录资源阶段。

### 34.2 操作语义

| 操作 | 前置条件 | 行为与成功条件 |
|---|---|---|
| 内部 configure | 构造期间 | 校验参数、资源和静态依赖，准备后端环境描述；无硬件副作用 |
| connect | 已配置 | 建立通信，按包契约获得有效连接状态；不要求先上电 |
| enable | 已连接且有对应能力 | 厂商请求或已验证的幂等确认，再以有效状态确认 |
| disable | 已连接且有对应能力 | 显式停用请求及对应实测确认；未知则不支持 |
| stop 动作 | 能力已声明、语义已验证 | 请求并确认运动停止；不由 disable/disconnect 模拟 |
| close | 任意资源阶段 | 清理该句柄拥有的连接、线程、Host、Driver；不隐式下电 |

停止动作的统一形式为 `Action(ActionSpec(type="stop", target=device_id, dimension=0), {})`，由 Runtime Mapper 生成 `Command(device_id, "stop", {})`。只接受已声明并实现的目标设备能力；停止请求不受普通运动授权、未使能、过期观测或已知故障门禁自动阻断，但仍须有有效连接与经过验证的停止语义。不得借停止动作携带普通运动负载。其 succeeded 表示按该能力契约确认停止，不能只表示请求发出。该分支当前待 implementation 实现。

Lifecycle 不再提供含混的 start/stop 复合入口。停止运动按 Catalog 中的 `stop` 能力通过统一动作链路执行；无该能力时明确拒绝，不把发零速度或取消请求自动认定为已停止。

### 34.3 重复调用、并发与失败

configure、connect、close 在各自资源意义上幂等；enable/disable 每次重新核查硬件。生命周期与命令需要明确串行化或冲突拒绝，不能并发执行互相冲突的硬件操作。

connect 失败由 Adapter 回滚已创建的部分资源，因为 Lifecycle 尚未记录连接成功。关闭时即使一个清理阶段失败，也应尝试后续 owned 资源清理，保留原异常和清理失败信息。外部 Driver 从不按本实例 owned 进程终止。

### 34.4 状态等待

依据观察到的状态转换和时间关系等待，不使用固定 sleep 代表成功。请求前等待可操作状态、请求响应和请求后确认分别超时并分别报告。非幂等操作不自动重试；超时和断连不证明物理状态已改变或恢复。

---

## 35. 错误体系

保留 PackageError、AssetError、DependencyError、BackendUnavailable、ConfigurationError、CompatibilityError、ConnectionError、DeviceError、CommandRejected、CommandTimeout、ObservationStale、PolicyError、DriverCrash、SafetyViolation、EmergencyStop、LifecycleError 等错误类别规划。

当前 `errors.py` 已实现其中一部分，新增类别按实际契约补齐，不把目录中不存在的类列作可直接导入 API。通过统一结构逐步提供 code、timestamp、package、backend、device、recoverable、suggested_action 和 native error。

生命周期错误需区分：前置状态不满足、请求未发送、厂商拒绝、通信失败、请求后状态未确认。动作结果需区分 rejected、not_dispatched、timed_out、outcome_unknown、failed 和经过证据支持的 succeeded 等状态。

错误信息不能被清理阶段异常吞掉，也不能因最终 close 成功而转为成功退出。日志不记录认证密钥等敏感连接内容。

---

## 36. 安全与控制约束

### 36.1 通用约束

SDK / Runtime 负责控制授权、有限值、目标完整性、设备能力、单位/坐标契约、适用的限位、状态新鲜度和已知故障/急停检查。缺少关键依据时拒绝动作；不允许后端迁移绕过这些检查。

workspace、速度/加速度约束、watchdog、通信中断处理、低速验证和 dry-run 按能力和实际实现补齐。默认拒绝越界，不隐式 clipping 改写请求；如提供 clipping，必须显式配置、记录原始/实际目标并通过验证。

### 36.2 厂商状态与效果确认

Adapter 负责将真实厂商状态映射为统一状态。初始化零值、目标回显、过期缓存和控制器模式都不能单独作为位置反馈有效的证明。请求接收、动作执行、实测到位与停止须分别有证据。

不把所有全零姿态在 Core 中统一判错：合法零位与启动占位值由厂商有效性信息区别；无法区别时应报告未确认，应用可以采取更保守策略。

### 36.3 授权与清理

构造、静态校验、build/install/activate 不连接硬件。只读、使能、运动、停用、停止和急停能力分别说明实际行为。`allow_motion` 授权不能由应用键盘的本地 armed 状态伪装成硬件已使能。

close、终止 Driver、UDP 零指令和取消 Action 不能自动等价于物理停止或急停。停止和下电不支持时必须显式报告。硬件验证独立授权，不能由离线测试或 Onboarding 自动触发。

---

## 37. 推荐的第一批 Reference Hardware Packages

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

## 38. 开发路线图

### 38.1 保留的整体演进路线

v0.3 中的阶段路线继续作为产品演进方向，不作为已完成版本承诺：

| 历史阶段 | 保留内容 |
|---|---|
| v0.1 基础闭环 | Hardware Package、Manifest、Instance、Local Registry、Resolver、Lock、Python Adapter、统一 SDK、EE Policy、Runtime、Mock、Reference Package 和 Project CLI |
| v0.2 多 Backend / Joint | ROS2、Native Host、Joint Policy/Mapping、多相机、Replay、Simulation、Remote |
| v0.3 平台方向 | Cloud Registry、Robot/Policy Registry、Onboarding Agent、Certification、兼容性数据库、远程部署与监控 |
| v1.0 生态方向 | Bimanual、Mobile Manipulation、Whole-body、Fleet、Skill、Dataset、Benchmark、Performance Matrix、自动适配与 Marketplace |

EE 基础闭环的目标仍是同一策略在不同 Hardware Package 上复用，不能由单个 WY 关节 Demo 代替这一目标的验证。

### 38.2 v0.4 基础交付

1. 固化包内 Adapter、通用 Transport/Host 和 Runtime 策略映射的职责边界。
2. 初始化配置、显式连接和使能、资源关闭与运动停止分离。
3. 完成包入口和代码资产校验，移除旧导入、执行器与兼容层。
4. 统一已安装实例与 Project 启停路径；修复旧生命周期调用和测试替身。
5. 骨架与可运行 Adapter 明确分级；逐步生成有证据支持的具体映射。
6. SDK、硬件包和应用各自完成离线检查，现场能力独立验收。

### 38.3 后续里程碑

完整 Adapter IPC、其他通用动作空间与状态类型、非 ROS Reference Package、实时 Runtime 和平台服务按独立需求推进。M20 接入当前属于调研，不作为此次文档升级的实施承诺。

---

## 39. 关键架构决策

1. Hardware Package 是安装与交付单位；Adapter 是其中的具体控制实现。
2. 保留原始资产格式，统一用途、语义、来源和版本，不强制统一为 URDF 或 ROS。
3. ROS、Python SDK、Native 和网络/总线均可成为 Backend；Core 不依赖厂商运行时。
4. 包内 Adapter 实现厂商映射，组合通用 Transport、环境与进程工具，不使用 Core 厂商 YAML 执行引擎。
5. Robot / Lifecycle 组合；构造时内部 configure，connect 和 enable 显式，close 只释放资源。
6. 安装、连接、使能、能力就绪、运动停止、停用和资源关闭分别定义与验证。
7. Driver Host 的隔离层级必须明示；Transport IPC 不冒充完整 Adapter IPC。
8. Model、Instance、Project 分离；Resolver、Lock 和精确摘要支撑实验复现。
9. Coding Agent 面向固定契约和证据生成包；骨架、离线通过和实机认证分别记录。
10. EE-first 保留，Runtime 跨本体策略转换保留；缺少通用能力时扩展契约，不为某厂商添加 Core 特判。
11. 旧入口通过迁移发布新包替代，不维护转发兼容文件。

---

## 40. 最终闭环

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

## 41. 最终产品形态

### 41.1 Package Mode

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

### 41.2 Platform Mode

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

## 42. 用户项目目录结构

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

### 42.1 Project 与 Hardware Package 的边界

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

## 43. SDK 源码仓库结构

模块分工以第 33 节为准，避免在本文维护两套冲突的源码目录。仓库顶层采用：

```text
cross-embody-sdk/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/cross_embodiment/
├── catalogs/                  # 平台能力与后端支持描述
├── schemas/                   # Package / Manifest / Instance / Policy / Project 等
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── onboarding/
│   ├── conformance/
│   └── mock/
├── examples/
└── docs/
    ├── architecture/
    └── implementation/
```

平台目录中随发行包携带的 Catalog / Schema 必须与源目录保持同步并有检查；不能以移动文件造成包安装后缺少平台资源。

### 43.1 核心 SDK 与厂商包分离

Core 维护标准、Schema、Runtime、Package System、Adapter Contract、Transport、Driver Host、CLI 和通用 Conformance Test。厂商包维护 SDK/驱动/模型资产、具体 Adapter、厂商配置与硬件测试。

独立包可在同一集合仓库维护，也可拆成 `ce-hardware-ufactory-xarm`、`ce-hardware-agilex-piper`、`ce-hardware-jaka`、`ce-hardware-dobot` 等独立发布仓库；不因引用它们而将厂商目录复制到 Core。

### 43.2 三类目录边界

| 目录 | 内容 |
|---|---|
| SDK Repository | 平台标准、运行基础设施和通用工具 |
| Hardware Package Repository | 型号资产、具体 Adapter、配置、证据和验证 |
| User Project | 本次应用如何组合 Robot、Policy、Task 与实例标定 |

同一个硬件包应能被多个项目复用，应用不依赖厂商源目录的偶然位置。

---

## 44. v0.4 交付边界、迁移与规范优先级

### 44.1 基础交付与当前差距

| 领域 | v0.4 基础要求 | 当前检查结论与实施入口 |
|---|---|---|
| Robot / Lifecycle | 构造内部配置、显式连接/使能、close 只释放资源 | 基础已存在；旧 stop 复合入口及 Project 调用需迁移，见 implementation P1/P6 |
| 包内 Adapter | 具体映射由包交付，只接受包内入口 | 基础已存在；契约和测试替身仍需一致，见 P2 |
| Transport | 通用 ROS 2 订阅/Action/Service，与厂商语义分开 | 基础已存在；JSON/数组和故障路径持续验证，见 P3 |
| Host | 明确隔离层级、所有权、失败清理 | Transport IPC 已有；完整 Adapter Host 后续独立实施，见 P4/P9 |
| Package / Instance | 不可变包、资产摘要、激活实例和后端验证 | 基础已有；清理旧 Mapping 专用元数据路径，见 P2 |
| Onboarding | 骨架不能宣称可运行，具体映射需要证据 | 当前为骨架；可执行生成与能力对齐待完成，见 P5 |
| 控制与验证 | 授权、实测有效性、未知结果和停止/停用能力不伪报 | 分层验证与发布证据待整合，见 P7/P8 |
| Policy / Platform | 保留既有产品体系，按能力演进 | 非本次全部实现承诺，后续路线见第 38 节 |

这里只记录源码检查边界，不复用草稿中的历史通过数，也不宣称本文编写过程中运行过机器人。

### 44.2 迁移矩阵

| v0.3 / 旧实现 | v0.4 正式归属或处理 |
|---|---|
| SDK 内置 MappedRos2Adapter、InterfaceMappingEngine | 删除，厂商映射在包内 `adapters/...` |
| `driver/ros2_transport.py`、`backend/protocol.py` | 使用 `transport/ros2.py`、`transport/protocol.py`，不保留转发 |
| `driver/backend.py` | 使用 `package/loader.py`，校验包内入口 |
| `driver/process.py`、`driver/health.py` | 使用 `driver_host/process.py`、`adapter/health.py` |
| `adapter/base.py` | 使用 `adapter/protocol.py`，不提供 BaseAdapter 兼容层 |
| `Robot` 内嵌 Lifecycle | 拆到 `sdk/lifecycle.py`，保留组合关系 |
| `connect(config)`、公开 configure、start/stop 复合生命周期 | 构造保存配置并内部 configure；显式 connect/enable/disable/close |
| `runtime/mapping.py` | 保留，负责策略/跨本体转换，不解释厂商报文 |
| 旧硬件包入口或运行资产 | 发布新包版本并重新安装、激活；不改已安装旧版本 |

### 44.3 v0.3 章节合并索引

| 范围 | 处理 |
|---|---|
| 1—9 产品与架构 | 保留定位/原则/资产概念；替换职责、包结构、契约与 Host 分层 |
| 10—17 包、实例与能力模型 | 保留 Registry/Model/Project/Lock/Catalog；替换启动关闭语义和 Manifest 控制布局 |
| 18—25 SDK 与策略接入 | 替换旧 SDK 示例和状态契约；保留 Policy/EE/Joint/Compatibility，重写厂商映射和生成边界 |
| 26—30 产品与平台模式 | 保留 Package/Platform/Onboarding/Policy 接入和性能矩阵 |
| 31—36 工程约束 | 按新架构更新测试、CLI、目录、生命周期、错误与安全 |
| 37—43 Reference 与整体演进 | 保留 Reference 目的、整体闭环和应用项目边界；更新路线标注、决策和 Core 目录 |

### 44.4 后续设计边界

完整 Adapter Host、Base/Whole-body 通用协议、具体非 ROS 硬件包和新的物理速度映射须分别形成验证过的能力设计。本文件不因近期 M20 可行性讨论而冻结其归一化输入、状态码或停止语义。

正式设计与当前代码不一致时，以本设计描述目标，以 implementation 记录迁移工作；不能用“代码已这样实现”覆盖设计契约。v0.4 草稿作为讨论与历史依据保留，后续实现不再以草稿中的过时测试计数或旧包版本作为验收结论。
