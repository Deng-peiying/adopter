# GitHub 发布边界审计：Unified Runtime + Onboarding Agent + Package Lifecycle

日期：2026-10-16
分支：`feature/body-aware-robot-agent-mvp`
审计基线提交：`3572c9ffd8776019a8e0a8628dc8c53adb086071`
发布实现提交：`4cf596f`；发布文档提交：`5eccb1d`
状态：本地发布候选；未 Push、未合并、未创建 PR

## 1. 发布产品边界

同一个 `cross-embodiment` wheel 必须包含三部分：

1. **Unified Robot Runtime**：统一 `Robot.get_joint_state()`、`Robot.move_joints()`、Mapping、Backend Protocol 与运行反馈。
2. **Hardware Onboarding Agent**：Scanner、Evidence、Matcher、DeepSeek Provider、Backend Fit、Generator 与 Conformance。
3. **Hardware Package Lifecycle**：`.cepack` 的 build、install、list、inspect、activate、use、deactivate 与 uninstall。

### 模式 A：已有 Hardware Package

`.cepack` 由 Package Store 校验、安装、激活并解析为运行描述。该流程不导入 DeepSeek Provider，不读取厂商 Mapping 源码，也不运行 Onboarding。厂商 Runtime、连接、启动和使能仍由部署环境负责。

### 模式 B：只有厂商原始资产

安装 `cross-embodiment[onboarding-agent]` 后，SDK 从原始资产建立 Inventory 与 Evidence，生成确定性候选，由 DeepSeek 通过六个类型化工具完成证据审阅和终态判断，再进行 Backend Fit、Package 生成和 Conformance。运行策略与真机运动仍需操作者明确确认。

Weiyi 已验证“已有 ROS2 Backend + 自动 Mapping + Package + L3”。Python SDK、C/C++ Library 和全新 Backend 插件的自动代码生成、编译、注册与真机执行尚未验证。

## 2. 审计发现及修复

| 项目 | 审计前 | 本地候选修复 | 结论 |
|---|---|---|---|
| Onboarding Python 模块 | wheel 已包含 | 无需修改 | 通过 |
| Catalog / Backend Descriptor / Schema | 依赖源码树和显式 `--platform-root` | 15 个通用平台资产随 wheel 分发；CLI 默认使用 wheel 资源 | 通过 |
| wheel 外运行 Onboarding | `PlatformLock` 强制执行 `git rev-parse` | 非 Git 安装使用 distribution version + 平台资产摘要 | 通过 |
| 根目录 ROS package 接口限定名 | 根目录 `package.xml` 未参与限定名解析 | Scanner 查找范围包含 vendor root | 通过 |
| 通用 Capability Catalog | 两项能力含 `weiyi_right_arm_v0` 标签 | 移除厂商 profile 标签 | 通过 |
| 模式 A 的 DeepSeek 依赖 | CLI 已按子命令延迟导入 | 新 wheel 验证 `providers` 与 `openai` 均未加载 | 通过 |
| Backend 缺失 | 已产生 `BackendPluginRequirement` | 验证 Python/Native 返回插件缺口和最低测试，不伪造 fit | 通过 |
| 新 Backend 自动代码生成 | 仅有扩展边界 | 未新增功能 | **未实现/未验证** |

## 3. 实际代码边界

### Unified Robot Runtime

- 统一 API：`src/cross_embodiment/sdk/robot.py:57`，状态读取位于 `:73`，关节目标位于 `:81`。
- Mapping Engine：`src/cross_embodiment/mapping/engine.py:65`。
- 通用 Transport 契约：`src/cross_embodiment/backend/protocol.py:11` 和 `:49`。
- ROS2 映射 Backend：`src/cross_embodiment/driver/ros2_mapped.py:21`。
- 动态 Backend 入口：`src/cross_embodiment/driver/backend.py:10`。

### Hardware Onboarding Agent

- Inventory：`src/cross_embodiment/onboarding/inventory.py:55`。
- ROS2 Scanner：`src/cross_embodiment/onboarding/extractors/ros2.py:679`。
- 确定性候选：`src/cross_embodiment/onboarding/candidate_builder.py:89`。
- Matcher：`src/cross_embodiment/onboarding/capability.py:120`。
- Backend Fit 与插件缺口：`src/cross_embodiment/onboarding/backend_fit.py:36`、`:66`。
- 类型化工具与 DeepSeek Provider：`src/cross_embodiment/onboarding/providers.py:71`、`:137`。
- Agent Orchestrator：`src/cross_embodiment/onboarding/agent.py:164`。
- Generator：`src/cross_embodiment/onboarding/generator.py:73`。
- Conformance：`src/cross_embodiment/onboarding/conformance.py:103`。
- 工作流：`src/cross_embodiment/onboarding/workflow.py:155`。

六个模型工具为：`list_evidence`、`get_evidence`、`submit_candidate`、`accept_deterministic_candidate`、`record_conclusion`、`assess`。它们不提供 Shell 或任意文件写权限。

### Hardware Package Lifecycle

- 生命周期实现：`src/cross_embodiment/package/lifecycle.py:204`。
- install：`:251`；list：`:299`；inspect：`:311`；activate：`:315`；use 解析：`:372`；deactivate：`:420`；uninstall：`:429`。
- CLI 注册：`src/cross_embodiment/cli/__init__.py:343` 起。
- install/activate/use 仅操作文件与 Registry；硬件连接只在显式 preflight/accept-l3 路径发生。

## 4. wheel 资产审计

本地候选 wheel 包含：

- Runtime Robot API、Mapping、Backend Protocol、ROS2 Mapped Adapter。
- 完整 Onboarding Python 模块。
- DeepSeek Provider 与类型化工具定义。
- Capability Catalog 1 份、Backend Descriptor 1 份、JSON Schema 13 份。
- Package Lifecycle。

wheel 不包含：

- Weiyi endpoint、消息类型、MoveJ、固定七轴或 `dual_o6` 字符串。
- 测试 fixture、Weiyi Reference Case、历史 Mapping、Demo。
- DeepSeek 凭据或 `.env`。

源码发布范围 `src/cross_embodiment/`、`catalogs/`、`schemas/` 对上述 Weiyi 专有字符串的扫描结果同样为空。仓库中的 Weiyi 文档和测试 fixture 仅作为外部验证资料；wheel 不分发它们，Onboarding 隔离策略也不将其作为 vendor evidence root。

## 5. 本地发布候选验证

本地审计制品目录：`release-candidates/cross-embodiment-0.1.0-rc1`（不纳入 SDK
源码仓库）。

### 模式 A

在新虚拟环境中从 wheel 安装 SDK，使用已验收 `.cepack` 执行 install、activate、use：

- `exit_code=0`
- `hardware_connected=false`
- Store 中的 package tree digest 已校验
- `cross_embodiment.onboarding.providers` 未加载
- `openai` 未加载

该验证没有连接、启动、使能机器人，也没有发送动作。

### 模式 B

在同一新虚拟环境中，不设置源码 `PYTHONPATH`，且不传 `--platform-root`：

- 从原始 `robot_launch` 扫描 838 个资产、形成 489 条证据。
- `joint_position_state`：`candidate_valid=true`、`interface_mapped=true`。
- `joint_position`：`candidate_valid=true`、`interface_mapped=true`，保留 `timeout_s`、`arrival_tolerance_rad`、`settle_window_s` 三项运行策略缺口。
- 生成不可执行 Candidate Hardware Package。
- Candidate Conformance 7/7 通过，`live_execution_ready=false`、`motion_sent=false`。
- DeepSeek Provider、Agent、Generator、Backend Fit 均从 site-packages 导入；Provider 用禁止网络的假客户端构造，未再次调用模型。

已有的真实 DeepSeek Gate D 与 Weiyi L3 仍是独立历史证据。本次验证只证明发布 wheel 完整保留该执行路径，没有用重复模型调用替代发布审计。

### 缺失 Backend

用 wheel 内置 Backend Descriptor 评估：

- `ros2_action` 匹配 `ros2_mapped`。
- `python_call` 与 `native_call` 均无 fit，并生成带 evidence IDs 和最低 Conformance 要求的 `BackendPluginRequirement`。

这证明系统会报告缺口；尚未证明它能自动实现插件。

### 测试

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src ... python -m pytest -q`

结果：`224 passed in 12.22s`。

### Git 源码与制品复现

从提交 `5eccb1d3046278a49ce02f391ce197b48f6b4c72` 创建全新本地 clone，使用
`setuptools 83.0.0` 和 `python -m build --no-isolation` 构建：

- wheel SHA-256：`c6a7bed9dba992b266d03bc5fba56599f8c5bd872cc86c0ec3aa2f14532514b1`
- sdist SHA-256：`265104897c5f692de30321fc241ecbee73b141ae21df1d5325cda5e3be623083`

构建前工作树为 clean，未使用源码 `PYTHONPATH`。此前 rc1 wheel 与最终重建 wheel
的 88 个成员中，只有构建工具写入的 `WHEEL` 和随之变化的 `RECORD` 不同；SDK
模块和平台资产内容相同。发布候选已替换为从固定提交重建的制品。

wheel、sdist 和源码目录分别安装到三个全新虚拟环境后，三者均确认：

- `cross-embodiment==0.1.0`
- 1 份 Capability Catalog
- 1 份 Backend Descriptor
- 13 项 JSON Schema
- Robot API、Mapping Engine、Ros2Transport、Onboarding Agent、Provider、Generator
  和 Package Lifecycle 模块均可定位
- `ce package list` 与 `ce onboard inspect --help` 可运行

此外，从干净 clone 做源码安装后，使用已验收 `.cepack` 完成 install、activate 和
use。三步均返回 `hardware_connected=false`，运行描述中的 package root 位于全新
Store，未引用 Clean-Room 输出目录或旧 Registry。

## 6. 可复用范围与已知限制

可直接复用：Robot API、Action/Command、Mapping Engine、Backend Protocol、Package Lifecycle、Inventory/Extractor 框架、Evidence Contract、Matcher、Agent Tool Calling、Generator、Conformance、Package Store。

新厂商必须重新提取：端点或函数、类型和字段、关节顺序与单位、生命周期、错误语义、Runtime 依赖、模型/Frame、运行策略来源以及真机证据。

需要 Backend 插件的情况：现有 Backend Descriptor 无法匹配 transport kind 或 binding operation。当前可输出结构化缺口，并通过 `BackendTransport` 与动态 entrypoint 接入实现；自动生成实现代码的工作流尚未落地。

当前 Agent CLI 第一版仍明确限定 `joint_position_state` 与 `joint_position`，可执行 Backend 只验证 `ros2_mapped`。这属于已声明的范围限制，不应对外表述为任意 Capability 或任意通信协议已自动接入。

## 7. GitHub 公开发布判定

**本地发布候选验证通过；公开发布仍有一个治理阻塞项：许可证。**

仓库没有顶层 LICENSE，wheel METADATA 也没有 SPDX/license 字段。公开发布前需要项目所有者选择许可证并补充 `pyproject.toml` 元数据。审计未代替所有者选择许可证。

Python/C++ Backend 自动生成未验证是产品能力限制，需要在 Release Notes 中明确，但不会阻止发布当前已验证的 ROS2 Mapping/Package 平台。

## 8. 建议提交到 `dpy` 的内容

远端 `origin/dpy` 当前为 `89abcf9`，是本分支 HEAD 的祖先，因此发布时可正常
fast-forward，不需要 force push。待许可证和所有者授权完成后，应提交完整分支历史至
最终发布审计提交，至少包括：

1. `5db8bd4..3572c9f`：Onboarding、Gate D/E、Package Lifecycle 和 Installed
   Package L3 的既有实现历史。
2. `4cf596f`：将 Catalog、Backend Descriptor、13 项 Schema 随 wheel 分发，并
   支持 wheel 外 Git 环境的 Onboarding。
3. `5eccb1d` 及其后的发布审计文档提交：模式 A/B README、许可证清单、包含/排除
   Manifest 和全新 clone 复现步骤。
4. 项目所有者后续明确选择许可证后新增的 LICENSE、包元数据与 Release Notes 提交。

不应提交：`release-candidates/`、本地 Distribution Kit、`.cepack`、厂商 Runtime、
原始 Gate transcript、凭据、虚拟环境和缓存。wheel/sdist 作为 GitHub Release
artifacts 上传，不进入源码 Git 历史。
