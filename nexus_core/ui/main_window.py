from __future__ import annotations

import sys
import threading
import time
from typing import Any, Dict, List, Optional, cast

from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFormLayout, QHBoxLayout, QLabel, QMainWindow, 
    QMenu, QMessageBox, QProgressBar, QPushButton, QStatusBar, QTabWidget, 
    QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
)


class NexusMainWindow(QMainWindow):
    """Main window for the Nexus Core application."""
    
    # Signal for updating UI from non-GUI threads
    update_signal = Signal(str, object)
    
    def __init__(self, app_core: Any) -> None:
        """Initialize the main window.
        
        Args:
            app_core: The Application Core instance.
        """
        super().__init__()
        
        # Store the app core reference
        self._app_core = app_core
        
        # Get manager references
        self._config_manager = app_core.get_manager("config")
        self._logging_manager = app_core.get_manager("logging")
        self._event_bus = app_core.get_manager("event_bus")
        self._plugin_manager = app_core.get_manager("plugin_manager")
        self._monitoring_manager = app_core.get_manager("monitoring")
        
        # Get logger
        if self._logging_manager:
            self._logger = self._logging_manager.get_logger("ui")
        else:
            # Fallback
            import logging
            self._logger = logging.getLogger("ui")
        
        # UI components
        self._status_bar: Optional[QStatusBar] = None
        self._central_tabs: Optional[QTabWidget] = None
        self._log_text: Optional[QTextEdit] = None
        self._system_status_widget: Optional[QTreeWidget] = None
        self._plugin_tree: Optional[QTreeWidget] = None
        self._metrics_widget: Optional[QWidget] = None
        
        # Event subscriptions
        self._event_subscriptions: List[str] = []
        
        # Set up the UI
        self._setup_ui()
        
        # Connect signals
        self.update_signal.connect(self._handle_update_signal)
        
        # Set up a timer for periodic updates
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_status)
        self._update_timer.start(5000)  # Update every 5 seconds
        
        # Subscribe to events
        self._subscribe_to_events()
        
        # Initial status update
        self._update_status()
        
        # Log UI started
        self._logger.info("Nexus Core UI started")
    
    def _setup_ui(self) -> None:
        """Set up the user interface."""
        # Window settings
        self.setWindowTitle("Nexus Core")
        self.setMinimumSize(1024, 768)
        
        # Create the central widget with tabs
        self._central_tabs = QTabWidget()
        self.setCentralWidget(self._central_tabs)
        
        # Create main tabs
        self._create_dashboard_tab()
        self._create_plugins_tab()
        self._create_logs_tab()
        
        # Create status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        # Add status widgets to status bar
        self._status_bar.addPermanentWidget(QLabel("Ready"))
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create tool bar
        self._create_tool_bar()
    
    def _create_menu_bar(self) -> None:
        """Create the menu bar."""
        # File menu
        file_menu = self.menuBar().addMenu("&File")
        
        # Add actions to file menu
        refresh_action = QAction("&Refresh", self)
        refresh_action.triggered.connect(self._update_status)
        file_menu.addAction(refresh_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = self.menuBar().addMenu("&Tools")
        
        # Add actions to tools menu
        reload_plugins_action = QAction("&Reload Plugins", self)
        reload_plugins_action.triggered.connect(self._reload_plugins)
        tools_menu.addAction(reload_plugins_action)
        
        # Help menu
        help_menu = self.menuBar().addMenu("&Help")
        
        # Add actions to help menu
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)
    
    def _create_tool_bar(self) -> None:
        """Create the tool bar."""
        tool_bar = QToolBar("Main Toolbar")
        tool_bar.setMovable(False)
        self.addToolBar(tool_bar)
        
        # Add refresh button
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._update_status)
        tool_bar.addAction(refresh_action)
    
    def _create_dashboard_tab(self) -> None:
        """Create the dashboard tab."""
        dashboard_widget = QWidget()
        layout = QVBoxLayout(dashboard_widget)
        
        # Add title
        title_label = QLabel("Nexus Core Dashboard")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title_label)
        
        # Add system status widget
        status_group_label = QLabel("System Status")
        status_group_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(status_group_label)
        
        self._system_status_widget = QTreeWidget()
        self._system_status_widget.setHeaderLabels(["Component", "Status"])
        self._system_status_widget.setMinimumHeight(200)
        layout.addWidget(self._system_status_widget)
        
        # Add metrics widget
        metrics_label = QLabel("System Metrics")
        metrics_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(metrics_label)
        
        self._metrics_widget = QWidget()
        metrics_layout = QFormLayout(self._metrics_widget)
        
        # Add CPU, memory, and disk metrics
        self._cpu_label = QLabel("N/A")
        self._memory_label = QLabel("N/A")
        self._disk_label = QLabel("N/A")
        
        self._cpu_progress = QProgressBar()
        self._cpu_progress.setRange(0, 100)
        self._cpu_progress.setValue(0)
        
        self._memory_progress = QProgressBar()
        self._memory_progress.setRange(0, 100)
        self._memory_progress.setValue(0)
        
        self._disk_progress = QProgressBar()
        self._disk_progress.setRange(0, 100)
        self._disk_progress.setValue(0)
        
        cpu_widget = QWidget()
        cpu_layout = QHBoxLayout(cpu_widget)
        cpu_layout.setContentsMargins(0, 0, 0, 0)
        cpu_layout.addWidget(self._cpu_progress)
        cpu_layout.addWidget(self._cpu_label)
        
        memory_widget = QWidget()
        memory_layout = QHBoxLayout(memory_widget)
        memory_layout.setContentsMargins(0, 0, 0, 0)
        memory_layout.addWidget(self._memory_progress)
        memory_layout.addWidget(self._memory_label)
        
        disk_widget = QWidget()
        disk_layout = QHBoxLayout(disk_widget)
        disk_layout.setContentsMargins(0, 0, 0, 0)
        disk_layout.addWidget(self._disk_progress)
        disk_layout.addWidget(self._disk_label)
        
        metrics_layout.addRow("CPU Usage:", cpu_widget)
        metrics_layout.addRow("Memory Usage:", memory_widget)
        metrics_layout.addRow("Disk Usage:", disk_widget)
        
        layout.addWidget(self._metrics_widget)
        
        # Add stretch to push everything up
        layout.addStretch()
        
        # Add the dashboard tab
        self._central_tabs.addTab(dashboard_widget, "Dashboard")
    
    def _create_plugins_tab(self) -> None:
        """Create the plugins tab."""
        plugins_widget = QWidget()
        layout = QVBoxLayout(plugins_widget)
        
        # Add title
        title_label = QLabel("Plugins")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title_label)
        
        # Add controls
        controls_layout = QHBoxLayout()
        
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_plugins)
        controls_layout.addWidget(refresh_button)
        
        load_button = QPushButton("Load Selected")
        load_button.clicked.connect(self._load_selected_plugin)
        controls_layout.addWidget(load_button)
        
        unload_button = QPushButton("Unload Selected")
        unload_button.clicked.connect(self._unload_selected_plugin)
        controls_layout.addWidget(unload_button)
        
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Add plugins tree widget
        self._plugin_tree = QTreeWidget()
        self._plugin_tree.setHeaderLabels(["Name", "Version", "State", "Description"])
        self._plugin_tree.setColumnWidth(0, 150)
        self._plugin_tree.setColumnWidth(1, 100)
        self._plugin_tree.setColumnWidth(2, 100)
        layout.addWidget(self._plugin_tree)
        
        # Add the plugins tab
        self._central_tabs.addTab(plugins_widget, "Plugins")
    
    def _create_logs_tab(self) -> None:
        """Create the logs tab."""
        logs_widget = QWidget()
        layout = QVBoxLayout(logs_widget)
        
        # Add title
        title_label = QLabel("Logs")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title_label)
        
        # Add log viewer
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setLineWrapMode(QTextEdit.NoWrap)
        self._log_text.setFont(QFont("Courier New", 9))
        layout.addWidget(self._log_text)
        
        # Add controls
        controls_layout = QHBoxLayout()
        
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_logs)
        controls_layout.addWidget(clear_button)
        
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Add the logs tab
        self._central_tabs.addTab(logs_widget, "Logs")
    
    def _subscribe_to_events(self) -> None:
        """Subscribe to events from the event bus."""
        if not self._event_bus:
            return
        
        # Subscribe to log events
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="log",
                callback=self._on_log_event,
                subscriber_id="ui_log_subscriber",
            )
        )
        
        # Subscribe to plugin events
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="plugin/loaded",
                callback=self._on_plugin_event,
                subscriber_id="ui_plugin_subscriber",
            )
        )
        
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="plugin/unloaded",
                callback=self._on_plugin_event,
                subscriber_id="ui_plugin_subscriber",
            )
        )
        
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="plugin/error",
                callback=self._on_plugin_event,
                subscriber_id="ui_plugin_subscriber",
            )
        )
        
        # Subscribe to monitoring events
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="monitoring/metrics",
                callback=self._on_metrics_event,
                subscriber_id="ui_monitoring_subscriber",
            )
        )
        
        self._event_subscriptions.append(
            self._event_bus.subscribe(
                event_type="monitoring/alert",
                callback=self._on_alert_event,
                subscriber_id="ui_alert_subscriber",
            )
        )
    
    @Slot(str, object)
    def _handle_update_signal(self, signal_type: str, data: Any) -> None:
        """Handle signals for updating the UI from non-GUI threads.
        
        Args:
            signal_type: Type of update signal.
            data: Data associated with the signal.
        """
        if signal_type == "log":
            self._update_logs(data)
        elif signal_type == "plugin":
            self._refresh_plugins()
        elif signal_type == "metrics":
            self._update_metrics(data)
        elif signal_type == "alert":
            self._show_alert(data)
    
    def _update_status(self) -> None:
        """Update the system status display."""
        if not self._app_core:
            return
        
        # Get system status
        status = self._app_core.status()
        
        # Update status tree
        if self._system_status_widget:
            self._system_status_widget.clear()
            
            # Add app core status
            app_item = QTreeWidgetItem(["Application Core", "Active" if status["initialized"] else "Inactive"])
            app_item.setIcon(1, self._get_status_icon(status["initialized"]))
            self._system_status_widget.addTopLevelItem(app_item)
            
            # Add managers status
            if "managers" in status:
                for manager_name, manager_status in status["managers"].items():
                    manager_item = QTreeWidgetItem([
                        manager_name, 
                        "Healthy" if manager_status.get("healthy", False) else "Unhealthy"
                    ])
                    manager_item.setIcon(1, self._get_status_icon(manager_status.get("healthy", False)))
                    app_item.addChild(manager_item)
                    
                    # Add manager details
                    for key, value in manager_status.items():
                        if key not in ("name", "initialized", "healthy"):
                            if isinstance(value, dict):
                                # Add sub-details
                                sub_item = QTreeWidgetItem([key, ""])
                                manager_item.addChild(sub_item)
                                
                                for sub_key, sub_value in value.items():
                                    sub_item.addChild(QTreeWidgetItem([sub_key, str(sub_value)]))
                            else:
                                # Add detail directly
                                manager_item.addChild(QTreeWidgetItem([key, str(value)]))
            
            # Expand top-level items
            app_item.setExpanded(True)
            self._system_status_widget.resizeColumnToContents(0)
        
        # Update metrics
        self._refresh_metrics()
    
    def _refresh_metrics(self) -> None:
        """Refresh system metrics display."""
        if self._monitoring_manager:
            try:
                # Get metrics from monitoring manager
                diagnostics = self._monitoring_manager.generate_diagnostic_report()
                
                if "system" in diagnostics:
                    # Update CPU usage
                    cpu_percent = diagnostics["system"]["cpu"]["percent"]
                    self._cpu_label.setText(f"{cpu_percent:.1f}%")
                    self._cpu_progress.setValue(int(cpu_percent))
                    self._set_progress_color(self._cpu_progress, cpu_percent)
                    
                    # Update memory usage
                    memory_percent = diagnostics["system"]["memory"]["percent"]
                    self._memory_label.setText(f"{memory_percent:.1f}%")
                    self._memory_progress.setValue(int(memory_percent))
                    self._set_progress_color(self._memory_progress, memory_percent)
                    
                    # Update disk usage
                    disk_percent = diagnostics["system"]["disk"]["percent"]
                    self._disk_label.setText(f"{disk_percent:.1f}%")
                    self._disk_progress.setValue(int(disk_percent))
                    self._set_progress_color(self._disk_progress, disk_percent)
            
            except Exception as e:
                self._logger.error(f"Error refreshing metrics: {str(e)}")
    
    def _refresh_plugins(self) -> None:
        """Refresh the plugins display."""
        if not self._plugin_manager or not self._plugin_tree:
            return
        
        try:
            # Clear the tree
            self._plugin_tree.clear()
            
            # Get all plugins
            plugins = self._plugin_manager.get_all_plugins()
            
            # Add plugins to the tree
            for plugin in plugins:
                item = QTreeWidgetItem([
                    plugin["name"],
                    plugin["version"],
                    plugin["state"],
                    plugin["description"],
                ])
                
                # Set icon based on state
                state = plugin["state"]
                if state == "active":
                    item.setIcon(2, self._get_status_icon(True))
                elif state == "loaded":
                    item.setIcon(2, self._get_status_icon(True))
                elif state == "failed":
                    item.setIcon(2, self._get_status_icon(False))
                else:
                    item.setIcon(2, self._get_status_icon(None))
                
                self._plugin_tree.addTopLevelItem(item)
            
            # Resize columns
            for i in range(4):
                self._plugin_tree.resizeColumnToContents(i)
        
        except Exception as e:
            self._logger.error(f"Error refreshing plugins: {str(e)}")
    
    def _load_selected_plugin(self) -> None:
        """Load the selected plugin."""
        if not self._plugin_manager or not self._plugin_tree:
            return
        
        # Get selected item
        selected_items = self._plugin_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a plugin to load.")
            return
        
        # Get plugin name from selected item
        plugin_name = selected_items[0].text(0)
        
        try:
            # Load the plugin
            success = self._plugin_manager.load_plugin(plugin_name)
            
            if success:
                QMessageBox.information(
                    self, "Plugin Loaded", f"Plugin '{plugin_name}' loaded successfully."
                )
                self._refresh_plugins()
            else:
                QMessageBox.warning(
                    self, "Load Failed", f"Failed to load plugin '{plugin_name}'."
                )
        
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error loading plugin '{plugin_name}': {str(e)}"
            )
    
    def _unload_selected_plugin(self) -> None:
        """Unload the selected plugin."""
        if not self._plugin_manager or not self._plugin_tree:
            return
        
        # Get selected item
        selected_items = self._plugin_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a plugin to unload.")
            return
        
        # Get plugin name from selected item
        plugin_name = selected_items[0].text(0)
        
        try:
            # Unload the plugin
            success = self._plugin_manager.unload_plugin(plugin_name)
            
            if success:
                QMessageBox.information(
                    self, "Plugin Unloaded", f"Plugin '{plugin_name}' unloaded successfully."
                )
                self._refresh_plugins()
            else:
                QMessageBox.warning(
                    self, "Unload Failed", f"Failed to unload plugin '{plugin_name}'."
                )
        
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error unloading plugin '{plugin_name}': {str(e)}"
            )
    
    def _reload_plugins(self) -> None:
        """Reload all plugins."""
        if not self._plugin_manager:
            return
        
        try:
            # Get all active plugins
            plugins = self._plugin_manager.get_all_plugins()
            active_plugins = [p["name"] for p in plugins if p["state"] == "active"]
            
            # Unload and then load each active plugin
            for plugin_name in active_plugins:
                try:
                    self._plugin_manager.unload_plugin(plugin_name)
                    self._plugin_manager.load_plugin(plugin_name)
                except Exception as e:
                    self._logger.error(f"Error reloading plugin '{plugin_name}': {str(e)}")
            
            # Refresh the display
            self._refresh_plugins()
            
            QMessageBox.information(
                self, "Plugins Reloaded", f"Reloaded {len(active_plugins)} active plugins."
            )
        
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error reloading plugins: {str(e)}"
            )
    
    def _update_logs(self, log_entry: str) -> None:
        """Update the log display with a new log entry.
        
        Args:
            log_entry: The log entry to add.
        """
        if self._log_text:
            # Add the log entry to the text edit
            self._log_text.append(log_entry)
            
            # Scroll to the bottom
            scrollbar = self._log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def _clear_logs(self) -> None:
        """Clear the log display."""
        if self._log_text:
            self._log_text.clear()
    
    def _update_metrics(self, metrics_data: Dict[str, Any]) -> None:
        """Update metrics display with new data.
        
        Args:
            metrics_data: Metrics data.
        """
        # Update CPU, memory, and disk metrics
        if "cpu_percent" in metrics_data:
            cpu_percent = metrics_data["cpu_percent"]
            self._cpu_label.setText(f"{cpu_percent:.1f}%")
            self._cpu_progress.setValue(int(cpu_percent))
            self._set_progress_color(self._cpu_progress, cpu_percent)
        
        if "memory_percent" in metrics_data:
            memory_percent = metrics_data["memory_percent"]
            self._memory_label.setText(f"{memory_percent:.1f}%")
            self._memory_progress.setValue(int(memory_percent))
            self._set_progress_color(self._memory_progress, memory_percent)
        
        if "disk_percent" in metrics_data:
            disk_percent = metrics_data["disk_percent"]
            self._disk_label.setText(f"{disk_percent:.1f}%")
            self._disk_progress.setValue(int(disk_percent))
            self._set_progress_color(self._disk_progress, disk_percent)
    
    def _show_alert(self, alert_data: Dict[str, Any]) -> None:
        """Show an alert dialog for a monitoring alert.
        
        Args:
            alert_data: Alert data.
        """
        level = alert_data.get("level", "info")
        message = alert_data.get("message", "No message")
        
        # Show different icon based on alert level
        if level == "critical":
            QMessageBox.critical(self, "Critical Alert", message)
        elif level == "error":
            QMessageBox.critical(self, "Error Alert", message)
        elif level == "warning":
            QMessageBox.warning(self, "Warning Alert", message)
        else:
            QMessageBox.information(self, "Information Alert", message)
    
    def _on_log_event(self, event: Any) -> None:
        """Handle log events.
        
        Args:
            event: The log event.
        """
        # Format the log message
        payload = event.payload
        if isinstance(payload, dict):
            log_entry = f"{payload.get('timestamp', '')} [{payload.get('level', 'INFO')}] {payload.get('message', '')}"
        else:
            log_entry = str(payload)
        
        # Update the UI via signal
        self.update_signal.emit("log", log_entry)
    
    def _on_plugin_event(self, event: Any) -> None:
        """Handle plugin events.
        
        Args:
            event: The plugin event.
        """
        # Update the plugins display
        self.update_signal.emit("plugin", None)
    
    def _on_metrics_event(self, event: Any) -> None:
        """Handle metrics events.
        
        Args:
            event: The metrics event.
        """
        # Update metrics display
        self.update_signal.emit("metrics", event.payload)
    
    def _on_alert_event(self, event: Any) -> None:
        """Handle alert events.
        
        Args:
            event: The alert event.
        """
        # Show alert dialog
        self.update_signal.emit("alert", event.payload)
    
    def _show_about_dialog(self) -> None:
        """Show the about dialog."""
        version = self._app_core.status().get("version", "0.1.0")
        
        QMessageBox.about(
            self,
            "About Nexus Core",
            f"<h1>Nexus Core</h1>"
            f"<p>Version: {version}</p>"
            f"<p>A modular, extensible platform for the automotive aftermarket industry.</p>"
            f"<p>Copyright &copy; 2025</p>"
        )
    
    def _get_status_icon(self, status: Optional[bool]) -> QIcon:
        """Get a status icon based on a boolean status.
        
        Args:
            status: The status (True for good, False for bad, None for unknown).
            
        Returns:
            QIcon: The status icon.
        """
        # In a real implementation, we would use actual icons
        # For now, we'll just use colored squares
        if status is True:
            return QIcon()  # Green icon
        elif status is False:
            return QIcon()  # Red icon
        else:
            return QIcon()  # Gray icon
    
    def _set_progress_color(self, progress_bar: QProgressBar, value: float) -> None:
        """Set the color of a progress bar based on the value.
        
        Args:
            progress_bar: The progress bar to set the color for.
            value: The value to determine the color.
        """
        if value < 60:
            # Green
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")
        elif value < 80:
            # Yellow
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #FFC107; }")
        else:
            # Red
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #F44336; }")
    
    def closeEvent(self, event: Any) -> None:
        """Handle the window close event.
        
        Args:
            event: The close event.
        """
        # Unsubscribe from events
        if self._event_bus:
            for subscription_id in self._event_subscriptions:
                self._event_bus.unsubscribe(subscription_id)
        
        # Stop the update timer
        self._update_timer.stop()
        
        # Shut down the application core
        if self._app_core:
            self._app_core.shutdown()
        
        # Accept the close event
        event.accept()


def start_ui(app_core: Any, debug: bool = False) -> None:
    """Start the user interface.
    
    Args:
        app_core: The Application Core instance.
        debug: Whether to enable debug mode.
    """
    # Create Qt application
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Create main window
    main_window = NexusMainWindow(app_core)
    main_window.show()
    
    # Start the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    # For testing the UI in isolation
    class MockAppCore:
        def __init__(self):
            self._managers = {}
        
        def get_manager(self, name):
            return self._managers.get(name)
        
        def status(self):
            return {
                "name": "Application Core",
                "initialized": True,
                "healthy": True,
                "version": "0.1.0",
                "managers": {},
            }
        
        def shutdown(self):
            print("MockAppCore.shutdown() called")
    
    start_ui(MockAppCore(), True)
