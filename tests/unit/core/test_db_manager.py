"""Unit tests for the Database Manager."""

import pytest
import tempfile
from unittest.mock import MagicMock, patch
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base

from nexus_core.core.database_manager import DatabaseManager, Base
from nexus_core.utils.exceptions import DatabaseError, ManagerInitializationError


# Create a simple test model
class TestModel(Base):
    __tablename__ = 'test_models'
    
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(50), nullable=False)
    value = sa.Column(sa.Integer, nullable=True)
    
    def __repr__(self):
        return f"<TestModel(id={self.id}, name='{self.name}')>"


@pytest.fixture
def db_config():
    """Create a database configuration for testing."""
    return {
        "type": "sqlite",
        "name": ":memory:",
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 3600,
        "echo": False
    }


@pytest.fixture
def config_manager_mock(db_config):
    """Create a mock ConfigManager for the DatabaseManager."""
    config_manager = MagicMock()
    config_manager.get.return_value = db_config
    return config_manager


@pytest.fixture
def db_manager(config_manager_mock):
    """Create a DatabaseManager for testing with SQLite in-memory database."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(config_manager_mock, logger_manager)
    db_mgr.initialize()
    
    # Create the test tables
    db_mgr.create_tables()
    
    yield db_mgr
    db_mgr.shutdown()


def test_db_manager_initialization(config_manager_mock):
    """Test that the DatabaseManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(config_manager_mock, logger_manager)
    db_mgr.initialize()
    
    assert db_mgr.initialized
    assert db_mgr.healthy
    assert db_mgr._engine is not None
    
    # Test connection
    assert db_mgr.check_connection()
    
    db_mgr.shutdown()
    assert not db_mgr.initialized


def test_session_context_manager(db_manager):
    """Test using the session context manager."""
    # Add a test record
    with db_manager.session() as session:
        model = TestModel(name="Test Record", value=42)
        session.add(model)
    
    # Verify record was added
    with db_manager.session() as session:
        result = session.query(TestModel).filter_by(name="Test Record").first()
        assert result is not None
        assert result.name == "Test Record"
        assert result.value == 42


def test_execute_query(db_manager):
    """Test executing a query directly."""
    # Add a test record
    with db_manager.session() as session:
        model = TestModel(name="Query Test", value=123)
        session.add(model)
    
    # Execute a select query
    query = sa.select(TestModel).where(TestModel.name == "Query Test")
    results = db_manager.execute(query)
    
    assert len(results) == 1
    assert results[0]["name"] == "Query Test"
    assert results[0]["value"] == 123


def test_execute_raw_sql(db_manager):
    """Test executing raw SQL queries."""
    # Add a test record
    with db_manager.session() as session:
        model = TestModel(name="Raw SQL Test", value=456)
        session.add(model)
    
    # Execute a raw SQL query
    results = db_manager.execute_raw(
        "SELECT * FROM test_models WHERE name = :name",
        params={"name": "Raw SQL Test"}
    )
    
    assert len(results) == 1
    assert results[0]["name"] == "Raw SQL Test"
    assert results[0]["value"] == 456


def test_session_rollback_on_error(db_manager):
    """Test that session is rolled back on error."""
    # Add a test record to ensure we have a valid session
    with db_manager.session() as session:
        model = TestModel(name="Rollback Test", value=789)
        session.add(model)
    
    # Attempt an operation that should fail
    try:
        with db_manager.session() as session:
            # This should succeed
            model1 = TestModel(name="Will Roll Back", value=999)
            session.add(model1)
            
            # This should fail (NULL value in a non-nullable column)
            model2 = TestModel(name=None, value=111)
            session.add(model2)
    except DatabaseError:
        pass  # Expected exception
    
    # Verify the failed transaction was rolled back
    with db_manager.session() as session:
        result = session.query(TestModel).filter_by(name="Will Roll Back").first()
        assert result is None  # Should not exist due to rollback


def test_engine_properties(db_manager):
    """Test accessing engine properties."""
    engine = db_manager.get_engine()
    assert engine is not None
    assert engine.dialect.name == "sqlite"
    
    # Check if async engine exists (should be None for SQLite)
    async_engine = db_manager.get_async_engine()
    assert async_engine is None


def test_error_handling(db_manager):
    """Test error handling in database operations."""
    # Test invalid query
    with pytest.raises(DatabaseError):
        db_manager.execute_raw("SELECT * FROM nonexistent_table")
    
    # Test execute with invalid statement
    invalid_stmt = "not a valid SQLAlchemy statement"
    with pytest.raises(DatabaseError):
        db_manager.execute(invalid_stmt)


def test_db_manager_initialization_failure():
    """Test that the DatabaseManager handles initialization failures gracefully."""
    config_manager = MagicMock()
    # Configure an invalid database type
    config_manager.get.return_value = {"type": "invalid_db"}
    
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(config_manager, logger_manager)
    
    with pytest.raises(ManagerInitializationError):
        db_mgr.initialize()


def test_db_manager_status(db_manager):
    """Test getting status from DatabaseManager."""
    status = db_manager.status()
    
    assert status["name"] == "DatabaseManager"
    assert status["initialized"] is True
    assert "database" in status
    assert status["database"]["type"] == "sqlite"
    assert status["database"]["connection_ok"] is True
    assert "sessions" in status
    assert "queries" in status


@pytest.mark.parametrize("db_type,expected_port", [
    ("postgresql", 5432),
    ("mysql", 3306),
    ("mariadb", 3306),
    ("oracle", 1521),
    ("mssql", 1433),
    ("sqlite", 0),
    ("unknown", 0),
])
def test_default_port_selection(db_type, expected_port):
    """Test default port selection for different database types."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(MagicMock(), logger_manager)
    assert db_mgr._get_default_port(db_type) == expected_port


def test_operations_without_initialization():
    """Test database operations before initialization."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(MagicMock(), logger_manager)
    
    with pytest.raises(DatabaseError):
        with db_mgr.session():
            pass
    
    with pytest.raises(DatabaseError):
        db_mgr.execute(sa.text("SELECT 1"))
