"""Unit tests for the Configuration Manager."""

import os
import pytest
from pathlib import Path

from nexus_core.core.config_manager import ConfigManager
from nexus_core.utils.exceptions import ConfigurationError

def test_config_manager_initialization(temp_config_file):
    """Test that the ConfigManager initializes correctly."""
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    
    assert manager.initialized
    assert manager.healthy
    
    manager.shutdown()
    assert not manager.initialized

def test_config_manager_get(config_manager):
    """Test getting configuration values."""
    assert config_manager.get("app.name") == "Nexus Core Test"
    assert config_manager.get("app.version") == "0.1.0"
    assert config_manager.get("app.environment") == "testing"
    
    # Test default value for non-existent key
    assert config_manager.get("non_existent_key", "default") == "default"

def test_config_manager_set(config_manager):
    """Test setting configuration values."""
    config_manager.set("app.name", "New Name")
    assert config_manager.get("app.name") == "New Name"
    
    # Test setting a new key
    config_manager.set("new.key", "value")
    assert config_manager.get("new.key") == "value"

def test_config_manager_env_vars(temp_config_file, monkeypatch):
    """Test that environment variables override configuration values."""
    monkeypatch.setenv("NEXUS_APP_NAME", "Env Test")
    monkeypatch.setenv("NEXUS_DATABASE_PORT", "5433")
    monkeypatch.setenv("NEXUS_LOGGING_LEVEL", "INFO")
    
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    
    assert manager.get("app.name") == "Env Test"
    assert manager.get("database.port") == 5433
    assert manager.get("logging.level") == "INFO"
    
    manager.shutdown()

def test_config_manager_validation(temp_config_file):
    """Test configuration validation."""
    manager = ConfigManager(config_path=temp_config_file)
    manager.initialize()
    
    # Test setting an invalid value
    with pytest.raises(ConfigurationError):
        manager.set("api.port", "not_a_number")
    
    manager.shutdown()

def test_config_manager_listener(config_manager):
    """Test configuration change listeners."""
    changes = []
    
    def on_change(key, value):
        changes.append((key, value))
    
    config_manager.register_listener("app", on_change)
    config_manager.set("app.name", "Listener Test")
    
    assert len(changes) == 1
    assert changes[0] == ("app.name", "Listener Test")
    
    config_manager.unregister_listener("app", on_change)
    config_manager.set("app.version", "0.2.0")
    
    assert len(changes) == 1  # No new changes recorded