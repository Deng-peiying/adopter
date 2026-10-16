# SDK v0.1-rc1 发布包含与排除清单

日期：2026-10-16
候选名称：`cross-embodiment-0.1.0-rc1`
Python 包版本：`0.1.0`
发布状态：本地候选；许可证与项目所有者授权完成前不得公开发布

## 包含范围

GitHub 源码仓库应包含：

- `src/cross_embodiment/`：Unified Robot Runtime、Hardware Onboarding Agent、
  Hardware Package Lifecycle 和 `ce` CLI。
- `src/cross_embodiment/onboarding/platform/`：wheel 运行时使用的 Capability
  Catalog、Backend Descriptor 和 13 项 JSON Schema。
- `catalogs/`、`schemas/`：平台契约的源码维护副本。
- `tests/`：单元、集成、Onboarding、Conformance 与合成 fixture。
- `docs/`、`README.md`、`pyproject.toml`：架构、使用、发布边界与构建元数据。

wheel 和 sdist 必须包含：

- `cross_embodiment.sdk`、`protocol`、`mapping`、`backend`、`driver`。
- `cross_embodiment.onboarding` 的 Scanner、Evidence、Matcher、Provider、Agent、
  Backend Fit、Generator、Conformance 与 Runtime Policy。
- `cross_embodiment.package` 的 build/install/list/inspect/activate/use/deactivate/
  uninstall 生命周期。
- 1 份 Capability Catalog、1 份 Backend Descriptor、13 项 JSON Schema。

单独发布、但不进入 SDK wheel/sdist 的制品：

- 已验收 Hardware Package 的 `.cepack`。
- 与 `.cepack` 配套的 Robot Instance 模板、运行环境说明和摘要清单。

## 排除范围

以下内容不得进入 SDK GitHub 发布制品：

- Weiyi 或其他厂商的 Driver、ROS workspace、源码、动态库、二进制和许可证未明资产。
- 原有或自动生成的 Weiyi Mapping、Demo 目标和 Robot Instance 实值。
- Gate D/E 原始 transcript、真机执行日志、扫描缓存和本机实验目录。
- DeepSeek API Key、`.deepseek_credentials.py`、`.env` 或其他凭据。
- `build/`、`dist/`、`*.egg-info`、`__pycache__`、pytest 缓存和临时虚拟环境。
- 本机绝对路径、CAN/网络设备参数和硬件使能状态。

`tests/onboarding/fixtures/` 中的文件是合成测试输入。名称看似动态库的
`libarm.so` 是 43 字节 ASCII fixture，不是厂商二进制；测试 fixture 不进入 wheel
或 sdist。

## 产品声明边界

- 模式 A 不依赖 DeepSeek：用户安装 SDK 和 `.cepack`，准备厂商 Runtime 后使用
  固定 Robot API。
- 模式 B 包含完整 Onboarding Agent；Weiyi 已验证通过现有 `ros2_mapped`
  Backend 自动生成 Mapping 和 Hardware Package。
- Python SDK、C/C++ Library 以及全新 Backend 插件的自动代码生成、编译、注册和
  真机执行尚未实现和验证。
- `.cepack` 不替代厂商 Runtime，也不自动启动、连接或使能机器人。

## 发布 Gate

1. 最终 Git commit 可从干净 clone 重建 wheel 和 sdist。
2. wheel、sdist 和源码安装的资源审计全部通过。
3. 完整测试通过，并保存命令、计数和 Python 版本。
4. 项目所有者确认代码权属、第三方许可证和顶层项目许可证。
5. 公开发布由项目所有者单独授权；本清单不构成发布授权。
