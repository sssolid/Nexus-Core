"""Unit tests for the Thread Manager."""

import pytest
import time
from unittest.mock import MagicMock, patch

from nexus_core.core.thread_manager import ThreadManager, TaskStatus
from nexus_core.utils.exceptions import ThreadManagerError


@pytest.fixture
def thread_manager(config_manager):
    """Create a ThreadManager for testing."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    thread_mgr = ThreadManager(config_manager, logger_manager)
    thread_mgr.initialize()
    yield thread_mgr
    thread_mgr.shutdown()


def test_thread_manager_initialization(config_manager):
    """Test that the ThreadManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    thread_mgr = ThreadManager(config_manager, logger_manager)
    thread_mgr.initialize()
    
    assert thread_mgr.initialized
    assert thread_mgr.healthy
    assert thread_mgr._thread_pool is not None
    
    thread_mgr.shutdown()
    assert not thread_mgr.initialized


def test_submit_task(thread_manager):
    """Test submitting a task to the thread pool."""
    result = []
    
    def test_function(value):
        result.append(value)
        return value
    
    # Submit a task
    task_id = thread_manager.submit_task(test_function, "test_value", name="test_task")
    
    # Task ID should be returned
    assert task_id is not None
    
    # Get task info
    task_info = thread_manager.get_task_info(task_id)
    assert task_info is not None
    assert task_info["name"] == "test_task"
    
    # Wait for task to complete
    time.sleep(0.1)
    
    # Verify task executed
    assert result == ["test_value"]
    
    # Verify task status was updated
    task_info = thread_manager.get_task_info(task_id)
    assert task_info["status"] == TaskStatus.COMPLETED.value


def test_get_task_result(thread_manager):
    """Test getting a task result."""
    def test_function(value):
        return value * 2
    
    # Submit a task
    task_id = thread_manager.submit_task(test_function, 5)
    
    # Wait for task to complete
    time.sleep(0.1)
    
    # Get task result
    result = thread_manager.get_task_result(task_id)
    assert result == 10


def test_failing_task(thread_manager):
    """Test handling of a failing task."""
    def failing_function():
        raise ValueError("Test error")
    
    # Submit a task that will fail
    task_id = thread_manager.submit_task(failing_function)
    
    # Wait for task to complete
    time.sleep(0.1)
    
    # Verify task status
    task_info = thread_manager.get_task_info(task_id)
    assert task_info["status"] == TaskStatus.FAILED.value
    assert "error" in task_info
    assert "Test error" in task_info["error"]
    
    # Getting result should raise the original exception
    with pytest.raises(ValueError, match="Test error"):
        thread_manager.get_task_result(task_id)


def test_cancel_task(thread_manager):
    """Test canceling a task."""
    # Create a task that will wait
    def waiting_task():
        time.sleep(10)
        return "Done"
    
    # Submit the task
    task_id = thread_manager.submit_task(waiting_task)
    
    # Immediately try to cancel it
    # This may or may not succeed depending on timing
    cancelled = thread_manager.cancel_task(task_id)
    
    # If we successfully cancelled it, verify the task status
    if cancelled:
        task_info = thread_manager.get_task_info(task_id)
        assert task_info["status"] == TaskStatus.CANCELLED.value
        
        # Getting result of a cancelled task should raise an exception
        with pytest.raises(ThreadManagerError, match="cancelled"):
            thread_manager.get_task_result(task_id)


def test_periodic_task(thread_manager):
    """Test scheduling a periodic task."""
    counter = {"value": 0}
    
    def increment_counter():
        counter["value"] += 1
    
    # Schedule a periodic task with a very short interval
    task_id = thread_manager.schedule_periodic_task(
        interval=0.1,  # Run every 100ms
        func=increment_counter
    )
    
    # Wait for a few executions
    time.sleep(0.5)
    
    # Cancel the periodic task
    thread_manager.cancel_periodic_task(task_id)
    
    # Verify it ran multiple times
    assert counter["value"] >= 3  # Should run at least 3 times in 500ms
    
    # Wait a bit more to ensure it was actually cancelled
    previous_value = counter["value"]
    time.sleep(0.3)
    assert counter["value"] == previous_value  # Should not increase after cancellation


def test_scheduler_shutdown(config_manager):
    """Test that periodic tasks are properly shut down."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    thread_mgr = ThreadManager(config_manager, logger_manager)
    thread_mgr.initialize()
    
    counter = {"value": 0}
    
    def increment_counter():
        counter["value"] += 1
    
    # Schedule a periodic task
    thread_mgr.schedule_periodic_task(interval=0.1, func=increment_counter)
    
    # Wait for a few executions
    time.sleep(0.3)
    
    # Shut down the manager
    thread_mgr.shutdown()
    
    # Record the counter value
    value_at_shutdown = counter["value"]
    
    # Wait to see if more executions occur
    time.sleep(0.3)
    
    # Counter should not have increased
    assert counter["value"] == value_at_shutdown


def test_thread_manager_status(thread_manager):
    """Test getting status from ThreadManager."""
    status = thread_manager.status()
    
    assert status["name"] == "ThreadManager"
    assert status["initialized"] is True
    assert "thread_pool" in status
    assert "tasks" in status
    assert "periodic_tasks" in status


def test_submit_without_initialization():
    """Test submitting tasks before initialization."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    
    thread_mgr = ThreadManager(config_manager, logger_manager)
    
    with pytest.raises(ThreadManagerError):
        thread_mgr.submit_task(lambda: None)
