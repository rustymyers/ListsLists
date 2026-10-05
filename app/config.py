from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LISTSLISTS_", env_file=".env", extra="ignore")

    app_name: str = "ListsLists"
    environment: Literal["development", "test", "production"] = "development"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./data/listslists.db"
    public_base_url: str = "http://localhost:8000"
    data_dir: Path = Path("./data")
    secrets_dir: Path = Path("./secrets")

    auth_mode: Literal["local", "proxy", "both"] = "local"
    proxy_user_header: str = "Remote-User"
    proxy_email_header: str = "Remote-Email"
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    proxy_auto_create_users: bool = True

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_email: EmailStr = "admin@example.com"
    bootstrap_admin_password: str | None = None

    session_https_only: bool = False
    access_token_minutes: int = 60
    password_reset_minutes: int = 30

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    mail_from: EmailStr = "listslists@example.com"

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_cidrs(cls, value):
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets_dir.chmod(0o700)


@lru_cache
def get_settings() -> Settings:
    return Settings()
