import os
import pytest
import tempfile
from pathlib import Path
from nexus_core.core.app import ApplicationCore
from nexus_core.core.config_manager import ConfigManager
@pytest.fixture
def temp_config_file():
    with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as tmp:
        tmp.write(b'\napp:\n  name: "Nexus Core Test"\n  version: "0.1.0"\n  environment: "testing"\ndatabase:\n  type: "sqlite"\n  name: ":memory:"\nlogging:\n  level: "DEBUG"\n  file:\n    enabled: false\n  console:\n    enabled: true\n    level: "DEBUG"\n')
        tmp_path = tmp.name
    yield tmp_path
    os.unlink(tmp_path)
@pytest.fixture
def config_manager(temp_config_file):
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    yield manager
    manager.shutdown()
@pytest.fixture
def app_core(temp_config_file):
    app = ApplicationCore(config_path=temp_config_file)
    app.initialize()
    yield app
    app.shutdown()