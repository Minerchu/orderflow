from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "replace_me"
    # Public base URL of THIS deployment. Telegram needs it to deliver button
    # taps, so it must be reachable from the internet (e.g. https://order.example.com).
    APP_BASE_URL: str = "http://localhost:8000"
    SESSION_SECRET: str = "replace_me_session"
    # Register the callback webhook automatically on startup. Turn off only if
    # you register it yourself (or run behind a tunnel that changes URLs often).
    AUTO_REGISTER_WEBHOOK: bool = True

    # ---- Database ----
    DATABASE_URL: str = "sqlite:///./orderflow.db"

    # ---- Telegram ----
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_DEFAULT_CHAT_ID: str = ""
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""
    ADMIN_TELEGRAM_USER_IDS: str = ""
    # Optional outbound proxy for api.telegram.org, e.g.
    #   http://user:pass@host:1080   or   socks5://user:pass@host:1080
    # Required when the server cannot reach api.telegram.org directly.
    TELEGRAM_PROXY: str = ""
    # Tests / local demos only: use an in-memory client instead of requiring a
    # real bot token. MUST stay false in production (see validate_required).
    TELEGRAM_DRY_RUN: bool = False

    # ---- i18n & Currency ----
    DEFAULT_LANGUAGE: str = "en"
    DEFAULT_CURRENCY: str = "INR"
    SUPPORTED_CURRENCIES: str = "INR,USD"
    TELEGRAM_MESSAGE_LANGUAGE: str = "en"

    # ---- Group message display ----
    SHOW_ORDER_ID_IN_GROUP: bool = False
    SHOW_CREDENTIALS_IN_GROUP: bool = True
    SHOW_PASSWORD_IN_GROUP: bool = True

    # ---- Group member permissions ----
    ALLOW_ANY_GROUP_MEMBER_TO_COMPLETE: bool = False
    ALLOW_ANY_GROUP_MEMBER_TO_FAIL: bool = False
    ALLOW_ANY_GROUP_MEMBER_TO_REOPEN: bool = False
    ALLOW_ANY_GROUP_MEMBER_TO_CLOSE: bool = False

    # ---- Storage ----
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_PATH: str = "/app/data/uploads"
    S3_ENDPOINT_URL: str = ""
    S3_BUCKET_NAME: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_REGION: str = ""

    # ---- Uploads ----
    MAX_UPLOAD_SIZE_MB: int = 10

    # ---- Derived helpers ----
    @property
    def allowed_chat_ids(self) -> List[str]:
        return [c.strip() for c in self.TELEGRAM_ALLOWED_CHAT_IDS.split(",") if c.strip()]

    @property
    def admin_telegram_user_ids(self) -> List[str]:
        return [u.strip() for u in self.ADMIN_TELEGRAM_USER_IDS.split(",") if u.strip()]

    @property
    def supported_currencies(self) -> List[str]:
        return [c.strip().upper() for c in self.SUPPORTED_CURRENCIES.split(",") if c.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    def validate_required(self) -> None:
        """Production must not start with insecure defaults / missing secrets."""
        if self.APP_ENV.lower() == "production":
            missing = []
            if self.APP_SECRET_KEY in ("replace_me", ""):
                missing.append("APP_SECRET_KEY")
            if self.SESSION_SECRET in ("replace_me_session", ""):
                missing.append("SESSION_SECRET")
            if missing:
                raise RuntimeError(
                    "Refusing to start in production with missing config: "
                    + ", ".join(missing)
                )
            if self.TELEGRAM_DRY_RUN:
                raise RuntimeError(
                    "TELEGRAM_DRY_RUN must not be enabled in production: "
                    "orders would appear sent without reaching the group."
                )


settings = Settings()
