from __future__ import annotations

import concurrent.futures
import functools
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar, cast

from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError, ThreadManagerError

# Type variable for task results
T = TypeVar("T")
R = TypeVar("R")


class TaskStatus(Enum):
    """Status of a task in the thread pool."""
    
    PENDING = "pending"  # Task is queued but not yet running
    RUNNING = "running"  # Task is currently running
    COMPLETED = "completed"  # Task completed successfully
    FAILED = "failed"  # Task failed with an exception
    CANCELLED = "cancelled"  # Task was cancelled before completion


@dataclass
class TaskInfo:
    """Information about a task submitted to the thread pool."""
    
    task_id: str  # Unique identifier for the task
    name: str  # Human-readable name for the task
    status: TaskStatus = TaskStatus.PENDING  # Current status of the task
    created_at: float = field(default_factory=time.time)  # When the task was created
    started_at: Optional[float] = None  # When the task started running
    completed_at: Optional[float] = None  # When the task completed (success or failure)
    exception: Optional[Exception] = None  # Exception if the task failed
    submitter: str = "unknown"  # Who/what submitted the task
    priority: int = 0  # Priority (higher numbers run first)
    future: Optional[concurrent.futures.Future] = None  # Future object for the task
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional task metadata


class ThreadManager(NexusManager):
    """Manages application threading and concurrency.
    
    The Thread Manager provides a centralized way to run background tasks and
    concurrent operations, ensuring that the main application thread (particularly
    the UI thread) remains responsive. It manages a thread pool for executing
    tasks and provides features for monitoring task status and health.
    """
    
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        """Initialize the Thread Manager.
        
        Args:
            config_manager: The Configuration Manager to use for thread pool settings.
            logger_manager: The Logging Manager to use for logging.
        """
        super().__init__(name="ThreadManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("thread_manager")
        
        # Thread pool for background tasks
        self._thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._max_workers = 4
        self._thread_name_prefix = "nexus-worker"
        
        # Task tracking
        self._tasks: Dict[str, TaskInfo] = {}
        self._tasks_lock = threading.RLock()
        
        # Periodic task scheduling
        self._periodic_tasks: Dict[str, Tuple[float, Callable, List, Dict]] = {}
        self._periodic_stop_event = threading.Event()
        self._periodic_thread: Optional[threading.Thread] = None
        
        # Active tasks counter
        self._active_tasks = 0
        self._active_tasks_lock = threading.RLock()
    
    def initialize(self) -> None:
        """Initialize the Thread Manager.
        
        Sets up the thread pool based on configuration and starts the
        periodic task scheduler thread.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get configuration
            thread_config = self._config_manager.get("thread_pool", {})
            self._max_workers = thread_config.get("worker_threads", 4)
            self._thread_name_prefix = thread_config.get("thread_name_prefix", "nexus-worker")
            
            # Create thread pool
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix=self._thread_name_prefix,
            )
            
            # Start periodic task scheduler thread
            self._periodic_thread = threading.Thread(
                target=self._periodic_task_scheduler,
                name="periodic-scheduler",
                daemon=True,
            )
            self._periodic_thread.start()
            
            # Register for config changes
            self._config_manager.register_listener("thread_pool", self._on_config_changed)
            
            self._logger.info(f"Thread Manager initialized with {self._max_workers} workers")
            self._initialized = True
            self._healthy = True
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Thread Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize ThreadManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def submit_task(
        self,
        func: Callable[..., T],
        *args: Any,
        name: Optional[str] = None,
        submitter: str = "unknown",
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Submit a task to be executed in the thread pool.
        
        Args:
            func: The function to execute.
            *args: Positional arguments to pass to the function.
            name: Human-readable name for the task (for logging and monitoring).
            submitter: Who/what submitted the task (for logging and monitoring).
            priority: Priority of the task (higher numbers run first).
            metadata: Additional metadata for the task.
            **kwargs: Keyword arguments to pass to the function.
        
        Returns:
            str: A unique ID for the submitted task.
            
        Raises:
            ThreadManagerError: If the thread pool is not initialized or the task cannot be submitted.
        """
        if not self._initialized or self._thread_pool is None:
            raise ThreadManagerError(
                "Cannot submit tasks before initialization",
                thread_id=None,
            )
        
        # Generate task ID and name
        task_id = str(uuid.uuid4())
        task_name = name or f"task-{task_id[:8]}"
        
        # Create task info
        task_info = TaskInfo(
            task_id=task_id,
            name=task_name,
            status=TaskStatus.PENDING,
            submitter=submitter,
            priority=priority,
            metadata=metadata or {},
        )
        
        # Wrap the function to update task status
        @functools.wraps(func)
        def _task_wrapper(*args, **kwargs):
            with self._tasks_lock:
                if task_id in self._tasks:
                    self._tasks[task_id].status = TaskStatus.RUNNING
                    self._tasks[task_id].started_at = time.time()
            
            with self._active_tasks_lock:
                self._active_tasks += 1
            
            try:
                result = func(*args, **kwargs)
                
                with self._tasks_lock:
                    if task_id in self._tasks:
                        self._tasks[task_id].status = TaskStatus.COMPLETED
                        self._tasks[task_id].completed_at = time.time()
                
                return result
            
            except Exception as e:
                with self._tasks_lock:
                    if task_id in self._tasks:
                        self._tasks[task_id].status = TaskStatus.FAILED
                        self._tasks[task_id].exception = e
                        self._tasks[task_id].completed_at = time.time()
                
                self._logger.error(
                    f"Task {task_name} failed: {str(e)}",
                    extra={
                        "task_id": task_id,
                        "submitter": submitter,
                        "error": str(e),
                    },
                )
                
                # Re-raise the exception to be captured by the Future
                raise
            
            finally:
                with self._active_tasks_lock:
                    self._active_tasks -= 1
        
        try:
            # Submit the wrapped task to the thread pool
            future = self._thread_pool.submit(_task_wrapper, *args, **kwargs)
            task_info.future = future
            
            # Store task info
            with self._tasks_lock:
                self._tasks[task_id] = task_info
            
            self._logger.debug(
                f"Submitted task {task_name}",
                extra={
                    "task_id": task_id,
                    "submitter": submitter,
                    "priority": priority,
                },
            )
            
            return task_id
        
        except Exception as e:
            self._logger.error(
                f"Failed to submit task {task_name}: {str(e)}",
                extra={"submitter": submitter},
            )
            raise ThreadManagerError(
                f"Failed to submit task: {str(e)}",
                thread_id=task_id,
            ) from e
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task if it hasn't started yet.
        
        Args:
            task_id: The ID of the task to cancel.
        
        Returns:
            bool: True if the task was cancelled, False if it couldn't be cancelled.
        """
        if not self._initialized:
            return False
        
        with self._tasks_lock:
            if task_id not in self._tasks:
                return False
            
            task_info = self._tasks[task_id]
            
            if task_info.status != TaskStatus.PENDING:
                # Task already running, completed, or failed
                return False
            
            if task_info.future and task_info.future.cancel():
                task_info.status = TaskStatus.CANCELLED
                task_info.completed_at = time.time()
                self._logger.debug(f"Cancelled task {task_info.name}")
                return True
        
        return False
    
    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a task.
        
        Args:
            task_id: The ID of the task to get information about.
        
        Returns:
            Optional[Dict[str, Any]]: Information about the task, or None if not found.
        """
        if not self._initialized:
            return None
        
        with self._tasks_lock:
            if task_id not in self._tasks:
                return None
            
            task_info = self._tasks[task_id]
            
            # Return a dictionary representation of the task info
            result = {
                "task_id": task_info.task_id,
                "name": task_info.name,
                "status": task_info.status.value,
                "created_at": task_info.created_at,
                "started_at": task_info.started_at,
                "completed_at": task_info.completed_at,
                "submitter": task_info.submitter,
                "priority": task_info.priority,
                "metadata": task_info.metadata,
            }
            
            if task_info.exception:
                result["error"] = str(task_info.exception)
            
            return result
    
    def get_task_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """Get the result of a task, waiting for it to complete if necessary.
        
        Args:
            task_id: The ID of the task to get the result for.
            timeout: Maximum time in seconds to wait for the result. If None, wait indefinitely.
        
        Returns:
            Any: The result of the task.
            
        Raises:
            ThreadManagerError: If the task doesn't exist or has failed.
            concurrent.futures.TimeoutError: If the task doesn't complete within the timeout.
        """
        if not self._initialized:
            raise ThreadManagerError("Manager not initialized", thread_id=task_id)
        
        with self._tasks_lock:
            if task_id not in self._tasks:
                raise ThreadManagerError(f"Task {task_id} not found", thread_id=task_id)
            
            task_info = self._tasks[task_id]
            
            if task_info.status == TaskStatus.FAILED:
                if task_info.exception:
                    raise task_info.exception
                raise ThreadManagerError(f"Task {task_id} failed", thread_id=task_id)
            
            if task_info.status == TaskStatus.CANCELLED:
                raise ThreadManagerError(f"Task {task_id} was cancelled", thread_id=task_id)
            
            if not task_info.future:
                raise ThreadManagerError(
                    f"Task {task_id} has no future object",
                    thread_id=task_id,
                )
            
            # Get the future for the task
            future = task_info.future
        
        # Wait for the future to complete
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise
        except Exception as e:
            # Task failed with an exception
            raise ThreadManagerError(
                f"Task {task_id} failed: {str(e)}",
                thread_id=task_id,
            ) from e
    
    def schedule_periodic_task(
        self,
        interval: float,
        func: Callable,
        *args: Any,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Schedule a task to run periodically.
        
        Args:
            interval: Time in seconds between executions.
            func: The function to execute.
            *args: Positional arguments to pass to the function.
            task_id: Optional ID for the task. If not provided, a UUID will be generated.
            **kwargs: Keyword arguments to pass to the function.
        
        Returns:
            str: A unique ID for the scheduled task.
        """
        if not self._initialized:
            raise ThreadManagerError("Manager not initialized", thread_id=task_id)
        
        # Generate task ID if not provided
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        # Register the periodic task
        self._periodic_tasks[task_id] = (interval, func, args, kwargs)
        self._logger.debug(f"Scheduled periodic task {task_id} with interval {interval}s")
        
        return task_id
    
    def cancel_periodic_task(self, task_id: str) -> bool:
        """Cancel a periodic task.
        
        Args:
            task_id: The ID of the task to cancel.
        
        Returns:
            bool: True if the task was cancelled, False if it wasn't found.
        """
        if not self._initialized:
            return False
        
        if task_id in self._periodic_tasks:
            del self._periodic_tasks[task_id]
            self._logger.debug(f"Cancelled periodic task {task_id}")
            return True
        
        return False
    
    def _periodic_task_scheduler(self) -> None:
        """Background thread that executes periodic tasks at their scheduled intervals."""
        self._logger.debug("Periodic task scheduler started")
        
        # Track the last execution time of each task
        last_run: Dict[str, float] = {}
        
        while not self._periodic_stop_event.is_set():
            try:
                # Check each periodic task
                current_time = time.time()
                
                for task_id, (interval, func, args, kwargs) in list(self._periodic_tasks.items()):
                    # If the task hasn't run yet or it's time to run again
                    if task_id not in last_run or (current_time - last_run[task_id]) >= interval:
                        # Submit the task to the thread pool
                        try:
                            self.submit_task(
                                func,
                                *args,
                                name=f"periodic-{task_id}",
                                submitter="periodic_scheduler",
                                metadata={"periodic": True, "interval": interval},
                                **kwargs,
                            )
                            
                            # Update last run time
                            last_run[task_id] = current_time
                        
                        except Exception as e:
                            self._logger.error(
                                f"Error scheduling periodic task {task_id}: {str(e)}"
                            )
                
                # Sleep a short time before checking again
                time.sleep(0.1)
            
            except Exception as e:
                self._logger.error(f"Error in periodic task scheduler: {str(e)}")
                # Continue running even after an error
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for the thread pool.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "thread_pool.worker_threads":
            self._logger.warning(
                "Cannot change thread pool size at runtime, restart required",
                extra={"current_size": self._max_workers, "new_size": value},
            )
    
    def shutdown(self) -> None:
        """Shut down the Thread Manager.
        
        Stops all tasks and cleans up the thread pool.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Thread Manager")
            
            # Stop periodic task scheduler
            self._periodic_stop_event.set()
            if self._periodic_thread and self._periodic_thread.is_alive():
                self._periodic_thread.join(timeout=2.0)
            
            # Cancel all pending tasks
            with self._tasks_lock:
                for task_id, task_info in list(self._tasks.items()):
                    if task_info.status == TaskStatus.PENDING:
                        if task_info.future:
                            task_info.future.cancel()
                            task_info.status = TaskStatus.CANCELLED
                            task_info.completed_at = time.time()
            
            # Shut down thread pool
            if self._thread_pool is not None:
                self._thread_pool.shutdown(wait=True, cancel_futures=True)
            
            # Clear task tracking
            with self._tasks_lock:
                self._tasks.clear()
            
            # Clear periodic tasks
            self._periodic_tasks.clear()
            
            # Unregister config listener
            self._config_manager.unregister_listener("thread_pool", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Thread Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Thread Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down ThreadManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Thread Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Thread Manager.
        """
        status = super().status()
        
        if self._initialized:
            # Count tasks by status
            task_counts = {status.value: 0 for status in TaskStatus}
            with self._tasks_lock:
                for task_info in self._tasks.values():
                    task_counts[task_info.status.value] += 1
            
            status.update({
                "thread_pool": {
                    "max_workers": self._max_workers,
                    "active_tasks": self._active_tasks,
                },
                "tasks": {
                    "total": len(self._tasks),
                    "by_status": task_counts,
                },
                "periodic_tasks": len(self._periodic_tasks),
            })
        
        return status
