#!/usr/bin/env python
"""Setup script for Nexus Core."""

import os
import re
from setuptools import setup, find_packages

# Read the version from the __init__.py file
with open(os.path.join("nexus_core", "__init__.py"), encoding="utf-8") as f:
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M)
    if version_match:
        version = version_match.group(1)
    else:
        raise RuntimeError("Unable to find version string.")

# Read the long description from the README.md file
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

# Define dependencies
install_requires = [
    "pydantic>=2.4.2,<3.0.0",
    "pyside6>=6.5.3,<7.0.0",
    "sqlalchemy[asyncio]>=2.0.0,<3.0.0",
    "asyncpg>=0.28.0,<0.29.0",
    "fastapi>=0.103.1,<0.104.0",
    "uvicorn>=0.23.2,<0.24.0",
    "pika>=1.3.2,<1.4.0",
    "python-json-logger>=2.0.7,<2.1.0",
    "psutil>=5.9.5,<6.0.0",
    "prometheus-client>=0.17.1,<0.18.0",
    "pyjwt>=2.8.0,<2.9.0",
    "passlib[bcrypt]>=1.7.4,<1.8.0",
    "python-multipart>=0.0.6,<0.1.0",
    "tenacity>=8.2.3,<8.3.0",
    "structlog>=23.1.0,<24.0.0",
    "trio>=0.22.2,<0.23.0",
    "typing-extensions>=4.8.0,<4.9.0",
    "httpx>=0.24.1,<0.25.0",
    "pyyaml>=6.0.0,<6.1.0",
]

# Optional dependencies
extras_require = {
    "aws": ["boto3>=1.28.50,<1.29.0"],
    "azure": ["azure-storage-blob>=12.18.3,<12.19.0"],
    "gcp": ["google-cloud-storage>=2.11.0,<2.12.0"],
    "dev": [
        "black>=23.9.1,<23.10.0",
        "ruff>=0.0.289,<0.1.0",
        "isort>=5.12.0,<5.13.0",
        "mypy>=1.5.1,<1.6.0",
        "pytest>=7.4.2,<7.5.0",
        "pytest-asyncio>=0.21.1,<0.22.0",
        "pytest-cov>=4.1.0,<4.2.0",
        "pytest-mock>=3.11.1,<3.12.0",
        "hypothesis>=6.87.0,<6.88.0",
        "line-profiler>=4.1.1,<4.2.0",
    ],
    "types": [
        "types-python-dateutil>=2.8.19.14,<2.9.0",
        "types-pytz>=2023.3.1.1,<2024.0.0",
        "types-pyyaml>=6.0.12.12,<6.1.0",
        "types-requests>=2.31.0.2,<2.32.0",
    ],
}

# All extras combined
extras_require["all"] = (
    extras_require["aws"]
    + extras_require["azure"]
    + extras_require["gcp"]
    + extras_require["dev"]
    + extras_require["types"]
)

setup(
    name="nexus-core",
    version=version,
    description="Modular Platform for Automotive Aftermarket Industry",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/nexus-core",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "nexus-core=nexus_core.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
)
