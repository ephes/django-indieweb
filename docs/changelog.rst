.. :changelog:

Changelog
=========

0.4.3 (2025-07-11)
------------------
* Fixed ``webmention_count`` template tag to always return integers for consistent template comparisons
* Previously returned string when used directly but integer when used with ``as`` variable assignment

0.4.2 (2025-07-11)
------------------
* *Version skipped*

0.4.1 (2025-07-11)
------------------
* *Version skipped*

0.4.0 (2025-07-11)
------------------
* **MAJOR**: Added complete Webmention support (W3C Recommendation compliance)
* Added Webmention model for storing incoming and outgoing webmentions
* Added WebmentionEndpoint view for receiving webmentions
* Added WebmentionProcessor for validating and parsing webmentions with microformats2
* Added WebmentionSender for discovering endpoints and sending webmentions
* Added pluggable interfaces for URL resolution, spam checking, and comment integration
* Added Django template tags for displaying webmentions (``webmentions_for``, ``webmention_count``, ``webmention_endpoint_link``)
* Added management command ``send_webmentions`` for sending webmentions from the command line
* Added comprehensive test suite for Webmention functionality (35 new tests)
* Added detailed Webmention documentation with integration examples
* Added CSS styling and templates for different webmention types (likes, reposts, replies, mentions)
* Added Django signals for webmention processing (``webmention_received``)
* Replaced requests library with httpx for better async support and HTTP/2 features
* Updated dependencies to use httpx instead of requests

0.3.5 (2025-06-29)
------------------
* Fixed Authorization header handling to check for HTTP_AUTHORIZATION (Django's standard header format)
* Maintained backward compatibility with test client Authorization format
* Added tests to verify both Authorization header formats work correctly

0.3.4 (2025-06-29)
------------------
* Fixed Token model unique constraint that prevented multiple clients from obtaining tokens for the same user
* Removed incorrect unique=True from Token.me field (kept unique_together constraint)

0.3.3 (2025-06-29)
------------------
* Fixed micropub authorization to accept "create" scope (standard Micropub) in addition to legacy "post" scope
* Added debug logging for token authentication failures

0.3.2 (2025-06-29)
------------------
* Fixed KeyError in TokenView when 'me' parameter is missing - the token endpoint now correctly handles optional parameters according to IndieAuth spec
* Improved token endpoint error responses to use proper IndieAuth error codes (invalid_request, invalid_grant)
* Added redirect_uri verification for enhanced security
* Implemented one-time use of authorization codes to prevent replay attacks
* Added proper content-type headers to token endpoint responses

0.3.1 (2025-06-28)
------------------
* Added merge migration to resolve parallel migration branches

0.3.0 (2025-06-28)
------------------
* **MAJOR**: Implemented fully functional Micropub endpoint with content creation
* Added pluggable content handler system for Micropub integration
* Added ``MicropubContentHandler`` abstract base class for custom implementations
* Added ``InMemoryMicropubHandler`` for testing and development
* Added support for both form-encoded and JSON Micropub requests
* Implemented Micropub query endpoints (``?q=config``, ``?q=syndicate-to``)
* Added comprehensive test suite for Micropub functionality (19 new tests)
* Added detailed Micropub documentation with integration examples
* Added example content handlers demonstrating various integration patterns
* Updated type hints to use modern Python syntax (``list``, ``dict`` instead of ``List``, ``Dict``)
* **BREAKING**: Removed old Micropub property methods that were implementation details
* Added comprehensive documentation for IndieAuth implementation including consent screen
* Added test suite for IndieAuth consent screen functionality (14 new tests)
* Fixed MyPy type errors in AuthView for better type safety
* Updated development guidelines with "Definition of Done" criteria

0.2.0 (2025-06-16)
------------------
* Fixed Read the Docs build by adding missing dependencies to docs/requirements.txt
* Added coverage configuration to exclude migrations from coverage reports
* Cleaned up duplicate documentation files (removed outdated .txt versions)
* Added type annotations to models.py and views.py
* Added mypy configuration with django-stubs for static type checking
* Added documentation for running mypy in development.rst
* Added comprehensive API reference documentation with examples
* Added usage tutorial with client-side implementation examples
* Added configuration guide documenting all settings and options
* Added concepts documentation explaining IndieWeb protocols with Mermaid diagrams
* Updated CONTRIBUTING.rst to reflect current development workflow (uv, ruff, pytest)
* Added warnings about Micropub endpoint stub implementation
* Converted all tests from unittest to pytest style
* Added __str__ method to Token model
* Added docstrings to all model and view classes
* **BREAKING**: Removed unnecessary dependencies:
  - Replaced django-model-utils TimeStampedModel with explicit timestamp fields
  - Replaced django-braces AccessMixin with direct login redirect
  - Removed setuptools (not needed at runtime with modern packaging)
  - Replaced pytz with Python's built-in datetime.timezone.utc
* Package now only depends on Django itself

0.1.0 (2025-06-13)
------------------
* Migrated from flit to uv build backend
* Moved package from top-level to src layout
* Replaced black, isort, and flake8 with ruff
* Added Python 3.13 support
* Dropped Python 3.9 support (minimum is now 3.10)
* Updated pre-commit hooks
* Consolidated dev dependencies into single group
* Added comprehensive documentation with Sphinx and Furo theme
* Updated documentation structure for Read the Docs
* Fixed Django settings configuration for tests

0.0.8 (unreleased)
------------------
* Development version (not released)

0.0.7 (2023-01-07)
------------------
* Added migration for auto field
* Updated pre-commit hooks

0.0.6 (2022-11-05)
------------------
* Use flit and pyproject.toml instead of setup.py
* Support recent Django versions
* Even better package infrastructure

0.0.5 (2019-05-19)
------------------
* Auth endpoint works with https://pin13.net/login/ \o/
* Use black for code formatting
* Better package infrastructure
* Require python >= 3.6

0.0.4 (2016-06-14)
------------------
* exempt csrf checking

0.0.3 (2016-06-13)
------------------
* added migrations

0.0.2 (2016-05-15)
------------------
* Auth and Token endpoints with some tests.

0.0.1 (2016-05-14)
------------------
* First release on PyPI.
