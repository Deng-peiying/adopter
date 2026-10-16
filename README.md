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

完整部署边界见 [Runtime 部署指南](docs/runtime-deployment.md)。

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

Weiyi 已验证“复用 `ros2_mapped` Backend 并自动生成 Mapping”。Python SDK、
C/C++ Library 和全新 Backend 插件的自动代码生成与真机运行尚未验证。当现有
Backend 无法表达厂商通信方式时，系统必须输出明确缺口，不得伪造支持。

详细步骤见 [Hardware Onboarding 工作流](docs/onboarding/workflow.md) 和
[新厂商接入手册](docs/onboarding/new-vendor-runbook.md)。

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

## 已验证范围

| 能力 | 状态 |
| --- | --- |
| wheel 独立安装 | 已验证 |
| `.cepack` build/install/activate/use/uninstall | 已验证 |
| `Robot.from_instance()` 真实七关节状态读取 | 已验证 |
| Weiyi `joint_position_state` / `joint_position` | 已真机验证 |
| ROS2 资产到 Mapping/Package 自动生成 | 已真机验证 |
| Python/C++ 自动 Backend 生成 | 尚未验证 |
| Driver Lifecycle `status/start/stop/health` | 尚未实现 |

## 文档

- [Unified Robot API](docs/architecture/unified-robot-api-v1.md)
- [Runtime 部署指南](docs/runtime-deployment.md)
- [Hardware Package 生命周期](docs/package-lifecycle.md)
- [Hardware Onboarding 工作流](docs/onboarding/workflow.md)
- [Evidence Policy](docs/onboarding/evidence-policy.md)
- [SDK 开发与测试](docs/development.md)
- [v0.3 架构设计](docs/architecture/cross-embodiment-sdk-design-v0.3.md)

## 源码目录

```text
src/cross_embodiment/
├── sdk/          # Robot API
├── protocol/     # Action、JointState、CommandResult
├── mapping/      # 映射验证、编码和解码
├── backend/      # BackendTransport 契约
├── driver/       # ros2_mapped 和 Ros2Transport
├── package/      # .cepack 和 Package Store
├── onboarding/   # Scanner、Matcher、Agent、Generator、Conformance
└── cli/          # ce CLI
```
