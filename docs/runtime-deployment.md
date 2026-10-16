# Installed Hardware Package Runtime 部署指南

## 职责边界

```text
Unified SDK wheel
       ↓
Installed Hardware Package (.cepack)
       ↓
Backend / Mapping
       ↓
外部厂商 Runtime / Driver
       ↓
真实机器人
```

- SDK 提供统一 API、Backend 契约和 Package 生命周期。
- `.cepack` 提供设备、Capability、Mapping、Runtime Policy 和 Backend 选择。
- 厂商 Runtime 提供 Driver、ROS2 类型支持、动态库、设备连接和底层进程。

Package 安装和激活只操作文件，不启动 Driver、不连接机器人、不使能也不发送
动作。

## 从 Robot Instance 创建 Robot

```python
from cross_embodiment import Robot

with Robot.from_instance(
    "lab/robot-01",
    allow_motion=False,
) as robot:
    state = robot.get_joint_state("right_arm")
    print(state.status)
    print(state.positions)
    print(robot.runtime_info.to_dict())
```

`Robot.from_instance()` 会校验实例绑定、Package 摘要、Mapping 路径与摘要，并按
Package 声明加载 Backend。它不自动启动 Driver。

默认 Store 为 `$HOME/.cross_embodiment`。可以传入 `store="/path/to/store"` 或设置：

```bash
export CROSS_EMBODIMENT_STORE=/srv/robot-package-store
```

## 运动权限

`allow_motion=False` 为默认值，并在 SDK 层拦截 `move_joints()` 和通用运动
`command()`。`allow_motion=True` 仅表示该 SDK 会话允许向 Backend 传递动作；它不会
启动 Driver、不会使能硬件，也不取代现场安全授权。

动作结果必须检查终态、厂商错误码和实测到位结果，不能仅根据 Action 已接受
宣称成功。

## Driver Lifecycle

v0.1 不提供通用 Driver `status/start/stop/health` API。Driver 由部署层显式启动，
SDK 通过 Backend 连接已运行的 Driver。`robot.connect()` 不会自动使能机器人。

## 厂商资产分发

Onboarding 输入资产不会默认全部进入 `.cepack`。建议分为：

1. **Hardware Package**：映射、能力、策略、Backend 声明和依赖元数据。
2. **Vendor Runtime Bundle**：可选，只包含运行所需且获得再分发授权的 Driver、类型支持、
   动态库、URDF 和配置。
3. **Onboarding Source Archive**：可选审计资料，不参与日常 Runtime 加载。

如果厂商资产没有明确许可，Distribution Kit 只记录外部依赖，由接收方从厂商或
授权集成商获取 Runtime。

## 只读预检

Driver 已启动且厂商要求的状态准备完成后，通过显式入口执行只读预检：

```bash
ce onboard preflight \
  --instance lab/robot-01 \
  --device right_arm \
  --output ./preflight.json \
  --json
```

预检记录应包含 Package/Mapping 路径与摘要、Backend、实测状态和
`motion_sent=false`。
