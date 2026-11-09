from django.apps import AppConfig


class IndieWebConfig(AppConfig):
    """App configuration for django-indieweb; registers the package's system checks."""

    name = "indieweb"
    verbose_name = "IndieWeb"

    def ready(self) -> None:
        from . import checks  # noqa: F401  (registers system checks)
