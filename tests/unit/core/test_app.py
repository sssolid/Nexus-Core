"""Unit tests for the Application Core."""

import os
import pytest
from unittest.mock import MagicMock, patch

from nexus_core.core.app import ApplicationCore
from nexus_core.utils.exceptions import ManagerInitializationError


def test_app_core_initialization(temp_config_file):
    """Test that the ApplicationCore initializes correctly."""
    app = ApplicationCore(config_path=temp_config_file)
    app.initialize()
    
    assert app._initialized
    
    # Check that required managers are initialized
    assert app.get_manager('config') is not None
    assert app.get_manager('logging') is not None
    assert app.get_manager('event_bus') is not None
    
    app.shutdown()
    assert not app._initialized


def test_app_core_get_manager(app_core):
    """Test retrieving managers from ApplicationCore."""
    # Core managers should be available
    assert app_core.get_manager('config') is not None
    assert app_core.get_manager('logging') is not None
    assert app_core.get_manager('event_bus') is not None
    
    # Non-existent manager should return None
    assert app_core.get_manager('nonexistent') is None


def test_app_core_status(app_core):
    """Test getting status from ApplicationCore."""
    status = app_core.status()
    
    assert status['name'] == 'ApplicationCore'
    assert status['initialized'] is True
    assert 'managers' in status
    
    # Check manager statuses
    managers = status['managers']
    assert 'config' in managers
    assert 'logging' in managers
    assert 'event_bus' in managers


@patch('nexus_core.core.config_manager.ConfigManager')
def test_app_core_initialization_failure(mock_config_manager, temp_config_file):
    """Test that ApplicationCore handles initialization failures gracefully."""
    # Mock ConfigManager to raise an exception during initialization
    mock_instance = mock_config_manager.return_value
    mock_instance.initialize.side_effect = Exception("Config initialization error")
    
    # ApplicationCore should propagate the exception
    with pytest.raises(ManagerInitializationError):
        app = ApplicationCore(config_path=temp_config_file)
        app.initialize()


def test_app_core_signal_handler():
    """Test that the signal handler properly shuts down ApplicationCore."""
    app = ApplicationCore()
    app._logger = MagicMock()
    app.shutdown = MagicMock()
    
    # We can't actually test signal handling directly, but we can call the handler
    with pytest.raises(SystemExit):
        app._signal_handler(15, None)  # 15 is SIGTERM
    
    # Verify shutdown was called
    app.shutdown.assert_called_once()
