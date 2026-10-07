# Cross-Embodiment SDK

本仓库是跨本体 SDK Core：提供通用 Manifest、Robot/Device/Capability、Action/Observation、Runtime、安全校验、Mock Adapter、Package Resolver、Registry 客户端和 `ce` CLI。当前设计基准为 [`v0.3`](docs/architecture/cross-embodiment-sdk-design-v0.3.md)。

Core 的源码按 v0.3 的职责边界组织：

```text
src/cross_embodiment/
├── sdk/          # Robot API 与生命周期
├── runtime/      # Policy 执行、安全和动作映射
├── protocol/     # Action、Observation、Policy 协议
├── hardware/     # Embodiment Manifest、Robot Instance
├── package/      # Package Manifest、Registry、Resolver、Lock
├── adapter/      # Adapter Contract 与通用 Mock
├── driver/       # Backend 加载、健康状态、进程托管
└── cli/          # ce 命令实现
cli/              # 源码检出时的轻量命令入口
schemas/          # Hardware、Embodiment、Instance、Policy、Project Schema
tests/            # unit / integration / mock / conformance
```

WY 双臂 + O6 的厂商 Adapter 和运行时位于独立的 `ce-hardware-weiyi-dual-o6` Hardware Package；示例项目位于独立的 `wy-dual-o6-demo`。三者是同级目录，SDK Core 不导入 ROS2 或 WY 代码：

```text
for_robot/
├── cross-embody-sdk/             # 本仓库：通用 SDK 与 ce 命令
├── ce-hardware-weiyi-dual-o6/   # WY Adapter、配置和裁剪后的厂商运行时
├── wy-dual-o6-demo/             # project.yaml、Robot Instance 和 task
└── assets/catalog.yaml           # 本地 Registry 索引
```

## 本地开发和 WY 项目

```bash
cd /home/robot/文档/for_robot/cross-embody-sdk
python3 -m pip install -e .

ce install --project ../wy-dual-o6-demo/project.yaml --registry ..
ce validate --project ../wy-dual-o6-demo/project.yaml --registry ..
ce up --project ../wy-dual-o6-demo/project.yaml --dry-run --registry ..
```

`ce install` 从本地 Registry 将包复制并校验到 `~/.cross_embodiment/packages/`，同时生成项目 `embodiment.lock`。该操作不运行硬件启动或包内安装脚本。当前没有远程 Registry；本地开发时 Registry 指向 `for_robot/`。

Native 启动还需要在目标机上构建硬件包的 ROS workspace，然后显式启动并停止：

```bash
bash ~/.cross_embodiment/packages/hardware/weiyi/dual_o6/0.1.0/scripts/build_runtime.sh
ce up --project ../wy-dual-o6-demo/project.yaml --live --registry ..
ce status --project ../wy-dual-o6-demo/project.yaml --registry ..
ce run --project ../wy-dual-o6-demo/project.yaml --registry ..
ce down --project ../wy-dual-o6-demo/project.yaml --registry ..
```

Native 路径需要 ROS 2 Humble、主机依赖、正确配置的 CAN 接口及对应权限。硬件二进制包尚无确认的再分发许可，因此当前仅保留在本地 Hardware Package。没有在本次重构中连接实体机器人或发送动作。

架构和实施计划位于 `docs/`；`outputs/` 仅用于可重新生成的输出文件。JSON Schema 已按契约分类，但当前 loader 尚未执行 JSON Schema 校验。
