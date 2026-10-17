# Unified SDK v0.1 抽象完整性与 SDK/Hardware Package 解耦审计

日期：2026-10-16  
审计分支：`dpy`  
审计基线：`1862ecb`（本轮修正前）

## 1. 范围与结论

本轮只审计 Unified SDK、Hardware Package 契约和已实现的右臂关节能力。没有新增
Runtime 工厂、Capability、Python/C++ Backend，也没有连接或控制机器人。

| 结论 | 判定 | 适用范围 |
| --- | --- | --- |
| Separation Complete | **是** | SDK wheel、`.cepack`、Package Store 和厂商 Runtime 已分层；SDK 不需要任何厂商 Package 才能安装和导入 |
| Runtime Contract Complete | **是** | 已实现并经 Weiyi L3 验证的 `joint_position_state` / `joint_position` |
| Extension Contract Ready | **部分就绪** | 新 Package、新设备、任意关节数量及新 Backend 入口已有边界；新的 Mapping operation 或新的公共 Action 类型仍需扩展 SDK |
| Release Ready | **是** | 可冻结为内部 v0.1；不得把 Catalog 中尚未实现的能力解释为运行时已支持 |

本轮发现并修复了三个发布前契约问题：

1. `RobotAdapter` Protocol 少声明了 `Robot` 已经实际调用的
   `capabilities()`、`supports_action()` 和 `get_joint_state()`；同时
   `MappedRos2Adapter` 少实现了 Protocol 已声明的 `load_manifest()`。
2. wheel 内外两份 Hardware Package JSON Schema 使用 `hardware-package/v0.3`，而
   Generator、Package Lifecycle 和已验收 `.cepack` 使用 `hardware-package/v0.1`。
   已统一到 Package Schema v0.1；架构文档 v0.3 与 Package Schema v0.1 是两个不同版本域。
3. Kinematics 测试和真实 Weiyi Evidence Replay 隐式依赖同级厂商仓库及本机路径。
   Kinematics 改用仓库内中性二关节 Fixture；真实资产 Replay 改为显式环境变量启用。

这些修正没有改变 `Robot` 公共方法、Interface Mapping 的编译/解码规则、
`Ros2Transport` 的消息构造或已验收 Weiyi Mapping。

## 2. 实际运行契约与调用链

### 2.1 安装、激活和解析

```text
.cepack
  -> PackageLifecycle.install()
     -> inspect_package_artifact()
     -> load_package_manifest()
     -> 校验 artifact/tree/asset digest
     -> 复制到不可变 Package Store 并写安装记录
  -> PackageLifecycle.activate()
     -> load_robot_instance()
     -> 按平台选择 Package 声明的 Backend
     -> 只写 Instance 与 activation 记录
  -> PackageLifecycle.resolve_use()
     -> 重新校验安装目录摘要
     -> 返回 Package root、manifest、Backend entrypoint 和 connection
```

源码入口：

- `src/cross_embodiment/package/artifact.py`：制品构建、检查和安全解包。
- `src/cross_embodiment/package/manifest.py:137`：Package Manifest 解析和 v0.1
  契约校验。
- `src/cross_embodiment/package/lifecycle.py:251`：安装。
- `src/cross_embodiment/package/lifecycle.py:315`：激活。
- `src/cross_embodiment/package/lifecycle.py:372`：带摘要校验的运行描述解析。
- `src/cross_embodiment/package/lifecycle.py:429`：卸载；不处理外部厂商 Driver。

上述过程只做文件操作，不导入 Onboarding Agent，不需要 DeepSeek，也不连接硬件。

### 2.2 从已安装 Package 到 Robot

```text
ce onboard preflight --store/--instance
  -> PackageLifecycle.resolve_use()
  -> 只接受 Store 中已激活且摘要一致的 Package
  -> load_package_manifest() + load_manifest()
  -> load_backend_entrypoint()
  -> sdk.robot.connect(adapter, manifest, connection)
  -> Robot(adapter, manifest)
```

源码入口：

- `src/cross_embodiment/onboarding/l3.py:140`：解析已安装运行描述并核验 Package
  root、Manifest、Backend 和 Mapping 均来自 Store。
- `src/cross_embodiment/onboarding/l3.py:172`：加载 Backend 后调用固定 SDK
  `connect()`。
- `src/cross_embodiment/driver/backend.py:12`：从 Package 声明的
  `module:factory` 动态加载 Backend。
- `src/cross_embodiment/sdk/robot.py:57`：公共 `Robot`。

当前没有通用 `Robot.from_package()` 工厂。v0.1 的正式已安装 Package 运行桥接位于
现有 `ce onboard preflight/accept-l3` 路径；这不影响已经完成的 Package Store L3，
也不在本轮扩展范围内。

### 2.3 读取关节状态

```text
Robot.get_joint_state(device_id)
  -> RobotAdapter.get_joint_state(device_id)
  -> MappedRos2Adapter 等待新鲜状态事件
  -> InterfaceMappingEngine.decode_joint_state()
  -> JointState(device_id, canonical positions, source/receive timestamps, status)
```

契约位置：

- `src/cross_embodiment/sdk/robot.py:73`
- `src/cross_embodiment/adapter/base.py:10`
- `src/cross_embodiment/driver/ros2_mapped.py:154`
- `src/cross_embodiment/mapping/engine.py`

`joint_position_state` 是 Capability Catalog 名称；其唯一 Binding operation 是
`joint_state`；公共读取方法是 `get_joint_state()`。三者分别属于能力、映射和 API
命名域，转换在 `catalogs/capabilities/v0.1.yaml:81` 显式声明，不是运行时猜测。

### 2.4 绝对关节位置命令

```text
Robot.move_joints(device_id, canonical-name -> radian)
  -> 检查 Manifest 声明、Adapter 活跃 Binding、完整关节集合
  -> SafetyGuard
  -> ActionMapper: Action -> backend-internal Command
  -> RobotAdapter.send_command()
  -> InterfaceMappingEngine.compile_command()
  -> TransportRequest
  -> BackendTransport.execute()
  -> InterfaceMappingEngine.decode_result()
  -> 实测 JointState 到位检查
  -> CommandResult
```

契约位置：

- `src/cross_embodiment/sdk/robot.py:81`
- `src/cross_embodiment/runtime/mapping.py`
- `src/cross_embodiment/mapping/engine.py:202`
- `src/cross_embodiment/backend/protocol.py:49`
- `src/cross_embodiment/driver/ros2_transport.py:96`
- `src/cross_embodiment/driver/ros2_mapped.py`

`Robot` 不接触 ROS 类型；Mapping Engine 不导入 ROS；Transport 不理解规范关节名称。

## 3. 逐项审计

| 问题 | 代码证据与影响 | 冻结结论 | 公共 API 修改 |
| --- | --- | --- | --- |
| wheel 独立性 | `pyproject.toml` 的 Core 依赖只有 PyYAML；ROS、PyKDL 和模型客户端均为可选或运行环境依赖。独立 wheel 导入及 13 项 Schema/Catalog 资源检查通过 | 不阻塞 | 否 |
| Package 可替换性 | Lifecycle 以 `name@version` 存储，摘要锁定，多个版本目录共存；安装/激活/卸载均不改 SDK | 不阻塞 | 否 |
| Weiyi 泄漏 | `src/`、`catalogs/`、`schemas/`、`cli/` 中没有 Weiyi Topic、Action、MoveJ、固定七轴或厂商字段。Weiyi 内容只存在文档和隔离测试证据 | 不阻塞 | 否 |
| Robot/Adapter 契约 | Protocol 原先少声明运行时实际方法；本轮补齐并让 Mock/ROS2 mapped 实现一致 | 已修复 | 否；仅补齐静态 Protocol |
| Adapter/Mapping/Transport | Adapter 组合规范语义与 Transport；Mapping 编译纯 `TransportRequest`；Transport 只处理机制 | 一致 | 否 |
| 状态命名 | Capability=`joint_position_state`，Mapping operation=`joint_state`，API=`get_joint_state()`；Catalog 显式绑定 | 可冻结，文档须保留分层说明 | 否 |
| Catalog 与实现范围 | Catalog 是标准词汇表；当前 Mapping Schema 只允许 `joint_state`、`joint_position`；Backend Descriptor 只证明 ROS2 mapped 对这两项的支持 | 可冻结，但不得把 Catalog 条目当作实现声明 | 否 |
| 新设备/关节数量 | Manifest 和 Mapping 使用设备列表与有序关节数组；Mock 已移除 `right_arm` 和两关节硬编码；三关节中性测试通过 | 可冻结 | 否 |
| 新 Backend | Package Manifest 声明 Backend id/type/entrypoint/platform/requirements；动态入口不含厂商分支 | 边界就绪，具体新协议仍需插件实现与验证 | 否 |
| 非关节能力 | Package 能声明新设备和 Capability；但 Mapping Schema 与 `InterfaceMappingEngine` 当前只实现两项关节 operation，`ActionMapper` 也只有有限公共 Action 规则 | 不阻塞当前 v0.1；未来新增 operation 需要 SDK 扩展 | 当前无需；未来可能需要 |
| Onboarding 解耦 | Package Lifecycle 模块不导入 Provider/Agent；模式 A 无 DeepSeek。模式 B 的 Catalog/Schema 随 wheel 分发 | 不阻塞 | 否 |
| Runtime Policy | `timeout_s`、到位容差、稳定窗口来自 Package Mapping；不会从厂商 Evidence 自动猜测。ROS2 server/goal/cancel wait 与状态采样还有平台 liveness 默认 | 可冻结，见下节 | 否 |

## 4. Runtime Policy 与平台 liveness 边界

经 L3 验证的 Package 控制完成策略是：

- Action terminal timeout：`90 s`
- arrival tolerance：`0.015 rad`
- settle window：`1.0 s`
- 来源：`previously_live_validated_runtime_policy`

Mapping Engine 要求 Package 明确提供这些字段，并将 Action timeout 编入
`TransportRequest`。SDK 不用别的默认值覆盖它们。

另有下列平台 liveness 边界：

- `MappedRos2Adapter` 状态首样本等待默认 `5 s`；可由 connection
  `state_timeout_s` 配置。
- `MappedRos2Adapter` 实测到位总等待默认 `20 s`；可由 connection
  `arrival_timeout_s` 配置。它限制状态观察周期，不改变 Package 的到位容差或稳定窗口。
- `Ros2Transport` Action Server 发现等待 `3 s`、Goal response 等待 `5 s`、取消响应
  等待 `3 s`。

这些值属于 Runtime/Transport 可用性策略，并非厂商接口语义。它们不会改写
Package Mapping，但当前部分仍是代码默认值。对已验证的两项能力不构成冻结阻塞；
未来若需要按部署环境治理，可迁移到平台或 Instance 配置，不能标为 vendor-declared。

## 5. 扩展边界

### 无需修改 SDK Core

- 新的 Package 名称和版本。
- 新设备 id、设备数量和非七轴关节数组。
- 新的规范关节名称、厂商关节顺序、单位转换、端点和消息字段。
- 已由 Mapping Engine 支持的 `joint_state` / `joint_position` 绑定。
- 新 Backend 实现，只要实现 `RobotAdapter` 或由 Adapter 组合实现
  `BackendTransport`，并由 Package entrypoint 显式声明。

### 需要扩展固定 SDK

- 新的 Mapping operation、encode/decode/result 生命周期。
- 当前 `ActionMapper` 尚不认识的公共动作语义。
- 新的通用状态类型或跨设备协调语义。

因此 Extension Contract 对“Backend 插件和 Package 声明”已经清晰；对“任意新增
Capability 全靠配置”尚未成立，v0.1 不应作此承诺。

## 6. 静态验收证据

- 全量测试：`221 passed, 8 skipped`。8 项为需要显式原始 Weiyi 资产目录的真实
  Evidence Replay。
- 显式真实资产 Replay：`8 passed`。
- wheel/sdist 构建：通过；wheel 中包含 Runtime、Onboarding Agent、Package
  Manager、Capability Catalog、Backend Descriptor 和 13 项 Schema。
- 独立临时 venv、无源码 `PYTHONPATH`：SDK 导入通过。
- 已验收 `.cepack` 在临时 HOME/Store：install → activate → use → Backend
  entrypoint 加载 → Mapping Engine 静态加载 → deactivate → uninstall 全部通过。
- 该过程 `hardware_connected=false`，没有发送动作；原 `.cepack` 未被修改。

制品摘要（本轮修正后最终提交应重新构建并记录最终值）：

- 已验收 `.cepack`：
  `db776e0653717148a5969fed0d6b6e0f60e65715d9f06859017cc60263f86a1c`
- Package tree：
  `sha256:a62635c0bcdc21fc2c9afc153f37012227dc85bcef253945af1495cc06471519`
- Mapping：
  `4eb0a18c67f4ad88c9cae33029edb5dd9997b0b8a87d309906361771f0ea2040`

## 7. 冻结规则

内部 v0.1 冻结后：

1. `Robot.get_joint_state()` 和 `Robot.move_joints()` 的语义保持稳定。
2. Hardware Package Schema 的规范标识为 `hardware-package/v0.1`。
3. Capability Catalog 是标准词汇表；Backend Descriptor、Mapping 与验证记录决定
   实际支持范围。
4. Package Lifecycle 与 Onboarding Agent 保持可独立使用；安装现成 `.cepack`
   不触发模型调用。
5. 新协议优先进入 Backend 插件，新厂商字段进入 Package Mapping；不得在 SDK
   Core 添加厂商特判。
6. 没有真机证据的 Capability 不得因 Catalog、Schema 或可编译代码存在而声明为
   live verified。
