"""Setup script for pip installation."""

import os

from setuptools import find_packages, setup

# Get version from __version__.py
about = {}
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "nexus_core", "__version__.py"), "r") as f:
    exec(f.read(), about)

# Get long description from README.md
with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="nexus-core",
    version=about["__version__"],
    description="A modular platform for the automotive aftermarket industry",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ryan Serra",
    author_email="ryan_serra@hotmail.com",
    url="https://github.com/sssolid/nexus-core",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "pydantic>=2.4.2",
        "pyside6>=6.5.3",
        "sqlalchemy>=2.0.0",
        "asyncpg>=0.28.0",
        "fastapi>=0.103.1",
        "uvicorn>=0.23.2",
        "pika>=1.3.2",
        "python-json-logger>=2.0.7",
        "psutil>=5.9.5",
        "prometheus-client>=0.17.1",
        "pyjwt>=2.8.0",
        "passlib>=1.7.4",
        "python-multipart>=0.0.6",
        "structlog>=23.1.0",
    ],
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
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.11",
)
