"""Integration tests for the API subsystem."""

import os
import pytest
import tempfile
import json
from unittest.mock import MagicMock, patch
import asyncio
from httpx import AsyncClient

try:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
except ImportError:
    # Mark all tests as skipped if FastAPI is not installed
    pytest.skip("FastAPI not installed", allow_module_level=True)

from nexus_core.core.api_manager import APIManager
from nexus_core.core.security_manager import SecurityManager, UserRole


@pytest.fixture
def mock_managers():
    """Create mock managers for the API."""
    config_manager = MagicMock()
    config_manager.get.return_value = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8000,
        "cors": {
            "origins": ["*"],
            "methods": ["*"],
            "headers": ["*"]
        },
        "rate_limit": {
            "enabled": False
        }
    }
    
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    # Mock security manager with user authentication
    security_manager = MagicMock(spec=SecurityManager)
    security_manager.authenticate_user.return_value = {
        "user_id": "test_user_id",
        "username": "testuser",
        "email": "test@example.com",
        "roles": ["admin"],
        "access_token": "test_access_token",
        "token_type": "bearer",
        "expires_in": 1800,
        "refresh_token": "test_refresh_token"
    }
    security_manager.verify_token.return_value = {
        "sub": "test_user_id",
        "jti": "test_jti"
    }
    security_manager.get_user_info.return_value = {
        "id": "test_user_id",
        "username": "testuser",
        "email": "test@example.com",
        "roles": ["admin"],
        "active": True,
        "created_at": "2025-01-01T00:00:00",
        "last_login": "2025-01-01T12:00:00"
    }
    security_manager.has_permission.return_value = True
    
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    
    # Registry containing the app_core and other managers
    registry = {
        "app_core": MagicMock(),
        "config": config_manager,
        "security": security_manager,
        "event_bus": event_bus_manager,
        "thread_manager": thread_manager,
    }
    
    # App core status mock
    registry["app_core"].status.return_value = {
        "name": "ApplicationCore",
        "initialized": True,
        "healthy": True,
        "version": "0.1.0",
        "managers": {
            "config": {"initialized": True, "healthy": True},
            "logging": {"initialized": True, "healthy": True},
            "event_bus": {"initialized": True, "healthy": True}
        }
    }
    
    return (config_manager, logger_manager, security_manager, event_bus_manager, 
            thread_manager, registry)


@pytest.fixture
def api_manager(mock_managers):
    """Create an APIManager for testing."""
    config_manager, logger_manager, security_manager, event_bus_manager, thread_manager, registry = mock_managers
    
    api_mgr = APIManager(
        config_manager, 
        logger_manager, 
        security_manager, 
        event_bus_manager, 
        thread_manager,
        registry
    )
    api_mgr.initialize()
    
    yield api_mgr
    api_mgr.shutdown()


@pytest.fixture
def test_client(api_manager):
    """Create a TestClient for the API."""
    app = api_manager._app
    return TestClient(app)


@pytest.mark.asyncio
async def test_async_client(api_manager):
    """Test the API with an async client."""
    app = api_manager._app
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "name" in response.json()
        assert response.json()["name"] == "Nexus Core API"


def test_api_root_endpoint(test_client):
    """Test the API root endpoint."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "Nexus Core API",
        "version": "0.1.0",
        "docs_url": "/api/docs"
    }


def test_health_check_endpoint(test_client):
    """Test the health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "healthy": True
    }


def test_authentication_endpoints(test_client, mock_managers):
    """Test the authentication endpoints."""
    # Get the security manager mock
    security_manager = mock_managers[2]
    
    # Test login
    response = test_client.post(
        "/api/v1/auth/token",
        data={
            "username": "testuser",
            "password": "password123"
        }
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"
    
    # Verify authenticate_user was called with correct args
    security_manager.authenticate_user.assert_called_with("testuser", "password123")
    
    # Test token refresh
    response = test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "test_refresh_token"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    
    # Verify refresh_token was called with correct args
    security_manager.refresh_token.assert_called_with("test_refresh_token")
    
    # Test token revocation
    response = test_client.post(
        "/api/v1/auth/revoke",
        json={"token": "test_access_token"}
    )
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Verify revoke_token was called with correct args
    security_manager.revoke_token.assert_called_with("test_access_token")


def test_protected_endpoints(test_client, mock_managers):
    """Test endpoints that require authentication."""
    # Get the security manager mock
    security_manager = mock_managers[2]
    
    # Set up authentication token
    token = "test_access_token"
    
    # Test user info endpoint
    response = test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    
    # Verify get_user_info was called
    security_manager.get_user_info.assert_called()
    
    # Test system status endpoint (requires system.view permission)
    response = test_client.get(
        "/api/v1/system/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert "name" in response.json()
    assert response.json()["initialized"] is True
    
    # Try without authentication token
    response = test_client.get("/api/v1/system/status")
    assert response.status_code == 401  # Unauthorized
    
    # Test API error handling  
    security_manager.has_permission.return_value = False
    
    response = test_client.get(
        "/api/v1/system/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403  # Forbidden


def test_api_endpoints_availability(test_client):
    """Test that all expected API endpoints are available."""
    # Set up authentication token
    token = "test_access_token"
    auth_header = {"Authorization": f"Bearer {token}"}
    
    # System endpoints
    response = test_client.get("/api/v1/system/status", headers=auth_header)
    assert response.status_code == 200
    
    # Config endpoints
    response = test_client.get("/api/v1/system/config/app.name", headers=auth_header)
    assert response.status_code in (200, 404)  # May return 404 if config key not found
    
    # Users endpoints
    response = test_client.get("/api/v1/users/", headers=auth_header)
    assert response.status_code == 200
    
    # Plugins endpoints
    response = test_client.get("/api/v1/plugins/", headers=auth_header)
    assert response.status_code in (200, 503)  # May return 503 if plugin manager not available
    
    # Monitoring endpoints
    response = test_client.get("/api/v1/monitoring/alerts", headers=auth_header)
    assert response.status_code in (200, 503)  # May return 503 if monitoring manager not available


def test_custom_endpoint_registration(api_manager, test_client):
    """Test registering a custom API endpoint."""
    # Define a custom endpoint function
    async def custom_endpoint():
        return {"message": "This is a custom endpoint"}
    
    # Register the endpoint
    result = api_manager.register_api_endpoint(
        path="/custom",
        method="get",
        endpoint=custom_endpoint,
        tags=["Custom"],
        summary="Custom test endpoint"
    )
    assert result is True
    
    # Test the endpoint
    response = test_client.get("/api/v1/custom")
    assert response.status_code == 200
    assert response.json() == {"message": "This is a custom endpoint"}


def test_api_manager_status(api_manager):
    """Test getting status from APIManager."""
    status = api_manager.status()
    
    assert status["name"] == "APIManager"
    assert status["initialized"] is True
    assert "api" in status
    assert status["api"]["enabled"] is True
    assert "endpoints" in status
