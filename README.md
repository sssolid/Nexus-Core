# Nexus Core

A modular, extensible platform for the automotive aftermarket industry built with Python 3.11+ and PySide6.

## Overview

Nexus Core is a microkernel-based platform that provides a robust foundation for building applications in the automotive aftermarket domain. It follows a plugin architecture that allows extending functionality without modifying the core system.

### Key Features

- **Modular Architecture**: Core functionality is divided into managers that handle specific aspects of the system.
- **Plugin System**: Extend functionality by adding plugins without modifying core code.
- **Event-Driven Communication**: Components communicate through a central event bus.
- **Modern UI**: Built with PySide6 (Qt 6) for a responsive and modern user interface.
- **API-First**: All functionality is accessible through a REST API.
- **Cloud-Agnostic**: Runs on any cloud platform or on-premise.
- **Comprehensive Monitoring**: Built-in monitoring with Prometheus integration.
- **Secure by Default**: Includes authentication, authorization, and encryption.

## Installation

### Prerequisites

- Python 3.11 or higher
- [Poetry](https://python-poetry.org/) for dependency management
- PostgreSQL (optional, for database storage)

### Local Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/nexus-core.git
   cd nexus-core
   ```

2. Install dependencies with Poetry:
   ```bash
   poetry install
   ```

3. Create a configuration file:
   ```bash
   cp config.yaml.example config.yaml
   # Edit config.yaml with your preferred settings
   ```

4. Run the application:
   ```bash
   poetry run python -m nexus_core
   ```

### Docker Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/nexus-core.git
   cd nexus-core
   ```

2. Build and run with Docker Compose:
   ```bash
   docker-compose up -d
   ```

3. Access the API at http://localhost:8000/api and the UI at http://localhost:8000/ (if enabled).

## Usage

### Command Line Arguments

- `--config`: Path to the configuration file (default: config.yaml in the current directory)
- `--headless`: Run in headless mode without the UI
- `--debug`: Enable debug mode for additional logging

### Using the UI

The UI provides an intuitive way to manage the Nexus Core system:

- **Dashboard**: View system status and metrics
- **Plugins**: Manage and configure plugins
- **Logs**: View system logs

### Using the API

The REST API is available at http://localhost:8000/api by default. API documentation is available at http://localhost:8000/api/docs.

Authentication is required for most endpoints:

```bash
# Get an authentication token
curl -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=admin" \
  -H "Content-Type: application/x-www-form-urlencoded"

# Use the token for authenticated requests
curl http://localhost:8000/api/v1/system/status \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

## Configuration

Nexus Core can be configured through a YAML configuration file. The configuration includes:

- Database connection settings
- Logging configuration
- API settings
- Security settings
- Plugin configuration
- Monitoring settings
- And more

See `config.yaml.example` for a complete example.

## Extending with Plugins

Nexus Core can be extended with plugins. Plugins can add new functionality, integrate with external systems, or modify existing behavior.

### Creating a Plugin

1. Create a new directory in the `plugins` directory with your plugin name.
2. Create a Python module with a class that implements the plugin interface.
3. Add any required dependencies to your plugin's `requirements.txt` file.

See the example plugin in `plugins/example_plugin` for a reference implementation.

## Development

### Project Structure

```
nexus_core/
├── core/               # Core managers and components
├── plugins/            # Plugin system
├── ui/                 # User interface
├── utils/              # Utility functions
├── tests/              # Tests
└── __main__.py         # Entry point
```

### Adding a New Manager

To add a new manager:

1. Create a new file in the `core` directory.
2. Implement a class that inherits from `NexusManager`.
3. Implement the required methods: `initialize()`, `shutdown()`, and `status()`.
4. Add the manager to the initialization sequence in `ApplicationCore`.

### Running Tests

```bash
poetry run pytest
```

### Building Documentation

```bash
poetry run sphinx-build -b html docs/source docs/build
```

## Monitoring

Nexus Core includes built-in monitoring via Prometheus. Metrics are exposed at http://localhost:9090/metrics by default.

A Grafana dashboard is available at http://localhost:3000 when using Docker Compose.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
