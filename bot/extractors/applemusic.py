import re
import time
import logging
import asyncio
from typing import Optional, List, Dict, Any, Tuple
import aiohttp

from .base import BaseExtractor, Track, ExtractionResult
from ..config import config

logger = logging.getLogger("sharmanka.extractors.applemusic")

# Регулярные выражения для распознавания URL Apple Music
TRACK_URL_REGEX = re.compile(
    r"music\.apple\.com/(?:(?P<storefront>[a-z]{2}(?:-[a-z]{2})?)/)?album/(?:[^/]+/)?(?P<album_id>\d+)\?(?:.*&)?i=(?P<track_id>\d+)",
    re.IGNORECASE,
)
SONG_URL_REGEX = re.compile(
    r"music\.apple\.com/(?:(?P<storefront>[a-z]{2}(?:-[a-z]{2})?)/)?song/(?:[^/]+/)?(?P<track_id>\d+)",
    re.IGNORECASE,
)
ALBUM_URL_REGEX = re.compile(
    r"music\.apple\.com/(?:(?P<storefront>[a-z]{2}(?:-[a-z]{2})?)/)?album/(?:[^/]+/)?(?P<album_id>\d+)(?:$|[?#])",
    re.IGNORECASE,
)
PLAYLIST_URL_REGEX = re.compile(
    r"music\.apple\.com/(?:(?P<storefront>[a-z]{2}(?:-[a-z]{2})?)/)?playlist/(?:[^/]+/)?(?P<playlist_id>pl\.[a-zA-Z0-9_\-]+|pl\.u-[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)

# Запасной статический публичный web-токен Apple Music на случай недоступности динамического скрейпинга
DEFAULT_APPLE_DEV_TOKEN = (
    "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IldlYlBsYXllcktleSJ9."
    "eyJpc3MiOiJNQTM1VlE2R1hDIiwiaWF0IjoxNTc0MTcxMDAwLCJleHAiOjE5MjA5NzEwMDB9."
    "r44Zz_l1Lg-9_m_4b54e7d70c4765d7a04ba94f57c6b45d2"
)


class AppleMusicExtractor(BaseExtractor):
    def __init__(self, ytdl_fallback_extractor=None):
        self.ytdl_fallback = ytdl_fallback_extractor
        self._dev_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    def can_handle(self, query: str) -> bool:
        q = query.strip().lower()
        if "music.apple.com" in q:
            return True
        if q.startswith("am:") or q.startswith("apple:"):
            return True
        return False

    async def _resolve_audio(self, artist: str, title: str) -> Optional[str]:
        if not self.ytdl_fallback:
            return None
        search_query = f"ytsearch1:{artist} - {title}"
        return await self.ytdl_fallback._resolve_single_stream(search_query)

    def _create_track_item(
        self,
        title: str,
        artist: str,
        webpage_url: str,
        duration: int,
        thumbnail: Optional[str],
        requester: str,
        requester_avatar: Optional[str],
    ) -> Track:
        async def stream_resolver() -> Optional[str]:
            return await self._resolve_audio(artist, title)

        return Track(
            title=title,
            artist=artist,
            webpage_url=webpage_url,
            duration=duration,
            thumbnail=thumbnail,
            source="applemusic",
            requester=requester,
            requester_avatar=requester_avatar,
            _stream_resolver=stream_resolver,
        )

    def _format_artwork(self, url_template: Optional[str], width: int = 600, height: int = 600) -> Optional[str]:
        if not url_template:
            return None
        url = url_template.replace("{w}x{h}", f"{width}x{height}").replace("{f}", "jpg")
        # Для ссылок iTunes: заменяем 100x100bb на 600x600bb
        url = url.replace("100x100bb", f"{width}x{height}bb")
        return url

    async def _get_developer_token(self) -> str:
        """Получает и кеширует анонимный Developer Token для Amp API."""
        if config and config.apple_music_token:
            return config.apple_music_token

        now = time.time()
        if self._dev_token and now < self._token_expires_at:
            return self._dev_token

        async with self._token_lock:
            # Повторная проверка под локом
            if self._dev_token and now < self._token_expires_at:
                return self._dev_token

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            }

            try:
                async with aiohttp.ClientSession(headers=headers) as session:
                    # 1. Загружаем главную страницу Apple Music Web Player
                    async with session.get(
                        "https://music.apple.com/us/browse",
                        timeout=aiohttp.ClientTimeout(total=8),
                    ) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            # Ищем ссылку на основной JS-бандл (index-*.js)
                            js_matches = re.findall(r'src="(/assets/index-[^"]+\.js)"', html)
                            if not js_matches:
                                js_matches = re.findall(r'"([^"]*index-[^"]+\.js)"', html)

                            if js_matches:
                                js_path = js_matches[0]
                                js_url = (
                                    f"https://music.apple.com{js_path}"
                                    if js_path.startswith("/")
                                    else js_path
                                )
                                async with session.get(
                                    js_url, timeout=aiohttp.ClientTimeout(total=10)
                                ) as js_resp:
                                    if js_resp.status == 200:
                                        js_content = await js_resp.text()
                                        token_matches = re.findall(
                                            r'(ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})',
                                            js_content,
                                        )
                                        if token_matches:
                                            self._dev_token = token_matches[0]
                                            # Кешируем токен на 24 часа
                                            self._token_expires_at = now + 86400
                                            logger.info("Успешно извлечен динамический токен Apple Music Web.")
                                            return self._dev_token
            except Exception as e:
                logger.debug(f"Не удалось получить динамический токен Apple Music: {e}")

            # Если динамический скрейпинг не сработал — используем резервный токен
            self._dev_token = DEFAULT_APPLE_DEV_TOKEN
            self._token_expires_at = now + 3600
            return self._dev_token

    async def _fetch_itunes_lookup(self, entity_id: str, storefront: str = "us") -> Optional[Dict[str, Any]]:
        """Использует официальный iTunes Lookup API (быстро, публично, без авторизации)."""
        url = f"https://itunes.apple.com/lookup?id={entity_id}&entity=song&country={storefront}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.debug(f"Ошибка обращения к iTunes Lookup API ({url}): {e}")
        return None

    async def _fetch_itunes_search(self, term: str, storefront: str = "us", limit: int = 1) -> Optional[Dict[str, Any]]:
        """Поиск треков через iTunes Search API."""
        url = "https://itunes.apple.com/search"
        params = {"term": term, "media": "music", "entity": "song", "limit": str(limit), "country": storefront}
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.debug(f"Ошибка обращения к iTunes Search API: {e}")
        return None

    async def _fetch_amp_playlist(
        self, playlist_id: str, storefront: str = "us", max_tracks: int = 1500
    ) -> Tuple[Optional[str], Optional[str], List[Dict[str, Any]]]:
        """
        Загружает плейлист через Amp API с поддержкой пагинации по 100 треков за запрос.
        Позволяет без проблем парсить плейлисты на 600+ песен.
        """
        token = await self._get_developer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Origin": "https://music.apple.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        base_url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/playlists/{playlist_id}"
        playlist_title = "Плейлист Apple Music"
        playlist_thumb: Optional[str] = None
        raw_tracks: List[Dict[str, Any]] = []

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        logger.warning(f"Amp API вернул статус {resp.status} для плейлиста {playlist_id}")
                        return playlist_title, playlist_thumb, raw_tracks

                    data = await resp.json()
                    pl_data_list = data.get("data", [])
                    if not pl_data_list:
                        return playlist_title, playlist_thumb, raw_tracks

                    pl_obj = pl_data_list[0]
                    attrs = pl_obj.get("attributes", {})
                    playlist_title = attrs.get("name", playlist_title)
                    art_dict = attrs.get("artwork")
                    if art_dict and "url" in art_dict:
                        playlist_thumb = self._format_artwork(art_dict["url"])

                    tracks_rel = pl_obj.get("relationships", {}).get("tracks", {})
                    initial_tracks = tracks_rel.get("data", [])
                    raw_tracks.extend(initial_tracks)

                    next_path = tracks_rel.get("next")

                    # Цикл пагинации для больших плейлистов (например, 600 треков = 6 запросов)
                    while next_path and len(raw_tracks) < max_tracks:
                        next_url = (
                            f"https://amp-api.music.apple.com{next_path}"
                            if next_path.startswith("/")
                            else next_path
                        )
                        async with session.get(next_url, timeout=aiohttp.ClientTimeout(total=8)) as p_resp:
                            if p_resp.status != 200:
                                break
                            p_data = await p_resp.json()
                            p_items = p_data.get("data", [])
                            if not p_items:
                                break
                            raw_tracks.extend(p_items)
                            next_path = p_data.get("next")

        except Exception as e:
            logger.error(f"Ошибка при загрузке плейлиста Apple Music через Amp API: {e}", exc_info=True)

        return playlist_title, playlist_thumb, raw_tracks

    async def extract(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        query = query.strip()

        # 1. Поисковый запрос с префиксом (am: или apple:)
        if query.lower().startswith(("am:", "apple:")):
            clean_term = query.split(":", 1)[1].strip()
            search_res = await self._fetch_itunes_search(clean_term, limit=1)
            if search_res and search_res.get("results"):
                item = search_res["results"][0]
                title = item.get("trackName", clean_term)
                artist = item.get("artistName", "Apple Music")
                duration = (item.get("trackTimeMillis") or 0) // 1000
                thumb = self._format_artwork(item.get("artworkUrl100"))
                track_url = item.get("trackViewUrl", query)

                track = self._create_track_item(
                    title=title,
                    artist=artist,
                    webpage_url=track_url,
                    duration=duration,
                    thumbnail=thumb,
                    requester=requester,
                    requester_avatar=requester_avatar,
                )
                return ExtractionResult(
                    tracks=[track],
                    title=track.title,
                    is_playlist=False,
                    source_name="applemusic",
                )
            # Если в iTunes ничего не нашлось — fallback на yt-dlp
            if self.ytdl_fallback:
                return await self.ytdl_fallback.extract(clean_term, requester, requester_avatar)
            return ExtractionResult(tracks=[], is_playlist=False, source_name="applemusic")

        # 2. Одиночный трек из альбома (?i=track_id)
        track_match = TRACK_URL_REGEX.search(query)
        if track_match:
            track_id = track_match.group("track_id")
            storefront = track_match.group("storefront") or "us"
            data = await self._fetch_itunes_lookup(track_id, storefront=storefront)
            if data and data.get("results"):
                for item in data["results"]:
                    if item.get("wrapperType") == "track" or str(item.get("trackId")) == track_id:
                        title = item.get("trackName", "Apple Music Track")
                        artist = item.get("artistName", "Apple Music")
                        duration = (item.get("trackTimeMillis") or 0) // 1000
                        thumb = self._format_artwork(item.get("artworkUrl100"))
                        track_url = item.get("trackViewUrl", query)
                        track = self._create_track_item(
                            title, artist, track_url, duration, thumb, requester, requester_avatar
                        )
                        return ExtractionResult(
                            tracks=[track], title=track.title, is_playlist=False, source_name="applemusic"
                        )

        # 3. Одиночная песня по ссылке /song/{id}
        song_match = SONG_URL_REGEX.search(query)
        if song_match:
            track_id = song_match.group("track_id")
            storefront = song_match.group("storefront") or "us"
            data = await self._fetch_itunes_lookup(track_id, storefront=storefront)
            if data and data.get("results"):
                item = data["results"][0]
                title = item.get("trackName", "Apple Music Track")
                artist = item.get("artistName", "Apple Music")
                duration = (item.get("trackTimeMillis") or 0) // 1000
                thumb = self._format_artwork(item.get("artworkUrl100"))
                track_url = item.get("trackViewUrl", query)
                track = self._create_track_item(
                    title, artist, track_url, duration, thumb, requester, requester_avatar
                )
                return ExtractionResult(
                    tracks=[track], title=track.title, is_playlist=False, source_name="applemusic"
                )

        # 4. Плейлист Apple Music (включая большие плейлисты на 600+ треков)
        playlist_match = PLAYLIST_URL_REGEX.search(query)
        if playlist_match:
            playlist_id = playlist_match.group("playlist_id")
            storefront = playlist_match.group("storefront") or "us"
            title, thumb, raw_tracks = await self._fetch_amp_playlist(
                playlist_id, storefront=storefront, max_tracks=1500
            )

            tracks: List[Track] = []
            for item in raw_tracks:
                attrs = item.get("attributes", {})
                t_name = attrs.get("name")
                if not t_name:
                    continue
                t_artist = attrs.get("artistName", "Apple Music")
                t_duration = (attrs.get("durationInMillis") or 0) // 1000
                t_art = attrs.get("artwork")
                t_thumb = self._format_artwork(t_art.get("url")) if t_art else thumb
                t_url = attrs.get("url", query)

                tracks.append(
                    self._create_track_item(
                        title=t_name,
                        artist=t_artist,
                        webpage_url=t_url,
                        duration=t_duration,
                        thumbnail=t_thumb,
                        requester=requester,
                        requester_avatar=requester_avatar,
                    )
                )

            if tracks:
                return ExtractionResult(
                    tracks=tracks,
                    title=f"Плейлист: {title}",
                    is_playlist=True,
                    source_name="applemusic_playlist",
                )

        # 5. Альбом Apple Music
        album_match = ALBUM_URL_REGEX.search(query)
        if album_match:
            album_id = album_match.group("album_id")
            storefront = album_match.group("storefront") or "us"
            data = await self._fetch_itunes_lookup(album_id, storefront=storefront)
            if data and data.get("results"):
                album_info = data["results"][0]
                album_name = album_info.get("collectionName", "Альбом Apple Music")
                album_artist = album_info.get("artistName", "")
                album_thumb = self._format_artwork(album_info.get("artworkUrl100"))

                tracks = []
                for item in data["results"]:
                    if item.get("wrapperType") == "track":
                        t_title = item.get("trackName")
                        if not t_title:
                            continue
                        t_artist = item.get("artistName", album_artist)
                        t_duration = (item.get("trackTimeMillis") or 0) // 1000
                        t_thumb = self._format_artwork(item.get("artworkUrl100")) or album_thumb
                        t_url = item.get("trackViewUrl", query)

                        tracks.append(
                            self._create_track_item(
                                title=t_title,
                                artist=t_artist,
                                webpage_url=t_url,
                                duration=t_duration,
                                thumbnail=t_thumb,
                                requester=requester,
                                requester_avatar=requester_avatar,
                            )
                        )

                if tracks:
                    return ExtractionResult(
                        tracks=tracks,
                        title=f"Альбом: {album_name} ({album_artist})",
                        is_playlist=True,
                        source_name="applemusic_album",
                    )

        # 6. Fallback на yt-dlp, если ссылка не подошла ни под один паттерн
        if self.ytdl_fallback:
            res = await self.ytdl_fallback.extract(query, requester, requester_avatar)
            res.source_name = "applemusic"
            return res

        return ExtractionResult(tracks=[], is_playlist=False, source_name="applemusic")
