from pydantic_settings import BaseSettings
from functools import lru_cache


class Config(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""

    # WDK Wallet — Python backend calls the WDK Node.js microservice
    wdk_api_key: str = ""
    wdk_wallet_address: str = ""
    wdk_endpoint: str = "http://localhost:3001"   # WDK microservice default

    # WDK Node.js microservice (wdk-service/index.js)
    wdk_seed_phrase: str = ""      # 12-word BIP39 mnemonic
    wdk_rpc_url: str = ""          # Polygon/Ethereum RPC URL
    wdk_chain: str = "polygon"     # "polygon" | "ethereum"

    # Database
    database_url: str = "sqlite+aiosqlite:///./tipmind.db"

    # Tipping
    max_tip_per_video: float = 5.00
    default_token: str = "USDT"

    # Autonomous poller — comma-separated YouTube channel IDs
    # Leave empty to use default channels (MKBHD, t3.gg, Coin Bureau, Dave2D)
    youtube_channel_ids: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
