# SDK v0.1 代码权属与第三方许可证核查清单

日期：2026-10-16

本文件提供项目所有者选择许可证前需要核实的事实，不代替所有者作许可证决定。

## 代码权属待确认

Git 历史当前出现两个作者身份：

| Git 作者 | 提交数 | 需要所有者确认 |
|---|---:|---|
| `Codex <codex@local>` | 40+ | AI 辅助产生的代码由谁拥有、是否受雇佣或机构 IP 条款约束 |
| `owlsan49 <1363477852@qq.com>` | 3 | 提交者身份、贡献授权及是否代表其他权利人 |

计数是发布审计期间的快照，后续审计文档提交仍使用同一作者身份。Git author 只能证明
提交元数据，不能单独证明著作权归属。公开发布前，项目所有者需要
确认：

1. 原始设计、代码和文档的权利归属。
2. AI 辅助输出可由项目所有者按所选许可证发布。
3. 是否包含雇主、学校、合作方或第三方尚未授权的材料。
4. 是否需要贡献者协议、Developer Certificate of Origin 或版权声明。
5. 仓库中的 Weiyi 验证文档是否可以公开；厂商二进制和源码保持排除。

## 直接 Python 依赖

| 依赖 | 用途 | 声明许可证 | 分发方式 |
|---|---|---|---|
| PyYAML | 核心 YAML 解析 | MIT | PyPI 依赖，不复制源码 |
| jsonschema | Onboarding Schema 校验 | MIT | 可选 PyPI extra，不复制源码 |
| openai | DeepSeek OpenAI 兼容客户端 | Apache-2.0 | 可选 PyPI extra，不复制源码 |
| urdf-parser-py | 可选 URDF 工具 | BSD-3-Clause | 可选 PyPI extra，不复制源码 |
| setuptools | 构建后端 | MIT | 构建依赖，不打入 wheel |

发布前需要由项目所有者或法律审查确认：所选项目许可证与上述依赖兼容、README 或
NOTICE 是否需要保留归属、以及 sdist 是否应附带第三方 notices。

## 系统和外部 Runtime

| 组件 | 已知状态 | SDK 发布处理 |
|---|---|---|
| PyKDL / Orocos KDL | Ubuntu `python3-pykdl` 包主许可证为 LGPL-2.1+，个别文件 BSD-2-Clause | 系统可选依赖，不进入 wheel |
| ROS2 Humble | 外部运行环境，由部署者安装 | 不随 SDK 分发 |
| Weiyi ROS2 Driver、消息接口、动态库和二进制 | 厂商资产；再分发权未确认 | 不进入 SDK wheel/sdist/GitHub 发布制品 |
| `.cepack` | 只含已审计的 Mapping/manifest/config | 作为独立制品发布，仍需单独核查内容和来源 |

## 仓库内 fixture

- `tests/onboarding/fixtures/` 是本项目创建的合成测试输入。
- fixture 中的 `package.xml` 许可证文本和 `libarm.so` 文件名用于验证扫描器；
  `libarm.so` 实际为 ASCII 测试数据，不是第三方库。
- fixture 不进入 wheel/sdist，但进入源码仓库，因此仍应随项目许可证明确覆盖。

## 尚未完成的治理项

- 仓库没有顶层 `LICENSE`、`NOTICE` 或 `COPYING`。
- `pyproject.toml` 没有 SPDX `license`/`license-files` 元数据。
- 项目所有者尚未明确公开发布授权。

完成上述选择后，才应添加 LICENSE、包元数据与 Release Notes，再公开 Push/Tag/发布。
