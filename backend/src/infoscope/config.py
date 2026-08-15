from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=REPOSITORY_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://infoscope:infoscope-local@127.0.0.1:5432/infoscope"
    )
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, gt=0)
    session_cookie_secure: bool = False
    worker_poll_seconds: float = Field(default=30.0, gt=0)
    trendradar_config_path: Path = Path("backend/config/trendradar.yaml")
    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: SecretStr | None = None
    telegram_phone: str | None = None
    telegram_session_path: Path = Path(".state/telegram/infoscope")
    telegram_folder_title: str = Field(default="News", min_length=1)
    telegram_initial_message_limit: int = Field(default=100, gt=0)
    normalization_batch_size: int = Field(default=500, gt=0, le=5000)
    deduplication_batch_size: int = Field(default=500, gt=0, le=5000)

    @property
    def resolved_trendradar_config_path(self) -> Path:
        if self.trendradar_config_path.is_absolute():
            return self.trendradar_config_path
        return REPOSITORY_ROOT / self.trendradar_config_path

    @property
    def resolved_telegram_session_path(self) -> Path:
        if self.telegram_session_path.is_absolute():
            return self.telegram_session_path
        return REPOSITORY_ROOT / self.telegram_session_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
