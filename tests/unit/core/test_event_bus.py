"""Unit tests for the Event Bus Manager."""

import pytest
import threading
import time
from unittest.mock import MagicMock

from nexus_core.core.event_bus_manager import EventBusManager
from nexus_core.core.event_model import Event
from nexus_core.utils.exceptions import EventBusError


@pytest.fixture
def event_bus_manager(config_manager):
    """Create an EventBusManager for testing."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    event_bus = EventBusManager(config_manager, logger_manager)
    event_bus.initialize()
    yield event_bus
    event_bus.shutdown()


def test_event_bus_initialization(config_manager):
    """Test that the EventBusManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    event_bus = EventBusManager(config_manager, logger_manager)
    event_bus.initialize()
    
    assert event_bus.initialized
    assert event_bus.healthy
    
    event_bus.shutdown()
    assert not event_bus.initialized


def test_publish_subscribe(event_bus_manager):
    """Test publishing and subscribing to events."""
    received_events = []
    
    def on_event(event):
        received_events.append(event)
    
    # Subscribe to test events
    sub_id = event_bus_manager.subscribe(event_type="test/event", callback=on_event)
    
    # Publish a test event
    event_id = event_bus_manager.publish(
        event_type="test/event",
        source="test",
        payload={"message": "Test message"}
    )
    
    # Give the event time to be delivered (since it's asynchronous)
    time.sleep(0.1)
    
    # Verify event was received
    assert len(received_events) == 1
    assert received_events[0].event_type == "test/event"
    assert received_events[0].event_id == event_id
    assert received_events[0].source == "test"
    assert received_events[0].payload["message"] == "Test message"
    
    # Test unsubscribe
    event_bus_manager.unsubscribe(sub_id)
    
    # Publish another event
    event_bus_manager.publish(
        event_type="test/event",
        source="test",
        payload={"message": "Another message"}
    )
    
    # Give the event time to be delivered
    time.sleep(0.1)
    
    # Verify no new event was received
    assert len(received_events) == 1


def test_wildcard_subscription(event_bus_manager):
    """Test subscribing to all events using wildcard."""
    received_events = []
    
    def on_event(event):
        received_events.append(event)
    
    # Subscribe to all events
    sub_id = event_bus_manager.subscribe(event_type="*", callback=on_event)
    
    # Publish events of different types
    event_bus_manager.publish(event_type="test/one", source="test", payload={})
    event_bus_manager.publish(event_type="test/two", source="test", payload={})
    
    # Give the events time to be delivered
    time.sleep(0.1)
    
    # Verify both events were received
    assert len(received_events) == 2
    assert received_events[0].event_type == "test/one"
    assert received_events[1].event_type == "test/two"
    
    event_bus_manager.unsubscribe(sub_id)


def test_synchronous_publish(event_bus_manager):
    """Test synchronous event publishing."""
    received_events = []
    
    def on_event(event):
        received_events.append(event)
    
    # Subscribe to test events
    event_bus_manager.subscribe(event_type="test/sync", callback=on_event)
    
    # Publish a synchronous event
    event_bus_manager.publish(
        event_type="test/sync",
        source="test",
        payload={"sync": True},
        synchronous=True
    )
    
    # No need to wait since it's synchronous
    
    # Verify event was received
    assert len(received_events) == 1
    assert received_events[0].event_type == "test/sync"
    assert received_events[0].payload["sync"] is True


def test_filter_criteria(event_bus_manager):
    """Test subscribing with filter criteria."""
    received_events = []
    
    def on_event(event):
        received_events.append(event)
    
    # Subscribe to events with specific filter criteria
    event_bus_manager.subscribe(
        event_type="test/filtered",
        callback=on_event,
        filter_criteria={"category": "important"}
    )
    
    # Publish events with and without matching criteria
    event_bus_manager.publish(
        event_type="test/filtered",
        source="test",
        payload={"category": "important", "message": "Match"}
    )
    event_bus_manager.publish(
        event_type="test/filtered",
        source="test",
        payload={"category": "normal", "message": "No match"}
    )
    
    # Give the events time to be delivered
    time.sleep(0.1)
    
    # Verify only the matching event was received
    assert len(received_events) == 1
    assert received_events[0].payload["message"] == "Match"


def test_error_handling(event_bus_manager):
    """Test handling errors in event callbacks."""
    error_logs = []
    event_bus_manager._logger.error = lambda msg, **kwargs: error_logs.append(msg)
    
    def failing_callback(event):
        raise ValueError("Test error")
    
    # Subscribe with a callback that will raise an exception
    event_bus_manager.subscribe(event_type="test/error", callback=failing_callback)
    
    # Publish an event
    event_bus_manager.publish(event_type="test/error", source="test", payload={})
    
    # Give the event time to be delivered
    time.sleep(0.1)
    
    # Verify error was logged
    assert any("Error in event handler" in log for log in error_logs)


def test_publish_without_initialization():
    """Test publishing events before initialization."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    
    event_bus = EventBusManager(config_manager, logger_manager)
    
    with pytest.raises(EventBusError):
        event_bus.publish(event_type="test/event", source="test")
