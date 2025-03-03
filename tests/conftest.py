"""Pytest configuration and fixtures for Nexus Core tests."""

import os
import pytest
import tempfile
import yaml
from pathlib import Path
from typing import Generator

from nexus_core.core.app import ApplicationCore
from nexus_core.core.config_manager import ConfigManager

@pytest.fixture
def temp_config_file() -> Generator[str, None, None]:
    """Create a temporary configuration file for testing."""
    test_config = {
        "app": {
            "name": "Nexus Core Test",
            "version": "0.1.0",
            "environment": "testing"
        },
        "database": {
            "type": "sqlite",
            "name": ":memory:"
        },
        "logging": {
            "level": "DEBUG",
            "file": {"enabled": False},
            "console": {"enabled": True, "level": "DEBUG"}
        },
        "security": {
            "jwt": {
                "secret": "test_secret_key_for_testing_only",  # Ensuring a valid JWT secret
                "algorithm": "HS256"
            }
        },
        "api": {
            "enabled": True  # Ensuring API is enabled
        }
    }

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as tmp:
        yaml.dump(test_config, tmp)
        tmp_path = tmp.name

    print(f"DEBUG: Using test config file at {tmp_path}")
    print(f"DEBUG: Test config content:\n{yaml.dump(test_config, default_flow_style=False)}")

    yield tmp_path

    try:
        os.unlink(tmp_path)
    except (IOError, OSError):
        pass


@pytest.fixture
def config_manager(temp_config_file: str) -> Generator[ConfigManager, None, None]:
    """Create a ConfigManager instance for testing."""
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    yield manager
    manager.shutdown()

@pytest.fixture
def app_core(temp_config_file: str) -> Generator[ApplicationCore, None, None]:
    """Create an ApplicationCore instance for testing."""
    app = ApplicationCore(config_path=temp_config_file)
    app.initialize()
    yield app
    app.shutdown()