from pathlib import Path
import sys

import pytest

from cross_embodiment.errors import LifecycleError
from cross_embodiment.hardware.manifest import EmbodimentManifest
from cross_embodiment.package.manifest import BackendSpec
from cross_embodiment.sdk.manipulator import ManipulatorRobot


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def configure(self): self.calls.append('configure')
    def connect(self): self.calls.append('connect')
    def enable(self): self.calls.append('enable')
    def disable(self): self.calls.append('disable')
    def disconnect(self): self.calls.append('disconnect')


def robot_with(adapter):
    return ManipulatorRobot(adapter, EmbodimentManifest(schema_version='embodiment/v0.2', embodiment={}))


def test_close_releases_connection_without_disabling_hardware():
    adapter = RecordingAdapter()
    robot = robot_with(adapter)
    robot.connect()
    robot.lifecycle.enable()
    robot.close()
    robot.close()
    assert adapter.calls == ['configure', 'connect', 'enable', 'disconnect']


def test_enable_requires_explicit_connection():
    adapter = RecordingAdapter()
    robot = robot_with(adapter)
    with pytest.raises(LifecycleError, match='connect'):
        robot.lifecycle.enable()
    assert adapter.calls == ['configure']


def test_explicit_disable_reaches_hardware_even_if_enabled_externally():
    adapter = RecordingAdapter()
    robot = robot_with(adapter).connect()
    robot.lifecycle.disable()
    assert adapter.calls[-1] == 'disable'
    robot.close()


def test_package_entrypoints_with_identical_names_do_not_share_modules(tmp_path):
    from cross_embodiment.package.loader import load_backend_entrypoint

    before = list(sys.path)
    factories = []
    for label in ('first', 'second'):
        root = tmp_path / label
        module = root / 'adapters' / 'ros2'
        module.mkdir(parents=True)
        (module / 'mapping.py').write_text(f'IDENTITY = {label!r}\n')
        (module / 'adapter.py').write_text(
            'from .mapping import IDENTITY\nclass Adapter:\n    identity = IDENTITY\n')
        factories.append(load_backend_entrypoint(
            BackendSpec(id='custom', type='python', entrypoint='adapters.ros2.adapter:Adapter'), root))
    assert [factory.identity for factory in factories] == ['first', 'second']
    assert sys.path == before


def test_context_rejects_assets_outside_package(tmp_path):
    from cross_embodiment.adapter.context import AdapterContext

    context = AdapterContext.from_connection({'package_root': str(tmp_path)})
    with pytest.raises(ValueError, match='package'):
        context.resource('../outside')
    assert context.resource('config/options.yaml') == tmp_path / 'config/options.yaml'
