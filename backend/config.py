from pydantic_settings import BaseSettings
from functools import lru_cache


class Config(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""

    # WDK Wallet
    wdk_api_key: str = ""
    wdk_wallet_address: str = ""
    wdk_endpoint: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./tipmind.db"

    # Tipping
    max_tip_per_video: float = 5.00
    default_token: str = "USDT"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
