import asyncio
import logging
from typing import Optional, List, Dict, Any
import yt_dlp

from .base import BaseExtractor, Track, ExtractionResult
from ..config import config

logger = logging.getLogger("sharmanka.extractors.ytdlp")

YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "extract_flat": "in_playlist",
    "skip_download": True,
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "socket_timeout": 5,
    "retries": 2,
    "fragment_retries": 2,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
}

if config and config.ytdl_cookies_file:
    YTDL_OPTIONS["cookiefile"] = config.ytdl_cookies_file


class YtDlpExtractor(BaseExtractor):
    def __init__(self):
        self.ydl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    def can_handle(self, query: str) -> bool:
        # Универсальный фоллбек для YouTube, SoundCloud, прямых стримов и поисковых запросов
        return True

    async def _resolve_single_stream(self, webpage_url: str) -> Optional[str]:
        def _fetch():
            opts = dict(YTDL_OPTIONS)
            opts["extract_flat"] = False
            opts["skip_download"] = True
            opts["youtube_include_dash_manifest"] = False
            opts["youtube_include_hls_manifest"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(webpage_url, download=False)

        try:
            info = await asyncio.to_thread(_fetch)
            if not info:
                return None
            return info.get("url")
        except Exception as e:
            logger.error(f"Ошибка получения stream URL для {webpage_url}: {e}")
            return None

    def _create_track_from_entry(
        self, entry: Dict[str, Any], requester: str, requester_avatar: Optional[str]
    ) -> Track:
        title = entry.get("title") or "Неизвестный трек"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "YouTube"
        duration = int(entry.get("duration") or 0)
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        
        # Получение thumbnail
        thumbnail = entry.get("thumbnail")
        if not thumbnail and "thumbnails" in entry and entry["thumbnails"]:
            thumbnail = entry["thumbnails"][-1].get("url")

        source = "youtube"
        extractor_key = (entry.get("extractor_key") or "").lower()
        if "soundcloud" in extractor_key:
            source = "soundcloud"
        elif "bandcamp" in extractor_key:
            source = "bandcamp"
        elif "twitch" in extractor_key:
            source = "twitch"

        direct_stream_url = entry.get("url") if entry.get("is_live") or not entry.get("extract_flat") else None

        # Функция ленивой дозагрузки ссылки на поток
        async def stream_resolver() -> Optional[str]:
            return await self._resolve_single_stream(webpage_url)

        return Track(
            title=title,
            artist=artist,
            webpage_url=webpage_url,
            duration=duration,
            thumbnail=thumbnail,
            source=source,
            requester=requester,
            requester_avatar=requester_avatar,
            stream_url=direct_stream_url,
            _stream_resolver=stream_resolver,
        )

    async def extract(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        query = query.strip()
        is_search = not (query.startswith("http://") or query.startswith("https://"))
        is_playlist = "list=" in query.lower() or "playlist" in query.lower() or "/sets/" in query.lower()
        target = f"ytsearch1:{query}" if is_search else query

        def _extract():
            opts = dict(YTDL_OPTIONS)
            opts["extract_flat"] = "in_playlist" if is_playlist else False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target, download=False)

        info = await asyncio.to_thread(_extract)
        if not info:
            return ExtractionResult(tracks=[], is_playlist=False, source_name="youtube")

        # Если это плейлист или результат поиска
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                return ExtractionResult(tracks=[], is_playlist=False, source_name="youtube")

            if is_search:
                # Одиночный результат поиска
                first_entry = entries[0]
                track = self._create_track_from_entry(first_entry, requester, requester_avatar)
                return ExtractionResult(tracks=[track], is_playlist=False, source_name="youtube")

            # Это настоящий плейлист
            tracks: List[Track] = []
            for entry in entries:
                tracks.append(
                    self._create_track_from_entry(entry, requester, requester_avatar)
                )

            playlist_title = info.get("title") or "Плейлист"
            return ExtractionResult(
                tracks=tracks,
                title=playlist_title,
                is_playlist=True,
                source_name="youtube_playlist",
            )

        # Одиночный трек/видео
        track = self._create_track_from_entry(info, requester, requester_avatar)
        return ExtractionResult(
            tracks=[track],
            title=track.title,
            is_playlist=False,
            source_name=track.source,
        )
