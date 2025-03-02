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
    """Alert severity levels."""
    
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Represents a monitoring alert."""
    
    id: str  # Unique identifier for the alert
    level: AlertLevel  # Severity level
    message: str  # Alert message
    source: str  # Component that generated the alert
    timestamp: datetime.datetime  # When the alert was created
    metric_name: Optional[str] = None  # Name of the metric that triggered the alert
    metric_value: Optional[float] = None  # Value of the metric that triggered the alert
    threshold: Optional[float] = None  # Threshold that was exceeded
    resolved: bool = False  # Whether the alert has been resolved
    resolved_at: Optional[datetime.datetime] = None  # When the alert was resolved
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata


class ResourceMonitoringManager(NexusManager):
    """Manages monitoring of system resources and application metrics.
    
    The Resource Monitoring Manager is responsible for collecting and exposing
    metrics about system resources (CPU, memory, disk) and application-specific
    metrics. It provides integrations with Prometheus for metrics collection
    and can generate alerts when metrics exceed defined thresholds.
    """
    
    def __init__(
        self,
        config_manager: Any,
        logger_manager: Any,
        event_bus_manager: Any,
        thread_manager: Any,
    ) -> None:
        """Initialize the Resource Monitoring Manager.
        
        Args:
            config_manager: The Configuration Manager for settings.
            logger_manager: The Logging Manager for logging.
            event_bus_manager: The Event Bus Manager for publishing alerts.
            thread_manager: The Thread Manager for scheduling metric collection.
        """
        super().__init__(name="ResourceMonitoringManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("monitoring_manager")
        self._event_bus = event_bus_manager
        self._thread_manager = thread_manager
        
        # Prometheus metrics
        self._metrics: Dict[str, Any] = {}  # name -> prometheus metric object
        self._prometheus_server_port: Optional[int] = None
        
        # System resource metrics
        self._cpu_percent_gauge: Optional[Gauge] = None
        self._memory_percent_gauge: Optional[Gauge] = None
        self._disk_percent_gauge: Optional[Gauge] = None
        
        # Alert thresholds
        self._alert_thresholds: Dict[str, float] = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
            "disk_percent": 90.0,
        }
        
        # Active alerts
        self._alerts: Dict[str, Alert] = {}
        self._resolved_alerts: deque = deque(maxlen=100)  # Keep last 100 resolved alerts
        self._alerts_lock = threading.RLock()
        
        # Metrics collection interval
        self._metrics_interval_seconds = 10
        
        # Collection tasks
        self._collection_tasks: Dict[str, str] = {}  # metric_name -> task_id
    
    def initialize(self) -> None:
        """Initialize the Resource Monitoring Manager.
        
        Starts the Prometheus HTTP server and sets up metric collection tasks.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get configuration
            monitoring_config = self._config_manager.get("monitoring", {})
            enabled = monitoring_config.get("enabled", True)
            
            if not enabled:
                self._logger.info("Resource Monitoring is disabled in configuration")
                self._initialized = True
                self._healthy = True
                return
            
            prometheus_config = monitoring_config.get("prometheus", {})
            prometheus_enabled = prometheus_config.get("enabled", True)
            prometheus_port = prometheus_config.get("port", 9090)
            
            # Alert thresholds
            alert_thresholds = monitoring_config.get("alert_thresholds", {})
            self._alert_thresholds.update(alert_thresholds)
            
            # Metrics interval
            self._metrics_interval_seconds = monitoring_config.get("metrics_interval_seconds", 10)
            
            # Set up Prometheus metrics
            if prometheus_enabled:
                # System resource metrics
                self._cpu_percent_gauge = Gauge(
                    "system_cpu_percent", "System CPU usage percentage"
                )
                self._memory_percent_gauge = Gauge(
                    "system_memory_percent", "System memory usage percentage"
                )
                self._disk_percent_gauge = Gauge(
                    "system_disk_percent", "System disk usage percentage"
                )
                
                # Application metrics
                self._metrics["app_uptime_seconds"] = Gauge(
                    "app_uptime_seconds", "Application uptime in seconds"
                )
                
                # Event metrics
                self._metrics["events_total"] = Counter(
                    "events_total", "Total number of events processed",
                    ["event_type", "source"]
                )
                self._metrics["event_processing_seconds"] = Histogram(
                    "event_processing_seconds", "Event processing time in seconds",
                    ["event_type"]
                )
                
                # Start Prometheus HTTP server
                start_http_server(prometheus_port)
                self._prometheus_server_port = prometheus_port
                
                self._logger.info(
                    f"Started Prometheus metrics server on port {prometheus_port}"
                )
            
            # Subscribe to events for monitoring
            self._event_bus.subscribe(
                event_type="*",  # All events
                callback=self._on_event,
                subscriber_id="monitoring_manager"
            )
            
            # Register for config changes
            self._config_manager.register_listener(
                "monitoring", self._on_config_changed
            )
            
            # Schedule metric collection tasks
            self._schedule_metric_collection()
            
            # Publish startup event
            self._event_bus.publish(
                event_type="monitoring/initialized",
                source="monitoring_manager",
                payload={"prometheus_port": self._prometheus_server_port},
            )
            
            self._initialized = True
            self._healthy = True
            
            self._logger.info("Resource Monitoring Manager initialized")
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Resource Monitoring Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize ResourceMonitoringManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _schedule_metric_collection(self) -> None:
        """Schedule periodic tasks for collecting metrics."""
        # System metrics collection
        system_metrics_task_id = self._thread_manager.schedule_periodic_task(
            interval=self._metrics_interval_seconds,
            func=self._collect_system_metrics,
            task_id="system_metrics_collection"
        )
        self._collection_tasks["system_metrics"] = system_metrics_task_id
        
        # Uptime metrics collection
        uptime_task_id = self._thread_manager.schedule_periodic_task(
            interval=60,  # Every minute
            func=self._collect_uptime_metrics,
            task_id="uptime_metrics_collection"
        )
        self._collection_tasks["uptime"] = uptime_task_id
    
    def _collect_system_metrics(self) -> None:
        """Collect system resource metrics (CPU, memory, disk)."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if self._cpu_percent_gauge:
                self._cpu_percent_gauge.set(cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            if self._memory_percent_gauge:
                self._memory_percent_gauge.set(memory_percent)
            
            # Disk usage (for the root/system partition)
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
            if self._disk_percent_gauge:
                self._disk_percent_gauge.set(disk_percent)
            
            # Check for threshold violations
            self._check_threshold("cpu_percent", cpu_percent)
            self._check_threshold("memory_percent", memory_percent)
            self._check_threshold("disk_percent", disk_percent)
            
            # Publish metrics event
            self._event_bus.publish(
                event_type="monitoring/metrics",
                source="monitoring_manager",
                payload={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent,
                    "timestamp": time.time(),
                },
            )
        
        except Exception as e:
            self._logger.error(f"Error collecting system metrics: {str(e)}")
    
    def _collect_uptime_metrics(self) -> None:
        """Collect application uptime metrics."""
        try:
            # Calculate uptime (time since process started)
            process = psutil.Process()
            uptime_seconds = time.time() - process.create_time()
            
            # Update Prometheus metric
            if "app_uptime_seconds" in self._metrics:
                self._metrics["app_uptime_seconds"].set(uptime_seconds)
        
        except Exception as e:
            self._logger.error(f"Error collecting uptime metrics: {str(e)}")
    
    def _check_threshold(self, metric_name: str, value: float) -> None:
        """Check if a metric value exceeds its alert threshold.
        
        Args:
            metric_name: The name of the metric to check.
            value: The current value of the metric.
        """
        if metric_name not in self._alert_thresholds:
            return
        
        threshold = self._alert_thresholds[metric_name]
        
        # Determine alert level based on how far the value exceeds the threshold
        if value >= threshold * 1.25:  # 25% over threshold - critical
            self._create_alert(
                level=AlertLevel.CRITICAL,
                message=f"{metric_name.replace('_', ' ').title()} is critically high: {value:.1f}%",
                source="monitoring_manager",
                metric_name=metric_name,
                metric_value=value,
                threshold=threshold
            )
        elif value >= threshold:  # At or over threshold - warning
            self._create_alert(
                level=AlertLevel.WARNING,
                message=f"{metric_name.replace('_', ' ').title()} is high: {value:.1f}%",
                source="monitoring_manager",
                metric_name=metric_name,
                metric_value=value,
                threshold=threshold
            )
        else:
            # Value is below threshold - resolve any existing alerts
            self._resolve_alerts_for_metric(metric_name)
    
    def _create_alert(
        self,
        level: AlertLevel,
        message: str,
        source: str,
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        threshold: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new alert.
        
        Args:
            level: The severity level of the alert.
            message: A descriptive message for the alert.
            source: The component that generated the alert.
            metric_name: Optional name of the metric that triggered the alert.
            metric_value: Optional value of the metric that triggered the alert.
            threshold: Optional threshold that was exceeded.
            metadata: Optional additional metadata for the alert.
            
        Returns:
            str: The ID of the created alert.
        """
        # Generate a unique ID for the alert
        import uuid
        alert_id = str(uuid.uuid4())
        
        # Check if there's already an active alert for this metric
        if metric_name:
            with self._alerts_lock:
                for existing_alert in self._alerts.values():
                    if (
                        existing_alert.metric_name == metric_name
                        and existing_alert.level == level
                        and not existing_alert.resolved
                    ):
                        # Don't create duplicate alerts, just update the existing one
                        existing_alert.timestamp = datetime.datetime.now()
                        existing_alert.metric_value = metric_value
                        
                        self._logger.debug(
                            f"Updated existing alert for {metric_name}: {message}",
                            extra={"alert_id": existing_alert.id, "level": level.value},
                        )
                        
                        return existing_alert.id
        
        # Create a new alert
        alert = Alert(
            id=alert_id,
            level=level,
            message=message,
            source=source,
            timestamp=datetime.datetime.now(),
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
            metadata=metadata or {},
        )
        
        # Store the alert
        with self._alerts_lock:
            self._alerts[alert_id] = alert
        
        # Log the alert
        log_method = {
            AlertLevel.INFO: self._logger.info,
            AlertLevel.WARNING: self._logger.warning,
            AlertLevel.ERROR: self._logger.error,
            AlertLevel.CRITICAL: self._logger.critical,
        }.get(level, self._logger.warning)
        
        log_method(
            f"Alert: {message}",
            extra={
                "alert_id": alert_id,
                "level": level.value,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "threshold": threshold,
            },
        )
        
        # Publish alert event
        self._event_bus.publish(
            event_type="monitoring/alert",
            source="monitoring_manager",
            payload={
                "alert_id": alert_id,
                "level": level.value,
                "message": message,
                "timestamp": alert.timestamp.isoformat(),
                "metric_name": metric_name,
                "metric_value": metric_value,
                "threshold": threshold,
            },
        )
        
        return alert_id
    
    def _resolve_alerts_for_metric(self, metric_name: str) -> None:
        """Resolve all active alerts for a specific metric.
        
        Args:
            metric_name: The name of the metric to resolve alerts for.
        """
        with self._alerts_lock:
            for alert_id, alert in list(self._alerts.items()):
                if alert.metric_name == metric_name and not alert.resolved:
                    # Resolve the alert
                    alert.resolved = True
                    alert.resolved_at = datetime.datetime.now()
                    
                    # Move to resolved alerts
                    self._resolved_alerts.append(alert)
                    del self._alerts[alert_id]
                    
                    self._logger.info(
                        f"Resolved alert for {metric_name}",
                        extra={"alert_id": alert_id, "level": alert.level.value},
                    )
                    
                    # Publish alert resolved event
                    self._event_bus.publish(
                        event_type="monitoring/alert_resolved",
                        source="monitoring_manager",
                        payload={
                            "alert_id": alert_id,
                            "metric_name": metric_name,
                            "resolved_at": alert.resolved_at.isoformat(),
                        },
                    )
    
    def _on_event(self, event: Any) -> None:
        """Handle events for monitoring purposes.
        
        Args:
            event: The event to handle.
        """
        # Increment event counter
        if "events_total" in self._metrics:
            self._metrics["events_total"].labels(
                event_type=event.event_type,
                source=event.source,
            ).inc()
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for monitoring.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "monitoring.enabled":
            # Can't easily disable/enable monitoring at runtime
            self._logger.warning(
                "Changing monitoring.enabled requires restart to take effect",
                extra={"enabled": value},
            )
        
        elif key.startswith("monitoring.alert_thresholds."):
            # Update alert threshold
            threshold_name = key.split(".")[-1]
            if threshold_name in self._alert_thresholds:
                self._alert_thresholds[threshold_name] = float(value)
                self._logger.info(
                    f"Updated alert threshold for {threshold_name}: {value}",
                    extra={"threshold": threshold_name, "value": value},
                )
        
        elif key == "monitoring.metrics_interval_seconds":
            # Update metrics interval
            old_interval = self._metrics_interval_seconds
            self._metrics_interval_seconds = value
            
            self._logger.info(
                f"Updated metrics interval: {value}s",
                extra={"old_interval": old_interval, "new_interval": value},
            )
            
            # Re-schedule metric collection tasks with new interval
            # For now, we'll just log that a restart is needed
            self._logger.warning(
                "Changing metrics interval requires restart to take full effect",
                extra={"interval": value},
            )
    
    def register_gauge(
        self,
        name: str,
        description: str,
        labels: Optional[List[str]] = None,
    ) -> Any:
        """Register a new gauge metric.
        
        Args:
            name: The name of the metric.
            description: Description of what the metric measures.
            labels: Optional list of label names for the metric.
            
        Returns:
            Any: The Prometheus gauge object.
            
        Raises:
            ValueError: If the metric name is already registered.
        """
        if not self._initialized:
            raise ValueError("ResourceMonitoringManager is not initialized")
        
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        
        gauge = Gauge(name, description, labels or [])
        self._metrics[name] = gauge
        
        return gauge
    
    def register_counter(
        self,
        name: str,
        description: str,
        labels: Optional[List[str]] = None,
    ) -> Any:
        """Register a new counter metric.
        
        Args:
            name: The name of the metric.
            description: Description of what the metric measures.
            labels: Optional list of label names for the metric.
            
        Returns:
            Any: The Prometheus counter object.
            
        Raises:
            ValueError: If the metric name is already registered.
        """
        if not self._initialized:
            raise ValueError("ResourceMonitoringManager is not initialized")
        
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        
        counter = Counter(name, description, labels or [])
        self._metrics[name] = counter
        
        return counter
    
    def register_histogram(
        self,
        name: str,
        description: str,
        labels: Optional[List[str]] = None,
        buckets: Optional[List[float]] = None,
    ) -> Any:
        """Register a new histogram metric.
        
        Args:
            name: The name of the metric.
            description: Description of what the metric measures.
            labels: Optional list of label names for the metric.
            buckets: Optional list of bucket boundaries.
            
        Returns:
            Any: The Prometheus histogram object.
            
        Raises:
            ValueError: If the metric name is already registered.
        """
        if not self._initialized:
            raise ValueError("ResourceMonitoringManager is not initialized")
        
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        
        histogram = Histogram(name, description, labels or [], buckets=buckets)
        self._metrics[name] = histogram
        
        return histogram
    
    def register_summary(
        self,
        name: str,
        description: str,
        labels: Optional[List[str]] = None,
    ) -> Any:
        """Register a new summary metric.
        
        Args:
            name: The name of the metric.
            description: Description of what the metric measures.
            labels: Optional list of label names for the metric.
            
        Returns:
            Any: The Prometheus summary object.
            
        Raises:
            ValueError: If the metric name is already registered.
        """
        if not self._initialized:
            raise ValueError("ResourceMonitoringManager is not initialized")
        
        if name in self._metrics:
            raise ValueError(f"Metric '{name}' is already registered")
        
        summary = Summary(name, description, labels or [])
        self._metrics[name] = summary
        
        return summary
    
    def get_alerts(
        self,
        include_resolved: bool = False,
        level: Optional[AlertLevel] = None,
        metric_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get active alerts, optionally filtered.
        
        Args:
            include_resolved: Whether to include resolved alerts.
            level: Optional filter by alert level.
            metric_name: Optional filter by metric name.
            
        Returns:
            List[Dict[str, Any]]: List of alert information dictionaries.
        """
        result = []
        
        with self._alerts_lock:
            # Add active alerts
            for alert in self._alerts.values():
                if (level is None or alert.level == level) and (metric_name is None or alert.metric_name == metric_name):
                    result.append({
                        "id": alert.id,
                        "level": alert.level.value,
                        "message": alert.message,
                        "source": alert.source,
                        "timestamp": alert.timestamp.isoformat(),
                        "metric_name": alert.metric_name,
                        "metric_value": alert.metric_value,
                        "threshold": alert.threshold,
                        "resolved": alert.resolved,
                        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                        "metadata": alert.metadata,
                    })
            
            # Add resolved alerts if requested
            if include_resolved:
                for alert in self._resolved_alerts:
                    if (level is None or alert.level == level) and (metric_name is None or alert.metric_name == metric_name):
                        result.append({
                            "id": alert.id,
                            "level": alert.level.value,
                            "message": alert.message,
                            "source": alert.source,
                            "timestamp": alert.timestamp.isoformat(),
                            "metric_name": alert.metric_name,
                            "metric_value": alert.metric_value,
                            "threshold": alert.threshold,
                            "resolved": alert.resolved,
                            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                            "metadata": alert.metadata,
                        })
        
        # Sort by timestamp (newest first)
        result.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return result
    
    def generate_diagnostic_report(self) -> Dict[str, Any]:
        """Generate a diagnostic report with system and application metrics.
        
        Returns:
            Dict[str, Any]: A diagnostic report with current metrics and status.
        """
        if not self._initialized:
            return {"error": "MonitoringManager not initialized"}
        
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            
            # Get process metrics
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent(interval=1)
            
            # Create report
            report = {
                "timestamp": datetime.datetime.now().isoformat(),
                "system": {
                    "cpu": {
                        "percent": cpu_percent,
                    },
                    "memory": {
                        "total_mb": memory.total / (1024 * 1024),
                        "available_mb": memory.available / (1024 * 1024),
                        "used_mb": memory.used / (1024 * 1024),
                        "percent": memory.percent,
                    },
                    "disk": {
                        "total_gb": disk.total / (1024 * 1024 * 1024),
                        "free_gb": disk.free / (1024 * 1024 * 1024),
                        "used_gb": disk.used / (1024 * 1024 * 1024),
                        "percent": disk.percent,
                    },
                },
                "process": {
                    "pid": process.pid,
                    "cpu_percent": process_cpu,
                    "memory_mb": process_memory.rss / (1024 * 1024),
                    "uptime_seconds": time.time() - process.create_time(),
                    "threads": process.num_threads(),
                },
                "alerts": {
                    "active": len(self._alerts),
                    "resolved": len(self._resolved_alerts),
                },
                "thresholds": self._alert_thresholds,
            }
            
            return report
        
        except Exception as e:
            self._logger.error(f"Error generating diagnostic report: {str(e)}")
            return {"error": f"Failed to generate report: {str(e)}"}
    
    def shutdown(self) -> None:
        """Shut down the Resource Monitoring Manager.
        
        Stops metrics collection and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Resource Monitoring Manager")
            
            # Cancel scheduled metric collection tasks
            for task_id in self._collection_tasks.values():
                self._thread_manager.cancel_periodic_task(task_id)
            
            # Unregister from event bus
            self._event_bus.unsubscribe("monitoring_manager")
            
            # Unregister config listener
            self._config_manager.unregister_listener("monitoring", self._on_config_changed)
            
            # Prometheus HTTP server cannot be easily stopped - it will continue running
            # until the process exits
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Resource Monitoring Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Resource Monitoring Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down ResourceMonitoringManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Resource Monitoring Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Resource Monitoring Manager.
        """
        status = super().status()
        
        if self._initialized:
            status.update({
                "prometheus": {
                    "enabled": self._prometheus_server_port is not None,
                    "port": self._prometheus_server_port,
                    "metrics_count": len(self._metrics),
                },
                "alerts": {
                    "active": len(self._alerts),
                    "resolved": len(self._resolved_alerts),
                },
                "metrics_interval": self._metrics_interval_seconds,
                "collection_tasks": len(self._collection_tasks),
            })
            
            # Add current system metrics
            try:
                status["current_metrics"] = {
                    "cpu_percent": psutil.cpu_percent(interval=None),  # Non-blocking
                    "memory_percent": psutil.virtual_memory().percent,
                    "disk_percent": psutil.disk_usage("/").percent,
                }
            except:
                # Ignore errors getting current metrics
                pass
        
        return status
