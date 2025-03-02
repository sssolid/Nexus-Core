"""Pytest fixtures for Nexus Core tests."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import tempfile
from typing import Any, Dict, Generator, Optional

import pytest
from pytest_mock import MockerFixture

# Import Nexus Core modules
# These imports may fail if running tests without the package installed,
# so we use try/except to handle that case
try:
    from nexus_core.core.app import ApplicationCore
    from nexus_core.core.config_manager import ConfigManager
    from nexus_core.core.logging_manager import LoggingManager
    from nexus_core.core.event_bus import EventBusManager, Event
    from nexus_core.core.thread_manager import ThreadManager
    from nexus_core.core.file_manager import FileManager
    from nexus_core.core.db_manager import DatabaseManager
    from nexus_core.core.plugin_manager import PluginManager
    from nexus_core.core.monitoring_manager import ResourceMonitoringManager
    from nexus_core.core.security_manager import SecurityManager, UserRole
    from nexus_core.core.api_manager import APIManager
    from nexus_core.core.cloud_manager import CloudManager
    from nexus_core.core.remote_manager import RemoteServicesManager
except ImportError:
    # Set dummy classes for typing if imports fail
    class ApplicationCore: pass
    class ConfigManager: pass
    class LoggingManager: pass
    class EventBusManager: pass
    class Event: pass
    class ThreadManager: pass
    class FileManager: pass
    class DatabaseManager: pass
    class PluginManager: pass
    class ResourceMonitoringManager: pass
    class SecurityManager: pass
    class UserRole: pass
    class APIManager: pass
    class CloudManager: pass
    class RemoteServicesManager: pass


# Basic fixture for test configuration
@pytest.fixture
def test_config() -> Dict[str, Any]:
    """Provide a basic configuration dictionary for testing."""
    return {
        "app": {
            "name": "Nexus Core Test",
            "version": "0.1.0",
            "environment": "testing",
            "debug": True,
        },
        "database": {
            "type": "sqlite",
            "name": ":memory:",
        },
        "logging": {
            "level": "DEBUG",
            "format": "text",
            "file": {
                "enabled": False,
            },
            "console": {
                "enabled": True,
                "level": "DEBUG",
            },
            "database": {
                "enabled": False,
            },
        },
        "event_bus": {
            "thread_pool_size": 2,
            "max_queue_size": 100,
        },
        "thread_pool": {
            "worker_threads": 2,
            "max_queue_size": 50,
        },
        "api": {
            "enabled": False,
        },
        "plugins": {
            "autoload": False,
        },
        "monitoring": {
            "enabled": True,
            "prometheus": {
                "enabled": False,
            },
        },
        "security": {
            "jwt": {
                "secret": "test_secret_key_for_testing_only",
                "algorithm": "HS256",
                "access_token_expire_minutes": 30,
                "refresh_token_expire_days": 7,
            },
        },
    }


@pytest.fixture
def temp_dir() -> Generator[pathlib.Path, None, None]:
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield pathlib.Path(temp_dir)


@pytest.fixture
def config_file(temp_dir: pathlib.Path, test_config: Dict[str, Any]) -> pathlib.Path:
    """Create a temporary config file for testing."""
    import yaml
    
    config_path = temp_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(test_config, f)
    
    return config_path


@pytest.fixture
def mock_logger() -> logging.Logger:
    """Provide a mock logger for testing."""
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    for handler in logger.handlers:
        logger.removeHandler(handler)
    
    # Add a console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


@pytest.fixture
def config_manager(config_file: pathlib.Path) -> Generator[ConfigManager, None, None]:
    """Provide an initialized ConfigManager instance."""
    manager = ConfigManager(config_path=str(config_file))
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def logging_manager(config_manager: ConfigManager) -> Generator[LoggingManager, None, None]:
    """Provide an initialized LoggingManager instance."""
    manager = LoggingManager(config_manager)
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def event_bus_manager(
    config_manager: ConfigManager, 
    logging_manager: LoggingManager
) -> Generator[EventBusManager, None, None]:
    """Provide an initialized EventBusManager instance."""
    manager = EventBusManager(config_manager, logging_manager)
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def thread_manager(
    config_manager: ConfigManager, 
    logging_manager: LoggingManager
) -> Generator[ThreadManager, None, None]:
    """Provide an initialized ThreadManager instance."""
    manager = ThreadManager(config_manager, logging_manager)
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def file_manager(
    config_manager: ConfigManager, 
    logging_manager: LoggingManager, 
    temp_dir: pathlib.Path
) -> Generator[FileManager, None, None]:
    """Provide an initialized FileManager instance."""
    # Override the file paths to use the temporary directory
    config_manager.set("files.base_directory", str(temp_dir / "data"))
    config_manager.set("files.temp_directory", str(temp_dir / "data/temp"))
    config_manager.set("files.plugin_data_directory", str(temp_dir / "data/plugins"))
    config_manager.set("files.backup_directory", str(temp_dir / "data/backups"))
    
    manager = FileManager(config_manager, logging_manager)
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def db_manager(
    config_manager: ConfigManager, 
    logging_manager: LoggingManager
) -> Generator[DatabaseManager, None, None]:
    """Provide an initialized DatabaseManager instance."""
    # Ensure we use an in-memory SQLite database for testing
    config_manager.set("database.type", "sqlite")
    config_manager.set("database.name", ":memory:")
    
    manager = DatabaseManager(config_manager, logging_manager)
    manager.initialize()
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def security_manager(
    config_manager: ConfigManager, 
    logging_manager: LoggingManager, 
    event_bus_manager: EventBusManager
) -> Generator[SecurityManager, None, None]:
    """Provide an initialized SecurityManager instance."""
    manager = SecurityManager(config_manager, logging_manager, event_bus_manager)
    manager.initialize()
    
    # Create a test admin user
    manager.create_user(
        username="admin",
        email="admin@example.com",
        password="admin123",
        roles=[UserRole.ADMIN],
    )
    
    yield manager
    
    manager.shutdown()


@pytest.fixture
def mock_app_core(mocker: MockerFixture) -> ApplicationCore:
    """Provide a mocked ApplicationCore instance."""
    mock_core = mocker.Mock(spec=ApplicationCore)
    
    # Mock the get_manager method to return mock managers
    mock_managers = {
        "config": mocker.Mock(spec=ConfigManager),
        "logging": mocker.Mock(spec=LoggingManager),
        "event_bus": mocker.Mock(spec=EventBusManager),
        "thread": mocker.Mock(spec=ThreadManager),
        "file": mocker.Mock(spec=FileManager),
        "db": mocker.Mock(spec=DatabaseManager),
        "plugin": mocker.Mock(spec=PluginManager),
        "monitoring": mocker.Mock(spec=ResourceMonitoringManager),
        "security": mocker.Mock(spec=SecurityManager),
        "api": mocker.Mock(spec=APIManager),
        "cloud": mocker.Mock(spec=CloudManager),
        "remote": mocker.Mock(spec=RemoteServicesManager),
    }
    
    mock_core.get_manager.side_effect = lambda name: mock_managers.get(name)
    mock_core.status.return_value = {
        "name": "ApplicationCore",
        "initialized": True,
        "healthy": True,
        "managers": {name: {"initialized": True, "healthy": True} for name in mock_managers},
    }
    
    return mock_core


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Provide an event loop for async tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    yield loop
    
    loop.close()


# Add more fixtures as needed for specific test scenarios...
