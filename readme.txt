# Nexus Core

A modular, extensible platform for the automotive aftermarket industry built with Python 3.11+ and PySide6.

## Architecture Overview

Nexus Core follows a microkernel (plugin) architecture, dividing the system into a minimal core and multiple pluggable managers. The core handles common services (event bus, threading, config, etc.), while each feature area is implemented as a manager module.

Components communicate via a central event bus using a publish-subscribe pattern, enabling loosely coupled, extensible design.

## Key Features

- **Modular Core Design**: Core managers for configuration, logging, event handling, etc.
- **Plugin Architecture**: Hot-loading, modular installation, and versioning of extensions
- **Event-Driven Communication**: Central event bus for decoupled communication
- **Comprehensive Monitoring**: Prometheus/Grafana integration for metrics and alerts
- **Secure by Design**: JWT-based authentication, RBAC authorization, secure defaults
- **Cloud-Agnostic**: Run on AWS, Azure, GCP, or on-premise with minimal adjustments
- **Modern UI**: PySide6 (Qt 6) for the desktop interface

## Core Managers

- **Configuration Manager**: Centralized config loading and access
- **Logging Manager**: Unified logging service with multiple outputs
- **Event Bus Manager**: Coordinates publish/subscribe system for decoupled communication
- **Thread Manager**: Handles application threading and concurrency
- **File Manager**: Manages file system interactions
- **Resource Manager**: Manages system resources
- **Database Manager**: Handles database interactions with SQLAlchemy
- **Plugin Manager**: Enables hot-loading and management of extensions
- **Remote Services Manager**: Handles integration with external services
- **Resource Monitoring Manager**: Monitors system performance and health
- **Security Manager**: Manages authentication, authorization, and encryption
- **REST API Manager**: Exposes functionality over HTTP RESTful APIs
- **Cloud Manager**: Ensures cloud-agnostic operation

## Technology Stack

- **Python 3.11+** with comprehensive type hints
- **PySide6 (Qt 6)** for desktop UI
- **SQLAlchemy** for database access
- **FastAPI** for the REST API layer
- **Prometheus** for monitoring
- **JWT/OAuth2** for security

## Installation

### Prerequisites

- Python 3.11 or higher
- [Poetry](https://python-poetry.org/) for dependency management

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/nexus-core.git
   cd nexus-core
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Configure the application:
   ```bash
   cp config.yaml.example config.yaml
   # Edit config.yaml with your settings
   ```

4. Run the application:
   ```bash
   poetry run python -m nexus_core
   ```

## Development

### Development Environment Setup

1. Install development dependencies:
   ```bash
   poetry install --with dev
   ```

2. Configure pre-commit hooks:
   ```bash
   poetry run pre-commit install
   ```

### Code Style

This project uses:
- Black for code formatting
- Ruff for linting
- MyPy for static type checking
- isort for import sorting

### Testing

Run tests with pytest:
```bash
poetry run pytest
```

## Docker Deployment

Build and run the Docker image:

```bash
docker build -t nexus-core .
docker run -p 8000:8000 nexus-core
```

## Contributing

Contributions are welcome! Please read the [CONTRIBUTING.md](CONTRIBUTING.md) file for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
