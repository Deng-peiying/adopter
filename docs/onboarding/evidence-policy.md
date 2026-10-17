# Hardware Onboarding 证据策略
Onboarding 只根据可追溯资产生成 Capability 结论。统一接口补全是把已存在且证据
充分的厂商能力绑定到固定语义，不是推测或发明硬件能力。

机器可读契约包括：

- `schemas/onboarding/asset-inventory.schema.json`
- `schemas/onboarding/interface-evidence.schema.json`
- `schemas/onboarding/capability-coverage.schema.json`
- `schemas/onboarding/backend-support.schema.json`
- `schemas/mapping/interface-mapping-v1.schema.json`
- `catalogs/capabilities/v0.1.yaml`
- `catalogs/backends/ros2_mapped_v0.1.yaml`

## EvidenceLevel

| 等级 | 含义 | 不能证明的内容 |
| --- | --- | --- |
| `declared` | 源码、接口定义、配置、文档或二进制静态声明 | 端点正在运行、真机动作成功 |
| `observed` | 工具在受限环境中观察到结构或行为证据 | 完整运行生命周期或真机完成 |
| `runtime_read` | 只读运行时图或状态已实测 | 动作接受、终态或到位 |
| `hardware_motion` | 有独立运动执行记录 | 记录范围之外的能力 |

同一 URDF 的 FK/IK 自洽只能支持模型内的 `derived` 结论，不能自动证明真机安装、
实时控制、碰撞安全或运动完成。

## CapabilityAssessment 状态

- `native`：厂商接口直接提供规范能力，必要字段、单位、顺序和生命周期证据齐全。
- `derived`：由已验证基础状态和确定性工具推导，必须注明推导链和限制。
- `unsupported`：证据明确显示当前资产或接口不能提供该语义。
- `unknown`：证据缺失、矛盾或不足，不能据此宣称不支持或支持。

这些状态与集成进度分开。每个 Capability 同时记录：

```text
discovered
backend_expressible
mapped
offline_verified
runtime_read_verified
hardware_motion_verified
```

只有外部 `L3ExecutionRecord` 存在时才能设置
`hardware_motion_verified=true`，并必须保存对应 record ID。模型、人工文字或
离线测试不能自行提升验证等级。

## 证据引用与冲突

每个 `CapabilityCandidate` 必须列出 `evidence_ids`。Matcher 只接受这些 ID 指向
的结构化 claim，不接受模型总结中的新端点、字段、单位、频率或默认值。

以下差异必须形成冲突或缺失项，而不能自动选择：

- 关节数量、规范名称或厂商顺序不同；
- radian/degree、位置/速度/力矩单位不明；
- Topic/Service/Action 类型或 endpoint 不一致；
- Base/Tip/目标坐标系未定义；
- Action 接受、终态、错误码、取消、超时、实测到位语义不完整；
- 运行平台、ABI 或依赖与二进制不兼容。

`.msg`、`.srv`、`.action` 类型存在只证明接口类型存在。二进制中的字符串只能形成
endpoint candidate。必须通过源码使用、Launch/配置或只读运行时图增加端点证据。

## Capability 与 Backend 分离

“厂商有接口”与“平台能执行该接口”是两件事。例如扫描器可以发现 ROS2 Service、
Python 方法或 CAN 协议，但当前 Backend 只支持：

- `ros2_subscription`
- `ros2_action`

当前明确排除：

- `ros2_service`
- `ros2_publisher`
- `python_call`
- `native_call`
- `raw_can`

发现排除机制时生成 `BackendPluginRequirement`，记录缺失机制、生命周期、证据和
最低测试要求。第一版不自动生成这些 Backend。

## 生成与验证边界

Generator 只消费无冲突、状态为 `native` 或 `derived`、且 Backend Fit 成功的
Coverage。生成文件保留每项 Capability 的证据 ID 和未映射证据清单。

Offline Conformance 验证：

1. Package/Mapping Schema 和资产摘要；
2. 显式生成目录解析，无旧包 fallback；
3. canonical state decode；
4. 完整关节目标 encode；
5. vendor failure、timeout/outcome uncertainty；
6. ROS Action 终态加新鲜实测到位。

它不发送真机动作，也不把 `offline_verified` 提升为
`runtime_read_verified` 或 `hardware_motion_verified`。

## Agent 边界

DeepSeek 可以选择证据、提出语义候选和判断缺口。它不能：

- 访问任意路径或旧答案；
- 执行 Shell 或厂商程序；
- 任意写文件；
- 创建不存在的厂商接口；
- 提升验证等级；
- 发送运动命令。

旧 Hardware Package 与 Demo 在第一次生成期间属于 denied roots。L2 封存后，
独立评估器可以比较旧答案，但必须列出差异、依据和处置；不能修改原 L2 摘要后
仍把它称为同一产物。

## 发布判断

L1 通过表示资产识别完成；L2 通过表示新包离线契约成立；L3 通过只表示该包在
指定硬件、Runtime 和测试目标上完成真机闭环。单个 Weiyi ROS2 案例不能证明
Python、C/C++、CAN/TCP、串口或其他机器人已经通用化。

# Evidence Contract

The versioned shared contract is defined by
`schemas/onboarding/evidence-contract.schema.json` and implemented by
`src/cross_embodiment/onboarding/evidence_contract.py`. Candidate fields,
required facts, allowed evidence types, deterministic normalization rules, and
platform-owned values are defined there once. The ROS2 scanner emits the claim
names and field provenance described by that contract; the matcher queries the
same contract; the onboarding Agent receives its structured export.

Transport vocabulary and SDK semantics remain distinct. For example, a
`ros2_subscription_usage` record proves the transport operation `subscribe`.
When the Capability Catalog has one canonical operation for
`joint_position_state`, the deterministic contract can normalize that evidence
to `joint_state`. It does not permit an unobserved operation such as `publish`.

## Candidate Hardware Package

Vendor interface mapping and Runtime Completion Policy have separate states.
The deterministic builder may establish `mapping_complete: true` while
`timeout_s`, `arrival_tolerance_rad`, and `settle_window_s` remain unresolved.
Those values are caller/runtime policy unless a vendor declaration, explicit
operator configuration, or validated test policy supplies them.

`ce onboard generate-candidate` therefore creates an auditable, non-executable
package when both interfaces are mapped but completion policy remains open.
The candidate has no runtime mapping asset, connection file, backend
entrypoint, or runtime defaults. `ce onboard validate-candidate` checks its
schema, evidence, policy gaps, digests, and isolation, while keeping
`live_execution_ready: false`.

DeepSeek reviews deterministic candidates, cites supporting Evidence IDs, and
records semantic decisions or gaps. It is not required to transcribe facts
that the Scanner has already normalized without ambiguity. Ambiguous or
conflicting facts still require an Agent decision or remain unresolved.
