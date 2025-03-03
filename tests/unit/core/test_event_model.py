import pytest
import json
import uuid
import datetime
from unittest.mock import MagicMock
from nexus_core.core.event_model import Event, EventSubscription

def test_event_creation():
    """Test creating an Event instance."""
    # Create event with default values
    event = Event(event_type='test/event', source='test_source')
    
    assert event.event_type == 'test/event'
    assert event.source == 'test_source'
    assert isinstance(event.event_id, str)
    assert isinstance(event.timestamp, datetime.datetime)
    assert event.payload == {}
    assert event.correlation_id is None
    
    # Create event with custom values
    custom_id = str(uuid.uuid4())
    custom_time = datetime.datetime(2025, 1, 1, 12, 0, 0)
    custom_payload = {'key1': 'value1', 'key2': 42}
    custom_correlation = str(uuid.uuid4())
    
    event = Event(
        event_type='test/custom',
        event_id=custom_id,
        timestamp=custom_time,
        source='custom_source',
        payload=custom_payload,
        correlation_id=custom_correlation
    )
    
    assert event.event_type == 'test/custom'
    assert event.event_id == custom_id
    assert event.timestamp == custom_time
    assert event.source == 'custom_source'
    assert event.payload == custom_payload
    assert event.correlation_id == custom_correlation

def test_event_factory_method():
    """Test the Event.create factory method."""
    event = Event.create(
        event_type='test/factory',
        source='factory_source',
        payload={'factory': True},
        correlation_id='correlation123'
    )
    
    assert event.event_type == 'test/factory'
    assert event.source == 'factory_source'
    assert event.payload == {'factory': True}
    assert event.correlation_id == 'correlation123'
    assert isinstance(event.event_id, str)
    assert isinstance(event.timestamp, datetime.datetime)
    
    # Test with minimal parameters
    minimal_event = Event.create(event_type='minimal', source='test')
    assert minimal_event.event_type == 'minimal'
    assert minimal_event.source == 'test'
    assert minimal_event.payload == {}
    assert minimal_event.correlation_id is None

def test_event_to_dict():
    """Test converting an Event to a dictionary."""
    event = Event(
        event_type='test/dict',
        source='dict_source',
        payload={'test': True}
    )
    
    event_dict = event.to_dict()
    
    assert isinstance(event_dict, dict)
    assert event_dict['event_type'] == 'test/dict'
    assert event_dict['source'] == 'dict_source'
    assert event_dict['payload'] == {'test': True}
    assert 'event_id' in event_dict
    assert 'timestamp' in event_dict

def test_event_string_representation():
    """Test the string representation of an Event."""
    event = Event(
        event_type='test/str',
        event_id='test-id-123',
        source='str_source'
    )
    
    event_str = str(event)
    
    assert 'Event' in event_str
    assert 'test/str' in event_str
    assert 'test-id-123' in event_str
    assert 'str_source' in event_str

def test_event_subscription_creation():
    """Test creating an EventSubscription instance."""
    # Create a mock callback function
    callback = MagicMock()
    
    # Create subscription
    subscription = EventSubscription(
        subscriber_id='test-subscriber',
        event_type='test/event',
        callback=callback
    )
    
    assert subscription.subscriber_id == 'test-subscriber'
    assert subscription.event_type == 'test/event'
    assert subscription.callback is callback
    assert subscription.filter_criteria is None
    
    # Create subscription with filter criteria
    filter_criteria = {'category': 'important', 'priority': 'high'}
    filtered_subscription = EventSubscription(
        subscriber_id='filtered-subscriber',
        event_type='filtered/event',
        callback=callback,
        filter_criteria=filter_criteria
    )
    
    assert filtered_subscription.subscriber_id == 'filtered-subscriber'
    assert filtered_subscription.event_type == 'filtered/event'
    assert filtered_subscription.callback is callback
    assert filtered_subscription.filter_criteria == filter_criteria

def test_event_subscription_matching():
    """Test EventSubscription.matches_event method."""
    callback = MagicMock()
    
    # Test without filter criteria
    subscription = EventSubscription(
        subscriber_id='test-subscriber',
        event_type='test/event',
        callback=callback
    )
    
    matching_event = Event(
        event_type='test/event',
        source='test_source'
    )
    
    non_matching_event = Event(
        event_type='different/event',
        source='test_source'
    )
    
    assert subscription.matches_event(matching_event) is True
    assert subscription.matches_event(non_matching_event) is False
    
    # Test with filter criteria
    filtered_subscription = EventSubscription(
        subscriber_id='filtered-subscriber',
        event_type='filtered/event',
        callback=callback,
        filter_criteria={'category': 'important', 'priority': 'high'}
    )
    
    matching_filtered_event = Event(
        event_type='filtered/event',
        source='test_source',
        payload={'category': 'important', 'priority': 'high', 'other': 'value'}
    )
    
    partially_matching_event = Event(
        event_type='filtered/event',
        source='test_source',
        payload={'category': 'important', 'priority': 'low'}
    )
    
    non_matching_filtered_event = Event(
        event_type='filtered/event',
        source='test_source',
        payload={'category': 'normal', 'other': 'value'}
    )
    
    assert filtered_subscription.matches_event(matching_filtered_event) is True
    assert filtered_subscription.matches_event(partially_matching_event) is False
    assert filtered_subscription.matches_event(non_matching_filtered_event) is False
    
    # Test with wildcard event type
    wildcard_subscription = EventSubscription(
        subscriber_id='wildcard-subscriber',
        event_type='*',
        callback=callback
    )
    
    any_event = Event(
        event_type='any/type',
        source='any_source'
    )
    
    assert wildcard_subscription.matches_event(any_event) is True
    
    # Test wildcard with filter criteria
    wildcard_filtered_subscription = EventSubscription(
        subscriber_id='wildcard-filtered',
        event_type='*',
        callback=callback,
        filter_criteria={'important': True}
    )
    
    important_event = Event(
        event_type='any/important',
        source='any_source',
        payload={'important': True}
    )
    
    unimportant_event = Event(
        event_type='any/unimportant',
        source='any_source',
        payload={'important': False}
    )
    
    assert wildcard_filtered_subscription.matches_event(important_event) is True
    assert wildcard_filtered_subscription.matches_event(unimportant_event) is False

def test_event_subscription_callback():
    """Test that the EventSubscription callback is callable."""
    # Create a mock callback that tracks calls
    callback = MagicMock()
    
    subscription = EventSubscription(
        subscriber_id='test-subscriber',
        event_type='test/event',
        callback=callback
    )
    
    event = Event(
        event_type='test/event',
        source='test_source',
        payload={'data': 'test'}
    )
    
    # Call the callback through the subscription
    subscription.callback(event)
    
    # Verify that the callback was called with the event
    callback.assert_called_once_with(event)
