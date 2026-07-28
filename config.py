import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    VK_GROUP_TOKEN: str = os.getenv("VK_GROUP_TOKEN", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///trips.db")
    YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")
    ADMIN_IDS: str = os.getenv("ADMIN_IDS", "")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/bot.log")

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

settings = Settings()