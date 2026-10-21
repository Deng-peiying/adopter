# Cross-Embodiment SDK

Cross-Embodiment SDK 是统一机器人接入与运行平台：

- **Unified Robot Runtime**：通过 `Robot` API 读取状态和执行标准能力。
- **Hardware Onboarding Agent**：从厂商原始资产提取证据，生成 Mapping 和 Hardware Package。
- **Hardware Package Lifecycle**：构建、安装、检查、激活、使用和卸载 `.cepack`。

SDK 不包含 Weiyi Mapping、Driver、Demo、凭据或历史缓存。厂商控制语义保存在
Hardware Package 中，厂商 Driver 作为独立 Runtime 部署。

## 两种使用模式

| 目标 | 入口 | 需要 DeepSeek |
| --- | --- | --- |
| 安装已验收的机器人 | SDK wheel + `.cepack` | 否 |
| 从新厂商资产接入 | SDK + Hardware Onboarding Agent | 仅语义审阅阶段 |

## Quick Start：使用已有 Hardware Package

Weiyi Dual O6 右臂的内部 Distribution Kit 在 `package_dpy` 分支。Kit 包含固定
SDK wheel 和已验收 `.cepack`，不需要 SDK 源码、DeepSeek 或历史 Mapping。

```bash
git clone --branch package_dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git \
  weiyi-dual-o6-right-arm
cd weiyi-dual-o6-right-arm

./install.sh
./verify.sh
```

如果系统只有 Ubuntu 自带的 PyYAML 5.4.1，`install.sh` 会通过当前 pip 配置在
Kit venv 中安装 PyYAML 6.x。离线部署应先配置内部 Package Index 或提供经过审核的
PyYAML wheel，再运行安装脚本。

`install.sh` 只安装 wheel、`.cepack` 并激活 Robot Instance。`verify.sh` 默认只做
摘要、Store、实例绑定和平台检查。两者都不启动 Driver、不使能、不连接
机器人，也不发送动作。

默认值：

- Store：`$HOME/.cross_embodiment`
- Robot Instance：`lab/weiyi-right-arm-01`
- venv：`${XDG_DATA_HOME:-$HOME/.local/share}/cross-embodiment/weiyi-dual-o6-right-arm/venv`

所有路径和 Instance ID 都可通过脚本参数或环境变量覆盖。

### 显式在线只读预检

目标主机还需要 Ubuntu 22.04 x86-64、ROS2 Humble、Python 3.10、厂商
Runtime、CAN/DDS 配置和已连接的机器人。这些不包在 `.cepack` 中。

```bash
./quickstart.sh preflight --vendor-root /path/to/robot_launch
```

`preflight` 会显式启动外部 Driver，等待操作员输入 `ENABLE RIGHT ARM`，然后仅读取
七关节状态。它不发送关节目标。授权运动的 L3 验收是独立入口，不属于安装
成功条件。

`preflight` 退出时会停止由它临时启动的 Driver。普通业务程序运行时，需要在另一个
终端按照厂商 Runtime 文档保持 Driver 运行，并由操作员完成必要使能；SDK 不会自动
启动 Driver 或使能机器人。

### 业务程序使用统一 API

`package_dpy` Kit 已提供真实存在的只读示例。`preflight` 退出后 Driver 已停止，
因此日常业务程序应使用两个终端：

终端 A 持续运行与验收流程相同的外部 Driver：

```bash
export VENDOR_ROOT=/path/to/robot_launch
cd "$VENDOR_ROOT"
source setup.sh
DRIVER_CONFIG="$VENDOR_ROOT/third_party/wy_arm_sdk/install/arm_control_system/share/arm_control_system/config/dual_arm_system.yaml"

ros2 run arm_control_system arm_system_node --ros-args \
  -r __ns:=/wy_robot1 \
  --params-file "$DRIVER_CONFIG" \
  -p arm_list:="['left_arm', 'right_arm']" \
  -p can_port:="[2, 3]" \
  --log-level info
```

该命令保持前台运行，结束使用时按 `Ctrl+C`。终端 B 加载相同环境、显式使能右臂，
然后在 Kit 根目录运行公共 SDK 示例：

```bash
export VENDOR_ROOT=/path/to/robot_launch
source "$VENDOR_ROOT/setup.sh"

ros2 service call /wy_robot1/right_arm_set_power \
  arm_control_interface/srv/SetPower \
  "{power_enable: true}"

cd /path/to/weiyi-dual-o6-right-arm
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/cross-embodiment/weiyi-dual-o6-right-arm/venv"
"$VENV/bin/python" examples/read_joint_state.py
```

`SetPower` 改变控制器使能状态但不发送关节目标。等待 mode 104 后，该示例使用
`allow_motion=False` 只读取状态，不发送运动命令。它的核心代码如下：

```python
from cross_embodiment import Robot

with Robot.from_instance(
    "lab/weiyi-right-arm-01",
    allow_motion=False,
) as robot:
    state = robot.get_joint_state("right_arm")
    print(state.positions)
    print(robot.runtime_info.to_dict())
```

`allow_motion=False` 是 SDK 层强制门禁。即使 Backend 处于可控状态，
`move_joints()` 和通用运动 `command()` 也会在下发前被拒绝。

需要使用自定义 Store 时：

```python
with Robot.from_instance(
    "lab/robot-01",
    store="/path/to/store",
    allow_motion=False,
) as robot:
    print(robot.get_joint_state("right_arm"))
```

`Robot.from_instance()` 不会启动厂商 Driver，构造时只完成配置。
`robot.connect()` 不会使能机器人，具体连接方式由硬件包 Adapter 实现。
运动需要显式 `allow_motion=True`；可先用 `target = dict(state.positions)` 从完整实测
状态准备具名目标，再按硬件包能力和限制修改。`robot.close()` 释放连接，不隐式下电。

## Onboard a New Robot

首次接入新厂商时，用户提供厂商 SDK、ROS2 接口、头文件、动态库、示例、
机器人模型和依赖资料。Onboarding 流程不使用历史厂商 Mapping 作为答案。

```bash
git clone --branch dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git
cd cross-embody-sdk

python3.10 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade 'pip>=23' 'setuptools>=68' wheel
.venv/bin/python -m pip install --no-build-isolation -e '.[onboarding-agent]'

.venv/bin/ce onboard inspect \
  --vendor-root /path/to/vendor-assets \
  --run-root ./onboarding-run \
  --json
```

正式流程为：

```text
Inventory → Evidence → Capability Match → Backend Fit
          → Candidate Package → Conformance
          → Operator Runtime Policy → Runtime Package → .cepack
```

Onboarding 生成的运行包包含包内 Adapter 骨架与映射证据文件。骨架不会解释厂商 YAML，
也不能连接或控制硬件；必须由硬件包作者实现并验证具体 Adapter。Python/C++
驱动和跨厂商代码生成仍未验证。

## Hardware Package 命令

```bash
ce package build --package-root ./hardware-package-runtime --output ./robot.cepack --json
ce package install --artifact ./robot.cepack --json
ce package list --json
ce package inspect vendor/model@1.0.0 --json
ce package activate vendor/model@1.0.0 --instance ./robot.instance.yaml --json
ce package use --instance lab/robot-01 --json
ce package deactivate --instance lab/robot-01 --json
ce package uninstall vendor/model@1.0.0 --json
```

Package 命令只操作文件、摘要、Store 和实例绑定，不自动启动 Driver、使能设备
或发送动作。`CROSS_EMBODIMENT_STORE` 可覆盖默认 Store。

## 当前验证状态

| 检查 | 状态 |
| --- | --- |
| 新源码语法编译 | 已通过 `compileall`，只检查语法 |
| 旧 Adapter 与 YAML Mapping Engine 删除后的 SDK / Onboarding 测试 | 尚未运行 |
| WY 新 Adapter 和硬件包端到端检查 | 尚未在本次重构后运行 |
| Driver、ROS2 节点及真实机器人控制 | 本次未运行 |

旧版本的离线与现场验证记录不代表当前 breaking refactor 已通过验证。

## 文档

- [v0.3 架构设计](docs/architecture/cross-embodiment-sdk-design-v0.3.md)
- [v0.4 正式架构设计](docs/architecture/cross-embodiment-sdk-design-v0.4.md)
- [v0.4 Implementation](docs/implementation/cross-embodiment-sdk-implementation-v0.4.md)
- [v0.4 历史设计草稿](docs/architecture/v0.4-draft.md)

`docs/implementation/` 保存版本实施说明与验收清单；旧指南和执行记录可从 Git 历史查阅。

## 源码目录

```text
src/cross_embodiment/
├── sdk/          # Robot API 与 Lifecycle
├── adapter/      # Adapter 契约、包资源上下文与健康报告
├── transport/    # 通用通信协议与 ROS2 Action/Service
├── driver_host/  # 子环境、进程管理与 Transport 子进程
├── protocol/     # Action、JointState、CommandResult
├── runtime/      # 安全约束、动作转换与实例装配
├── package/      # .cepack、Package Store 和包内 Adapter 加载
├── onboarding/   # 证据评估、包骨架生成与契约检查
└── cli/          # ce CLI
```
