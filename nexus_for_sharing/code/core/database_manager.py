from __future__ import annotations
import contextlib
import functools
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple, TypeVar, Union, cast
import sqlalchemy
from sqlalchemy import URL, Connection, Engine, MetaData, create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import DatabaseError, ManagerInitializationError, ManagerShutdownError
T = TypeVar('T')
R = TypeVar('R')
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={'ix': 'ix_%(column_0_label)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s', 'ck': 'ck_%(table_name)s_%(constraint_name)s', 'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s'})
class DatabaseManager(NexusManager):
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        super().__init__(name='DatabaseManager')
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger('database_manager')
        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._async_session_factory: Optional[sessionmaker] = None
        self._active_sessions: Set[Session] = set()
        self._active_sessions_lock = threading.RLock()
        self._db_type: str = 'postgresql'
        self._db_url: Optional[str] = None
        self._db_async_url: Optional[str] = None
        self._pool_size: int = 5
        self._max_overflow: int = 10
        self._pool_recycle: int = 3600
        self._echo: bool = False
        self._queries_total: int = 0
        self._queries_failed: int = 0
        self._query_times: List[float] = []
        self._metrics_lock = threading.RLock()
    def initialize(self) -> None:
        try:
            db_config = self._config_manager.get('database', {})
            self._db_type = db_config.get('type', 'postgresql').lower()
            host = db_config.get('host', 'localhost')
            port = db_config.get('port', self._get_default_port(self._db_type))
            name = db_config.get('name', 'nexus_core')
            user = db_config.get('user', '')
            password = db_config.get('password', '')
            self._pool_size = db_config.get('pool_size', 5)
            self._max_overflow = db_config.get('max_overflow', 10)
            self._pool_recycle = db_config.get('pool_recycle', 3600)
            self._echo = db_config.get('echo', False)
            if self._db_type == 'sqlite':
                self._db_url = f'sqlite:///{name}'
                self._db_async_url = f'sqlite+aiosqlite:///{name}'
            else:
                self._db_url = URL.create(self._db_type, username=user, password=password, host=host, port=port, database=name)
                if self._db_type == 'postgresql':
                    self._db_async_url = URL.create('postgresql+asyncpg', username=user, password=password, host=host, port=port, database=name)
            self._engine = create_engine(self._db_url, pool_size=self._pool_size, max_overflow=self._max_overflow, pool_recycle=self._pool_recycle, echo=self._echo)
            if self._db_async_url:
                self._async_engine = create_async_engine(self._db_async_url, echo=self._echo, pool_size=self._pool_size, max_overflow=self._max_overflow, pool_recycle=self._pool_recycle)
            self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
            if self._async_engine:
                self._async_session_factory = sessionmaker(bind=self._async_engine, expire_on_commit=False, class_=AsyncSession)
            event.listen(self._engine, 'before_cursor_execute', self._before_cursor_execute)
            event.listen(self._engine, 'after_cursor_execute', self._after_cursor_execute)
            with self._engine.connect() as connection:
                connection.execute(sqlalchemy.text('SELECT 1'))
            self._config_manager.register_listener('database', self._on_config_changed)
            self._logger.info(f'Database Manager initialized with {self._db_type} database', extra={'host': host, 'port': port, 'database': name})
            self._initialized = True
            self._healthy = True
        except Exception as e:
            self._logger.error(f'Failed to initialize Database Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize DatabaseManager: {str(e)}', manager_name=self.name) from e
    def _get_default_port(self, db_type: str) -> int:
        default_ports = {'postgresql': 5432, 'mysql': 3306, 'mariadb': 3306, 'oracle': 1521, 'mssql': 1433, 'sqlite': 0}
        return default_ports.get(db_type, 0)
    @contextlib.contextmanager
    def session(self) -> Generator[Session, None, None]:
        if not self._initialized or not self._session_factory:
            raise DatabaseError('Database Manager not initialized')
        session = self._session_factory()
        with self._active_sessions_lock:
            self._active_sessions.add(session)
        try:
            yield session
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Database error: {str(e)}')
            raise DatabaseError(f'Database error: {str(e)}') from e
        except Exception as e:
            session.rollback()
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Error during database operation: {str(e)}')
            raise
        finally:
            session.close()
            with self._active_sessions_lock:
                self._active_sessions.discard(session)
    async def async_session(self) -> AsyncSession:
        if not self._initialized or not self._async_session_factory:
            raise DatabaseError('Async database not initialized')
        return self._async_session_factory()
    def execute(self, statement: Any) -> List[Dict[str, Any]]:
        if not self._initialized or not self._engine:
            raise DatabaseError('Database Manager not initialized')
        try:
            with self._engine.connect() as connection:
                result = connection.execute(statement)
                return [dict(row._mapping) for row in result]
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Database error: {str(e)}')
            raise DatabaseError(f'Database error: {str(e)}') from e
    def execute_raw(self, sql: str, params: Optional[Dict[str, Any]]=None) -> List[Dict[str, Any]]:
        if not self._initialized or not self._engine:
            raise DatabaseError('Database Manager not initialized')
        try:
            with self._engine.connect() as connection:
                result = connection.execute(sqlalchemy.text(sql), params or {})
                return [dict(row._mapping) for row in result]
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Database error: {str(e)}')
            raise DatabaseError(f'Database error: {str(e)}', query=sql) from e
    async def execute_async(self, statement: Any) -> List[Dict[str, Any]]:
        if not self._initialized or not self._async_engine:
            raise DatabaseError('Async database not initialized')
        try:
            async with self._async_engine.connect() as connection:
                result = await connection.execute(statement)
                return [dict(row._mapping) for row in result]
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Database error: {str(e)}')
            raise DatabaseError(f'Database error: {str(e)}') from e
        except Exception as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f'Error during async database operation: {str(e)}')
            raise
    def create_tables(self) -> None:
        if not self._initialized or not self._engine:
            raise DatabaseError('Database Manager not initialized')
        try:
            Base.metadata.create_all(self._engine)
            self._logger.info('Created database tables')
        except SQLAlchemyError as e:
            self._logger.error(f'Failed to create tables: {str(e)}')
            raise DatabaseError(f'Failed to create tables: {str(e)}') from e
    async def create_tables_async(self) -> None:
        if not self._initialized or not self._async_engine:
            raise DatabaseError('Async database not initialized')
        try:
            async with self._async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self._logger.info('Created database tables asynchronously')
        except SQLAlchemyError as e:
            self._logger.error(f'Failed to create tables asynchronously: {str(e)}')
            raise DatabaseError(f'Failed to create tables asynchronously: {str(e)}') from e
    def check_connection(self) -> bool:
        if not self._initialized or not self._engine:
            return False
        try:
            with self._engine.connect() as connection:
                connection.execute(sqlalchemy.text('SELECT 1'))
            return True
        except SQLAlchemyError:
            return False
    def get_engine(self) -> Optional[Engine]:
        return self._engine
    def get_async_engine(self) -> Optional[AsyncEngine]:
        return self._async_engine
    def _before_cursor_execute(self, conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        context._query_start_time = time.time()
    def _after_cursor_execute(self, conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        query_time = time.time() - context._query_start_time
        with self._metrics_lock:
            self._queries_total += 1
            self._query_times.append(query_time)
            if len(self._query_times) > 100:
                self._query_times.pop(0)
            if query_time > 1.0:
                self._logger.warning(f'Slow query: {query_time:.3f}s', extra={'query_time': query_time, 'statement': statement[:1000]})
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key.startswith('database.'):
            self._logger.warning(f'Configuration change to {key} requires restart to take effect', extra={'key': key})
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down Database Manager')
            with self._active_sessions_lock:
                for session in list(self._active_sessions):
                    try:
                        session.close()
                    except:
                        pass
                self._active_sessions.clear()
            if self._engine:
                self._engine.dispose()
            if self._async_engine:
                pass
            self._config_manager.unregister_listener('database', self._on_config_changed)
            self._initialized = False
            self._healthy = False
            self._logger.info('Database Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down Database Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down DatabaseManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            pool_status = {}
            if self._engine:
                try:
                    pool = self._engine.pool
                    pool_status = {'size': pool.size(), 'checkedin': pool.checkedin(), 'checkedout': pool.checkedout(), 'overflow': getattr(pool, 'overflow', 0)}
                except:
                    pool_status = {'error': 'Failed to get pool status'}
            with self._metrics_lock:
                query_stats = {'total': self._queries_total, 'failed': self._queries_failed, 'success_rate': (self._queries_total - self._queries_failed) / self._queries_total * 100 if self._queries_total > 0 else 100.0}
                if self._query_times:
                    avg_time = sum(self._query_times) / len(self._query_times)
                    max_time = max(self._query_times)
                    query_stats.update({'avg_time_ms': round(avg_time * 1000, 2), 'max_time_ms': round(max_time * 1000, 2), 'last_queries': len(self._query_times)})
            connection_ok = self.check_connection()
            status.update({'database': {'type': self._db_type, 'connection_ok': connection_ok, 'async_supported': self._async_engine is not None}, 'pool': pool_status, 'sessions': {'active': len(self._active_sessions)}, 'queries': query_stats})
        return status