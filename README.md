# Cross-Embodiment SDK

Cross-Embodiment SDK 是一个私有的统一机器人接入与运行平台，由三部分组成：

1. **Unified Robot Runtime**：稳定的 `Robot` API、动作/状态类型、安全检查、Mapping Engine 和 Backend 协议。
2. **Hardware Onboarding Agent**：扫描厂商资产，建立证据，匹配 Capability，选择 Backend，并生成 Hardware Package。
3. **Hardware Package Lifecycle**：构建、安装、检查、激活、使用、停用和卸载不可变 `.cepack`。

内部 v0.1 已用 Weiyi Dual O6 右臂验证完整 ROS2 路径：独立 wheel 安装、Clean-Room Onboarding、`.cepack` 安装、Package Store 加载、七关节状态读取，以及经操作员授权的 Probe + Return。当前真机验证范围仅为 `right_arm` 的 `joint_position_state` 和 `joint_position`。

## 0. 选择一种独立流程

下面三种流程目的不同。每次只执行其中一种，不要共用虚拟环境或 Package Store。

### 流程 A：部署已经验收的 Weiyi Package

适用对象：只想安装并使用机器人，不修改 SDK，也不重新运行 Onboarding。

需要准备：

- `package_dpy` Distribution Kit；
- 外部 Weiyi `robot_launch` Runtime；
- Ubuntu 22.04、ROS2 Humble、Python 3.10 和已经配置的 CAN；
- 真实机器人和现场操作员。

完整命令：

```bash
git clone --branch package_dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git \
  package-distribution
cd package-distribution

sha256sum -c SHA256SUMS

read -er -p "Weiyi robot_launch 目录: " VENDOR_ROOT_INPUT
VENDOR_ROOT="$(realpath "$VENDOR_ROOT_INPUT")"
test -f "$VENDOR_ROOT/setup.sh"
test -f "$VENDOR_ROOT/install/setup.bash"
test -d "$VENDOR_ROOT/third_party/wy_arm_sdk/install"

./quickstart.sh all \
  --runtime-root "$HOME/ce-runtime/weiyi-right-arm" \
  --vendor-root "$VENDOR_ROOT" \
  --instance-id lab/weiyi-right-arm-01 \
  --operator "$USER"
```

该流程使用 Kit 内固定 wheel 和 `.cepack`，不需要 SDK 源码或 DeepSeek。安装阶段不
连接机器人；在线阶段分别等待 `ENABLE RIGHT ARM` 和 `EXECUTE L3`。最终成功标志是
`classification: passed`、`motion_sent: true`，且 Probe 与 Return 均为
`status: succeeded`、`arrival_confirmed: true`。

### 流程 B：安装 SDK 源码开发环境

适用对象：阅读、修改、调试 SDK，或运行 SDK 自身开发检查。该流程只安装 SDK，不安装
`.cepack`，不启动 Driver，也不连接机器人。

```bash
git clone --branch dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git \
  cross-embody-sdk
cd cross-embody-sdk

python3.10 -m venv --system-site-packages .venv && \
.venv/bin/python -m pip install --upgrade \
  'pip>=23' 'setuptools>=68' wheel && \
.venv/bin/python -m pip install --no-build-isolation -e .

.venv/bin/python - <<'PY'
from pathlib import Path
import cross_embodiment
import yaml

source_root = (Path.cwd() / "src").resolve()
sdk_path = Path(cross_embodiment.__file__).resolve()
assert sdk_path.is_relative_to(source_root), (sdk_path, source_root)
assert tuple(map(int, yaml.__version__.split(".")[:2])) >= (6, 0)
print("Core SDK editable install: OK")
print("sdk_path:", sdk_path)
print("yaml_version:", yaml.__version__)
PY

source /opt/ros/humble/setup.bash
.venv/bin/python -c '
import cross_embodiment, yaml, numpy, rclpy, rosidl_runtime_py
print("SDK + ROS2 Python environment: OK")
'
```

最终成功标志是 `sdk_path` 位于当前仓库的 `src/cross_embodiment`，并打印
`SDK + ROS2 Python environment: OK`。如果开发者还要手动验证现成 `.cepack`，再执行
“在源码环境中手动验证已有 Package”一节；普通部署用户应使用流程 A。

### 流程 C：从新厂商原始资产开始 Onboarding

适用对象：首次接入新厂商。该流程安装包含 Agent 客户端的 SDK，读取厂商原始资产并
创建新的运行目录；它不使用历史 Mapping，也不会在扫描阶段连接机器人。

```bash
git clone --branch dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git \
  cross-embody-sdk-onboarding
cd cross-embody-sdk-onboarding

python3.10 -m venv --system-site-packages .venv && \
.venv/bin/python -m pip install --upgrade \
  'pip>=23' 'setuptools>=68' wheel && \
.venv/bin/python -m pip install --no-build-isolation -e '.[onboarding-agent]'

read -er -p "厂商原始资产目录: " VENDOR_ASSET_ROOT_INPUT
VENDOR_ASSET_ROOT="$(realpath "$VENDOR_ASSET_ROOT_INPUT")"
RUN_ROOT="$(realpath -m ../onboarding-run)"
test -d "$VENDOR_ASSET_ROOT"

.venv/bin/ce onboard inspect \
  --vendor-root "$VENDOR_ASSET_ROOT" \
  --run-root "$RUN_ROOT" \
  --json
```

`inspect` 成功后，Inventory、Evidence、隔离清单和平台锁定信息位于 `RUN_ROOT`。
DeepSeek 凭据、Scope、Candidate、Runtime Policy、Conformance 和 L3 步骤继续严格按照
[Hardware Onboarding 工作流](docs/onboarding/workflow.md)执行。新厂商接入不要运行
流程 A 的 Weiyi `quickstart.sh`。

路径规则：流程 A 的 `VENDOR_ROOT` 是可运行 Driver；流程 C 的
`VENDOR_ASSET_ROOT` 是供 Scanner 读取的原始资产。两者可能相同，也可能不同，SDK
不会假定固定绝对路径。

## 1. 平台边界

```text
应用 / Agent
    │
    ▼
Unified Robot API
Robot.get_joint_state() / Robot.move_joints()
    │
    ▼
Hardware Package
设备、关节、Capability、Mapping、Runtime Policy、Backend 声明
    │
    ▼
通用 Backend
当前已验证：ros2_mapped
    │
    ▼
厂商 Runtime / Driver
    │
    ▼
真实机器人
```

SDK wheel 不包含 Weiyi Mapping、Driver、Demo、凭据或历史运行缓存。厂商端点、消息字段、关节顺序和控制枚举保存在 Hardware Package 中；厂商 Driver 作为外部 Runtime 单独安装和启动。

源码主要目录：

```text
src/cross_embodiment/
├── sdk/          # Robot API 与生命周期
├── protocol/     # Action、Command、JointState、CommandResult
├── mapping/      # 映射验证、命令编译、状态/结果解码
├── backend/      # 协议无关 BackendTransport 契约
├── adapter/      # RobotAdapter 静态契约
├── driver/       # ros2_mapped、ROS2 Transport、Backend 加载
├── hardware/     # Embodiment Manifest、Robot Instance
├── package/      # .cepack、Store、安装和激活
├── onboarding/   # Scanner、Evidence、Matcher、Agent、Generator、Conformance
└── cli/          # ce CLI
```

## 2. 两种使用模式

### 模式 A：使用已有 Hardware Package

适用于普通部署用户。需要 SDK wheel、已验收的 `.cepack`，以及对应厂商 Runtime、机器人连接和系统依赖。该流程不需要 DeepSeek、SDK 源码、厂商 Mapping 源码或历史 Onboarding 记录。

```text
SDK wheel + .cepack + 厂商 Runtime
              ↓
 install → activate → use
              ↓
 read-only preflight
              ↓
 操作员授权后执行动作
```

### 模式 B：从厂商原始资产接入

适用于首次接入新机器人。用户提供 ROS2/Python/C++ 接口、头文件、动态库、示例、模型和依赖资料，Onboarding Agent 执行：

```text
Inventory → Evidence → Capability Match → Backend Fit
          → Candidate Package → Conformance
          → Operator Runtime Policy → Runtime Package → .cepack
```

Weiyi 已验证“复用现有 ROS2 Backend 并自动生成 Mapping”。Python SDK、C/C++ Library 和全新 Backend 插件的自动代码生成、编译及真机运行尚未验证；Backend 不支持时，系统应输出明确缺口，不能伪造支持。

## 3. 安装 SDK

### 从 wheel 安装

```bash
python3.10 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install ./cross_embodiment-0.1.0-py3-none-any.whl

.venv/bin/ce --help
.venv/bin/python -c 'import cross_embodiment; print(cross_embodiment.__file__)'
```

核心依赖为 Python 3.10+ 和 PyYAML 6.0+。ROS2 Backend 还需要目标系统提供兼容的 ROS2 Python 环境，例如 Humble 的 `rclpy`、`rosidl_runtime_py`、消息类型和类型支持库。

### 从源码安装开发环境

源码安装适合查看代码、运行 Onboarding 或验证当前分支。它只安装 SDK，不会自动安装 Hardware Package，也不会启动厂商 Driver。

```bash
git clone --branch dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git
cd cross-embody-sdk

# 需要 ROS2 Backend 时使用 --system-site-packages，使 venv 能访问
# Ubuntu/ROS2 通过 apt 安装的 rclpy、rosidl_runtime_py 和 NumPy。
python3.10 -m venv --system-site-packages .venv && \
.venv/bin/python -m pip install --upgrade \
  'pip>=23' 'setuptools>=68' wheel && \
.venv/bin/python -m pip install --no-build-isolation -e .
```

`--system-site-packages` 让 ROS2 Humble 的 apt 安装版 `rclpy`、
`rosidl_runtime_py` 和 NumPy 可以被开发环境使用；pip 安装的 PyYAML 6.x 仍位于
虚拟环境中。仅做静态开发时也可以使用普通 venv。

源码项目的 `pyproject.toml` 要求 `setuptools>=68`。Ubuntu 22.04 自带的
`setuptools 59.6` 不支持本项目所需的 PEP 660 editable install，因此必须先升级
构建工具，再使用 `--no-build-isolation` 复用已确认版本。上面的 `&&` 确保任一步
失败时不会继续执行，避免旧 editable 安装残留造成导入成功的假象。

若部署网络不能访问 Python 包索引，应从内部 wheelhouse 安装匹配的 pip、setuptools
和 wheel，或改用 Distribution Kit 中已经构建好的 SDK wheel；不能把 editable
安装失败后的旧环境当成新安装结果。

如果同一个 `.venv` 中已经发生过 editable 安装失败，先清空并重建，避免残留的
`__editable__.*.pth` 影响验证：

```bash
python3.10 -m venv --clear --system-site-packages .venv
```

验证 Core SDK 确实来自当前源码目录：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import cross_embodiment
import yaml

source_root = (Path.cwd() / "src").resolve()
sdk_path = Path(cross_embodiment.__file__).resolve()
assert sdk_path.is_relative_to(source_root), (sdk_path, source_root)
assert tuple(map(int, yaml.__version__.split(".")[:2])) >= (6, 0)
print("Core SDK editable install: OK")
print("sdk_path:", sdk_path)
print("yaml_version:", yaml.__version__)
PY

.venv/bin/ce --help
```

Core SDK 验证通过后，再检查实际要使用的 Backend。已验证的 ROS2 Humble 环境：

```bash
source /opt/ros/humble/setup.bash

.venv/bin/python -c '
import cross_embodiment
import yaml
import numpy
import rclpy
import rosidl_runtime_py
print("SDK + ROS2 Python environment: OK")
'
```

如果 `rclpy`、`rosidl_runtime_py` 或 `numpy` 导入失败，先确认 ROS2 Humble 及其
Ubuntu Python 包已安装，并确认创建 venv 时使用了 `--system-site-packages`。不要用
pip 安装来源不明的 ROS2 二进制包来绕过系统 ROS 环境。

`pip check` 会同时检查通过 `--system-site-packages` 暴露的全部 Ubuntu Python
包，可能报告与本 SDK 无关的系统包问题。源码安装是否成功应以上述源码路径、
PyYAML 版本和所选 Backend 的针对性导入检查为准；若 `pip check` 报告
`cross-embodiment` 自身依赖错误，则必须处理。

需要运行 Hardware Onboarding Agent 时安装可选依赖：

```bash
.venv/bin/python -m pip install --no-build-isolation -e '.[onboarding-agent]'
```

### 在源码环境中手动验证已有 Package（可选）

本节只供 SDK 开发者验证“当前源码 + 已有 `.cepack`”。普通部署使用流程 A；新厂商
接入使用流程 C。

首先取得内部 Distribution Kit，并显式指定外部厂商 Runtime。下面只采用目录约定方便
说明；实际目录可以不同，后续命令只使用已经解析的绝对路径变量：

```text
workspace/
├── cross-embody-sdk/       # dpy 源码和 .venv
├── package-distribution/   # package_dpy，包含 .cepack
└── robot_launch/           # 外部 Weiyi Runtime，不进入 SDK 仓库
```

在 SDK 源码目录执行以下纯文件操作：

```bash
SDK_ROOT="$PWD"
KIT_ROOT="$(realpath ../package-distribution)"

read -er -p "Weiyi robot_launch 目录: " VENDOR_ROOT_INPUT
VENDOR_ROOT="$(realpath "$VENDOR_ROOT_INPUT")"

RUNTIME_ROOT="$(realpath -m ../weiyi-source-runtime)"
STORE="$RUNTIME_ROOT/store"
INSTANCE_ID=lab/weiyi-right-arm-source
CE="$SDK_ROOT/.venv/bin/ce"

test -x "$CE"
test -f "$KIT_ROOT/SHA256SUMS"
test -f "$VENDOR_ROOT/setup.sh"
test -f "$VENDOR_ROOT/install/setup.bash"
test -d "$VENDOR_ROOT/third_party/wy_arm_sdk/install"

(cd "$KIT_ROOT" && sha256sum -c SHA256SUMS)
mkdir -p "$RUNTIME_ROOT"

"$CE" package install \
  --artifact "$KIT_ROOT/packages/weiyi-right-arm-runtime.cepack" \
  --store "$STORE" \
  --json

sed "s|__INSTANCE_ID__|$INSTANCE_ID|g" \
  "$KIT_ROOT/instances/right-arm.instance.template.yaml" \
  > "$RUNTIME_ROOT/right-arm.instance.yaml"

"$CE" package activate \
  weiyi/dual_o6_cleanroom_20261016@0.1.0 \
  --instance "$RUNTIME_ROOT/right-arm.instance.yaml" \
  --store "$STORE" \
  --json

"$CE" package use \
  --instance "$INSTANCE_ID" \
  --store "$STORE" \
  --json
```

到这里仅完成 Package 安装和实例绑定，没有连接机器人。接下来必须由部署环境提供
Weiyi `robot_launch`、ROS2 Humble、CAN 和真实机器人；启动 Driver、使能右臂后，
再按照“已安装 Package 的运行命令”执行 `preflight` 和经授权的 `accept-l3`。

`VENDOR_ROOT` 是外部 Runtime 路径，不会写入 `.cepack` 或 SDK Store。若重新打开终端，
需要重新设置 `SDK_ROOT`、`KIT_ROOT`、`VENDOR_ROOT`、`RUNTIME_ROOT`、`STORE`、
`INSTANCE_ID` 和 `CE`，或将它们写入仅供本机使用且不提交 Git 的环境文件。

若目标是最少步骤完成真机验收，返回本 README 的“流程 A”，使用
`quickstart.sh all`。它会自动编排 Driver、使能等待、只读预检和 L3 确认。

## 4. Hardware Package 命令

Package 生命周期命令只操作文件、摘要、Store 记录和 Robot Instance 绑定。它们不会启动 Driver、连接机器人、使能硬件或发送动作。

```bash
CE=.venv/bin/ce
STORE="$HOME/.cross_embodiment"

"$CE" package build \
  --package-root ./hardware-package-runtime \
  --output ./robot.cepack \
  --json

"$CE" package install --artifact ./robot.cepack --store "$STORE" --json
"$CE" package list --store "$STORE" --json
"$CE" package inspect vendor/model@1.0.0 --store "$STORE" --json

"$CE" package activate vendor/model@1.0.0 \
  --instance ./robot.instance.yaml \
  --store "$STORE" \
  --json

"$CE" package use \
  --instance lab/robot-01 \
  --store "$STORE" \
  --json

"$CE" package deactivate --instance lab/robot-01 --store "$STORE" --json
"$CE" package uninstall vendor/model@1.0.0 --store "$STORE" --json
```

Robot Instance 最小格式：

```yaml
schema_version: robot-instance/v0.1
instance:
  id: lab/robot-01
robot:
  package: vendor/model
  version: 1.0.0
backend:
  preferred: ros2_mapped
connection: {}
```

`package use` 返回的 `package.root` 必须位于指定 Store；运行时 Mapping 也必须从该 Package 目录解析。安装版本不会回退到源码工作树、Onboarding 输出目录或旧 Registry。

## 5. Unified Robot API

当前冻结的关节 API：

```python
state = robot.get_joint_state("right_arm")

result = robot.move_joints(
    "right_arm",
    {
        "arm.right.joint.0": q0,
        "arm.right.joint.1": q1,
        "arm.right.joint.2": q2,
        "arm.right.joint.3": q3,
        "arm.right.joint.4": q4,
        "arm.right.joint.5": q5,
        "arm.right.joint.6": q6,
    },
)
```

`get_joint_state(device_id)` 返回 `JointState`：

| 字段 | 含义 |
| --- | --- |
| `device_id` | 规范设备 ID |
| `positions` | 规范关节名到实测弧度值的映射 |
| `source_timestamp` | 厂商状态时间戳，若接口没有提供则为 `None` |
| `received_at` | SDK 收到状态的时间 |
| `status` | `ready`、`not_ready`、`fault`、`stale` 等状态 |
| `details` | Backend 模式、厂商故障码等可审计信息 |

`move_joints(device_id, positions)` 接收完整的绝对关节目标。目标键必须与 Package 声明的规范关节集合完全一致。返回 `CommandResult`，关键字段包括：

| 字段 | 含义 |
| --- | --- |
| `accepted` | Backend 是否接受本次请求 |
| `status` | `succeeded`、`rejected` 等终态 |
| `dispatched` | 是否尝试发送到 Backend |
| `backend_code` | 厂商结果码 |
| `arrival_confirmed` | 是否通过实测状态确认到位 |
| `max_joint_error_rad` | 最大实测关节误差 |
| `final_joint_state` | 完成后的实测状态 |

业务逻辑应只依赖 `Robot` 与标准类型：

```python
from cross_embodiment import Robot


def execute_known_target(robot: Robot, target: dict[str, float]) -> None:
    state = robot.get_joint_state("right_arm")
    if state.status != "ready":
        raise RuntimeError(f"right_arm is {state.status}: {state.details}")

    result = robot.move_joints("right_arm", target)
    if result.status != "succeeded" or result.arrival_confirmed is not True:
        raise RuntimeError(f"motion failed: {result}")
```

`cross_embodiment.connect()` 是 Backend 集成使用的低层入口，需要显式传入 Manifest 与 Adapter callable。v0.1 尚未提供公共 `Robot.from_package(...)` 工厂。安装 Package 后的正式加载路径由 `ce package use`、`ce onboard preflight` 和 `ce onboard accept-l3` 完成，内部会验证 Package、Mapping、Backend 和 Store 摘要后创建 `Robot`。

## 6. 已安装 Package 的运行命令

### 只读预检

先按厂商文档启动 Driver 并完成必须的硬件使能，再显式执行：

```bash
CE=.venv/bin/ce
STORE="$HOME/.cross_embodiment"

"$CE" onboard preflight \
  --store "$STORE" \
  --instance lab/robot-01 \
  --device right_arm \
  --output ./preflight.json \
  --json
```

预检只读取状态，不发送目标。Weiyi 已验证条件为：七个关节、`status=ready`、`backend_mode=104`、`backend_fault_code=0`、`motion_sent=false`。

### 操作员授权的 L3

```bash
"$CE" onboard accept-l3 \
  --store "$STORE" \
  --instance lab/robot-01 \
  --device right_arm \
  --target ./validated-target.yaml \
  --operator "$USER" \
  --output ./installed-package-l3.json
```

命令会先显示 Package/Mapping 摘要、当前实测状态、Probe 目标和返回策略。只有现场操作员输入精确确认词 `EXECUTE L3` 后才发送 Probe，并使用动作前的新鲜实测姿态执行 Return。

## 7. Weiyi 已验证分发包

团队内部 `package_dpy` 分支提供独立 Distribution Kit，包含固定 SDK wheel、`weiyi-right-arm-runtime.cepack`、环境要求、安装验证脚本，以及带两次人工确认的一键 `quickstart.sh`。

```bash
./quickstart.sh all \
  --runtime-root "$HOME/ce-runtime/weiyi-right-arm" \
  --vendor-root "$HOME/vendor/robot_launch" \
  --instance-id lab/weiyi-right-arm-01 \
  --operator "$USER"
```

也可分阶段执行：

```bash
./quickstart.sh install   --runtime-root "$RUNTIME_ROOT" --vendor-root "$VENDOR_ROOT"
./quickstart.sh preflight --runtime-root "$RUNTIME_ROOT" --vendor-root "$VENDOR_ROOT"
./quickstart.sh accept-l3 --runtime-root "$RUNTIME_ROOT" --vendor-root "$VENDOR_ROOT" --operator "$USER"
```

`quickstart.sh` 会要求操作员分别输入：

- `ENABLE RIGHT ARM`：调用厂商 `SetPower`，不包含关节目标；
- `EXECUTE L3`：在只读预检通过后授权 Probe + Return。

`.cepack` 不包含 Weiyi Driver。目标主机仍需提供兼容的 Ubuntu 22.04 x86-64、ROS2 Humble、Python 3.10、CAN 配置及授权的 `robot_launch`/`wy_arm_sdk` Runtime。

## 8. Hardware Onboarding Agent

确定性资产扫描不会连接机器人或发送动作：

```bash
RUN_ROOT="$PWD/onboarding-run"
VENDOR_ROOT="/path/to/vendor-assets"

ce onboard inspect \
  --vendor-root "$VENDOR_ROOT" \
  --run-root "$RUN_ROOT" \
  --json
```

DeepSeek 模式需要 `cross-embodiment[onboarding-agent]` 可选依赖和本地凭据。Agent 只能使用限定的类型化工具；Scanner、Matcher、Generator、Schema 和 Conformance 保持确定性。第一次生成必须隔离旧 Package、Mapping、Demo、Transcript 和缓存。

完整流程见：

- [Hardware Onboarding 工作流](docs/onboarding/workflow.md)
- [新厂商接入手册](docs/onboarding/new-vendor-runbook.md)
- [Evidence Policy](docs/onboarding/evidence-policy.md)
- [Hardware Package 生命周期](docs/package-lifecycle.md)
- [Unified SDK v0.1 抽象冻结审计](docs/release/unified-sdk-v0.1-abstraction-freeze-audit-2026-10-16.md)

## 9. 当前已验证与未验证范围

| 项目 | 状态 |
| --- | --- |
| SDK wheel 独立安装 | 已验证 |
| `.cepack` build/install/list/inspect/activate/use/uninstall | 已验证 |
| Installed Package Store 显式加载 | 已验证 |
| Weiyi 右臂 ROS2 状态读取 | 已验证 |
| Weiyi 右臂 ROS2 绝对关节位置与实测到位 | 已验证 |
| Clean-Room DeepSeek Mapping 生成 | 已验证 |
| 左臂、灵巧手、笛卡尔、Stop/Power 统一 Capability | 未纳入 v0.1 |
| 通用 Python SDK Backend | 未验证 |
| 通用 C/C++ Native Backend | 未验证 |
| 自动生成并注册全新 Backend 插件 | 未验证 |
| 公共 `Robot.from_package(...)` 工厂 | 尚未实现 |

## 10. 安全和生命周期规则

- `package install/activate/use` 均为纯文件操作。
- 安装不会启动 Driver、配置 CAN、连接、使能或移动机器人。
- Driver 启动与硬件使能是独立步骤。
- `preflight` 只读，必须报告 `motion_sent=false`。
- 真机动作必须显示当前状态与目标，并由现场操作员确认。
- Action 接受不等于动作成功；必须检查终态、厂商错误码和实测到位。
- 卸载 `.cepack` 不删除共享厂商 Driver、ROS2 或设备数据。
