"""VAROS configuration — loaded from environment / .env file."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    varos_llm_model: str = Field(default="claude-sonnet-4-6", alias="VAROS_LLM_MODEL")

    # NCBI
    ncbi_email: str = Field(default="varos@varos.io", alias="NCBI_EMAIL")
    ncbi_api_key: str = Field(default="", alias="NCBI_API_KEY")

    # OMIM
    omim_api_key: str = Field(default="", alias="OMIM_API_KEY")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./varos.db", alias="DATABASE_URL"
    )

    # Billing
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    stripe_starter_price_id: str = Field(default="", alias="STRIPE_STARTER_PRICE_ID")
    stripe_pro_price_id: str = Field(default="", alias="STRIPE_PRO_PRICE_ID")

    # Email
    sendgrid_api_key: str = Field(default="", alias="SENDGRID_API_KEY")
    sendgrid_from_email: str = Field(default="alerts@varos.io", alias="SENDGRID_FROM_EMAIL")

    # App
    varos_env: str = Field(default="development", alias="VAROS_ENV")
    varos_log_level: str = Field(default="INFO", alias="VAROS_LOG_LEVEL")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    secret_key: str = Field(default="change-me-in-production", alias="SECRET_KEY")

    @property
    def is_production(self) -> bool:
        return self.varos_env == "production"

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
