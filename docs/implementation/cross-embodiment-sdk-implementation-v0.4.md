# Cross-Embodiment SDK v0.4 Implementation

**日期：** 2026-10-21  
**状态：** 实施说明与验收清单；未勾选项不代表已完成  
**设计基线：** [v0.4 正式设计](../architecture/cross-embodiment-sdk-design-v0.4.md)  
**目标：** 将 SDK 通用契约、包内具体 Adapter、通用通信及运行环境的边界落实为一致的 API、包入口、CLI 和验证流程。

本文面向实施者，描述应改哪些模块、当前有哪些基础、剩余工作如何验收。它不执行 SDK 重构、硬件包发布或现场控制，也不以文档版本代替 Python 发行版本和包版本。

## 1. 实施范围

v0.4 基础交付完成包内 Adapter 路径、初始化/连接/使能分离、Transport 与厂商映射分离、资源所有权、统一实例与 Project 路径，以及能力与验证状态的可信表达。

保留 v0.3 的 Policy、EE/Joint、Registry、资产、Lock、Project、Runtime、平台和性能矩阵设计。这些模块按既有职责继续维护，不因本轮重构被删除，也不要求本轮实现整个长期平台。

完整 Adapter Host 作为 P9 后续独立里程碑；基础版本清楚标注当前只有 Transport IPC。M20 的机身运动、归一化输入与物理速度转换尚未定案，本实施范围不新增其具体适配代码或冻结相关协议。

### 全局约束

- SDK Core 只放通用契约与机制；厂商报文、模式、错误码和映射代码放硬件包。
- `Robot.__init__()` 内部 configure；不增加公开 `Robot.configure()`。
- 构造、静态检查、build/install/activate 不连接硬件或启动 Driver。
- connect、enable、disable、stop 动作和 close 分别定义；close 不隐式下电。
- `allow_motion` 是运动授权；不能替代控制器使能或实测 READY。
- 不保留旧导入转发、SDK 内置 YAML Adapter 或 YAML 映射执行引擎。
- `runtime/mapping.py` 保留为策略和跨本体转换模块。
- 包内代码、脚本和影响行为的配置参与摘要；已安装包不可变。
- SDK 基础 Python 下限保持 `>=3.10`；ROS/WY 的 Python 3.10 和 ROS 2 Humble 是该后端要求，不是所有后端要求。
- 缺失、未知和未验证分别表达，不用零值、成功应答或本地历史伪造硬件事实。
- 开发验收使用离线替身和受控子进程；实机连接、使能和运动另行明确授权。

## 2. 当前实现基线

以下由源码检查得到，不是本次测试通过报告。

| 模块 | 已有基础 | 主要差距 |
|---|---|---|
| `sdk/robot.py`、`sdk/lifecycle.py` | 构造内部 configure、独立 connect、显式 enable/disable、资源 close | Lifecycle 仍有 stop 复合入口；CLI 和测试替身尚未全部对齐 |
| `adapter/` | Protocol、包资源 Context、HealthReport、Mock | 契约验收、能力声明与未实现操作需保持一致 |
| `package/loader.py` | 仅允许包内入口，按包根区分模块命名空间 | 需覆盖多版本、路径越界、失败导入和依赖错误 |
| `runtime/installed.py` | 激活实例解析、摘要/后端检查和断开状态工厂 | 仍有 `mapping_path` / `interface_mapping` 专用元数据约束 |
| `transport/` | 通用请求/事件/结果与 ROS 2 订阅、Action、Service | 数组转换、错误边界、状态与结果需系统回归 |
| `driver_host/` | 子环境、进程组、Transport IPC、日志通道分离 | 完整 Adapter IPC 未实现；失败清理和异常传播需验收 |
| `onboarding/` | Inventory、Evidence、Catalog、骨架生成与检查 | 运行包产物仍是骨架；存在旧 Mapping 资产专用路径 |
| `cli/` | Project 和 Package 命令族 | `_up/_host` 仍有 ROS 注入、管理选项覆盖、等待 ready 和 stop 清理等旧行为 |
| WY 外部硬件包 | 包内映射、生命周期、原始资产、受管/外部 Driver | 下电与停止证据不足；实测反馈有效性仍需现场确认 |

`pyproject.toml` 当前发行版本并非 0.4；正式设计和本实施说明的创建不会自动改变发行版本。

## 3. 文件与责任分配

| 位置 | 责任 | 实施方式 |
|---|---|---|
| `src/cross_embodiment/sdk/` | 应用 API、生命周期调度 | 收敛单一资源状态，移除旧复合入口 |
| `src/cross_embodiment/adapter/` | Adapter 契约、包资源上下文、健康报告 | 固定无副作用配置与明确不支持行为 |
| `src/cross_embodiment/transport/` | 通信请求、响应、事件和 ROS 2 机制 | 保持厂商中立，补序列化与失败边界 |
| `src/cross_embodiment/driver_host/` | 环境、进程所有权、当前 Transport IPC | 修正回滚与退出行为；后续独立增加 Adapter Host |
| `src/cross_embodiment/package/` | 解析、安装、入口、摘要和激活 | 只接受包内实现；移除旧执行器假设 |
| `src/cross_embodiment/runtime/` | 实例构造、策略映射、安全 | 实例和 Project 共享解析规则，保留策略转换 |
| `src/cross_embodiment/onboarding/` | 证据、包生成和能力验收 | 明确骨架等级；生成有证据支持的具体代码 |
| `catalogs/`、`schemas/` | 平台标准描述 | 与发行包内 `onboarding/platform/` 资源同步 |
| `ce-hardware-*/adapters/` | 厂商资产使用、映射、状态和命令确认 | 由各硬件包实施，Core 不放厂商分支 |
| 用户项目 | Instance、任务和应用级检查 | 依赖 SDK 与硬件包，不注入厂商运行时路径 |

## 4. 实施顺序与交付项

依赖顺序：**P1/P2 → P3/P4 → P5/P6/P7 → P8**。P9 独立推进。已有模块先用失败用例固定差距，再完成最小修改，不重复重写已满足契约的代码。

### P1：统一 Robot、Lifecycle 与停止语义

**设计对应：** 第 8、18、34、36 节。  
**主要文件：** `sdk/robot.py`、`sdk/lifecycle.py`、`adapter/protocol.py`、`adapter/mock.py`、`runtime/mapping.py`、`runtime/safety.py`。

**接口决策：**

- 保留 `Robot.from_instance(instance_id, *, store=None, allow_motion=False)`。
- `Robot.connect() -> Robot`，`Robot.close() -> None`；二者委托 Lifecycle。
- `Lifecycle.configure/connect/enable/disable/close() -> None`。
- 删除 `Lifecycle.stop()`，不增加 start/stop 兼容别名。
- 运动停止采用 `Action(ActionSpec(type="stop", target=device_id, dimension=0), {})`；Mapper 转为 `Command(device_id, "stop", {})`。仅声明并实现此能力的 Adapter 接受。
- 停止动作走独立校验分支：连接与能力必须有效，不因 `allow_motion=False`、未使能、状态过期或故障而自动阻断请求；不能借此绕过任意普通运动授权。

**步骤与验收：**

- [ ] 先补失败用例：初始化无进程/网络/环境副作用；配置失败不返回句柄；重复 configure/connect/close 幂等。
- [ ] 生命周期操作串行化或明确拒绝冲突；enable/disable 成功后才更新本地记录，重复调用重新核查硬件。
- [ ] connect 失败由 Adapter 清理部分资源；close 不调用 disable，清理失败时仍尝试后续 owned 资源并保留错误。
- [ ] 将 CLI 和测试替身迁移到明确接口，不为旧替身增加生产代码回退。
- [ ] 补停止能力的支持/不支持、控制门禁、状态故障、未知结果用例；不把 cancel/发零请求算成实测停止。

**验证文件：** `tests/unit/test_adapter_lifecycle.py`、`test_robot_joint_api.py`、`test_action_mapping.py`、`test_safety.py`；新增 `tests/unit/test_motion_stop.py` 覆盖独立停止动作。

### P2：包内入口、资源与实例解析

**设计对应：** 第 6—8、10—14、18、43 节。  
**主要文件：** `package/loader.py`、`package/manifest.py`、`package/lifecycle.py`、`runtime/installed.py`、`adapter/context.py`、`hardware/instance.py`。

**步骤与验收：**

- [ ] 补包内入口、非法模块名、绝对/越界路径、导入失败、同名包多版本并存用例；拒绝旧 `cross_embodiment.driver...` 入口。
- [ ] Package Manifest 的 `entrypoint` 必须指向包内具体实现；不由 Backend 的 ROS/native 标签选择 SDK 内置厂商类。
- [ ] 移除 Runtime 对 `mapping_path` 和 `interface_mapping` slot 的强制配对；映射证据按通用资产保存，不触发 Core 控制解释。
- [ ] RuntimeInfo 保留实例、包版本/摘要、Manifest、Backend 和控制授权；删除仅服务旧 YAML 执行器的元数据字段和测试依赖。
- [ ] 对齐 `lock_version: v0.1` 的 Backend ID 和资产 Variant 列表布局，拒绝把旧概念示例的 Backend 对象当成另一套格式；Policy/Runtime 尚未锁定时如实记录缺口。
- [ ] 验证 Adapter 代码、环境/启动脚本和配置摘要；修改已安装内容必须被拒绝，新版本安装和激活不改旧版本。
- [ ] 明确配置优先级：包默认配置 → Instance 覆盖 → 平台保留的经验证资源字段；禁止 Instance 改写包根或入口逃逸。
- [ ] 纯 Python 运行 `from_instance()` 构造与 close，不建立连接；证明实例解析本身不加载 ROS 通信运行时。

**验证文件：** `test_installed_runtime.py`、`test_v04_adapter_boundary.py`、`test_package_models.py`、`test_package_lifecycle.py`、`tests/integration/test_package_lifecycle_cleanroom.py`。

### P3：通用 Transport 和消息边界

**设计对应：** 第 8、9、19、31 节。  
**主要文件：** `transport/protocol.py`、`transport/ros2.py`、`driver_host/transport.py`、`driver_host/worker.py`。

**固定边界：**

- `TransportRequest` 携带 binding/backend/kind/endpoint/interface/payload/timeout。
- `TransportEvent` 携带 binding/kind/payload/received_at。
- `TransportResult` 记录通信阶段、派发、接收、错误与取消信息；由 Adapter 决定硬件意义。

**步骤与验收：**

- [ ] 用真实数组对象复现序列化问题，覆盖 ROS sequence、固定数组、NumPy 标量/数组、嵌套消息及空数组；Core 不新增 NumPy 强依赖。
- [ ] 覆盖订阅、服务和 Action 的可用性、拒绝、反馈、终态、超时与取消；返回的未知值不伪装为成功。
- [ ] 覆盖事件回调异常的传播，不能仅在后台线程崩溃后让调用者看到不相关超时。
- [ ] 验证请求 ID、事件、错误与超时的关联；Host 写出前死亡返回未派发，写出后失联返回结果未知。
- [ ] 证明 Transport 没有厂商关节名、模式值、成功码或特定端点分支。

**验证文件：** `test_backend_transport_protocol.py`、`test_ros2_action_transport.py`、`test_ros2_service_transport.py`、`test_ros2_plain_payload.py`、`test_hosted_transport.py`。

### P4：环境隔离、进程所有权与关闭

**设计对应：** 第 9、34、36 节。  
**主要文件：** `driver_host/environment.py`、`process.py`、`transport.py`、`worker.py`。

**步骤与验收：**

- [ ] 初始化仅构造 `EnvironmentSpec`；连接时在子环境执行包内脚本，父进程 env、`sys.path` 和依赖不被修改。
- [ ] 明确 external/managed 的所有权；外部 Driver 不被终止，受管资源按实例记录。
- [ ] 覆盖启动失败、部分连接失败、重复关闭、Driver 提前退出和退出竞态；不遗留拥有的进程组、线程、管道或文件描述符。
- [ ] 控制协议与 Python/native 日志分离；异常保留主错误和清理错误，不覆盖原始原因。
- [ ] 文档和诊断准确显示当前为 Transport Host；不能把 worker 的通信 RPC 描述为完整 Adapter 生命周期隔离。

**验证文件：** `test_process_supervisor.py`、`test_hosted_transport.py`，必要时增加 `test_driver_environment.py`。

### P5：Onboarding、能力证据和具体映射生成

**设计对应：** 第 16、17、25、31 节。  
**主要文件：** `onboarding/generator.py`、`conformance.py`、`backend_fit.py`、`workflow.py`、`templates/ros2_adapter.py`、Catalog 和 Schema。

**步骤与验收：**

- [ ] 将“生成骨架”“具备离线实现”“具备已验证硬件能力”分级；骨架 `supports_action=False`、`health.ready=False`、必要操作明确未实现。
- [ ] 修正当前 `runtime_package_generated` 等字段的组合校验，防止骨架仅因完整方法名和 Mapping YAML 就通过运行能力预检。
- [ ] 对证据充分的模板生成包内编解码和结果处理；证据不足的操作保留 unknown，不以默认字段或猜测模式生成硬件命令。
- [ ] 清理 Conformance 对某个 Mapping slot 的执行语义依赖；保留证据追溯，不调用已删除引擎。
- [ ] 明确 Catalog 能力 ID 与设备 token 的对照，例如 `joint_position_state` / `joint_state`；Profile 不将未实现能力暴露为当前可执行动作。
- [ ] 修改根目录 `catalogs/`、`schemas/` 后同步发行包内 `onboarding/platform/` 和生成器自身 schema，校验安装后资源可用。

**验证文件：** `tests/onboarding/test_package_generator.py`、`test_conformance_runner.py`、`test_backend_fit.py`、`test_evidence_contract.py`、`test_onboarding_schemas.py`、`test_capability_matching.py`。

### P6：统一 Project CLI 的启动和关闭闭环

**设计对应：** 第 12—14、18、23、32、34 节。  
**主要文件：** `cli/__init__.py`，可新增 `runtime/shutdown.py` 承载通用关闭编排，避免 CLI 复制生命周期逻辑。

**目标接口：**

- `ce up`：默认连接到 CONNECTED，允许未使能；不等待必须上电后才成立的 ready 条件。
- `ce up --enable`：显式请求并确认使能；与普通运动授权选项分别记录。
- `ce down`：停止下发 → 停止能力及确认 → disable 及确认 → close；分阶段返回结果。
- `ce down --disconnect-only`：仅释放连接与拥有资源，不声称停机或下电。

**步骤与验收：**

- [ ] 将 `_up/_host` 的后端选择和配置合并收敛到与已安装实例相同的规则；移除对所有 Backend 的 `require_ros` 注入与 `manage_process` 强制覆盖。
- [ ] 移除 `wait_ready()` 对尚未使能设备的循环依赖；启动记录分别表达 connected/enabled/ready，而非一个 ready 文件隐含所有事实。
- [ ] 删除 `lifecycle.stop()` 调用点，普通上下文退出使用 close；受控 `ce down` 使用显式关闭编排。
- [ ] 停止或停用不支持、拒绝、超时或未知时，记录阶段结果并非零退出；最终资源释放不能擦掉失败状态。
- [ ] 信号退出、Host 崩溃、重复 down、陈旧 PID 和部分启动失败使用 owned 资源校验；不结束其他实例进程。
- [ ] 两个新增 CLI 参数落地前，README 明确它们是设计目标；落地后更新 `--help` 和可复制示例。

**验证文件：** `tests/integration/test_package_lifecycle_cli.py`、`tests/mock/test_v01.py`，新增 `tests/integration/test_project_lifecycle_cli.py`；所有设备行为使用离线替身。

### P7：硬件包与应用侧参考验证

**设计对应：** 第 6、8、19、31、34、36 节。  
**范围：** 外部 Hardware Package 与应用仓库；不将其厂商实现移回 SDK。

以现有 WY 包作为关节参考，验证：

- [ ] configure 无硬件副作用，connect 支持未使能状态；external/managed 选择和失败回滚准确。
- [ ] 请求前允许状态、请求成功和请求后实测状态分别验证；等待状态转换，不靠固定延时宣称成功。
- [ ] 位置反馈区分初始化值、目标值和实测值；验证来源、顺序、单位和有效性，不能仅凭 mode=104 判定位置已可信。
- [ ] 完整目标保留未移动关节的有效实测位置；缺失关节不补零，非法/未知状态不下发。
- [ ] CommandResult 区分 Action 成功与实测到位；超时不证明停止。
- [ ] 未验证 disable/stop 明确不支持；不以任意非 104 模式作为下电完成证据。
- [ ] 包版本和资产摘要更新，先在独立 Store 验证构建/安装/激活与迁移，不修改旧版本。

当前 Demo 的全零基准拦截属于应用侧保守保护，不上升为 Core 的通用“零姿态非法”规则。仅使能观察路径也会改变硬件状态，不能作为开发环境的自动测试。

非 ROS 第二参考包用于后续证明契约不绑定 ROS；其运动空间若尚无统一协议，先单独设计，再补 SDK 通用能力。

### P8：回归、发布与交付证据

**设计对应：** 第 14、31、38、44 节。  
**范围：** SDK、硬件包、示例与发布记录。

- [ ] 在隔离开发环境安装 `pytest`、Schema 检查所需依赖等，运行完整 SDK 测试；列出失败、跳过与环境缺失，不引用草稿的历史通过数。
- [ ] 在具有 NumPy 的离线环境执行数组回归，避免仅因可选依赖缺失跳过这次已出现的边界。
- [ ] 运行硬件包自己的完整离线套件及资产摘要校验；确认环境检查脚本不创建 ROS 节点或访问设备。
- [ ] 运行应用 Demo 的离线测试，确认默认只读、诊断使能与运动三种行为清晰；不自动执行现场路径。
- [ ] 检查旧 import/类名只存在于拒绝用例和迁移说明中，生产代码不保留转发。
- [ ] 记录包/Backend/SDK 版本、摘要、平台、测试层级、日志和未验证能力；新版本不继承旧版本现场认证。
- [ ] 按设计第 31.6 节逐项验收；基础交付明确不包含完整 Adapter Host 与未经设计的新动作空间。

建议验证命令（先激活项目开发环境，Python 应能导入 pytest）：

```bash
python -m pytest -q tests/unit/test_adapter_lifecycle.py tests/unit/test_robot_joint_api.py
python -m pytest -q tests/unit/test_v04_adapter_boundary.py tests/unit/test_installed_runtime.py
python -m pytest -q tests/unit/test_ros2_action_transport.py tests/unit/test_ros2_service_transport.py tests/unit/test_ros2_plain_payload.py tests/unit/test_hosted_transport.py
python -m pytest -q tests/onboarding
python -m pytest -q
```

新增文件的测试随相应任务执行；SDK 测试通过后再运行各外部包和应用自己的测试命令。文档编辑本身不需要启动上述软件实施流程。

### P9：后续完整 Adapter Host 里程碑

**设计对应：** 第 9、38、44 节。  
**状态：** 后续独立交付，不阻塞明确标注范围的 v0.4 基础版。

建议新增 `driver_host/adapter_client.py`、`adapter_worker.py`、`protocol.py`，由应用侧代理覆盖完整 Adapter 契约。运行位置选择、协议版本、构造时 configure 如何保持无硬件副作用、超时/重入/Host 恢复需在此里程碑冻结。

必须验证应用进程不导入厂商 SDK 或冲突 Native 库；Host 崩溃可感知，失联不伪报执行结果；Transport Host 与 Adapter Host 资源不能重复拥有。此时再扩展 Backend Schema 和锁定信息，不先给当前 Manifest 添加未实现的隔离开关。

## 5. 高风险输入与对应验收

| 输入或条件 | 期望行为 | 负责任务 |
|---|---|---|
| 首帧有新时间戳但位置仍为初始化占位值 | 不作为可信运动基准；标明未知或阻止动作 | P7 |
| 已使能状态下由外部操作改变设备模式 | 每次操作重新核查实测状态，不信任本地 `_enabled` | P1/P7 |
| Host 写请求后断连或超时 | 结果未知，不自动重发，也不声称已停止 | P3/P4 |
| 一台机器多个包/实例且导入模块同名 | 入口、摘要、配置和进程所有权互不串用 | P2/P4 |
| 上层要求停止但停用不支持、状态过期或故障 | 独立停止链路按能力执行；受控关闭分阶段失败，不以 close 冒充成功 | P1/P6 |

## 6. 完成标准

基础版完成需同时满足 P1—P8 的适用交付项及设计第 31.6 节；不要求在缺少厂商证据时伪造 stop、disable 或高频能力。缺失能力被正确拒绝和记录，是契约的一部分。

每项完成都应附代码位置、验证环境、测试结果和剩余限制。本文件当前只描述实施目标，未因已有类或目录存在而将任务自动勾选完成。现场验收按硬件包独立开展。
