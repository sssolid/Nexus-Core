import pytest
import time
from unittest.mock import MagicMock, patch
from nexus_core.core.thread_manager import ThreadManager, TaskStatus
from nexus_core.utils.exceptions import ThreadManagerError
@pytest.fixture
def thread_manager(config_manager):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    thread_mgr = ThreadManager(config_manager, logger_manager)
    thread_mgr.initialize()
    yield thread_mgr
    thread_mgr.shutdown()
def test_thread_manager_initialization(config_manager):
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
    result = []
    def test_function(value):
        result.append(value)
        return value
    task_id = thread_manager.submit_task(test_function, 'test_value', name='test_task')
    assert task_id is not None
    task_info = thread_manager.get_task_info(task_id)
    assert task_info is not None
    assert task_info['name'] == 'test_task'
    time.sleep(0.1)
    assert result == ['test_value']
    task_info = thread_manager.get_task_info(task_id)
    assert task_info['status'] == TaskStatus.COMPLETED.value
def test_get_task_result(thread_manager):
    def test_function(value):
        return value * 2
    task_id = thread_manager.submit_task(test_function, 5)
    time.sleep(0.1)
    result = thread_manager.get_task_result(task_id)
    assert result == 10
def test_failing_task(thread_manager):
    def failing_function():
        raise ValueError('Test error')
    task_id = thread_manager.submit_task(failing_function)
    time.sleep(0.1)
    task_info = thread_manager.get_task_info(task_id)
    assert task_info['status'] == TaskStatus.FAILED.value
    assert 'error' in task_info
    assert 'Test error' in task_info['error']
    with pytest.raises(ValueError, match='Test error'):
        thread_manager.get_task_result(task_id)
def test_cancel_task(thread_manager):
    def waiting_task():
        time.sleep(10)
        return 'Done'
    task_id = thread_manager.submit_task(waiting_task)
    cancelled = thread_manager.cancel_task(task_id)
    if cancelled:
        task_info = thread_manager.get_task_info(task_id)
        assert task_info['status'] == TaskStatus.CANCELLED.value
        with pytest.raises(ThreadManagerError, match='cancelled'):
            thread_manager.get_task_result(task_id)
def test_periodic_task(thread_manager):
    counter = {'value': 0}
    def increment_counter():
        counter['value'] += 1
    task_id = thread_manager.schedule_periodic_task(interval=0.1, func=increment_counter)
    time.sleep(0.5)
    thread_manager.cancel_periodic_task(task_id)
    assert counter['value'] >= 3
    previous_value = counter['value']
    time.sleep(0.3)
    assert counter['value'] == previous_value
def test_scheduler_shutdown(config_manager):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    thread_mgr = ThreadManager(config_manager, logger_manager)
    thread_mgr.initialize()
    counter = {'value': 0}
    def increment_counter():
        counter['value'] += 1
    thread_mgr.schedule_periodic_task(interval=0.1, func=increment_counter)
    time.sleep(0.3)
    thread_mgr.shutdown()
    value_at_shutdown = counter['value']
    time.sleep(0.3)
    assert counter['value'] == value_at_shutdown
def test_thread_manager_status(thread_manager):
    status = thread_manager.status()
    assert status['name'] == 'ThreadManager'
    assert status['initialized'] is True
    assert 'thread_pool' in status
    assert 'tasks' in status
    assert 'periodic_tasks' in status
def test_submit_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    thread_mgr = ThreadManager(config_manager, logger_manager)
    with pytest.raises(ThreadManagerError):
        thread_mgr.submit_task(lambda: None)