from pathlib import Path

import pytest
from pydantic import SecretStr

from infoscope.config import Settings
from infoscope.integrations.telegram.config import (
    TelegramConfigurationError,
    load_telegram_config,
)


def test_telegram_config_requires_credentials() -> None:
    with pytest.raises(TelegramConfigurationError, match="TELEGRAM_API_ID"):
        load_telegram_config(Settings(_env_file=None))


def test_telegram_secret_is_not_exposed_by_repr() -> None:
    config = load_telegram_config(
        Settings(
            _env_file=None,
            telegram_api_id=12345,
            telegram_api_hash=SecretStr("secret-value"),
            telegram_session_path=Path(".state/test-session"),
        )
    )

    assert "secret-value" not in repr(config)
    assert config.folder_title == "News"
