"""Pytest configuration and fixtures for Nexus Core tests."""

import os
import pytest
import tempfile
from pathlib import Path

from nexus_core.core.app import ApplicationCore
from nexus_core.core.config_manager import ConfigManager

@pytest.fixture
def temp_config_file():
    """Create a temporary configuration file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as tmp:
        tmp.write(b"""
app:
  name: "Nexus Core Test"
  version: "0.1.0"
  environment: "testing"
database:
  type: "sqlite"
  name: ":memory:"
logging:
  level: "DEBUG"
  file:
    enabled: false
  console:
    enabled: true
    level: "DEBUG"
""")
        tmp_path = tmp.name
    
    yield tmp_path
    os.unlink(tmp_path)

@pytest.fixture
def config_manager(temp_config_file):
    """Create a ConfigManager instance for testing."""
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    yield manager
    manager.shutdown()

@pytest.fixture
def app_core(temp_config_file):
    """Create an ApplicationCore instance for testing."""
    app = ApplicationCore(config_path=temp_config_file)
    app.initialize()
    yield app
    app.shutdown()