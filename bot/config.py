import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    discord_token: str
    yandex_music_token: Optional[str] = None
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None
    default_volume: int = 100
    idle_timeout_seconds: int = 300
    ytdl_cookies_file: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "DISCORD_TOKEN не задан! Пожалуйста, укажите токен вашего бота в файле .env"
            )

        ym_token = os.getenv("YANDEX_MUSIC_TOKEN", "").strip() or None
        spot_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None
        spot_sec = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None
        cookies = os.getenv("YTDL_COOKIES_FILE", "").strip() or None

        try:
            default_vol = int(os.getenv("DEFAULT_VOLUME", "100"))
        except ValueError:
            default_vol = 100

        try:
            idle_timeout = int(os.getenv("IDLE_TIMEOUT_SECONDS", "300"))
        except ValueError:
            idle_timeout = 300

        return cls(
            discord_token=token,
            yandex_music_token=ym_token,
            spotify_client_id=spot_id,
            spotify_client_secret=spot_sec,
            default_volume=max(1, min(150, default_vol)),
            idle_timeout_seconds=max(10, idle_timeout),
            ytdl_cookies_file=cookies,
        )


config = Config.from_env() if os.getenv("DISCORD_TOKEN") else None
