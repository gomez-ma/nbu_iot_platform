from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NBU IoT Platform"
    app_env: str = "development"
    secret_key: str = "development-only-change-this-secret-key"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nbu_iot"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:8000"
    emqx_base_url: str = "http://emqx:18083"
    emqx_username: str = "admin"
    emqx_password: str = Field(default="", validation_alias=AliasChoices("EMQX_PASSWORD", "EMQX_DASHBOARD_PASSWORD"))
    emqx_timeout_seconds: float = 8.0
    emqx_mqtt_host: str = "emqx"
    emqx_mqtt_port: int = 1883
    emqx_mqtt_public_host: str = ""
    emqx_mqtt_public_port: int = 1883
    emqx_mqtt_public_tls_port: int = 8883
    emqx_mqtt_tls_enabled: bool = False
    mqtt_keepalive_seconds: int = 60
    device_heartbeat_timeout_seconds: int = 90
    device_event_webhook_url: str = "http://nbu-iot-platform:8000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secret(self):
        if self.app_env.lower() == "production" and len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters in production")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
