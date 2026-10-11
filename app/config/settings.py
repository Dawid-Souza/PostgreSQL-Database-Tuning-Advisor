from pathlib import Path

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    app_name: str = "PostgreSQL Database Tuning Advisor"
    app_version: str = "1.0.0"
    app_secret: str = "change-me-local-only"

    config_file: str = "environment_configs.json"
    app_sqlite_file: str = "app.sqlite3"

    log_cache_page_size: int = 50
    max_log_fetch_bytes: int = 0
    max_log_recommendation_groups: int = 250
    max_log_recommendations: int = 250

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def config_path(self) -> Path:
        return DATA_DIR / self.config_file

    @property
    def app_sqlite_path(self) -> Path:
        return DATA_DIR / self.app_sqlite_file


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
