from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from .base import Provider
from .cloud import CloudProvider
from .config import ModelSettings
from .errors import ProviderError
from .mock import MockProvider


def create_provider(settings: ModelSettings | None = None) -> Provider:
    try:
        settings = settings if settings is not None else ModelSettings()
    except (ValidationError, SettingsError):
        raise ProviderError("PROVIDER_CONFIG_ERROR") from None
    if settings.model_provider == "mock":
        return MockProvider(max_output_tokens=settings.model_max_output_tokens)
    return CloudProvider(settings)
