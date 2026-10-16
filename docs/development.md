# SDK 开发与测试

本文档面向需要阅读、修改或测试 SDK 源码的开发者。普通部署用户应使用
Distribution Kit，不需要 clone `dpy` 源码。

## 安装 Core SDK

```bash
git clone --branch dpy --single-branch \
  git@github.com:owlsan49/cross-embody-sdk.git
cd cross-embody-sdk

python3.10 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade 'pip>=23' 'setuptools>=68' wheel
.venv/bin/python -m pip install --no-build-isolation -e .
```

Ubuntu 22.04 自带的 setuptools 59.6 不支持本项目需要的 PEP 660 editable
install，因此必须先升级构建工具。`--system-site-packages` 用于暴露 ROS2
Humble 通过 apt 安装的 `rclpy`、`rosidl_runtime_py`、NumPy 和 PyKDL。

如果 editable install 失败过，先清空环境：

```bash
python3.10 -m venv --clear --system-site-packages .venv
```

## 验证安装来源

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import cross_embodiment
import yaml

source_root = (Path.cwd() / "src").resolve()
sdk_path = Path(cross_embodiment.__file__).resolve()
assert sdk_path.is_relative_to(source_root), (sdk_path, source_root)
assert tuple(map(int, yaml.__version__.split(".")[:2])) >= (6, 0)
print("Core SDK editable install: OK")
print("sdk_path:", sdk_path)
print("yaml_version:", yaml.__version__)
PY
```

ROS2 Backend 导入检查：

```bash
source /opt/ros/humble/setup.bash
.venv/bin/python -c '
import cross_embodiment, yaml, numpy, rclpy, rosidl_runtime_py
print("SDK + ROS2 Python environment: OK")
'
```

## Onboarding Agent 可选依赖

```bash
.venv/bin/python -m pip install --no-build-isolation -e '.[onboarding-agent]'
```

DeepSeek 凭据必须保存在 Git 忽略的本地数据文件中。不得把 Key 写入源码、
README、测试 Fixture 或提交历史。

## 测试与构建

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip install build
.venv/bin/python -m build
sha256sum dist/*
```

PyKDL 相关测试要求 Ubuntu `python3-pykdl`。Onboarding Schema 测试要求
`jsonschema`。Platform Lock 测试会按设计拒绝非 Python 3.10 环境。

wheel 和 sdist 必须包含 Catalog、Backend Descriptor、Schema、Onboarding Agent 代码和
Package Manager。发布前应在新虚拟环境中重新安装 wheel 并检查实际导入路径。
