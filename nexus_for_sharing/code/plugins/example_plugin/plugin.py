from __future__ import annotations
import time
from typing import Any, Dict, Optional
from nexus_core.core.event_model import Event
class ExamplePlugin:
    name = 'example_plugin'
    version = '0.1.0'
    description = 'Example plugin demonstrating Nexus Core plugin architecture'
    author = 'Your Name'
    dependencies = []
    def __init__(self) -> None:
        self._event_bus = None
        self._logger = None
        self._config = None
        self._subscriber_id = None
        self._initialized = False
    def initialize(self, event_bus: Any, logger_provider: Any, config_provider: Any) -> None:
        self._event_bus = event_bus
        self._logger = logger_provider.get_logger(f'plugin.{self.name}')
        self._config = config_provider
        self._logger.info(f'Initializing {self.name} plugin v{self.version}')
        self._subscriber_id = self._event_bus.subscribe(event_type='example/trigger', callback=self.on_example_event, subscriber_id=f'{self.name}_subscriber')
        self._event_bus.subscribe(event_type='config/changed', callback=self.on_config_changed, subscriber_id=f'{self.name}_config_subscriber')
        self._initialized = True
        self._logger.info(f'{self.name} plugin initialized')
        self._event_bus.publish(event_type='plugin/initialized', source=self.name, payload={'plugin_name': self.name, 'version': self.version})
    def on_example_event(self, event: Event) -> None:
        self._logger.info(f'Received example event: {event.event_id}')
        message = event.payload.get('message', 'No message provided')
        timestamp = event.timestamp
        self._logger.debug(f"Example event details: message='{message}', timestamp={timestamp}")
        time.sleep(0.1)
        self._event_bus.publish(event_type='example/response', source=self.name, payload={'original_event_id': event.event_id, 'message': f'Processed: {message}', 'processing_time_ms': 100}, correlation_id=event.correlation_id)
    def on_config_changed(self, event: Event) -> None:
        if not event.payload.get('key', '').startswith('plugins.example_plugin'):
            return
        self._logger.info(f"Configuration changed: {event.payload.get('key')} = {event.payload.get('value')}")
        if event.payload.get('key') == 'plugins.example_plugin.active':
            active = event.payload.get('value', False)
            if active:
                self._logger.info('Plugin activated by configuration change')
            else:
                self._logger.info('Plugin deactivated by configuration change')
    def shutdown(self) -> None:
        if not self._initialized:
            return
        self._logger.info(f'Shutting down {self.name} plugin')
        if self._event_bus and self._subscriber_id:
            self._event_bus.unsubscribe(self._subscriber_id)
            self._event_bus.unsubscribe(f'{self.name}_config_subscriber')
        if self._event_bus:
            self._event_bus.publish(event_type='plugin/shutdown', source=self.name, payload={'plugin_name': self.name}, synchronous=True)
        self._initialized = False
        self._logger.info(f'{self.name} plugin shut down')
    def status(self) -> Dict[str, Any]:
        return {'name': self.name, 'version': self.version, 'initialized': self._initialized, 'subscriptions': ['example/trigger', 'config/changed']}