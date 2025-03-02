# Use Python 3.11 slim as the base image
FROM python:3.11-slim

# Set up environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LANG=C.UTF-8 \
    TZ=UTC \
    APP_HOME=/app \
    PATH="/app/.local/bin:${PATH}"

# Set the working directory
WORKDIR $APP_HOME

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libpq-dev \
        libssl-dev \
        # QT dependencies for PySide6 (when running with UI)
        libgl1-mesa-glx \
        libx11-xcb1 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python - \
    && poetry config virtualenvs.create false

# Copy pyproject.toml and poetry.lock files
COPY pyproject.toml poetry.lock* ./

# Install Python dependencies
RUN poetry install --only main --no-interaction --no-ansi \
    && rm -rf ~/.cache/pypoetry

# Create necessary directories
RUN mkdir -p \
    $APP_HOME/data \
    $APP_HOME/data/temp \
    $APP_HOME/data/plugins \
    $APP_HOME/data/backups \
    $APP_HOME/logs

# Create a non-root user to run the application
RUN groupadd -r nexus && useradd -r -g nexus nexus \
    && chown -R nexus:nexus $APP_HOME

# Copy the application code
COPY nexus_core $APP_HOME/nexus_core

# Ownership and permissions
RUN chown -R nexus:nexus $APP_HOME

# Switch to the non-root user
USER nexus

# Set up healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose the API port
EXPOSE 8000

# Expose Prometheus metrics port
EXPOSE 9090

# Set the entrypoint
ENTRYPOINT ["python", "-m", "nexus_core"]

# By default, run in headless mode (no UI)
CMD ["--headless"]
