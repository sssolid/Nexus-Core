"""Unit tests for the exceptions module."""

import pytest

from nexus_core.utils.exceptions import (
    NexusError,
    ManagerError,
    ManagerInitializationError,
    ManagerShutdownError,
    ConfigurationError,
    EventBusError,
    PluginError,
    DatabaseError,
    SecurityError,
    ThreadManagerError,
    FileError,
    APIError
)


def test_nexus_error():
    """Test the base NexusError class."""
    # Test basic error
    error = NexusError("Test error message")
    assert str(error) == "Test error message"
    assert error.code == "NexusError"
    assert error.details == {}
    
    # Test with custom code
    error = NexusError("Test with code", code="CUSTOM_CODE")
    assert error.code == "CUSTOM_CODE"
    
    # Test with details
    details = {"key": "value", "number": 123}
    error = NexusError("Test with details", details=details)
    assert error.details == details


def test_manager_error():
    """Test the ManagerError class."""
    # Test basic error
    error = ManagerError("Manager error message")
    assert str(error) == "Manager error message"
    assert error.code == "ManagerError"
    assert "manager_name" not in error.details
    
    # Test with manager name
    error = ManagerError("Manager error with name", manager_name="TestManager")
    assert error.details["manager_name"] == "TestManager"
    
    # Test with additional details
    details = {"key": "value"}
    error = ManagerError("Manager error with details", manager_name="TestManager", details=details)
    assert error.details["manager_name"] == "TestManager"
    assert error.details["key"] == "value"


def test_manager_initialization_error():
    """Test the ManagerInitializationError class."""
    error = ManagerInitializationError("Init error", manager_name="TestManager")
    assert str(error) == "Init error"
    assert error.code == "ManagerInitializationError"
    assert error.details["manager_name"] == "TestManager"


def test_manager_shutdown_error():
    """Test the ManagerShutdownError class."""
    error = ManagerShutdownError("Shutdown error", manager_name="TestManager")
    assert str(error) == "Shutdown error"
    assert error.code == "ManagerShutdownError"
    assert error.details["manager_name"] == "TestManager"


def test_configuration_error():
    """Test the ConfigurationError class."""
    # Test basic error
    error = ConfigurationError("Config error message")
    assert str(error) == "Config error message"
    assert error.code == "ConfigurationError"
    assert "config_key" not in error.details
    
    # Test with config key
    error = ConfigurationError("Config error with key", config_key="database.host")
    assert error.details["config_key"] == "database.host"
    
    # Test with additional details
    details = {"suggestion": "Check your settings"}
    error = ConfigurationError("Config error with details", config_key="database.host", details=details)
    assert error.details["config_key"] == "database.host"
    assert error.details["suggestion"] == "Check your settings"


def test_event_bus_error():
    """Test the EventBusError class."""
    # Test basic error
    error = EventBusError("Event bus error message")
    assert str(error) == "Event bus error message"
    assert error.code == "EventBusError"
    assert "event_type" not in error.details
    
    # Test with event type
    error = EventBusError("Event bus error with type", event_type="test/event")
    assert error.details["event_type"] == "test/event"


def test_plugin_error():
    """Test the PluginError class."""
    # Test basic error
    error = PluginError("Plugin error message")
    assert str(error) == "Plugin error message"
    assert error.code == "PluginError"
    assert "plugin_name" not in error.details
    
    # Test with plugin name
    error = PluginError("Plugin error with name", plugin_name="test_plugin")
    assert error.details["plugin_name"] == "test_plugin"


def test_database_error():
    """Test the DatabaseError class."""
    # Test basic error
    error = DatabaseError("Database error message")
    assert str(error) == "Database error message"
    assert error.code == "DatabaseError"
    assert "query" not in error.details
    
    # Test with query
    error = DatabaseError("Database error with query", query="SELECT * FROM users")
    assert error.details["query"] == "SELECT * FROM users"


def test_security_error():
    """Test the SecurityError class."""
    # Test basic error
    error = SecurityError("Security error message")
    assert str(error) == "Security error message"
    assert error.code == "SecurityError"
    assert "user_id" not in error.details
    assert "permission" not in error.details
    
    # Test with user ID
    error = SecurityError("Security error with user", user_id="user123")
    assert error.details["user_id"] == "user123"
    
    # Test with permission
    error = SecurityError("Security error with permission", permission="admin.read")
    assert error.details["permission"] == "admin.read"
    
    # Test with both
    error = SecurityError("Security error with both", user_id="user123", permission="admin.read")
    assert error.details["user_id"] == "user123"
    assert error.details["permission"] == "admin.read"


def test_thread_manager_error():
    """Test the ThreadManagerError class."""
    # Test basic error
    error = ThreadManagerError("Thread error message")
    assert str(error) == "Thread error message"
    assert error.code == "ThreadManagerError"
    assert "thread_id" not in error.details
    
    # Test with thread ID
    error = ThreadManagerError("Thread error with ID", thread_id="thread123")
    assert error.details["thread_id"] == "thread123"


def test_file_error():
    """Test the FileError class."""
    # Test basic error
    error = FileError("File error message")
    assert str(error) == "File error message"
    assert error.code == "FileError"
    assert "file_path" not in error.details
    
    # Test with file path
    error = FileError("File error with path", file_path="/path/to/file.txt")
    assert error.details["file_path"] == "/path/to/file.txt"


def test_api_error():
    """Test the APIError class."""
    # Test basic error
    error = APIError("API error message")
    assert str(error) == "API error message"
    assert error.code == "APIError"
    assert "status_code" not in error.details
    assert "endpoint" not in error.details
    
    # Test with status code
    error = APIError("API error with status", status_code=404)
    assert error.details["status_code"] == 404
    
    # Test with endpoint
    error = APIError("API error with endpoint", endpoint="/api/users")
    assert error.details["endpoint"] == "/api/users"
    
    # Test with both
    error = APIError("API error with both", status_code=404, endpoint="/api/users")
    assert error.details["status_code"] == 404
    assert error.details["endpoint"] == "/api/users"


def test_exception_chaining():
    """Test exception chaining."""
    try:
        try:
            raise ValueError("Original error")
        except ValueError as e:
            raise DatabaseError("Database wrapper error", query="SELECT 1") from e
    except DatabaseError as db_error:
        assert str(db_error) == "Database wrapper error"
        assert db_error.details["query"] == "SELECT 1"
        assert db_error.__cause__ is not None
        assert str(db_error.__cause__) == "Original error"
