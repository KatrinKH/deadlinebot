"""Конфигурация приложения из переменных окружения / файла .env."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    admin_id: int
    database_url: str = "sqlite+aiosqlite:///data/deadlinebot.db"
    timezone: str = "Europe/Moscow"
    seed_path: str = "seed.yaml"
    # При запуске приводить треки и разделы предметов в БД к seed.yaml.
    # Выключите, когда начнёте править треки через /admin_tracks, иначе перезапуск их перетрёт.
    seed_sync_tracks: bool = True
    # Сколько раз студент может сам изменить предметы после онбординга;
    # дальше — только с разрешения админа
    subject_change_limit: int = 2

    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""

    log_level: str = "INFO"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
