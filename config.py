from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str
    DATABASE_URL: str
    LOCAL_DEBUG: bool = True
    ADMIN_IDS: str  # "123456789,987654321"
    WEBHOOK_URL: str = "https://benefon-bot.onrender.com"
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    @property
    def admin_list(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]


settings = Settings()
