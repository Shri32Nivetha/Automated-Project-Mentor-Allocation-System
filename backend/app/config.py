"""Application configuration, loaded from environment variables / backend/.env.

The database URL is always built with SQLAlchemy's URL.create(), so passwords
containing characters such as @ # / : % are handled safely (no manual escaping).
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PLACEHOLDER_SECRETS = {"", "change-me", "changeme", "replace-with-a-long-random-secret", "your-secret-here"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- MySQL ---
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "project_guide_allocation"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800

    # --- Auth ---
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # --- HTTP ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_base_url: str = "http://localhost:5173"

    # --- Allocation optimiser (OR-Tools CP-SAT) ---
    # Total wall-clock budget for one allocation run; it is shared between the lexicographic stages.
    allocation_solver_time_limit_seconds: float = 30.0
    # 1 worker keeps results deterministic for unchanged inputs (more workers can reorder equal-cost solutions).
    allocation_solver_workers: int = 1

    # --- Optional e-mail (leave smtp_host empty to disable delivery) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    @field_validator("jwt_secret")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        if v.strip().lower() in PLACEHOLDER_SECRETS or len(v) < 32:
            raise ValueError(
                "JWT_SECRET is missing, a placeholder, or shorter than 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return v

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


@lru_cache
def get_settings() -> Settings:
    return Settings()
