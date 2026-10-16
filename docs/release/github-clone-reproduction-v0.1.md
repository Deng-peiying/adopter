# 从全新 GitHub Clone 复现 SDK 与已验收 Hardware Package

以下步骤面向发布后的 `dpy` 分支或对应不可变 tag。命令不依赖开发者本机路径，
不运行 DeepSeek，也不包含厂商 Driver。

## 1. 从源码安装固定 SDK

```bash
git clone https://github.com/owlsan49/cross-embody-sdk.git
cd cross-embody-sdk
git checkout dpy

python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[onboarding]'
ce --help
```

若使用发布 wheel，则用经过 SHA-256 核验的文件替换最后一条安装命令：

```bash
python -m pip install ./cross_embodiment-0.1.0-py3-none-any.whl
```

模式 B 的真实 DeepSeek Onboarding 才需要安装
`cross-embodiment[onboarding-agent]` 并配置本地 API Key。模式 A 不需要模型依赖。

## 2. 安装并激活 `.cepack`

准备从独立 Distribution Kit 获得的文件：

- `weiyi-right-arm-runtime.cepack`
- `right-arm.instance.yaml`
- 对应 `SHA256SUMS`

编辑实例 ID；包名、版本和 Backend 必须与 `.cepack` manifest 一致：

```yaml
schema_version: robot-instance/v0.1
instance:
  id: lab/right-arm-01
robot:
  package: weiyi/dual_o6_cleanroom_20261016
  version: 0.1.0
backend:
  preferred: ros2_mapped
connection: {}
```

安装、激活和解析均为文件操作，不连接或使能机器人：

```bash
export CROSS_EMBODIMENT_STORE="$HOME/.cross_embodiment"
sha256sum --check SHA256SUMS

ce package install \
  --artifact ./weiyi-right-arm-runtime.cepack \
  --store "$CROSS_EMBODIMENT_STORE" \
  --json

ce package activate weiyi/dual_o6_cleanroom_20261016@0.1.0 \
  --instance ./right-arm.instance.yaml \
  --store "$CROSS_EMBODIMENT_STORE" \
  --json

ce package use \
  --instance lab/right-arm-01 \
  --store "$CROSS_EMBODIMENT_STORE" \
  --json
```

`package use` 的 `package_root` 和 Mapping 路径必须位于
`$CROSS_EMBODIMENT_STORE/packages/`，其摘要必须与 Distribution Kit 记录一致。

## 3. 显式只读预检

使用者自行安装并启动许可范围内的 Weiyi Runtime，source 对应 ROS2 环境，并单独
使能右臂。`.cepack` 不包含、不启动也不删除该 Runtime。

状态达到 `mode=104`、`fault_code=0` 后运行只读预检：

```bash
ce onboard preflight \
  --instance lab/right-arm-01 \
  --store "$CROSS_EMBODIMENT_STORE" \
  --device right_arm \
  --output ./preflight.json \
  --json
```

该命令只读取状态。真实运动仍须使用项目已验证的目标文件，并通过
`ce onboard accept-l3` 的 `EXECUTE L3` 现场确认。新的机器、安装方式或目标不得把
旧 L3 结果当作当前真机授权。

## 4. 卸载

```bash
ce package deactivate \
  --instance lab/right-arm-01 \
  --store "$CROSS_EMBODIMENT_STORE" \
  --json

ce package uninstall weiyi/dual_o6_cleanroom_20261016@0.1.0 \
  --store "$CROSS_EMBODIMENT_STORE" \
  --json
```

卸载只删除 SDK Store 中的包与记录，不删除 ROS2、Weiyi Driver 或共享动态库。
