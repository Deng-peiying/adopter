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
- `schemas/onboarding/capability-coverage.schema.json`
- `schemas/onboarding/backend-support.schema.json`
- `schemas/mapping/interface-mapping-v1.schema.json`

## 职责边界

| 组件 | 责任 |
| --- | --- |
| Unified Robot SDK | 稳定的 Robot API、Action、State、CommandResult 与公共校验 |
| Onboarding Scanner | 静态识别 ROS2、Python、ELF/头文件、URDF/Mesh 和运行环境证据 |
| DeepSeek Onboarding Agent | 查询证据、提出 Capability 候选、判断缺口和选择可表达的映射 |
| Deterministic Matcher | 验证候选语义是否由引用的证据支持，拒绝缺字段或冲突 |
| Generator | 只根据已通过的 Coverage 和 Backend Fit 生成结构化文件 |
| Conformance Runner | 校验 Schema、编码/解码、错误、超时和实测到位语义 |
| Hardware Package | 保存厂商/型号绑定、端点、字段、依赖和证据来源 |
| Backend Transport | 执行通信机制；当前实现为 ROS2 subscription/action |

DeepSeek 没有 Shell、任意读文件、任意写文件、运动执行或验证等级提升工具。
它每轮只能返回一个允许的类型化调用：`list_evidence`、`get_evidence`、
`submit_candidate`、`assess`、`backend_fit`、`generate` 或 `validate`。
因此它负责语义推理，而扫描、校验、生成和测试仍由确定性代码执行。

## 隔离要求

第一次生成必须给出四类根目录：

1. 固定的平台根目录；
2. 一个或多个厂商原始资产根目录；
3. 新的 staging 输出目录；
4. 禁止读取的旧 Hardware Package 与旧 Demo 根目录。

`inspect` 会写入 `isolation-manifest.yaml` 和 `platform-lock.yaml`。禁止目录不能
作为生成证据；符号链接也不能逃逸根目录。旧映射只能在 L2 包完成、Conformance
通过并记录树摘要后，由独立评估器用于差异比较。差异不能静默复制回已封存产物。

## 确定性 L1/L2 命令

以下命令不调用 LLM，也不发送机器人动作。候选文件必须由人工评审或受限 Agent
根据 `interface-evidence.yaml` 生成；不能填写无法追溯的端点或字段。

```bash
cd ~/文档/for_robot_dpy/.worktrees/body-aware-robot-agent-mvp/cross-embody-sdk
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

RUN_ROOT=/tmp/ce-onboarding/weiyi-right-arm-new
VENDOR_ROOT=~/文档/for_robot_dpy/robot_launch
OLD_PACKAGE=~/文档/for_robot_dpy/.worktrees/body-aware-robot-agent-mvp/ce-hardware-weiyi-dual-o6
OLD_DEMO=~/文档/for_robot_dpy/.worktrees/body-aware-robot-agent-mvp/wy-dual-o6-demo

python3.10 -m cross_embodiment.cli onboard inspect \
  --vendor-root "$VENDOR_ROOT" \
  --platform-root "$PWD" \
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

评审后的 `candidates.yaml` 使用 `CapabilityCandidate` 结构：每项包含
`capability_id`、`evidence_ids` 和 `proposed_semantics`。随后执行：

```bash
python3.10 -m cross_embodiment.cli onboard assess \
  --run-root "$RUN_ROOT" \
  --scope "$RUN_ROOT/scope.yaml" \
  --candidates "$RUN_ROOT/candidates.yaml" \
  --json

python3.10 -m cross_embodiment.cli onboard generate \
  --run-root "$RUN_ROOT" \
  --identity "$RUN_ROOT/package-identity.yaml" \
  --json

python3.10 -m cross_embodiment.cli onboard validate \
  --run-root "$RUN_ROOT" \
  --json

python3.10 -m cross_embodiment.cli onboard report \
  --run-root "$RUN_ROOT" \
  --json
```

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

安装可选依赖并通过环境变量提供密钥；密钥不写入仓库、日志或 Agent 上下文：

```bash
python3.10 -m pip install -e '.[onboarding-agent]'
read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY; echo
export DEEPSEEK_API_KEY
```

确定性 `inspect` 完成后，调用程序构造 `DeepSeekProvider`、
`OnboardingGoal` 与同一个 `OnboardingWorkflow`：

```python
from pathlib import Path
from cross_embodiment.onboarding.agent import OnboardingAgent, OnboardingGoal
from cross_embodiment.onboarding.providers import DeepSeekProvider
from cross_embodiment.onboarding.workflow import OnboardingWorkflow

run_root = Path("/tmp/ce-onboarding/weiyi-right-arm-new")
workflow = OnboardingWorkflow(run_root, Path.cwd())
goal = OnboardingGoal(
    device_id="right_arm",
    capability_ids=("joint_position_state", "joint_position"),
    ordered_joints=tuple(f"arm.right.joint.{index}" for index in range(7)),
    identity_path=run_root / "package-identity.yaml",
)
result = OnboardingAgent(DeepSeekProvider(model="deepseek-chat")).run(goal, workflow)
print(result)
```

模型不是调用“一键生成脚本”。它需要逐项查询证据、提交两个 Capability
候选、读取确定性 Matcher 的拒绝原因、确认 Backend Fit，再调用生成和验证工具。
任何不受证据支持的语义都会在 `submit_candidate` 阶段被拒绝。

## L1、L2、L3

- **L1**：完成资产清单和接口证据矩阵。证明“发现了什么”，不证明映射或真机。
- **L2**：生成新包并通过离线 Conformance。证明文件契约及已覆盖的编码/解码行为。
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
