from __future__ import annotations

import concurrent.futures
import queue
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import EventBusError, ManagerInitializationError, ManagerShutdownError
from nexus_core.core.event_model import Event, EventSubscription


class EventBusManager(NexusManager):
    """Manages the event bus system for inter-component communication.
    
    The Event Bus Manager provides a publish-subscribe messaging system for
    decoupled communication between components. It allows components to publish
    events and subscribe to events they're interested in without direct coupling.
    
    This implementation provides both synchronous and asynchronous event delivery,
    with configurable thread pools for handling event processing.
    """
    
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        """Initialize the Event Bus Manager.
        
        Args:
            config_manager: The Configuration Manager to use for event bus settings.
            logger_manager: The Logging Manager to use for logging.
        """
        super().__init__(name="EventBusManager")
        self._config_manager = config_manager
        self._logger_manager = logger_manager
        self._logger = logger_manager.get_logger("event_bus")
        
        # Thread pool for asynchronous event processing
        self._thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._max_queue_size = 1000
        self._publish_timeout = 5.0
        
        # Event subscriptions
        self._subscriptions: Dict[str, Dict[str, EventSubscription]] = {}
        self._subscription_lock = threading.RLock()
        
        # Event queue for asynchronous processing
        self._event_queue: Optional[queue.Queue] = None
        self._worker_threads: List[threading.Thread] = []
        self._running = False
        self._stop_event = threading.Event()
    
    def initialize(self) -> None:
        """Initialize the Event Bus Manager.
        
        Sets up the event processing thread pool and starts worker threads
        based on configuration.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get configuration
            event_bus_config = self._config_manager.get("event_bus", {})
            thread_pool_size = event_bus_config.get("thread_pool_size", 4)
            self._max_queue_size = event_bus_config.get("max_queue_size", 1000)
            self._publish_timeout = event_bus_config.get("publish_timeout", 5.0)
            
            # Create thread pool
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=thread_pool_size,
                thread_name_prefix="event-worker",
            )
            
            # Create event queue for asynchronous processing
            self._event_queue = queue.Queue(maxsize=self._max_queue_size)
            
            # Start worker threads
            self._running = True
            for i in range(thread_pool_size):
                worker = threading.Thread(
                    target=self._event_worker,
                    name=f"event-worker-{i}",
                    daemon=True,
                )
                worker.start()
                self._worker_threads.append(worker)
            
            # Register for config changes
            self._config_manager.register_listener("event_bus", self._on_config_changed)
            
            self._logger.info("Event Bus Manager initialized")
            self._initialized = True
            self._healthy = True
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Event Bus Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize EventBusManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _event_worker(self) -> None:
        """Worker thread function for processing events from the queue."""
        while self._running and not self._stop_event.is_set():
            try:
                # Get next event from queue with timeout
                event, subscriptions = self._event_queue.get(timeout=0.1)
                
                try:
                    # Process event (call all subscriber callbacks)
                    for subscription in subscriptions:
                        try:
                            subscription.callback(event)
                        except Exception as e:
                            self._logger.error(
                                f"Error in event handler for {event.event_type}: {str(e)}",
                                extra={
                                    "event_id": event.event_id,
                                    "subscription_id": subscription.subscriber_id,
                                    "error": str(e),
                                },
                            )
                
                finally:
                    # Mark task as done
                    self._event_queue.task_done()
            
            except queue.Empty:
                # No events to process, just continue waiting
                continue
            
            except Exception as e:
                # Log any unexpected errors but keep the worker running
                self._logger.error(f"Unexpected error in event worker: {str(e)}")
    
    def publish(
        self,
        event_type: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        synchronous: bool = False,
    ) -> str:
        """Publish an event to the event bus.
        
        Args:
            event_type: The type of event being published.
            source: The source component that is publishing the event.
            payload: Optional data associated with the event.
            correlation_id: Optional ID for tracking related events.
            synchronous: If True, process the event synchronously (blocking).
                         If False, queue the event for asynchronous processing.
        
        Returns:
            str: The ID of the published event.
            
        Raises:
            EventBusError: If the event cannot be published.
        """
        if not self._initialized:
            raise EventBusError(
                "Cannot publish events before initialization",
                event_type=event_type,
            )
        
        # Create the event
        event = Event.create(
            event_type=event_type,
            source=source,
            payload=payload or {},
            correlation_id=correlation_id,
        )
        
        # Find matching subscriptions
        matching_subs = self._get_matching_subscriptions(event)
        
        if not matching_subs:
            # No subscribers for this event
            self._logger.debug(
                f"No subscribers for event {event_type}",
                extra={"event_id": event.event_id},
            )
            return event.event_id
        
        if synchronous:
            # Process event synchronously
            self._process_event_sync(event, matching_subs)
        else:
            # Queue event for asynchronous processing
            try:
                if self._event_queue is None:
                    raise EventBusError(
                        "Event queue is not initialized",
                        event_type=event_type,
                    )
                
                self._event_queue.put(
                    (event, matching_subs),
                    block=True,
                    timeout=self._publish_timeout,
                )
            
            except queue.Full:
                self._logger.error(
                    f"Event queue is full, cannot publish event {event_type}",
                    extra={"event_id": event.event_id},
                )
                raise EventBusError(
                    f"Event queue is full, cannot publish event {event_type}",
                    event_type=event_type,
                )
        
        self._logger.debug(
            f"Published event {event_type}",
            extra={
                "event_id": event.event_id,
                "source": source,
                "subscribers": len(matching_subs),
                "synchronous": synchronous,
            },
        )
        
        return event.event_id
    
    def _process_event_sync(self, event: Event, subscriptions: List[EventSubscription]) -> None:
        """Process an event synchronously.
        
        Args:
            event: The event to process.
            subscriptions: The subscriptions that match the event.
        """
        for subscription in subscriptions:
            try:
                subscription.callback(event)
            except Exception as e:
                self._logger.error(
                    f"Error in event handler for {event.event_type}: {str(e)}",
                    extra={
                        "event_id": event.event_id,
                        "subscription_id": subscription.subscriber_id,
                        "error": str(e),
                    },
                )
    
    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], None],
        subscriber_id: Optional[str] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Subscribe to events of a specific type.
        
        Args:
            event_type: The type of events to subscribe to. Use "*" for all events.
            callback: A function to call when matching events are published.
            subscriber_id: Optional ID for the subscriber. If not provided, a UUID is generated.
            filter_criteria: Optional criteria for filtering events beyond their type.
                             A dict where keys are payload fields and values are the required values.
        
        Returns:
            str: The subscriber ID, which can be used to unsubscribe.
            
        Raises:
            EventBusError: If the subscription cannot be created.
        """
        if not self._initialized:
            raise EventBusError(
                "Cannot subscribe to events before initialization",
                event_type=event_type,
            )
        
        # Generate subscriber ID if not provided
        if subscriber_id is None:
            subscriber_id = str(uuid.uuid4())
        
        # Create subscription
        subscription = EventSubscription(
            subscriber_id=subscriber_id,
            event_type=event_type,
            callback=callback,
            filter_criteria=filter_criteria,
        )
        
        # Add to subscriptions
        with self._subscription_lock:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = {}
            
            self._subscriptions[event_type][subscriber_id] = subscription
        
        self._logger.debug(
            f"Subscription added for {event_type}",
            extra={
                "subscriber_id": subscriber_id,
                "has_filter": filter_criteria is not None,
            },
        )
        
        return subscriber_id
    
    def unsubscribe(self, subscriber_id: str, event_type: Optional[str] = None) -> bool:
        """Unsubscribe from events.
        
        Args:
            subscriber_id: The ID of the subscriber to remove.
            event_type: Optional event type to unsubscribe from. If None,
                        unsubscribe from all event types.
        
        Returns:
            bool: True if the subscription was removed, False if not found.
        """
        if not self._initialized:
            return False
        
        removed = False
        
        with self._subscription_lock:
            if event_type is not None:
                # Unsubscribe from specific event type
                if event_type in self._subscriptions and subscriber_id in self._subscriptions[event_type]:
                    del self._subscriptions[event_type][subscriber_id]
                    removed = True
                    
                    # Clean up empty event type dictionaries
                    if not self._subscriptions[event_type]:
                        del self._subscriptions[event_type]
            else:
                # Unsubscribe from all event types
                for evt_type in list(self._subscriptions.keys()):
                    if subscriber_id in self._subscriptions[evt_type]:
                        del self._subscriptions[evt_type][subscriber_id]
                        removed = True
                        
                        # Clean up empty event type dictionaries
                        if not self._subscriptions[evt_type]:
                            del self._subscriptions[evt_type]
        
        if removed:
            self._logger.debug(
                f"Unsubscribed {subscriber_id} from {event_type or 'all events'}",
            )
        
        return removed
    
    def _get_matching_subscriptions(self, event: Event) -> List[EventSubscription]:
        """Get subscriptions that match an event.
        
        Args:
            event: The event to match against subscriptions.
        
        Returns:
            List[EventSubscription]: The matching subscriptions.
        """
        matching: List[EventSubscription] = []
        
        with self._subscription_lock:
            # Check specific event type subscriptions
            if event.event_type in self._subscriptions:
                for subscription in self._subscriptions[event.event_type].values():
                    if subscription.matches_event(event):
                        matching.append(subscription)
            
            # Check wildcard subscriptions (if any)
            if "*" in self._subscriptions:
                for subscription in self._subscriptions["*"].values():
                    if subscription.matches_event(event):
                        matching.append(subscription)
        
        return matching
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for the event bus.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "event_bus.max_queue_size":
            # Can't easily change queue size at runtime, log a warning
            self._logger.warning(
                "Cannot change event queue size at runtime, restart required",
                extra={"current_size": self._max_queue_size, "new_size": value},
            )
        
        elif key == "event_bus.publish_timeout":
            # Update publish timeout
            self._publish_timeout = float(value)
            self._logger.info(
                f"Updated event publish timeout to {self._publish_timeout} seconds",
            )
        
        elif key == "event_bus.thread_pool_size":
            # Can't easily change thread pool size at runtime, log a warning
            self._logger.warning(
                "Cannot change thread pool size at runtime, restart required",
                extra={"current_size": len(self._worker_threads), "new_size": value},
            )
    
    def shutdown(self) -> None:
        """Shut down the Event Bus Manager.
        
        Stops the event processing threads and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Event Bus Manager")
            
            # Signal threads to stop
            self._running = False
            self._stop_event.set()
            
            # Wait for queue to be processed
            if self._event_queue is not None:
                try:
                    self._event_queue.join(timeout=5.0)
                except:
                    # Continue with shutdown even if join times out
                    pass
            
            # Shut down thread pool
            if self._thread_pool is not None:
                self._thread_pool.shutdown(wait=True, cancel_futures=True)
            
            # Clear subscriptions
            with self._subscription_lock:
                self._subscriptions.clear()
            
            # Unregister config listener
            self._config_manager.unregister_listener("event_bus", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Event Bus Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Event Bus Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down EventBusManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Event Bus Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Event Bus Manager.
        """
        status = super().status()
        
        if self._initialized:
            with self._subscription_lock:
                # Count total subscriptions and unique subscribers
                total_subscriptions = sum(len(subs) for subs in self._subscriptions.values())
                unique_subscribers: Set[str] = set()
                for subs in self._subscriptions.values():
                    unique_subscribers.update(subs.keys())
            
            # Get queue size and worker thread status
            queue_size = self._event_queue.qsize() if self._event_queue else 0
            queue_full = (queue_size >= self._max_queue_size) if self._event_queue else False
            
            status.update({
                "subscriptions": {
                    "total": total_subscriptions,
                    "unique_subscribers": len(unique_subscribers),
                    "event_types": len(self._subscriptions),
                },
                "queue": {
                    "size": queue_size,
                    "capacity": self._max_queue_size,
                    "full": queue_full,
                },
                "threads": {
                    "worker_count": len(self._worker_threads),
                    "running": self._running,
                },
            })
        
        return status
