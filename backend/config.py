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
    max_tip_per_day: float = 50.00
    default_token: str = "USDT"

    # Demo recipient — if set, all tips are routed to this address instead of
    # creator_id (which is a YouTube channel ID, not an EVM address).
    # Set this to any valid Polygon wallet you control.
    demo_recipient_address: str = ""

    # Autonomous poller — comma-separated YouTube channel IDs
    # Leave empty to use default channels (MKBHD, t3.gg, Coin Bureau, Dave2D)
    youtube_channel_ids: str = ""

    # xAI Grok API key — enables real LLM (Grok-3-mini) for all agents.
    # Sign up at https://console.x.ai to get a key.
    # When set, USE_MOCK_CLAUDE is automatically treated as false.
    xai_api_key: str = ""

    # Groq fallback key (kept for compatibility)
    groq_api_key: str = ""

    # Set true to use pre-computed JSON responses instead of live LLM API calls.
    # Automatically false when xai_api_key or groq_api_key is set.
    use_mock_claude: bool = True

    @property
    def llm_enabled(self) -> bool:
        """True when a real LLM is available."""
        return bool(self.xai_api_key or self.groq_api_key)

    @property
    def effective_mock(self) -> bool:
        """
        Whether to use pre-computed mock responses.
        True when no real LLM key is configured (safe fallback)
        or when use_mock_claude is explicitly forced on.
        """
        if self.llm_enabled:
            return self.use_mock_claude  # Groq available; only mock if forced
        return True  # No Groq key → always fall back to mock

    # YouTube Data API v3 key — enables real engagement scoring.
    # Free quota: 10,000 units/day. videos.list costs 1 unit per call.
    # Get one at: https://console.cloud.google.com/apis/library/youtube.googleapis.com
    # Leave empty to fall back to heuristic scoring (no API calls).
    youtube_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
