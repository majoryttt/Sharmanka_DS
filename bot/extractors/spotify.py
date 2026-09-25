import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
import aiohttp

from .base import BaseExtractor, Track, ExtractionResult
from ..config import config

logger = logging.getLogger("sharmanka.extractors.spotify")

SPOTIFY_URL_REGEX = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)"
)


class SpotifyExtractor(BaseExtractor):
    def __init__(self, ytdl_fallback_extractor=None):
        self.ytdl_fallback = ytdl_fallback_extractor
        self._sp = None
        self._init_spotify_client()

    def _init_spotify_client(self):
        if config and config.spotify_client_id and config.spotify_client_secret:
            try:
                import spotipy
                from spotipy.oauth2 import SpotifyClientCredentials

                self._sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=config.spotify_client_id,
                        client_secret=config.spotify_client_secret,
                    )
                )
                logger.info("Spotify API клиент успешно инициализирован.")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать Spotipy: {e}")

    def can_handle(self, query: str) -> bool:
        return "open.spotify.com" in query.lower()

    async def _resolve_audio(self, artist: str, title: str) -> Optional[str]:
        if not self.ytdl_fallback:
            return None
        search_query = f"ytsearch:{artist} - {title}"
        return await self.ytdl_fallback._resolve_single_stream(search_query)

    async def _fetch_oembed(self, url: str) -> Optional[Dict[str, Any]]:
        oembed_url = f"https://open.spotify.com/oembed?url={url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.debug(f"Ошибка запроса Spotify oEmbed: {e}")
        return None

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
            source="spotify",
            requester=requester,
            requester_avatar=requester_avatar,
            _stream_resolver=stream_resolver,
        )

    async def extract(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        match = SPOTIFY_URL_REGEX.search(query.strip())
        if not match:
            return ExtractionResult(tracks=[], is_playlist=False, source_name="spotify")

        entity_type, entity_id = match.group(1), match.group(2)
        clean_url = f"https://open.spotify.com/{entity_type}/{entity_id}"

        # 1. Если настроен официальный клиент Spotipy
        if self._sp:
            try:
                if entity_type == "track":
                    t = await asyncio.to_thread(self._sp.track, entity_id)
                    title = t["name"]
                    artist = ", ".join(a["name"] for a in t["artists"])
                    duration = t["duration_ms"] // 1000
                    thumbnail = t["album"]["images"][0]["url"] if t["album"]["images"] else None
                    track = self._create_track_item(
                        title, artist, clean_url, duration, thumbnail, requester, requester_avatar
                    )
                    return ExtractionResult(
                        tracks=[track], title=track.title, is_playlist=False, source_name="spotify"
                    )

                elif entity_type == "album":
                    alb = await asyncio.to_thread(self._sp.album, entity_id)
                    album_title = alb["name"]
                    thumbnail = alb["images"][0]["url"] if alb["images"] else None
                    tracks = []
                    for item in alb["tracks"]["items"]:
                        title = item["name"]
                        artist = ", ".join(a["name"] for a in item["artists"])
                        duration = item["duration_ms"] // 1000
                        item_url = item["external_urls"].get("spotify", clean_url)
                        tracks.append(
                            self._create_track_item(
                                title, artist, item_url, duration, thumbnail, requester, requester_avatar
                            )
                        )
                    return ExtractionResult(
                        tracks=tracks,
                        title=f"Альбом: {album_title}",
                        is_playlist=True,
                        source_name="spotify_album",
                    )

                elif entity_type == "playlist":
                    pl = await asyncio.to_thread(self._sp.playlist, entity_id)
                    pl_title = pl["name"]
                    thumbnail = pl["images"][0]["url"] if pl["images"] else None
                    tracks = []
                    for item in pl["tracks"]["items"]:
                        t = item.get("track")
                        if not t:
                            continue
                        title = t["name"]
                        artist = ", ".join(a["name"] for a in t["artists"])
                        duration = t["duration_ms"] // 1000
                        t_thumb = t["album"]["images"][0]["url"] if t["album"]["images"] else thumbnail
                        t_url = t["external_urls"].get("spotify", clean_url)
                        tracks.append(
                            self._create_track_item(
                                title, artist, t_url, duration, t_thumb, requester, requester_avatar
                            )
                        )
                    return ExtractionResult(
                        tracks=tracks,
                        title=f"Плейлист: {pl_title}",
                        is_playlist=True,
                        source_name="spotify_playlist",
                    )
            except Exception as e:
                logger.error(f"Ошибка запроса к Spotipy API: {e}")

        # 2. Быстрый fallback через oEmbed для одиночного трека
        oembed_data = await self._fetch_oembed(clean_url)
        if oembed_data and entity_type == "track":
            title = oembed_data.get("title", "Spotify Track")
            thumbnail = oembed_data.get("thumbnail_url")
            # Заголовок oEmbed трека обычно "Title" или "Title by Artist"
            track = self._create_track_item(
                title=title,
                artist="Spotify",
                webpage_url=clean_url,
                duration=0,
                thumbnail=thumbnail,
                requester=requester,
                requester_avatar=requester_avatar,
            )
            return ExtractionResult(
                tracks=[track], title=track.title, is_playlist=False, source_name="spotify"
            )

        # 3. Полный fallback через YtDlpExtractor (yt-dlp умеет парсить Spotify страницы)
        if self.ytdl_fallback:
            res = await self.ytdl_fallback.extract(clean_url, requester, requester_avatar)
            res.source_name = "spotify"
            return res

        return ExtractionResult(tracks=[], is_playlist=False, source_name="spotify")
