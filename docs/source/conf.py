"""Sphinx configuration for Nexus Core documentation."""

import os
import sys
import datetime

# Add the project root directory to the path
sys.path.insert(0, os.path.abspath('../..'))

# Project information
project = 'Nexus Core'
copyright = f'{datetime.datetime.now().year}, Your Name'
author = 'Your Name'

# Import the project version
from nexus_core.__version__ import __version__
version = __version__
release = __version__

# Extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx_rtd_theme',
    'myst_parser',
]

# Templates
templates_path = ['_templates']
exclude_patterns = []

# HTML output
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_rtype = True