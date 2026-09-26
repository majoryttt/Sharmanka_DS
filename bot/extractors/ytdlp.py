import os
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
    "default_search": "ytsearch5",
    "source_address": "0.0.0.0",
    "socket_timeout": 10,
    "retries": 3,
    "fragment_retries": 3,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
}

if config and config.ytdl_cookies_file:
    if os.path.exists(config.ytdl_cookies_file):
        YTDL_OPTIONS["cookiefile"] = config.ytdl_cookies_file
    elif os.path.exists(f"/app/{config.ytdl_cookies_file}"):
        YTDL_OPTIONS["cookiefile"] = f"/app/{config.ytdl_cookies_file}"


class YtDlpExtractor(BaseExtractor):
    def __init__(self):
        self.ydl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    def can_handle(self, query: str) -> bool:
        # Универсальный фоллбек для YouTube, SoundCloud, прямых стримов и поисковых запросов
        return True

    async def _resolve_single_stream(self, webpage_url: str) -> Optional[str]:
        def _fetch(target: str):
            opts = dict(YTDL_OPTIONS)
            opts["extract_flat"] = False
            opts["skip_download"] = True
            opts["youtube_include_dash_manifest"] = False
            opts["youtube_include_hls_manifest"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target, download=False)

        try:
            info = await asyncio.to_thread(_fetch, webpage_url)
            if info:
                if "entries" in info:
                    entries = [e for e in (info.get("entries") or []) if e]
                    if entries and entries[0].get("url"):
                        return entries[0].get("url")
                elif info.get("url"):
                    return info.get("url")
        except Exception as e:
            logger.warning(f"Ошибка получения stream URL для {webpage_url}: {e}")

        # Резервный поиск на SoundCloud, если поиск на YouTube не дал прямого потока
        if webpage_url.startswith("ytsearch"):
            query_part = webpage_url.split(":", 1)[1] if ":" in webpage_url else webpage_url
            sc_target = f"scsearch1:{query_part}"
            try:
                logger.info(f"Пробуем резервный поиск аудио на SoundCloud: {sc_target}")
                info = await asyncio.to_thread(_fetch, sc_target)
                if info:
                    if "entries" in info:
                        entries = [e for e in (info.get("entries") or []) if e]
                        if entries and entries[0].get("url"):
                            return entries[0].get("url")
                    elif info.get("url"):
                        return info.get("url")
            except Exception as e:
                logger.warning(f"Ошибка SoundCloud fallback для {sc_target}: {e}")

        return None

    def _create_track_from_entry(
        self, entry: Dict[str, Any], requester: str, requester_avatar: Optional[str]
    ) -> Track:
        title = entry.get("title") or "Неизвестный трек"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "YouTube"
        duration = int(entry.get("duration") or 0)
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        
        # Если в flat-режиме передан только ID видео
        if (not str(webpage_url).startswith("http")) and entry.get("id"):
            webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"

        # Получение thumbnail
        thumbnail = entry.get("thumbnail")
        if not thumbnail and "thumbnails" in entry and entry["thumbnails"]:
            thumbnail = entry["thumbnails"][-1].get("url")

        source = "youtube"
        extractor_key = (entry.get("extractor_key") or entry.get("ie_key") or "").lower()
        if "soundcloud" in extractor_key:
            source = "soundcloud"
        elif "bandcamp" in extractor_key:
            source = "bandcamp"
        elif "twitch" in extractor_key:
            source = "twitch"

        # Stream URL: только если это реальный медиапоток (googlevideo, m3u8, mp3, прямой эфир),
        # а НЕ URL веб-страницы
        raw_url = str(entry.get("url") or "")
        is_webpage = any(domain in raw_url for domain in ("youtube.com/watch", "youtu.be/", "soundcloud.com/", "spotify.com", "music.apple.com"))
        direct_stream_url = None
        if raw_url and not is_webpage and ("googlevideo.com" in raw_url or ".m3u8" in raw_url or ".mp3" in raw_url or entry.get("is_live")):
            direct_stream_url = raw_url

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
        target = f"ytsearch5:{query}" if is_search else query

        def _extract():
            opts = dict(YTDL_OPTIONS)
            # Для поиска и плейлистов запрашиваем метаданные в flat-режиме для скорости
            opts["extract_flat"] = True if (is_search or is_playlist) else False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target, download=False)

        info = await asyncio.to_thread(_extract)
        if not info:
            return ExtractionResult(tracks=[], is_playlist=False, source_name="youtube")

        # Если это плейлист или результат поиска
        if "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                return ExtractionResult(tracks=[], is_playlist=False, source_name="youtube")

            if is_search:
                # Одиночный поиск: перебираем выдачу и берем первый доступный трек
                for entry in entries:
                    if entry and (entry.get("title") or entry.get("id")):
                        track = self._create_track_from_entry(entry, requester, requester_avatar)
                        return ExtractionResult(tracks=[track], is_playlist=False, source_name=track.source)
                return ExtractionResult(tracks=[], is_playlist=False, source_name="youtube")

            # Это настоящий плейлист
            tracks: List[Track] = []
            for entry in entries:
                if entry and (entry.get("title") or entry.get("id")):
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
