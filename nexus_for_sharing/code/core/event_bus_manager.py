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
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        super().__init__(name='EventBusManager')
        self._config_manager = config_manager
        self._logger_manager = logger_manager
        self._logger = logger_manager.get_logger('event_bus')
        self._thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._max_queue_size = 1000
        self._publish_timeout = 5.0
        self._subscriptions: Dict[str, Dict[str, EventSubscription]] = {}
        self._subscription_lock = threading.RLock()
        self._event_queue: Optional[queue.Queue] = None
        self._worker_threads: List[threading.Thread] = []
        self._running = False
        self._stop_event = threading.Event()
    def initialize(self) -> None:
        try:
            event_bus_config = self._config_manager.get('event_bus', {})
            thread_pool_size = event_bus_config.get('thread_pool_size', 4)
            self._max_queue_size = event_bus_config.get('max_queue_size', 1000)
            self._publish_timeout = event_bus_config.get('publish_timeout', 5.0)
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=thread_pool_size, thread_name_prefix='event-worker')
            self._event_queue = queue.Queue(maxsize=self._max_queue_size)
            self._running = True
            for i in range(thread_pool_size):
                worker = threading.Thread(target=self._event_worker, name=f'event-worker-{i}', daemon=True)
                worker.start()
                self._worker_threads.append(worker)
            self._config_manager.register_listener('event_bus', self._on_config_changed)
            self._logger.info('Event Bus Manager initialized')
            self._initialized = True
            self._healthy = True
        except Exception as e:
            self._logger.error(f'Failed to initialize Event Bus Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize EventBusManager: {str(e)}', manager_name=self.name) from e
    def _event_worker(self) -> None:
        while self._running and (not self._stop_event.is_set()):
            try:
                event, subscriptions = self._event_queue.get(timeout=0.1)
                try:
                    for subscription in subscriptions:
                        try:
                            subscription.callback(event)
                        except Exception as e:
                            self._logger.error(f'Error in event handler for {event.event_type}: {str(e)}', extra={'event_id': event.event_id, 'subscription_id': subscription.subscriber_id, 'error': str(e)})
                finally:
                    self._event_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self._logger.error(f'Unexpected error in event worker: {str(e)}')
    def publish(self, event_type: str, source: str, payload: Optional[Dict[str, Any]]=None, correlation_id: Optional[str]=None, synchronous: bool=False) -> str:
        if not self._initialized:
            raise EventBusError('Cannot publish events before initialization', event_type=event_type)
        event = Event.create(event_type=event_type, source=source, payload=payload or {}, correlation_id=correlation_id)
        matching_subs = self._get_matching_subscriptions(event)
        if not matching_subs:
            self._logger.debug(f'No subscribers for event {event_type}', extra={'event_id': event.event_id})
            return event.event_id
        if synchronous:
            self._process_event_sync(event, matching_subs)
        else:
            try:
                if self._event_queue is None:
                    raise EventBusError('Event queue is not initialized', event_type=event_type)
                self._event_queue.put((event, matching_subs), block=True, timeout=self._publish_timeout)
            except queue.Full:
                self._logger.error(f'Event queue is full, cannot publish event {event_type}', extra={'event_id': event.event_id})
                raise EventBusError(f'Event queue is full, cannot publish event {event_type}', event_type=event_type)
        self._logger.debug(f'Published event {event_type}', extra={'event_id': event.event_id, 'source': source, 'subscribers': len(matching_subs), 'synchronous': synchronous})
        return event.event_id
    def _process_event_sync(self, event: Event, subscriptions: List[EventSubscription]) -> None:
        for subscription in subscriptions:
            try:
                subscription.callback(event)
            except Exception as e:
                self._logger.error(f'Error in event handler for {event.event_type}: {str(e)}', extra={'event_id': event.event_id, 'subscription_id': subscription.subscriber_id, 'error': str(e)})
    def subscribe(self, event_type: str, callback: Callable[[Event], None], subscriber_id: Optional[str]=None, filter_criteria: Optional[Dict[str, Any]]=None) -> str:
        if not self._initialized:
            raise EventBusError('Cannot subscribe to events before initialization', event_type=event_type)
        if subscriber_id is None:
            subscriber_id = str(uuid.uuid4())
        subscription = EventSubscription(subscriber_id=subscriber_id, event_type=event_type, callback=callback, filter_criteria=filter_criteria)
        with self._subscription_lock:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = {}
            self._subscriptions[event_type][subscriber_id] = subscription
        self._logger.debug(f'Subscription added for {event_type}', extra={'subscriber_id': subscriber_id, 'has_filter': filter_criteria is not None})
        return subscriber_id
    def unsubscribe(self, subscriber_id: str, event_type: Optional[str]=None) -> bool:
        if not self._initialized:
            return False
        removed = False
        with self._subscription_lock:
            if event_type is not None:
                if event_type in self._subscriptions and subscriber_id in self._subscriptions[event_type]:
                    del self._subscriptions[event_type][subscriber_id]
                    removed = True
                    if not self._subscriptions[event_type]:
                        del self._subscriptions[event_type]
            else:
                for evt_type in list(self._subscriptions.keys()):
                    if subscriber_id in self._subscriptions[evt_type]:
                        del self._subscriptions[evt_type][subscriber_id]
                        removed = True
                        if not self._subscriptions[evt_type]:
                            del self._subscriptions[evt_type]
        if removed:
            self._logger.debug(f"Unsubscribed {subscriber_id} from {event_type or 'all events'}")
        return removed
    def _get_matching_subscriptions(self, event: Event) -> List[EventSubscription]:
        matching: List[EventSubscription] = []
        with self._subscription_lock:
            if event.event_type in self._subscriptions:
                for subscription in self._subscriptions[event.event_type].values():
                    if subscription.matches_event(event):
                        matching.append(subscription)
            if '*' in self._subscriptions:
                for subscription in self._subscriptions['*'].values():
                    if subscription.matches_event(event):
                        matching.append(subscription)
        return matching
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key == 'event_bus.max_queue_size':
            self._logger.warning('Cannot change event queue size at runtime, restart required', extra={'current_size': self._max_queue_size, 'new_size': value})
        elif key == 'event_bus.publish_timeout':
            self._publish_timeout = float(value)
            self._logger.info(f'Updated event publish timeout to {self._publish_timeout} seconds')
        elif key == 'event_bus.thread_pool_size':
            self._logger.warning('Cannot change thread pool size at runtime, restart required', extra={'current_size': len(self._worker_threads), 'new_size': value})
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down Event Bus Manager')
            self._running = False
            self._stop_event.set()
            if self._event_queue is not None:
                try:
                    self._event_queue.join(timeout=5.0)
                except:
                    pass
            if self._thread_pool is not None:
                self._thread_pool.shutdown(wait=True, cancel_futures=True)
            with self._subscription_lock:
                self._subscriptions.clear()
            self._config_manager.unregister_listener('event_bus', self._on_config_changed)
            self._initialized = False
            self._healthy = False
            self._logger.info('Event Bus Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down Event Bus Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down EventBusManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            with self._subscription_lock:
                total_subscriptions = sum((len(subs) for subs in self._subscriptions.values()))
                unique_subscribers: Set[str] = set()
                for subs in self._subscriptions.values():
                    unique_subscribers.update(subs.keys())
            queue_size = self._event_queue.qsize() if self._event_queue else 0
            queue_full = queue_size >= self._max_queue_size if self._event_queue else False
            status.update({'subscriptions': {'total': total_subscriptions, 'unique_subscribers': len(unique_subscribers), 'event_types': len(self._subscriptions)}, 'queue': {'size': queue_size, 'capacity': self._max_queue_size, 'full': queue_full}, 'threads': {'worker_count': len(self._worker_threads), 'running': self._running}})
        return status