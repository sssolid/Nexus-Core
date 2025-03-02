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

# Type variables for function overloading
T = TypeVar("T")
R = TypeVar("R")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    })


class DatabaseManager(NexusManager):
    """Manages database connections and operations.
    
    The Database Manager provides a centralized way to interact with the database,
    handling connection pooling, session management, and transaction control.
    It abstracts the underlying database technology and provides a consistent
    interface for other components to use.
    """
    
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        """Initialize the Database Manager.
        
        Args:
            config_manager: The Configuration Manager to use for database settings.
            logger_manager: The Logging Manager to use for logging.
        """
        super().__init__(name="DatabaseManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("database_manager")
        
        # Database engine and session factories
        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._async_session_factory: Optional[sessionmaker] = None
        
        # Track active sessions
        self._active_sessions: Set[Session] = set()
        self._active_sessions_lock = threading.RLock()
        
        # Database connection info
        self._db_type: str = "postgresql"  # sqlite, postgresql, mysql, etc.
        self._db_url: Optional[str] = None
        self._db_async_url: Optional[str] = None
        self._pool_size: int = 5
        self._max_overflow: int = 10
        self._pool_recycle: int = 3600  # Recycle connections after 1 hour
        self._echo: bool = False  # Log SQL statements
        
        # Metrics
        self._queries_total: int = 0
        self._queries_failed: int = 0
        self._query_times: List[float] = []  # Track the last 100 query times
        self._metrics_lock = threading.RLock()
    
    def initialize(self) -> None:
        """Initialize the Database Manager.
        
        Sets up database connections based on configuration.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get database configuration
            db_config = self._config_manager.get("database", {})
            self._db_type = db_config.get("type", "postgresql").lower()
            
            host = db_config.get("host", "localhost")
            port = db_config.get("port", self._get_default_port(self._db_type))
            name = db_config.get("name", "nexus_core")
            user = db_config.get("user", "")
            password = db_config.get("password", "")
            
            self._pool_size = db_config.get("pool_size", 5)
            self._max_overflow = db_config.get("max_overflow", 10)
            self._pool_recycle = db_config.get("pool_recycle", 3600)
            self._echo = db_config.get("echo", False)
            
            # Construct database URL
            if self._db_type == "sqlite":
                # For SQLite, the name is the file path
                self._db_url = f"sqlite:///{name}"
                self._db_async_url = f"sqlite+aiosqlite:///{name}"
            else:
                # For other databases, construct a URL
                self._db_url = URL.create(
                    self._db_type,
                    username=user,
                    password=password,
                    host=host,
                    port=port,
                    database=name,
                )
                
                # Construct async URL (not all dialects support async)
                if self._db_type == "postgresql":
                    self._db_async_url = URL.create(
                        "postgresql+asyncpg",
                        username=user,
                        password=password,
                        host=host,
                        port=port,
                        database=name,
                    )
            
            # Create database engines
            self._engine = create_engine(
                self._db_url,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_recycle=self._pool_recycle,
                echo=self._echo,
            )
            
            if self._db_async_url:
                self._async_engine = create_async_engine(
                    self._db_async_url,
                    echo=self._echo,
                    pool_size=self._pool_size,
                    max_overflow=self._max_overflow,
                    pool_recycle=self._pool_recycle,
                )
            
            # Create session factories
            self._session_factory = sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )
            
            if self._async_engine:
                self._async_session_factory = sessionmaker(
                    bind=self._async_engine,
                    expire_on_commit=False,
                    class_=AsyncSession,
                )
            
            # Set up event listeners for metrics
            event.listen(self._engine, "before_cursor_execute", self._before_cursor_execute)
            event.listen(self._engine, "after_cursor_execute", self._after_cursor_execute)
            
            # Test database connection
            with self._engine.connect() as connection:
                # Execute a simple query to test the connection
                connection.execute(sqlalchemy.text("SELECT 1"))
            
            # Register for config changes
            self._config_manager.register_listener("database", self._on_config_changed)
            
            self._logger.info(
                f"Database Manager initialized with {self._db_type} database",
                extra={"host": host, "port": port, "database": name},
            )
            
            self._initialized = True
            self._healthy = True
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Database Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize DatabaseManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _get_default_port(self, db_type: str) -> int:
        """Get the default port for a database type.
        
        Args:
            db_type: The type of database.
        
        Returns:
            int: The default port for the database type.
        """
        default_ports = {
            "postgresql": 5432,
            "mysql": 3306,
            "mariadb": 3306,
            "oracle": 1521,
            "mssql": 1433,
            "sqlite": 0,  # SQLite doesn't use a port
        }
        
        return default_ports.get(db_type, 0)
    
    @contextlib.contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Get a database session for transactional operations.
        
        This context manager provides a session that is automatically committed
        on success or rolled back on exception.
        
        Yields:
            Session: A SQLAlchemy Session object.
            
        Raises:
            DatabaseError: If a database error occurs.
        """
        if not self._initialized or not self._session_factory:
            raise DatabaseError("Database Manager not initialized")
        
        session = self._session_factory()
        
        # Track the session
        with self._active_sessions_lock:
            self._active_sessions.add(session)
        
        try:
            yield session
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Database error: {str(e)}")
            raise DatabaseError(f"Database error: {str(e)}") from e
        except Exception as e:
            session.rollback()
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Error during database operation: {str(e)}")
            raise
        finally:
            session.close()
            # Remove the session from tracking
            with self._active_sessions_lock:
                self._active_sessions.discard(session)
    
    async def async_session(self) -> AsyncSession:
        """Get an async database session for transactional operations.
        
        Use this as an async context manager:
        
        ```python
        async with db_manager.async_session() as session:
            # Use session here
        ```
        
        Returns:
            AsyncSession: An async SQLAlchemy Session object.
            
        Raises:
            DatabaseError: If async database is not supported or not initialized.
        """
        if not self._initialized or not self._async_session_factory:
            raise DatabaseError("Async database not initialized")
        
        return self._async_session_factory()
    
    def execute(self, statement: Any) -> List[Dict[str, Any]]:
        """Execute a SQLAlchemy statement and return the results as dictionaries.
        
        Args:
            statement: A SQLAlchemy statement to execute.
            
        Returns:
            List[Dict[str, Any]]: The query results as a list of dictionaries.
            
        Raises:
            DatabaseError: If a database error occurs.
        """
        if not self._initialized or not self._engine:
            raise DatabaseError("Database Manager not initialized")
        
        try:
            with self._engine.connect() as connection:
                result = connection.execute(statement)
                # Convert to dictionaries
                return [dict(row._mapping) for row in result]
        
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Database error: {str(e)}")
            raise DatabaseError(f"Database error: {str(e)}") from e
    
    def execute_raw(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a raw SQL statement and return the results as dictionaries.
        
        Args:
            sql: A SQL statement to execute.
            params: Optional parameters for the SQL statement.
            
        Returns:
            List[Dict[str, Any]]: The query results as a list of dictionaries.
            
        Raises:
            DatabaseError: If a database error occurs.
        """
        if not self._initialized or not self._engine:
            raise DatabaseError("Database Manager not initialized")
        
        try:
            with self._engine.connect() as connection:
                result = connection.execute(sqlalchemy.text(sql), params or {})
                # Convert to dictionaries
                return [dict(row._mapping) for row in result]
        
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Database error: {str(e)}")
            raise DatabaseError(f"Database error: {str(e)}", query=sql) from e
    
    async def execute_async(self, statement: Any) -> List[Dict[str, Any]]:
        """Execute a SQLAlchemy statement asynchronously and return the results as dictionaries.
        
        Args:
            statement: A SQLAlchemy statement to execute.
            
        Returns:
            List[Dict[str, Any]]: The query results as a list of dictionaries.
            
        Raises:
            DatabaseError: If a database error occurs or async is not supported.
        """
        if not self._initialized or not self._async_engine:
            raise DatabaseError("Async database not initialized")
        
        try:
            async with self._async_engine.connect() as connection:
                result = await connection.execute(statement)
                # Convert to dictionaries
                return [dict(row._mapping) for row in result]
        
        except SQLAlchemyError as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Database error: {str(e)}")
            raise DatabaseError(f"Database error: {str(e)}") from e
        
        except Exception as e:
            with self._metrics_lock:
                self._queries_failed += 1
            self._logger.error(f"Error during async database operation: {str(e)}")
            raise
    
    def create_tables(self) -> None:
        """Create all tables defined in the Base class.
        
        Raises:
            DatabaseError: If the tables cannot be created.
        """
        if not self._initialized or not self._engine:
            raise DatabaseError("Database Manager not initialized")
        
        try:
            Base.metadata.create_all(self._engine)
            self._logger.info("Created database tables")
        
        except SQLAlchemyError as e:
            self._logger.error(f"Failed to create tables: {str(e)}")
            raise DatabaseError(f"Failed to create tables: {str(e)}") from e
    
    async def create_tables_async(self) -> None:
        """Create all tables defined in the Base class asynchronously.
        
        Raises:
            DatabaseError: If the tables cannot be created or async is not supported.
        """
        if not self._initialized or not self._async_engine:
            raise DatabaseError("Async database not initialized")
        
        try:
            async with self._async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self._logger.info("Created database tables asynchronously")
        
        except SQLAlchemyError as e:
            self._logger.error(f"Failed to create tables asynchronously: {str(e)}")
            raise DatabaseError(f"Failed to create tables asynchronously: {str(e)}") from e
    
    def check_connection(self) -> bool:
        """Check if the database connection is working.
        
        Returns:
            bool: True if the connection is working, False otherwise.
        """
        if not self._initialized or not self._engine:
            return False
        
        try:
            with self._engine.connect() as connection:
                connection.execute(sqlalchemy.text("SELECT 1"))
            return True
        
        except SQLAlchemyError:
            return False
    
    def get_engine(self) -> Optional[Engine]:
        """Get the SQLAlchemy engine.
        
        Returns:
            Optional[Engine]: The SQLAlchemy engine, or None if not initialized.
        """
        return self._engine
    
    def get_async_engine(self) -> Optional[AsyncEngine]:
        """Get the SQLAlchemy async engine.
        
        Returns:
            Optional[AsyncEngine]: The SQLAlchemy async engine, or None if not available.
        """
        return self._async_engine
    
    def _before_cursor_execute(
        self, 
        conn: Connection, 
        cursor: Any, 
        statement: str, 
        parameters: Any, 
        context: Any, 
        executemany: bool,
    ) -> None:
        """Event hook called before executing a query.
        
        Args:
            conn: The SQLAlchemy connection.
            cursor: The database cursor.
            statement: The SQL statement.
            parameters: The query parameters.
            context: The execution context.
            executemany: Whether this is an executemany operation.
        """
        # Store the start time in the connection info
        context._query_start_time = time.time()
    
    def _after_cursor_execute(
        self, 
        conn: Connection, 
        cursor: Any, 
        statement: str, 
        parameters: Any, 
        context: Any, 
        executemany: bool,
    ) -> None:
        """Event hook called after executing a query.
        
        Args:
            conn: The SQLAlchemy connection.
            cursor: The database cursor.
            statement: The SQL statement.
            parameters: The query parameters.
            context: The execution context.
            executemany: Whether this is an executemany operation.
        """
        # Calculate the query time
        query_time = time.time() - context._query_start_time
        
        with self._metrics_lock:
            self._queries_total += 1
            
            # Keep only the last 100 query times
            self._query_times.append(query_time)
            if len(self._query_times) > 100:
                self._query_times.pop(0)
            
            # Log slow queries
            if query_time > 1.0:  # 1 second
                self._logger.warning(
                    f"Slow query: {query_time:.3f}s",
                    extra={
                        "query_time": query_time,
                        "statement": statement[:1000],  # Truncate long queries
                    },
                )
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for the database.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key.startswith("database."):
            self._logger.warning(
                f"Configuration change to {key} requires restart to take effect",
                extra={"key": key},
            )
    
    def shutdown(self) -> None:
        """Shut down the Database Manager.
        
        Closes all connections and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Database Manager")
            
            # Close any active sessions
            with self._active_sessions_lock:
                for session in list(self._active_sessions):
                    try:
                        session.close()
                    except:
                        pass
                self._active_sessions.clear()
            
            # Dispose of engines
            if self._engine:
                self._engine.dispose()
            
            if self._async_engine:
                # Async engines need to be disposed differently
                pass  # No direct way to dispose async engines, they will be garbage collected
            
            # Unregister config listener
            self._config_manager.unregister_listener("database", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Database Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Database Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down DatabaseManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Database Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Database Manager.
        """
        status = super().status()
        
        if self._initialized:
            # Get connection pool status
            pool_status = {}
            if self._engine:
                try:
                    pool = self._engine.pool
                    pool_status = {
                        "size": pool.size(),
                        "checkedin": pool.checkedin(),
                        "checkedout": pool.checkedout(),
                        "overflow": getattr(pool, "overflow", 0),
                    }
                except:
                    pool_status = {"error": "Failed to get pool status"}
            
            # Calculate query statistics
            with self._metrics_lock:
                query_stats = {
                    "total": self._queries_total,
                    "failed": self._queries_failed,
                    "success_rate": (
                        (self._queries_total - self._queries_failed) / self._queries_total * 100
                        if self._queries_total > 0 else 100.0
                    ),
                }
                
                # Calculate average query time
                if self._query_times:
                    avg_time = sum(self._query_times) / len(self._query_times)
                    max_time = max(self._query_times)
                    query_stats.update({
                        "avg_time_ms": round(avg_time * 1000, 2),
                        "max_time_ms": round(max_time * 1000, 2),
                        "last_queries": len(self._query_times),
                    })
            
            # Check connection
            connection_ok = self.check_connection()
            
            status.update({
                "database": {
                    "type": self._db_type,
                    "connection_ok": connection_ok,
                    "async_supported": self._async_engine is not None,
                },
                "pool": pool_status,
                "sessions": {
                    "active": len(self._active_sessions),
                },
                "queries": query_stats,
            })
        
        return status
