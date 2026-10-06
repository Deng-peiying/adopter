# Cross-Embodiment SDK v0.1

这是跨本体具身智能 SDK 的 v0.1 实现，当前提供 EE-first 的最小可运行闭环：

```text
Manifest → Mock Adapter → Robot SDK → Runtime → EE Policy → Action
```

## 当前能力

- `Robot / Device / Capability` 的基础 Manifest 模型
- `RobotState`、`Observation`、`Action`、`ActionSpec` 数据结构
- Mock Robot Adapter
- `ee_delta` 控制模式
- Runtime 生命周期和执行循环
- Compatibility Check
- 坐标系字段、动作限幅、NaN/Inf 检查和安全错误
- 可替换 Adapter 接口

## 本地运行

安装开发包：

```bash
python3 -m pip install -e .
```

运行 EE 示例：

```bash
python3 examples/ee_policy.py
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 接入真实机器人

实现 `cross_embodiment.adapters.base.RobotAdapter` 中的接口，并在 `connect()` 中注册对应 Adapter。核心 Runtime 不应直接依赖厂商 SDK；厂商依赖应放在独立 Adapter 包中。

v0.1 的 Runtime 只执行 `ee_delta`。但 `ActionSpec.type`、Manifest 的 `supported_modes` 和 SDK 的 `Command.mode` 已经按可扩展方式设计，后续可以增加 `joint_position`、`base_velocity`、`bimanual` 和 `whole_body`。
