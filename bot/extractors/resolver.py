import logging
from typing import Optional, List
from .base import Track, ExtractionResult, BaseExtractor
from .ytdlp import YtDlpExtractor
from .yandex import YandexMusicExtractor
from .spotify import SpotifyExtractor

logger = logging.getLogger("sharmanka.extractors.resolver")


class TrackResolver:
    def __init__(self):
        self.ytdl = YtDlpExtractor()
        self.yandex = YandexMusicExtractor(ytdl_fallback_extractor=self.ytdl)
        self.spotify = SpotifyExtractor(ytdl_fallback_extractor=self.ytdl)

    async def resolve(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        query = query.strip()
        logger.info(f"Резолвинг запроса: '{query}' от {requester}")

        # Проверка Яндекс Музыки
        if self.yandex.can_handle(query):
            try:
                res = await self.yandex.extract(query, requester, requester_avatar)
                if res.tracks:
                    return res
            except Exception as e:
                logger.error(f"Ошибка извлечения из Яндекс Музыки: {e}", exc_info=True)

        # Проверка Spotify
        if self.spotify.can_handle(query):
            try:
                res = await self.spotify.extract(query, requester, requester_avatar)
                if res.tracks:
                    return res
            except Exception as e:
                logger.error(f"Ошибка извлечения из Spotify: {e}", exc_info=True)

        # Универсальный yt-dlp (YouTube, SoundCloud, веб-стримы, текстовый поиск)
        try:
            return await self.ytdl.extract(query, requester, requester_avatar)
        except Exception as e:
            logger.error(f"Ошибка извлечения через yt-dlp: {e}", exc_info=True)
            return ExtractionResult(tracks=[], is_playlist=False, source_name="unknown")
