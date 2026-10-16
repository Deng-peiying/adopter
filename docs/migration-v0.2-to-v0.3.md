# 从仓库内 WY Demo 迁移到 v0.3

v0.3 将代码按交付边界拆成三个目录：

```text
for_robot/
├── cross-embody-sdk/             # SDK Core 和 ce CLI
├── ce-hardware-weiyi-dual-o6/   # weiyi/dual_o6 Hardware Package
├── wy-dual-o6-demo/             # 项目、实例和任务
└── assets/catalog.yaml           # 本地 Registry 索引
```

WY Adapter、ROS 消息映射、启动命令、模型清单和厂商运行时属于 Hardware
Package。项目只通过 `package: weiyi/dual_o6` 与版本依赖它，不再用相对路径
导入 SDK 仓库中的包。`ce install` 将版本复制到
`~/.cross_embodiment/packages/hardware/weiyi/dual_o6/0.1.0/` 并生成
`wy-dual-o6-demo/embodiment.lock`。

本地开发命令：

```bash
cd cross-embody-sdk
python3 -m pip install -e .
ce install --project ../wy-dual-o6-demo/project.yaml --registry ..
ce validate --project ../wy-dual-o6-demo/project.yaml
ce up --project ../wy-dual-o6-demo/project.yaml --dry-run
```

需要 Native 启动时，先用已安装 Hardware Package 的脚本在目标机构建 ROS
workspace，然后显式启动。构建输出保存在 `~/.cache/cross-embodiment/`，不会
改写已锁定的 Hardware Package：

```bash
bash ~/.cross_embodiment/packages/hardware/weiyi/dual_o6/0.1.0/scripts/build_runtime.sh
ce up --project ../wy-dual-o6-demo/project.yaml --live
ce run --project ../wy-dual-o6-demo/project.yaml
ce down --project ../wy-dual-o6-demo/project.yaml
```

Registry 目前是本机 `assets/catalog.yaml` 索引，不从网络下载；安装后
`validate/up/status/run/down` 从项目锁和 SDK 包存储解析依赖，不要求保留这三个
同级 checkout。主机仍须安装 ROS 2 Humble，并提供适配的 Python 3.10、系统库和
CAN 设备/权限。此布局不是包含 SDK、硬件包和所有主机依赖的离线单目录包。

`ce install` 只复制并校验包，不执行包提供的任意安装钩子。Hardware Package
构建是单独的显式操作。当前项目 task 仅演示 READY 检查；完整 Policy Protocol
及跨进程 Observation/Action 通道仍是后续实现范围。
