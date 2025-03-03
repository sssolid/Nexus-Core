import pytest
import tempfile
from unittest.mock import MagicMock, patch
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base
from nexus_core.core.database_manager import DatabaseManager, Base
from nexus_core.utils.exceptions import DatabaseError, ManagerInitializationError
class TestModel(Base):
    __tablename__ = 'test_models'
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(50), nullable=False)
    value = sa.Column(sa.Integer, nullable=True)
    def __repr__(self):
        return f"<TestModel(id={self.id}, name='{self.name}')>"
@pytest.fixture
def db_config():
    return {'type': 'sqlite', 'name': ':memory:', 'pool_size': 5, 'max_overflow': 10, 'pool_recycle': 3600, 'echo': False}
@pytest.fixture
def config_manager_mock(db_config):
    config_manager = MagicMock()
    config_manager.get.return_value = db_config
    return config_manager
@pytest.fixture
def db_manager(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(config_manager_mock, logger_manager)
    db_mgr.initialize()
    db_mgr.create_tables()
    yield db_mgr
    db_mgr.shutdown()
def test_db_manager_initialization(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(config_manager_mock, logger_manager)
    db_mgr.initialize()
    assert db_mgr.initialized
    assert db_mgr.healthy
    assert db_mgr._engine is not None
    assert db_mgr.check_connection()
    db_mgr.shutdown()
    assert not db_mgr.initialized
def test_session_context_manager(db_manager):
    with db_manager.session() as session:
        model = TestModel(name='Test Record', value=42)
        session.add(model)
    with db_manager.session() as session:
        result = session.query(TestModel).filter_by(name='Test Record').first()
        assert result is not None
        assert result.name == 'Test Record'
        assert result.value == 42
def test_execute_query(db_manager):
    with db_manager.session() as session:
        model = TestModel(name='Query Test', value=123)
        session.add(model)
    query = sa.select(TestModel).where(TestModel.name == 'Query Test')
    results = db_manager.execute(query)
    assert len(results) == 1
    assert results[0]['name'] == 'Query Test'
    assert results[0]['value'] == 123
def test_execute_raw_sql(db_manager):
    with db_manager.session() as session:
        model = TestModel(name='Raw SQL Test', value=456)
        session.add(model)
    results = db_manager.execute_raw('SELECT * FROM test_models WHERE name = :name', params={'name': 'Raw SQL Test'})
    assert len(results) == 1
    assert results[0]['name'] == 'Raw SQL Test'
    assert results[0]['value'] == 456
def test_session_rollback_on_error(db_manager):
    with db_manager.session() as session:
        model = TestModel(name='Rollback Test', value=789)
        session.add(model)
    try:
        with db_manager.session() as session:
            model1 = TestModel(name='Will Roll Back', value=999)
            session.add(model1)
            model2 = TestModel(name=None, value=111)
            session.add(model2)
    except DatabaseError:
        pass
    with db_manager.session() as session:
        result = session.query(TestModel).filter_by(name='Will Roll Back').first()
        assert result is None
def test_engine_properties(db_manager):
    engine = db_manager.get_engine()
    assert engine is not None
    assert engine.dialect.name == 'sqlite'
    async_engine = db_manager.get_async_engine()
    assert async_engine is None
def test_error_handling(db_manager):
    with pytest.raises(DatabaseError):
        db_manager.execute_raw('SELECT * FROM nonexistent_table')
    invalid_stmt = 'not a valid SQLAlchemy statement'
    with pytest.raises(DatabaseError):
        db_manager.execute(invalid_stmt)
def test_db_manager_initialization_failure():
    config_manager = MagicMock()
    config_manager.get.return_value = {'type': 'invalid_db'}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(config_manager, logger_manager)
    with pytest.raises(ManagerInitializationError):
        db_mgr.initialize()
def test_db_manager_status(db_manager):
    status = db_manager.status()
    assert status['name'] == 'DatabaseManager'
    assert status['initialized'] is True
    assert 'database' in status
    assert status['database']['type'] == 'sqlite'
    assert status['database']['connection_ok'] is True
    assert 'sessions' in status
    assert 'queries' in status
@pytest.mark.parametrize('db_type,expected_port', [('postgresql', 5432), ('mysql', 3306), ('mariadb', 3306), ('oracle', 1521), ('mssql', 1433), ('sqlite', 0), ('unknown', 0)])
def test_default_port_selection(db_type, expected_port):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(MagicMock(), logger_manager)
    assert db_mgr._get_default_port(db_type) == expected_port
def test_operations_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(MagicMock(), logger_manager)
    with pytest.raises(DatabaseError):
        with db_mgr.session():
            pass
    with pytest.raises(DatabaseError):
        db_mgr.execute(sa.text('SELECT 1'))