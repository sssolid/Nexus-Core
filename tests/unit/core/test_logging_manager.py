"""Unit tests for the Logging Manager."""

import logging
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from nexus_core.core.logging_manager import LoggingManager
from nexus_core.utils.exceptions import ManagerInitializationError


@pytest.fixture
def temp_log_dir():
    """Create a temporary logging directory."""
    temp_dir = tempfile.mkdtemp()
    log_dir = os.path.join(temp_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    yield log_dir
    
    # Clean up created log files
    for file in os.listdir(log_dir):
        os.remove(os.path.join(log_dir, file))
    os.rmdir(log_dir)
    os.rmdir(temp_dir)


@pytest.fixture
def logging_config(temp_log_dir):
    """Create a logging configuration for testing."""
    return {
        "level": "INFO",
        "format": "text",
        "file": {
            "enabled": True,
            "path": os.path.join(temp_log_dir, "test.log"),
            "rotation": "1 MB",
            "retention": "5 days"
        },
        "console": {
            "enabled": True,
            "level": "DEBUG"
        },
        "database": {
            "enabled": False
        },
        "elk": {
            "enabled": False
        }
    }


@pytest.fixture
def config_manager_mock(logging_config):
    """Create a mock ConfigManager for the LoggingManager."""
    config_manager = MagicMock()
    config_manager.get.return_value = logging_config
    return config_manager


def test_logging_manager_initialization(config_manager_mock, temp_log_dir):
    """Test that the LoggingManager initializes correctly."""
    logging_manager = LoggingManager(config_manager_mock)
    logging_manager.initialize()
    
    assert logging_manager.initialized
    assert logging_manager.healthy
    
    # Check log directory was created
    assert os.path.exists(temp_log_dir)
    
    # Check root logger was set up
    assert logging_manager._root_logger is not None
    
    # Clean up
    logging_manager.shutdown()
    assert not logging_manager.initialized


def test_get_logger(config_manager_mock):
    """Test getting a logger from the LoggingManager."""
    logging_manager = LoggingManager(config_manager_mock)
    logging_manager.initialize()
    
    logger = logging_manager.get_logger("test_logger")
    assert logger is not None
    
    # For text format, should be a regular logger
    assert isinstance(logger, logging.Logger)
    
    # Clean up
    logging_manager.shutdown()


@patch("nexus_core.core.logging_manager.logging")
def test_logging_manager_config_changes(mock_logging, config_manager_mock):
    """Test the LoggingManager responds correctly to configuration changes."""
    logging_manager = LoggingManager(config_manager_mock)
    logging_manager.initialize()
    
    # Mock the root logger
    mock_logger = MagicMock()
    logging_manager._root_logger = mock_logger
    mock_file_handler = MagicMock()
    logging_manager._file_handler = mock_file_handler
    mock_logger.handlers = [mock_file_handler]
    
    # Test changing log level
    logging_manager._on_config_changed("logging.level", "DEBUG")
    mock_logger.setLevel.assert_called_with(logging.DEBUG)
    
    # Test changing file handler level
    logging_manager._on_config_changed("logging.file.level", "ERROR")
    mock_file_handler.setLevel.assert_called_with(logging.ERROR)
    
    # Test disabling file handler
    mock_logger.removeHandler.reset_mock()
    logging_manager._on_config_changed("logging.file.enabled", False)
    mock_logger.removeHandler.assert_called_with(mock_file_handler)
    
    # Test enabling file handler
    mock_logger.addHandler.reset_mock()
    logging_manager._on_config_changed("logging.file.enabled", True)
    mock_logger.addHandler.assert_called_with(mock_file_handler)
    
    # Clean up
    logging_manager.shutdown()


def test_logging_manager_status(config_manager_mock, temp_log_dir):
    """Test getting status from LoggingManager."""
    logging_manager = LoggingManager(config_manager_mock)
    logging_manager.initialize()
    
    status = logging_manager.status()
    
    assert status["name"] == "LoggingManager"
    assert status["initialized"] is True
    assert status["log_directory"] == temp_log_dir
    assert "handlers" in status
    
    # Clean up
    logging_manager.shutdown()


@patch("nexus_core.core.logging_manager.structlog")
def test_json_format_logger(mock_structlog, config_manager_mock):
    """Test creating a JSON format logger."""
    # Update config to use JSON format
    config_manager_mock.get.return_value.update({"format": "json"})
    
    logging_manager = LoggingManager(config_manager_mock)
    logging_manager.initialize()
    
    # Verify structlog was configured
    assert logging_manager._enable_structlog is True
    mock_structlog.configure.assert_called_once()
    
    # Clean up
    logging_manager.shutdown()


def test_logging_manager_initialization_failure(config_manager_mock):
    """Test that the LoggingManager handles initialization failures gracefully."""
    # Make the config manager raise an exception
    config_manager_mock.get.side_effect = Exception("Test exception")
    
    logging_manager = LoggingManager(config_manager_mock)
    
    with pytest.raises(ManagerInitializationError):
        logging_manager.initialize()
