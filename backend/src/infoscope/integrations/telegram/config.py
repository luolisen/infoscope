from __future__ import annotations

from infoscope.config import Settings
from infoscope.integrations.telegram.models import TelegramConfig


class TelegramConfigurationError(ValueError):
    error_code = "TGNEWS_CREDENTIALS_MISSING"


def load_telegram_config(settings: Settings) -> TelegramConfig:
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise TelegramConfigurationError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for TG News"
        )
    api_hash = settings.telegram_api_hash.get_secret_value().strip()
    if not api_hash:
        raise TelegramConfigurationError("TELEGRAM_API_HASH must not be empty")
    folder_title = settings.telegram_folder_title.strip()
    if not folder_title:
        raise TelegramConfigurationError("TELEGRAM_FOLDER_TITLE must not be empty")
    return TelegramConfig(
        api_id=settings.telegram_api_id,
        api_hash=api_hash,
        phone=settings.telegram_phone,
        session_path=settings.resolved_telegram_session_path,
        folder_title=folder_title,
        initial_message_limit=settings.telegram_initial_message_limit,
    )
