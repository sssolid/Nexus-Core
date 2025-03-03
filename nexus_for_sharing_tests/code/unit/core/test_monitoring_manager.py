import pytest
import time
from unittest.mock import MagicMock, patch, call
from nexus_core.core.monitoring_manager import ResourceMonitoringManager, AlertLevel
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError
@pytest.fixture
def monitoring_config():
    return {'enabled': True, 'prometheus': {'enabled': True, 'port': 9090}, 'alert_thresholds': {'cpu_percent': 80.0, 'memory_percent': 80.0, 'disk_percent': 90.0}, 'metrics_interval_seconds': 10}
@pytest.fixture
def config_manager_mock(monitoring_config):
    config_manager = MagicMock()
    config_manager.get.return_value = monitoring_config
    return config_manager
@pytest.fixture
def monitoring_manager(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    monitoring_mgr = ResourceMonitoringManager(config_manager_mock, logger_manager, event_bus_manager, thread_manager)
    with patch('nexus_core.core.monitoring_manager.Gauge'), patch('nexus_core.core.monitoring_manager.Counter'), patch('nexus_core.core.monitoring_manager.Histogram'), patch('nexus_core.core.monitoring_manager.start_http_server'):
        monitoring_mgr.initialize()
    yield monitoring_mgr
    monitoring_mgr.shutdown()
@patch('nexus_core.core.monitoring_manager.psutil')
def test_monitoring_manager_initialization(mock_psutil, config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    with patch('nexus_core.core.monitoring_manager.Gauge'), patch('nexus_core.core.monitoring_manager.Counter'), patch('nexus_core.core.monitoring_manager.Histogram'), patch('nexus_core.core.monitoring_manager.start_http_server') as mock_start_server:
        monitoring_mgr = ResourceMonitoringManager(config_manager_mock, logger_manager, event_bus_manager, thread_manager)
        monitoring_mgr.initialize()
        assert monitoring_mgr.initialized
        assert monitoring_mgr.healthy
        assert mock_start_server.called
        event_bus_manager.subscribe.assert_called_with(event_type='*', callback=monitoring_mgr._on_event, subscriber_id='monitoring_manager')
        thread_manager.schedule_periodic_task.assert_any_call(interval=10, func=monitoring_mgr._collect_system_metrics, task_id='system_metrics_collection')
        config_manager_mock.register_listener.assert_called_with('monitoring', monitoring_mgr._on_config_changed)
        event_bus_manager.publish.assert_called_with(event_type='monitoring/initialized', source='monitoring_manager', payload={'prometheus_port': 9090})
        monitoring_mgr.shutdown()
@patch('nexus_core.core.monitoring_manager.psutil')
def test_collect_system_metrics(mock_psutil, monitoring_manager):
    mock_psutil.cpu_percent.return_value = 50.0
    mock_psutil.virtual_memory.return_value.percent = 60.0
    mock_psutil.disk_usage.return_value.percent = 70.0
    monitoring_manager._collect_system_metrics()
    mock_psutil.cpu_percent.assert_called_with(interval=1)
    mock_psutil.virtual_memory.assert_called_once()
    mock_psutil.disk_usage.assert_called_with('/')
    monitoring_manager._event_bus.publish.assert_called_with(event_type='monitoring/metrics', source='monitoring_manager', payload={'cpu_percent': 50.0, 'memory_percent': 60.0, 'disk_percent': 70.0, 'timestamp': mock.ANY})
    if monitoring_manager._cpu_percent_gauge:
        monitoring_manager._cpu_percent_gauge.set.assert_called_with(50.0)
    if monitoring_manager._memory_percent_gauge:
        monitoring_manager._memory_percent_gauge.set.assert_called_with(60.0)
    if monitoring_manager._disk_percent_gauge:
        monitoring_manager._disk_percent_gauge.set.assert_called_with(70.0)
@patch('nexus_core.core.monitoring_manager.psutil')
def test_threshold_alerts(mock_psutil, monitoring_manager):
    mock_psutil.cpu_percent.return_value = 50.0
    mock_psutil.virtual_memory.return_value.percent = 60.0
    mock_psutil.disk_usage.return_value.percent = 70.0
    monitoring_manager._collect_system_metrics()
    assert len(monitoring_manager._alerts) == 0
    mock_psutil.cpu_percent.return_value = 85.0
    monitoring_manager._collect_system_metrics()
    assert len(monitoring_manager._alerts) == 1
    assert list(monitoring_manager._alerts.values())[0].level == AlertLevel.WARNING
    mock_psutil.cpu_percent.return_value = 95.0
    monitoring_manager._collect_system_metrics()
    assert len(monitoring_manager._alerts) == 1
    assert list(monitoring_manager._alerts.values())[0].level == AlertLevel.CRITICAL
    mock_psutil.cpu_percent.return_value = 50.0
    monitoring_manager._collect_system_metrics()
    assert len(monitoring_manager._alerts) == 0
    assert len(monitoring_manager._resolved_alerts) == 1
def test_alert_creation_and_resolution(monitoring_manager):
    alert_id = monitoring_manager._create_alert(level=AlertLevel.WARNING, message='Test alert', source='test', metric_name='test_metric', metric_value=85.0, threshold=80.0)
    assert alert_id in monitoring_manager._alerts
    alert = monitoring_manager._alerts[alert_id]
    assert alert.level == AlertLevel.WARNING
    assert alert.message == 'Test alert'
    assert alert.metric_name == 'test_metric'
    assert alert.metric_value == 85.0
    assert alert.threshold == 80.0
    assert alert.resolved is False
    monitoring_manager._resolve_alerts_for_metric('test_metric')
    assert alert_id not in monitoring_manager._alerts
    assert len(monitoring_manager._resolved_alerts) == 1
    resolved_alert = monitoring_manager._resolved_alerts[0]
    assert resolved_alert.id == alert_id
    assert resolved_alert.resolved is True
    assert resolved_alert.resolved_at is not None
def test_get_alerts(monitoring_manager):
    warning_id = monitoring_manager._create_alert(level=AlertLevel.WARNING, message='Warning alert', source='test', metric_name='cpu_percent')
    critical_id = monitoring_manager._create_alert(level=AlertLevel.CRITICAL, message='Critical alert', source='test', metric_name='memory_percent')
    alerts = monitoring_manager.get_alerts()
    assert len(alerts) == 2
    critical_alerts = monitoring_manager.get_alerts(level=AlertLevel.CRITICAL)
    assert len(critical_alerts) == 1
    assert critical_alerts[0]['level'] == 'critical'
    cpu_alerts = monitoring_manager.get_alerts(metric_name='cpu_percent')
    assert len(cpu_alerts) == 1
    assert cpu_alerts[0]['metric_name'] == 'cpu_percent'
    monitoring_manager._resolve_alerts_for_metric('cpu_percent')
    all_alerts = monitoring_manager.get_alerts(include_resolved=True)
    assert len(all_alerts) == 2
    active_alerts = monitoring_manager.get_alerts(include_resolved=False)
    assert len(active_alerts) == 1
def test_register_metrics(monitoring_manager):
    with patch('nexus_core.core.monitoring_manager.Gauge') as mock_gauge, patch('nexus_core.core.monitoring_manager.Counter') as mock_counter, patch('nexus_core.core.monitoring_manager.Histogram') as mock_histogram, patch('nexus_core.core.monitoring_manager.Summary') as mock_summary:
        gauge = monitoring_manager.register_gauge(name='custom_gauge', description='A custom gauge metric')
        counter = monitoring_manager.register_counter(name='custom_counter', description='A custom counter metric', labels=['label1', 'label2'])
        histogram = monitoring_manager.register_histogram(name='custom_histogram', description='A custom histogram metric', buckets=[0.1, 0.5, 1.0, 5.0])
        summary = monitoring_manager.register_summary(name='custom_summary', description='A custom summary metric')
        mock_gauge.assert_called_with('custom_gauge', 'A custom gauge metric', [])
        mock_counter.assert_called_with('custom_counter', 'A custom counter metric', ['label1', 'label2'])
        mock_histogram.assert_called_with('custom_histogram', 'A custom histogram metric', [], buckets=[0.1, 0.5, 1.0, 5.0])
        mock_summary.assert_called_with('custom_summary', 'A custom summary metric', [])
@patch('nexus_core.core.monitoring_manager.psutil')
def test_diagnostic_report(mock_psutil, monitoring_manager):
    mock_process = MagicMock()
    mock_process.pid = 1234
    mock_process.cpu_percent.return_value = 10.0
    mock_process.memory_info.return_value.rss = 1024 * 1024 * 100
    mock_process.num_threads.return_value = 10
    mock_process.create_time.return_value = time.time() - 3600
    mock_psutil.Process.return_value = mock_process
    mock_psutil.cpu_percent.return_value = 50.0
    mock_memory = MagicMock()
    mock_memory.total = 1024 * 1024 * 1024 * 8
    mock_memory.available = 1024 * 1024 * 1024 * 4
    mock_memory.used = 1024 * 1024 * 1024 * 4
    mock_memory.percent = 50.0
    mock_psutil.virtual_memory.return_value = mock_memory
    mock_disk = MagicMock()
    mock_disk.total = 1024 * 1024 * 1024 * 100
    mock_disk.free = 1024 * 1024 * 1024 * 50
    mock_disk.used = 1024 * 1024 * 1024 * 50
    mock_disk.percent = 50.0
    mock_psutil.disk_usage.return_value = mock_disk
    report = monitoring_manager.generate_diagnostic_report()
    assert 'timestamp' in report
    assert 'system' in report
    assert 'process' in report
    assert 'alerts' in report
    assert 'thresholds' in report
    system = report['system']
    assert system['cpu']['percent'] == 50.0
    assert system['memory']['percent'] == 50.0
    assert system['disk']['percent'] == 50.0
    process = report['process']
    assert process['pid'] == 1234
    assert process['cpu_percent'] == 10.0
    assert process['memory_mb'] == 100.0
    assert process['threads'] == 10
    assert 'uptime_seconds' in process
def test_config_change_handling(monitoring_manager):
    monitoring_manager._on_config_changed('monitoring.alert_thresholds.cpu_percent', 90.0)
    assert monitoring_manager._alert_thresholds['cpu_percent'] == 90.0
    monitoring_manager._on_config_changed('monitoring.metrics_interval_seconds', 20)
    assert monitoring_manager._metrics_interval_seconds == 20
    monitoring_manager._on_config_changed('monitoring.enabled', False)
    monitoring_manager._logger.warning.assert_called_with('Changing monitoring.enabled requires restart to take effect', extra={'enabled': False})
def test_event_handling(monitoring_manager):
    event = MagicMock()
    event.event_type = 'test/event'
    event.source = 'test_source'
    monitoring_manager._metrics['events_total'] = MagicMock()
    monitoring_manager._on_event(event)
    monitoring_manager._metrics['events_total'].labels.assert_called_with(event_type='test/event', source='test_source')
    monitoring_manager._metrics['events_total'].labels().inc.assert_called_once()
def test_monitoring_manager_status(monitoring_manager):
    status = monitoring_manager.status()
    assert status['name'] == 'ResourceMonitoringManager'
    assert status['initialized'] is True
    assert 'prometheus' in status
    assert 'alerts' in status
    assert 'metrics_interval' in status
    assert 'collection_tasks' in status
    if 'current_metrics' in status:
        assert 'cpu_percent' in status['current_metrics']
        assert 'memory_percent' in status['current_metrics']
        assert 'disk_percent' in status['current_metrics']