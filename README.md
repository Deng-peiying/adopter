# Cross-Embodiment SDK

本仓库是跨本体 SDK Core：提供通用 Manifest、Robot/Device/Capability、Action/Observation、Runtime、安全校验、Mock Adapter、Package Resolver、Registry 客户端和 `ce` CLI。当前设计基准为 [`v0.3`](docs/architecture/cross-embodiment-sdk-design-v0.3.md)。

Core 的源码按 v0.3 的职责边界组织：

```text
src/cross_embodiment/
├── sdk/          # Robot API 与生命周期
├── runtime/      # Policy 执行、安全和动作映射
├── protocol/     # Action、Observation、Policy 协议
├── mapping/      # Hardware Package 映射校验、编译与解码
├── backend/      # 与 ROS/Python/Native 无关的传输协议
├── hardware/     # Embodiment Manifest、Robot Instance
├── package/      # Package Manifest、Registry、Resolver、Lock
├── adapter/      # Adapter Contract 与通用 Mock
├── driver/       # ROS2 Transport、Backend 加载、健康状态、进程托管
└── cli/          # ce 命令实现
cli/              # 源码检出时的轻量命令入口
schemas/          # Hardware、Embodiment、Instance、Policy、Project Schema
tests/            # unit / integration / mock / conformance
```

WY 双臂 + O6 的厂商运行时和接口映射位于独立的 `ce-hardware-weiyi-dual-o6` Hardware Package；示例项目位于独立的 `wy-dual-o6-demo`。三者是同级目录，SDK Core 不导入 ROS 2 或 WY 代码：

```text
for_robot_dpy/
├── cross-embody-sdk/             # 本仓库：通用 SDK 与 ce 命令
├── ce-hardware-weiyi-dual-o6/   # 厂商接口映射和运行时
├── wy-dual-o6-demo/             # project.yaml、Robot Instance 和统一 API task
└── assets/catalog.yaml           # 本地 Registry 索引
```

## 本地开发和 WY 项目

```bash
cd /home/robot/文档/for_robot_dpy/cross-embody-sdk
python3 -m pip install -e .

ce install --project ../wy-dual-o6-demo/project.yaml --registry ..
ce validate --project ../wy-dual-o6-demo/project.yaml --registry ..
ce up --project ../wy-dual-o6-demo/project.yaml --dry-run --registry ..
```

`ce install` 从本地 Registry 将包复制并校验到 `~/.cross_embodiment/packages/`，同时生成项目 `embodiment.lock`。该操作不运行硬件启动或包内安装脚本。当前没有远程 Registry；本地开发时 Registry 指向 `for_robot_dpy/`。

Native 运行需要先构建 Hardware Package 的 ROS workspace，再在独立终端启动厂商驱动。当前映射后端使用 `manage_process: false` 附着到已有 ROS graph：

```bash
cd ../ce-hardware-weiyi-dual-o6
bash scripts/build_runtime.sh
bash runtime/scripts/start.sh
```

驱动就绪后，在第二个终端通过 Demo 的公共 Robot API 执行任务：

```bash
cd ../wy-dual-o6-demo
source ../ce-hardware-weiyi-dual-o6/runtime/setup.sh
export PYTHONPATH="$PWD/../cross-embody-sdk/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
python3.10 tasks/wave_goodbye.py --cycles 2 --amplitude-rad 0.30 --send
```

Native 路径需要 ROS 2 Humble、主机依赖、正确配置的 CAN 接口及对应权限。硬件二进制包尚无确认的再分发许可，因此当前仅保留在本地 Hardware Package。

2026-10-13 已通过 `wy-dual-o6-demo/tasks/wave_goodbye.py` 完成右臂真机链路验证：Demo 只调用 `Robot.get_joint_state()` 和 `Robot.move_joints()`；`MappedRos2Adapter` 组合纯 Mapping Engine 与 ROS2 Transport，根据 Hardware Package 的 YAML 编译 `TransportRequest`，再把 Action 结果和实测状态恢复为 SDK 类型。该验证覆盖右臂关节状态和绝对关节位置，不代表左臂、灵巧手、笛卡尔、停止或使能接口已经映射。

架构和实施计划位于 `docs/`；`outputs/` 仅用于可重新生成的输出文件。JSON Schema 已按契约分类，但当前 loader 尚未执行 JSON Schema 校验。

## Hardware Onboarding Agent

当前分支提供独立的 Hardware Onboarding 工具链：扫描厂商原始资产，建立可追溯
接口证据，匹配固定 Capability，评估 Backend 支持，生成隔离的 Hardware Package，
并执行 L1/L2/L3 分级验收。接入新机器人时不修改 Unified Robot API；厂商差异
进入 Hardware Package，新的通信机制才进入 Backend 插件。

- [完整工作流](docs/onboarding/workflow.md)
- [证据、Capability 与验证等级策略](docs/onboarding/evidence-policy.md)
- [Weiyi 独立 L1/L2 结果](docs/onboarding/weiyi-independent-acceptance.md)
- [Weiyi 新生成 Package 的 L3 三终端手册](docs/onboarding/weiyi-l3-runbook.md)

当前自动生成范围仅为 Weiyi 右臂 `joint_position_state` 和
`joint_position`，当前 Backend 只支持 ROS2 subscription/action。L1/L2 不发送
动作；L3 必须显式加载新生成目录，并由现场操作者确认后执行。
