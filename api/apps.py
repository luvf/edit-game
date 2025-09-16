"""apps for api."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """Config for api app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
