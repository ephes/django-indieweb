# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os  # noqa
import sys  # noqa
import django  # noqa

sys.path.insert(0, os.path.abspath("../src"))
sys.path.insert(0, os.path.abspath(".."))

# Configure Django settings
os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
django.setup()

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "django-indieweb"
copyright = "2025, Jochen Wersdörfer"
author = "Jochen Wersdörfer"
release = "0.0.8"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]

# -- Extension configuration -------------------------------------------------

# Autodoc settings
autodoc_mock_imports = []
