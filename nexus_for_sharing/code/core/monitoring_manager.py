from __future__ import annotations
import datetime
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, cast
import psutil
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError
class AlertLevel(Enum):
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'
@dataclass
class Alert:
    id: str
    level: AlertLevel
    message: str
    source: str
    timestamp: datetime.datetime
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    resolved: bool = False
    resolved_at: Optional[datetime.datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
class ResourceMonitoringManager(NexusManager):
    def __init__(self, config_manager: Any, logger_manager: Any, event_bus_manager: Any, thread_manager: Any) -> None:
        super().__init__(name='ResourceMonitoringManager')
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger('monitoring_manager')
        self._event_bus = event_bus_manager
        self._thread_manager = thread_manager
        self._metrics: Dict[str, Any] = {}
        self._prometheus_server_port: Optional[int] = None
        self._cpu_percent_gauge: Optional[Gauge] = None
        self._memory_percent_gauge: Optional[Gauge] = None
        self._disk_percent_gauge: Optional[Gauge] = None
        self._alert_thresholds: Dict[str, float] = {'cpu_percent': 80.0, 'memory_percent': 80.0, 'disk_percent': 90.0}
        self._alerts: Dict[str, Alert] = {}
        self._resolved_alerts: deque = deque(maxlen=100)
        self._alerts_lock = threading.RLock()
        self._metrics_interval_seconds = 10
        self._collection_tasks: Dict[str, str] = {}
    def initialize(self) -> None:
        try:
            monitoring_config = self._config_manager.get('monitoring', {})
            enabled = monitoring_config.get('enabled', True)
            if not enabled:
                self._logger.info('Resource Monitoring is disabled in configuration')
                self._initialized = True
                self._healthy = True
                return
            prometheus_config = monitoring_config.get('prometheus', {})
            prometheus_enabled = prometheus_config.get('enabled', True)
            prometheus_port = prometheus_config.get('port', 9090)
            alert_thresholds = monitoring_config.get('alert_thresholds', {})
            self._alert_thresholds.update(alert_thresholds)
            self._metrics_interval_seconds = monitoring_config.get('metrics_interval_seconds', 10)
            if prometheus_enabled:
                self._cpu_percent_gauge = Gauge('system_cpu_percent', 'System CPU usage percentage')
                self._memory_percent_gauge = Gauge('system_memory_percent', 'System memory usage percentage')
                self._disk_percent_gauge = Gauge('system_disk_percent', 'System disk usage percentage')
                self._metrics['app_uptime_seconds'] = Gauge('app_uptime_seconds', 'Application uptime in seconds')
                self._metrics['events_total'] = Counter('events_total', 'Total number of events processed', ['event_type', 'source'])
                self._metrics['event_processing_seconds'] = Histogram('event_processing_seconds', 'Event processing time in seconds', ['event_type'])
                start_http_server(prometheus_port)
                self._prometheus_server_port = prometheus_port
                self._logger.info(f'Started Prometheus metrics server on port {prometheus_port}')
            self._event_bus.subscribe(event_type='*', callback=self._on_event, subscriber_id='monitoring_manager')
            self._config_manager.register_listener('monitoring', self._on_config_changed)
            self._schedule_metric_collection()
            self._event_bus.publish(event_type='monitoring/initialized', source='monitoring_manager', payload={'prometheus_port': self._prometheus_server_port})
            self._initialized = True
            self._healthy = True
            self._logger.info('Resource Monitoring Manager initialized')
        except Exception as e:
            self._logger.error(f'Failed to initialize Resource Monitoring Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize ResourceMonitoringManager: {str(e)}', manager_name=self.name) from e
    def _schedule_metric_collection(self) -> None:
        system_metrics_task_id = self._thread_manager.schedule_periodic_task(interval=self._metrics_interval_seconds, func=self._collect_system_metrics, task_id='system_metrics_collection')
        self._collection_tasks['system_metrics'] = system_metrics_task_id
        uptime_task_id = self._thread_manager.schedule_periodic_task(interval=60, func=self._collect_uptime_metrics, task_id='uptime_metrics_collection')
        self._collection_tasks['uptime'] = uptime_task_id
    def _collect_system_metrics(self) -> None:
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            if self._cpu_percent_gauge:
                self._cpu_percent_gauge.set(cpu_percent)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            if self._memory_percent_gauge:
                self._memory_percent_gauge.set(memory_percent)
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            if self._disk_percent_gauge:
                self._disk_percent_gauge.set(disk_percent)
            self._check_threshold('cpu_percent', cpu_percent)
            self._check_threshold('memory_percent', memory_percent)
            self._check_threshold('disk_percent', disk_percent)
            self._event_bus.publish(event_type='monitoring/metrics', source='monitoring_manager', payload={'cpu_percent': cpu_percent, 'memory_percent': memory_percent, 'disk_percent': disk_percent, 'timestamp': time.time()})
        except Exception as e:
            self._logger.error(f'Error collecting system metrics: {str(e)}')
    def _collect_uptime_metrics(self) -> None:
        try:
            process = psutil.Process()
            uptime_seconds = time.time() - process.create_time()
            if 'app_uptime_seconds' in self._metrics:
                self._metrics['app_uptime_seconds'].set(uptime_seconds)
        except Exception as e:
            self._logger.error(f'Error collecting uptime metrics: {str(e)}')
    def _check_threshold(self, metric_name: str, value: float) -> None:
        if metric_name not in self._alert_thresholds:
            return
        threshold = self._alert_thresholds[metric_name]
        if value >= threshold * 1.25:
            self._create_alert(level=AlertLevel.CRITICAL, message=f"{metric_name.replace('_', ' ').title()} is critically high: {value:.1f}%", source='monitoring_manager', metric_name=metric_name, metric_value=value, threshold=threshold)
        elif value >= threshold:
            self._create_alert(level=AlertLevel.WARNING, message=f"{metric_name.replace('_', ' ').title()} is high: {value:.1f}%", source='monitoring_manager', metric_name=metric_name, metric_value=value, threshold=threshold)
        else:
            self._resolve_alerts_for_metric(metric_name)
    def _create_alert(self, level: AlertLevel, message: str, source: str, metric_name: Optional[str]=None, metric_value: Optional[float]=None, threshold: Optional[float]=None, metadata: Optional[Dict[str, Any]]=None) -> str:
        import uuid
        alert_id = str(uuid.uuid4())
        if metric_name:
            with self._alerts_lock:
                for existing_alert in self._alerts.values():
                    if existing_alert.metric_name == metric_name and existing_alert.level == level and (not existing_alert.resolved):
                        existing_alert.timestamp = datetime.datetime.now()
                        existing_alert.metric_value = metric_value
                        self._logger.debug(f'Updated existing alert for {metric_name}: {message}', extra={'alert_id': existing_alert.id, 'level': level.value})
                        return existing_alert.id
        alert = Alert(id=alert_id, level=level, message=message, source=source, timestamp=datetime.datetime.now(), metric_name=metric_name, metric_value=metric_value, threshold=threshold, metadata=metadata or {})
        with self._alerts_lock:
            self._alerts[alert_id] = alert
        log_method = {AlertLevel.INFO: self._logger.info, AlertLevel.WARNING: self._logger.warning, AlertLevel.ERROR: self._logger.error, AlertLevel.CRITICAL: self._logger.critical}.get(level, self._logger.warning)
        log_method(f'Alert: {message}', extra={'alert_id': alert_id, 'level': level.value, 'metric_name': metric_name, 'metric_value': metric_value, 'threshold': threshold})
        self._event_bus.publish(event_type='monitoring/alert', source='monitoring_manager', payload={'alert_id': alert_id, 'level': level.value, 'message': message, 'timestamp': alert.timestamp.isoformat(), 'metric_name': metric_name, 'metric_value': metric_value, 'threshold': threshold})
        return alert_id
    def _resolve_alerts_for_metric(self, metric_name: str) -> None:
        with self._alerts_lock:
            for alert_id, alert in list(self._alerts.items()):
                if alert.metric_name == metric_name and (not alert.resolved):
                    alert.resolved = True
                    alert.resolved_at = datetime.datetime.now()
                    self._resolved_alerts.append(alert)
                    del self._alerts[alert_id]
                    self._logger.info(f'Resolved alert for {metric_name}', extra={'alert_id': alert_id, 'level': alert.level.value})
                    self._event_bus.publish(event_type='monitoring/alert_resolved', source='monitoring_manager', payload={'alert_id': alert_id, 'metric_name': metric_name, 'resolved_at': alert.resolved_at.isoformat()})
    def _on_event(self, event: Any) -> None:
        if 'events_total' in self._metrics:
            self._metrics['events_total'].labels(event_type=event.event_type, source=event.source).inc()
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key == 'monitoring.enabled':
            self._logger.warning('Changing monitoring.enabled requires restart to take effect', extra={'enabled': value})
        elif key.startswith('monitoring.alert_thresholds.'):
            threshold_name = key.split('.')[-1]
            if threshold_name in self._alert_thresholds:
                self._alert_thresholds[threshold_name] = float(value)
                self._logger.info(f'Updated alert threshold for {threshold_name}: {value}', extra={'threshold': threshold_name, 'value': value})
        elif key == 'monitoring.metrics_interval_seconds':
            old_interval = self._metrics_interval_seconds
            self._metrics_interval_seconds = value
            self._logger.info(f'Updated metrics interval: {value}s', extra={'old_interval': old_interval, 'new_interval': value})
            self._logger.warning('Changing metrics interval requires restart to take full effect', extra={'interval': value})
    def register_gauge(self, name: str, description: str, labels: Optional[List[str]]=None) -> Any:
        if not self._initialized:
            raise ValueError('ResourceMonitoringManager is not initialized')
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        gauge = Gauge(name, description, labels or [])
        self._metrics[name] = gauge
        return gauge
    def register_counter(self, name: str, description: str, labels: Optional[List[str]]=None) -> Any:
        if not self._initialized:
            raise ValueError('ResourceMonitoringManager is not initialized')
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        counter = Counter(name, description, labels or [])
        self._metrics[name] = counter
        return counter
    def register_histogram(self, name: str, description: str, labels: Optional[List[str]]=None, buckets: Optional[List[float]]=None) -> Any:
        if not self._initialized:
            raise ValueError('ResourceMonitoringManager is not initialized')
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        histogram = Histogram(name, description, labels or [], buckets=buckets)
        self._metrics[name] = histogram
        return histogram
    def register_summary(self, name: str, description: str, labels: Optional[List[str]]=None) -> Any:
        if not self._initialized:
            raise ValueError('ResourceMonitoringManager is not initialized')
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        summary = Summary(name, description, labels or [])
        self._metrics[name] = summary
        return summary
    def get_alerts(self, include_resolved: bool=False, level: Optional[AlertLevel]=None, metric_name: Optional[str]=None) -> List[Dict[str, Any]]:
        result = []
        with self._alerts_lock:
            for alert in self._alerts.values():
                if (level is None or alert.level == level) and (metric_name is None or alert.metric_name == metric_name):
                    result.append({'id': alert.id, 'level': alert.level.value, 'message': alert.message, 'source': alert.source, 'timestamp': alert.timestamp.isoformat(), 'metric_name': alert.metric_name, 'metric_value': alert.metric_value, 'threshold': alert.threshold, 'resolved': alert.resolved, 'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None, 'metadata': alert.metadata})
            if include_resolved:
                for alert in self._resolved_alerts:
                    if (level is None or alert.level == level) and (metric_name is None or alert.metric_name == metric_name):
                        result.append({'id': alert.id, 'level': alert.level.value, 'message': alert.message, 'source': alert.source, 'timestamp': alert.timestamp.isoformat(), 'metric_name': alert.metric_name, 'metric_value': alert.metric_value, 'threshold': alert.threshold, 'resolved': alert.resolved, 'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None, 'metadata': alert.metadata})
        result.sort(key=lambda x: x['timestamp'], reverse=True)
        return result
    def generate_diagnostic_report(self) -> Dict[str, Any]:
        if not self._initialized:
            return {'error': 'MonitoringManager not initialized'}
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent(interval=1)
            report = {'timestamp': datetime.datetime.now().isoformat(), 'system': {'cpu': {'percent': cpu_percent}, 'memory': {'total_mb': memory.total / (1024 * 1024), 'available_mb': memory.available / (1024 * 1024), 'used_mb': memory.used / (1024 * 1024), 'percent': memory.percent}, 'disk': {'total_gb': disk.total / (1024 * 1024 * 1024), 'free_gb': disk.free / (1024 * 1024 * 1024), 'used_gb': disk.used / (1024 * 1024 * 1024), 'percent': disk.percent}}, 'process': {'pid': process.pid, 'cpu_percent': process_cpu, 'memory_mb': process_memory.rss / (1024 * 1024), 'uptime_seconds': time.time() - process.create_time(), 'threads': process.num_threads()}, 'alerts': {'active': len(self._alerts), 'resolved': len(self._resolved_alerts)}, 'thresholds': self._alert_thresholds}
            return report
        except Exception as e:
            self._logger.error(f'Error generating diagnostic report: {str(e)}')
            return {'error': f'Failed to generate report: {str(e)}'}
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down Resource Monitoring Manager')
            for task_id in self._collection_tasks.values():
                self._thread_manager.cancel_periodic_task(task_id)
            self._event_bus.unsubscribe('monitoring_manager')
            self._config_manager.unregister_listener('monitoring', self._on_config_changed)
            self._initialized = False
            self._healthy = False
            self._logger.info('Resource Monitoring Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down Resource Monitoring Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down ResourceMonitoringManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            status.update({'prometheus': {'enabled': self._prometheus_server_port is not None, 'port': self._prometheus_server_port, 'metrics_count': len(self._metrics)}, 'alerts': {'active': len(self._alerts), 'resolved': len(self._resolved_alerts)}, 'metrics_interval': self._metrics_interval_seconds, 'collection_tasks': len(self._collection_tasks)})
            try:
                status['current_metrics'] = {'cpu_percent': psutil.cpu_percent(interval=None), 'memory_percent': psutil.virtual_memory().percent, 'disk_percent': psutil.disk_usage('/').percent}
            except:
                pass
        return status