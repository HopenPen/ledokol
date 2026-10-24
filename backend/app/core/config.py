from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-change-me-0123456789abcdef"


class Settings(BaseSettings):
    """Все настройки — из окружения / .env. Секретов в коде и репозитории нет."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CASHFLOW_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./cashflow.db"
    jwt_secret: SecretStr = SecretStr(_DEV_SECRET)
    jwt_ttl_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_mb: int = 50

    forecast_horizon: int = 30
    forecast_sims: int = 1000
    forecast_seed: int = 7

    demo_user: str = "demo"
    demo_password: SecretStr | None = None

    onec_base_url: str = "http://localhost:8101"
    onec_token: SecretStr = SecretStr("")
    fns_base_url: str = "http://localhost:8102"
    fns_token: SecretStr = SecretStr("")
    integration_timeout_s: float = 5.0

    # LLM выключен по умолчанию: всё работает на шаблонах. Любой OpenAI-совместимый API; ключ — только из окружения.
    llm_provider: Literal["none", "openai"] = "none"
    llm_base_url: str | None = None      # None — api.openai.com; иначе свой шлюз / модель в контуре банка
    llm_model: str = ""
    llm_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _prod_guards(self) -> Settings:
        if self.env == "prod" and self.jwt_secret.get_secret_value() == _DEV_SECRET:
            raise ValueError("CASHFLOW_JWT_SECRET must be set in prod")
        if self.llm_provider == "openai" and not (self.llm_api_key and self.llm_model):
            raise ValueError("CASHFLOW_LLM_API_KEY and CASHFLOW_LLM_MODEL are required when CASHFLOW_LLM_PROVIDER=openai")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
