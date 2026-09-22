"""Configuration settings for TiqueTaque Sync Admin via Pydantic Settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # TiqueTaque Public Admin API (v2.1)
    tiquetaque_admin_token: str = Field(
        default="",
        description="Public API Token from https://admin.tiquetaque.app/settings/integrations/publicapi"
    )
    tiquetaque_api_base_url: str = Field(
        default="https://api.tiquetaque.com/v2.1",
        description="Base URL for TiqueTaque Public Admin API"
    )

    # Slack Bot Configuration ("TiqueTaque Ponto")
    slack_enabled: bool = Field(default=False)
    slack_bot_token: str | None = Field(default=None, description="xoxb-... bot token")
    slack_signing_secret: str | None = Field(default=None, description="Slack request signing secret")
    slack_allowed_team_id: str | None = Field(default=None, description="Allowed Slack Team/Workspace ID (e.g. T01V8LQHBE1)")

    # Polling & Timers
    poll_interval_seconds: int = Field(default=180, description="Interval in seconds to poll TiqueTaque Admin API")
    alert_ticker_interval_seconds: int = Field(default=15, description="Interval in seconds for memory alert ticker")
    timezone: str = Field(default="America/Sao_Paulo")

    # Company Defaults for Alerts
    default_work_hours_per_day: float = Field(default=8.0)
    default_lunch_duration_minutes: int = Field(default=60)
    default_lunch_warning_advance_minutes: int = Field(default=10)
    default_lunch_warning_final_minutes: int = Field(default=1)
    default_end_work_warning_advance_minutes: int = Field(default=15)
    default_end_work_warning_final_minutes: int = Field(default=1)
    default_continuous_work_limit_hours: float = Field(default=6.0)
    default_continuous_work_warning_advance_minutes: int = Field(default=10)
    default_continuous_work_warning_final_minutes: int = Field(default=1)

    # Company Policy Controls
    allow_employee_customization: bool = Field(
        default=True,
        description="Whether employees can customize their alert lead time via Slack interactive buttons"
    )

    # Server & Storage
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path("data")
    admin_secret_key: str = "default-insecure-admin-key"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tiquetaque_admin.db"


settings = Settings()
