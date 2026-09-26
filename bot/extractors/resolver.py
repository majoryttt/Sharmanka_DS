import time
import logging
from typing import Optional, List, Dict, Tuple
from .base import Track, ExtractionResult, BaseExtractor
from .ytdlp import YtDlpExtractor
from .yandex import YandexMusicExtractor
from .spotify import SpotifyExtractor
from .applemusic import AppleMusicExtractor

logger = logging.getLogger("sharmanka.extractors.resolver")


class QueryCache:
    """Кеш результатов поиска и метаданных треков (TTL: 2 часа, до 1000 записей)."""

    def __init__(self, ttl: int = 7200, max_size: int = 1000):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, Tuple[float, ExtractionResult]] = {}

    def get(self, query: str, requester: str, requester_avatar: Optional[str]) -> Optional[ExtractionResult]:
        key = query.strip().lower()
        if key in self._cache:
            created_at, res = self._cache[key]
            if time.time() - created_at < self.ttl:
                # Клонируем треки с новым пользователем (requester)
                cloned_tracks = [t.clone(requester=requester, requester_avatar=requester_avatar) for t in res.tracks]
                return ExtractionResult(
                    tracks=cloned_tracks,
                    title=res.title,
                    is_playlist=res.is_playlist,
                    source_name=res.source_name,
                )
            else:
                del self._cache[key]
        return None

    def set(self, query: str, res: ExtractionResult):
        if not res.tracks:
            return
        if len(self._cache) >= self.max_size:
            # Очищаем 10% самых старых записей
            oldest = sorted(self._cache.items(), key=lambda x: x[1][0])[: max(1, self.max_size // 10)]
            for k, _ in oldest:
                self._cache.pop(k, None)
        key = query.strip().lower()
        self._cache[key] = (time.time(), res)


class TrackResolver:
    def __init__(self):
        self.ytdl = YtDlpExtractor()
        self.yandex = YandexMusicExtractor(ytdl_fallback_extractor=self.ytdl)
        self.spotify = SpotifyExtractor(ytdl_fallback_extractor=self.ytdl)
        self.applemusic = AppleMusicExtractor(ytdl_fallback_extractor=self.ytdl)
        self.cache = QueryCache()

    async def resolve(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        query = query.strip()
        logger.info(f"Резолвинг запроса: '{query}' от {requester}")

        cached = self.cache.get(query, requester, requester_avatar)
        if cached:
            logger.info(f"Запрос '{query}' мгновенно получен из кеша ({len(cached.tracks)} треков)")
            return cached

        res: Optional[ExtractionResult] = None

        # 1. Проверка Яндекс Музыки
        if self.yandex.can_handle(query):
            try:
                res = await self.yandex.extract(query, requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.error(f"Ошибка извлечения из Яндекс Музыки: {e}", exc_info=True)

        # 2. Проверка Spotify
        if self.spotify.can_handle(query):
            try:
                res = await self.spotify.extract(query, requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.error(f"Ошибка извлечения из Spotify: {e}", exc_info=True)

        # 3. Проверка Apple Music
        if self.applemusic.can_handle(query):
            try:
                res = await self.applemusic.extract(query, requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.error(f"Ошибка извлечения из Apple Music: {e}", exc_info=True)

        # 4. Универсальный yt-dlp (YouTube, SoundCloud, веб-стримы, текстовый поиск)
        is_url = query.startswith("http://") or query.startswith("https://")
        try:
            res = await self.ytdl.extract(query, requester, requester_avatar)
            if res and res.tracks:
                self.cache.set(query, res)
                return res
        except Exception as e:
            logger.warning(f"Ошибка извлечения через yt-dlp: {e}")

        # 5. Если это текстовый поиск и YouTube ничего не нашел — каскадный поиск
        if not is_url:
            # 5a. Пробуем Яндекс Музыку
            try:
                logger.info(f"Каскадный поиск: пробуем Яндекс Музыку для '{query}'")
                res = await self.yandex.search(query, requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.debug(f"Ошибка каскадного поиска в Яндекс Музыке: {e}")

            # 5b. Пробуем SoundCloud
            try:
                logger.info(f"Каскадный поиск: пробуем SoundCloud для '{query}'")
                res = await self.ytdl.extract(f"scsearch5:{query}", requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.debug(f"Ошибка каскадного поиска в SoundCloud: {e}")

            # 5c. Пробуем Apple Music (iTunes Search)
            try:
                logger.info(f"Каскадный поиск: пробуем Apple Music для '{query}'")
                res = await self.applemusic.extract(f"am:{query}", requester, requester_avatar)
                if res and res.tracks:
                    self.cache.set(query, res)
                    return res
            except Exception as e:
                logger.debug(f"Ошибка каскадного поиска в Apple Music: {e}")

        return ExtractionResult(tracks=[], is_playlist=False, source_name="unknown")
