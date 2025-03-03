import pytest
import threading
import time
from unittest.mock import MagicMock
from nexus_core.core.event_bus_manager import EventBusManager
from nexus_core.core.event_model import Event
from nexus_core.utils.exceptions import EventBusError
@pytest.fixture
def event_bus_manager(config_manager):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus = EventBusManager(config_manager, logger_manager)
    event_bus.initialize()
    yield event_bus
    event_bus.shutdown()
def test_event_bus_initialization(config_manager):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus = EventBusManager(config_manager, logger_manager)
    event_bus.initialize()
    assert event_bus.initialized
    assert event_bus.healthy
    event_bus.shutdown()
    assert not event_bus.initialized
def test_publish_subscribe(event_bus_manager):
    received_events = []
    def on_event(event):
        received_events.append(event)
    sub_id = event_bus_manager.subscribe(event_type='test/event', callback=on_event)
    event_id = event_bus_manager.publish(event_type='test/event', source='test', payload={'message': 'Test message'})
    time.sleep(0.1)
    assert len(received_events) == 1
    assert received_events[0].event_type == 'test/event'
    assert received_events[0].event_id == event_id
    assert received_events[0].source == 'test'
    assert received_events[0].payload['message'] == 'Test message'
    event_bus_manager.unsubscribe(sub_id)
    event_bus_manager.publish(event_type='test/event', source='test', payload={'message': 'Another message'})
    time.sleep(0.1)
    assert len(received_events) == 1
def test_wildcard_subscription(event_bus_manager):
    received_events = []
    def on_event(event):
        received_events.append(event)
    sub_id = event_bus_manager.subscribe(event_type='*', callback=on_event)
    event_bus_manager.publish(event_type='test/one', source='test', payload={})
    event_bus_manager.publish(event_type='test/two', source='test', payload={})
    time.sleep(0.1)
    assert len(received_events) == 2
    assert received_events[0].event_type == 'test/one'
    assert received_events[1].event_type == 'test/two'
    event_bus_manager.unsubscribe(sub_id)
def test_synchronous_publish(event_bus_manager):
    received_events = []
    def on_event(event):
        received_events.append(event)
    event_bus_manager.subscribe(event_type='test/sync', callback=on_event)
    event_bus_manager.publish(event_type='test/sync', source='test', payload={'sync': True}, synchronous=True)
    assert len(received_events) == 1
    assert received_events[0].event_type == 'test/sync'
    assert received_events[0].payload['sync'] is True
def test_filter_criteria(event_bus_manager):
    received_events = []
    def on_event(event):
        received_events.append(event)
    event_bus_manager.subscribe(event_type='test/filtered', callback=on_event, filter_criteria={'category': 'important'})
    event_bus_manager.publish(event_type='test/filtered', source='test', payload={'category': 'important', 'message': 'Match'})
    event_bus_manager.publish(event_type='test/filtered', source='test', payload={'category': 'normal', 'message': 'No match'})
    time.sleep(0.1)
    assert len(received_events) == 1
    assert received_events[0].payload['message'] == 'Match'
def test_error_handling(event_bus_manager):
    error_logs = []
    event_bus_manager._logger.error = lambda msg, **kwargs: error_logs.append(msg)
    def failing_callback(event):
        raise ValueError('Test error')
    event_bus_manager.subscribe(event_type='test/error', callback=failing_callback)
    event_bus_manager.publish(event_type='test/error', source='test', payload={})
    time.sleep(0.1)
    assert any(('Error in event handler' in log for log in error_logs))
def test_publish_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    event_bus = EventBusManager(config_manager, logger_manager)
    with pytest.raises(EventBusError):
        event_bus.publish(event_type='test/event', source='test')