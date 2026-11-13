"""Application configuration loaded from environment variables."""

import os


DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/auction_search.db")
SCHEDULER_TICK_SECONDS: int = int(os.getenv("SCHEDULER_TICK_SECONDS", "60"))
EQUIPBID_BASE_URL: str = os.getenv("EQUIPBID_BASE_URL", "https://www.equip-bid.com").rstrip("/")
USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
