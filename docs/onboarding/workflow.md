# Hardware Onboarding 工作流

Hardware Onboarding 将厂商原始资产转换为可由固定 Unified Robot SDK
加载的 Hardware Package。它不修改 `Robot.get_joint_state()`、
`Robot.move_joints()`、Action/Command、Mapping Engine 或 Backend Protocol。

```text
厂商原始资产
  → Inventory / Evidence
  → Capability 语义匹配
  → Backend Fit
  → Hardware Package Generator
  → Offline Conformance
  → 显式 Package L3 验收
```

当前第一版只接入右臂 `joint_position_state` 与 `joint_position`。平台契约位于：

- `catalogs/capabilities/v0.1.yaml`
- `catalogs/backends/ros2_mapped_v0.1.yaml`
- `schemas/onboarding/asset-inventory.schema.json`
- `schemas/onboarding/interface-evidence.schema.json`
- `schemas/onboarding/evidence-contract.schema.json`
- `schemas/onboarding/capability-coverage.schema.json`
- `schemas/onboarding/backend-support.schema.json`
- `schemas/onboarding/interface-mapping-candidate.schema.json`
- `schemas/mapping/interface-mapping-v1.schema.json`

## 职责边界

| 组件 | 责任 |
| --- | --- |
| Unified Robot SDK | 稳定的 Robot API、Action、State、CommandResult 与公共校验 |
| Onboarding Scanner | 静态识别 ROS2、Python、ELF/头文件、URDF/Mesh 和运行环境证据 |
| DeepSeek Onboarding Agent | 审查确定性候选及证据、处理歧义、判断 Capability 与缺口 |
| Deterministic Matcher | 验证候选语义是否由引用的证据支持，拒绝缺字段或冲突 |
| Generator | 只根据已通过的 Coverage 和 Backend Fit 生成结构化文件 |
| Conformance Runner | 校验 Schema、编码/解码、错误、超时和实测到位语义 |
| Hardware Package | 保存厂商/型号绑定、端点、字段、依赖和证据来源 |
| Backend Transport | 执行通信机制；当前实现为 ROS2 subscription/action |

DeepSeek 没有 Shell、任意读文件、任意写文件、运动执行或验证等级提升工具。
一轮可以返回零个、一个或多个原生 Tool Call；Runtime 会处理完整批次并保持
call ID 与结果关联。允许的工具是 `list_evidence`、`get_evidence`、
`accept_deterministic_candidate`、`submit_candidate`、`record_conclusion` 和
`assess`。因此它负责语义判断，而扫描、字段装配、校验、生成和测试仍由确定性
代码执行。

## 隔离要求

第一次生成必须给出四类根目录。wheel 已内置固定平台资产，因此通常只需显式
提供厂商、输出与禁止读取目录；`--platform-root` 只在需要固定其他平台契约版本时
使用：

1. 固定的平台根目录；
2. 一个或多个厂商原始资产根目录；
3. 新的 staging 输出目录；
4. 禁止读取的旧 Hardware Package 与旧 Demo 根目录。

`inspect` 会写入 `isolation-manifest.yaml` 和 `platform-lock.yaml`。禁止目录不能
作为生成证据；符号链接也不能逃逸根目录。旧映射只能在 L2 包完成、Conformance
通过并记录树摘要后，由独立评估器用于差异比较。差异不能静默复制回已封存产物。

## 确定性 L1/L2 命令

以下命令不调用 LLM，也不发送机器人动作。Scanner 已唯一解析的字段由确定性
Builder 从 `interface-evidence.yaml` 装配；冲突或缺失字段不会被猜测。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'cross-embodiment[onboarding-agent]'

: "${VENDOR_ROOT:?set VENDOR_ROOT to the vendor asset directory}"
: "${RUN_ROOT:?set RUN_ROOT to a new onboarding output directory}"
: "${OLD_PACKAGE:?set OLD_PACKAGE to the denied historical package directory}"
: "${OLD_DEMO:?set OLD_DEMO to the denied historical demo directory}"

ce onboard inspect \
  --vendor-root "$VENDOR_ROOT" \
  --run-root "$RUN_ROOT" \
  --denied-root "$OLD_PACKAGE" \
  --denied-root "$OLD_DEMO" \
  --json
```

创建只含授权范围的 `scope.yaml`：

```yaml
device_id: right_arm
capability_ids: [joint_position_state, joint_position]
ordered_joints:
  - arm.right.joint.0
  - arm.right.joint.1
  - arm.right.joint.2
  - arm.right.joint.3
  - arm.right.joint.4
  - arm.right.joint.5
  - arm.right.joint.6
```

创建 `package-identity.yaml` 后执行：

```bash
ce onboard derive-candidates \
  --run-root "$RUN_ROOT" \
  --scope "$RUN_ROOT/scope.yaml" \
  --json

ce onboard generate-candidate \
  --run-root "$RUN_ROOT" \
  --identity "$RUN_ROOT/package-identity.yaml" \
  --json

ce onboard validate-candidate \
  --run-root "$RUN_ROOT" \
  --json

ce onboard report \
  --run-root "$RUN_ROOT" \
  --json
```

当所有 Runtime Completion Policy 具有明确来源并通过 Matcher 后，才使用
`generate` 与 `validate` 生成可运行包。策略仍未解决时，候选包没有 runtime
mapping、连接文件或可执行 Backend，且固定标记
`live_execution_ready: false`。

`package-identity.yaml` 只定义包身份、设备和 Backend，例如：

```yaml
package_name: weiyi/dual_o6_agent_generated
version: 0.1.0
vendor: weiyi
model: dual_o6
device_id: right_arm
embodiment_type: single_arm
backend_id: ros2_mapped
backend_entrypoint: cross_embodiment.driver.ros2_mapped:MappedRos2Adapter
ros_distro: humble
os: linux
arch: x86_64
```

退出码区分资产不足、语义冲突、Backend 缺口、Schema 失败和 Conformance
失败。`motion_sent` 在 L1/L2 始终为 `false`。

## DeepSeek 编排

安装可选依赖。Provider 优先读取 `DEEPSEEK_API_KEY`；也可通过
`CROSS_EMBODIMENT_DEEPSEEK_CREDENTIAL_FILE` 指定本地、Git 忽略的凭据文件。凭据不进入
wheel、sdist 或 Hardware Package：

```bash
python -m pip install 'cross-embodiment[onboarding-agent]'
install -d -m 700 "$HOME/.config/cross-embodiment"
cat > "$HOME/.config/cross-embodiment/deepseek_credentials.py" <<'PY'
DEEPSEEK_API_KEY = "replace-with-local-key"
PY
chmod 600 "$HOME/.config/cross-embodiment/deepseek_credentials.py"
export CROSS_EMBODIMENT_DEEPSEEK_CREDENTIAL_FILE="$HOME/.config/cross-embodiment/deepseek_credentials.py"
```

凭据文件只允许一个字面量 `DEEPSEEK_API_KEY` 赋值；Provider 用 AST 读取该
赋值，不执行文件内容。密钥不会写入 Provider transcript 或 Agent 上下文。

确定性 `inspect` 和 `derive-candidates` 完成后，只使用正式 CLI：

```bash
ce onboard agent \
  --run-root "$RUN_ROOT" \
  --identity "$RUN_ROOT/package-identity.yaml" \
  --device right_arm \
  --capability joint_position_state \
  --capability joint_position \
  --joint arm.right.joint.0 \
  --joint arm.right.joint.1 \
  --joint arm.right.joint.2 \
  --joint arm.right.joint.3 \
  --joint arm.right.joint.4 \
  --joint arm.right.joint.5 \
  --joint arm.right.joint.6 \
  --provider deepseek \
  --model deepseek-chat \
  --json
```

模型不是调用“一键生成脚本”。它需要审查候选及其 Evidence ID，对两项
Capability 分别形成 `mapped`、`gap`、`unsupported` 或 `unknown` 结论。
确定性 Runtime 在结论完成后执行 Backend Fit、候选/运行包生成和对应
Conformance。任何不受证据支持的替代语义仍会在 `submit_candidate` 阶段被拒绝。

## L1、L2、L3

- **L1**：完成资产清单和接口证据矩阵。证明“发现了什么”，不证明映射或真机。
- **L2 Candidate**：接口字段已映射、缺口已记录、非执行候选包通过静态
  Conformance；不代表真机执行就绪。
- **L2 Runtime**：完成策略也已解析，生成运行包并通过离线运行语义
  Conformance。证明文件契约及已覆盖的编码/解码行为。
- **L3**：显式加载新包读取真机状态，并在现场授权后完成一次目标和返回。

L3 的三个终端、精确目标文件、确认词和证据记录见
[`weiyi-l3-runbook.md`](weiyi-l3-runbook.md)。

## 当前 Backend 事实

`ros2_mapped` 当前只声明 `ros2_subscription` 和 `ros2_action`，并只表达
`joint_state` 与 `joint_position` 映射。发现以下机制时生成缺口报告，而不会
冒充支持：`ros2_service`、`ros2_publisher`、`python_call`、`native_call`、
`raw_can`。后续应在真实厂商案例需要时实现并验证相应 Backend 插件。

厂商源码不完整不等于不可接入。若已有二进制 Driver 能在匹配的 OS、CPU、ABI、
ROS 和依赖环境中运行，Hardware Package 可以声明并复用该外部 Runtime；验证等级
仍必须按 L1/L2/L3 单独记录。
