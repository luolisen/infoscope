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
    worker_heartbeat_seconds: float = Field(default=5.0, gt=0, le=60)
    worker_stale_after_seconds: float = Field(default=20.0, gt=0, le=300)
    maintenance_stale_after_seconds: float = Field(default=60.0, gt=10, le=3600)
    trendradar_config_path: Path = Path("backend/config/trendradar.yaml")
    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: SecretStr | None = None
    telegram_phone: str | None = None
    telegram_session_path: Path = Path(".state/telegram/infoscope")
    telegram_folder_title: str = Field(default="News", min_length=1)
    telegram_initial_message_limit: int = Field(default=100, gt=0)
    normalization_batch_size: int = Field(default=500, gt=0, le=5000)
    deduplication_batch_size: int = Field(default=500, gt=0, le=5000)
    analysis_api_base_url: str = "https://api.deepseek.com"
    analysis_model: str = "deepseek-v4-flash"
    analysis_api_keys: SecretStr | None = None
    analysis_timeout_seconds: float = Field(default=180, gt=0)
    analysis_max_retries: int = Field(default=3, ge=0, le=10)
    analysis_max_tokens: int = Field(default=16_384, gt=0, le=384000)
    user_analysis_max_tokens: int = Field(default=16_384, gt=0, le=384000)
    dragon_api_base_url: str | None = None
    dragon_api_keys: SecretStr | None = None
    dragon_model: str = "gpt-5.5"
    aiping_api_base_url: str | None = None
    aiping_api_keys_group_1: SecretStr | None = None
    aiping_api_keys_group_2: SecretStr | None = None
    window_analysis_max_windows: int = Field(default=24, gt=0, le=168)
    window_analysis_max_signals: int = Field(default=50, gt=0, le=5000)
    window_analysis_max_input_chars: int = Field(default=100_000, gt=0, le=10_000_000)
    window_analysis_max_batches: int = Field(default=64, gt=0, le=256)
    window_analysis_batch_concurrency: int = Field(default=3, gt=0, le=8)
    event_reconstruction_candidate_limit: int = Field(default=100, gt=0, le=1000)
    research_openclaw_executable: str = "openclaw"
    research_agent_reach_executable: str = "agent-reach"
    research_openclaw_config_path: Path = Path(".state/openclaw/research.json")
    research_openclaw_state_dir: Path = Path(".state/openclaw/research")
    research_openclaw_model: str = Field(default="deepseek/deepseek-chat", min_length=1)
    research_deepseek_api_key: SecretStr | None = None
    research_timeout_seconds: int = Field(default=300, gt=0, le=1800)
    research_grok_executable: str = str(Path.home() / ".grok/bin/grok")
    research_grok_model: str = "grok-4.6"
    research_grok_timeout_seconds: int = Field(default=180, gt=0, le=900)
    research_max_attempts: int = Field(default=3, gt=0, le=10)
    ask_comparison_max_attempts: int = Field(default=3, gt=0, le=10)
    ask_research_bridge_max_attempts: int = Field(default=3, gt=0, le=10)
    ask_event_reconciliation_max_attempts: int = Field(default=3, gt=0, le=10)
    ask_finalization_max_attempts: int = Field(default=3, gt=0, le=10)
    backwrite_max_attempts: int = Field(default=3, gt=0, le=10)
    personalization_max_attempts: int = Field(default=3, gt=0, le=10)
    personalization_batch_size: int = Field(default=10, gt=0, le=100)
    personalization_batch_concurrency: int = Field(default=2, gt=0, le=8)
    brief_max_attempts: int = Field(default=3, gt=0, le=10)
    event_localization_batch_size: int = Field(default=10, gt=0, le=10)
    event_localization_batch_concurrency: int = Field(default=2, gt=0, le=3)
    event_localization_max_attempts: int = Field(default=3, gt=0, le=10)

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

    @property
    def resolved_research_openclaw_config_path(self) -> Path:
        if self.research_openclaw_config_path.is_absolute():
            return self.research_openclaw_config_path
        return REPOSITORY_ROOT / self.research_openclaw_config_path

    @property
    def resolved_research_openclaw_state_dir(self) -> Path:
        if self.research_openclaw_state_dir.is_absolute():
            return self.research_openclaw_state_dir
        return REPOSITORY_ROOT / self.research_openclaw_state_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
