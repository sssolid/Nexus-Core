Installation
============

This guide will help you install and set up Nexus Core on your system.

Prerequisites
------------

Before installing Nexus Core, you'll need:

* Python 3.11 or higher
* pip or Poetry (recommended) for dependency management
* PostgreSQL (optional, for database storage)

Installing with Poetry (Recommended)
-----------------------------------

Poetry is a dependency management and packaging tool for Python. It's the recommended method for installing Nexus Core.

1. Install Poetry:

   .. code-block:: bash

       curl -sSL https://install.python-poetry.org | python -

2. Clone the repository:

   .. code-block:: bash

       git clone https://github.com/yourusername/nexus-core.git
       cd nexus-core

3. Install dependencies:

   .. code-block:: bash

       poetry install

4. Create a configuration file:

   .. code-block:: bash

       cp config-example.yaml config.yaml
       # Edit config.yaml with your preferred settings

5. Run the application:

   .. code-block:: bash

       poetry run python -m nexus_core

Installing with pip
------------------

If you prefer using pip instead of Poetry:

1. Clone the repository:

   .. code-block:: bash

       git clone https://github.com/yourusername/nexus-core.git
       cd nexus-core

2. Create and activate a virtual environment:

   .. code-block:: bash

       python -m venv venv
       source venv/bin/activate  # On Windows, use: venv\Scripts\activate

3. Install dependencies:

   .. code-block:: bash

       pip install -r requirements.txt

4. Create a configuration file:

   .. code-block:: bash

       cp config-example.yaml config.yaml
       # Edit config.yaml with your preferred settings

5. Run the application:

   .. code-block:: bash

       python -m nexus_core

Docker Installation
-----------------

Nexus Core can also be run using Docker:

1. Clone the repository:

   .. code-block:: bash

       git clone https://github.com/yourusername/nexus-core.git
       cd nexus-core

2. Build and start the Docker containers:

   .. code-block:: bash

       docker-compose up -d

3. Access the UI at http://localhost:8000/ and the API at http://localhost:8000/api

Next Steps
---------

After installation, you should:

1. Configure the application by editing the `config.yaml` file
2. Set up a proper database for production use
3. Create an admin user with a secure password
4. Install any plugins you need

See the :doc:`configuration` and :doc:`usage` guides for more details.