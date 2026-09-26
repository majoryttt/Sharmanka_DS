import asyncio
import logging
import re
from typing import Optional, List, Tuple, Any
from yandex_music import ClientAsync

from .base import BaseExtractor, Track, ExtractionResult
from ..config import config

logger = logging.getLogger("sharmanka.extractors.yandex")

# Регулярные выражения для ссылок Яндекс Музыки
TRACK_REGEX = re.compile(r"music\.yandex\.(?:ru|com)/(?:album/(\d+)/)?track/(\d+)")
ALBUM_REGEX = re.compile(r"music\.yandex\.(?:ru|com)/album/(\d+)(?:$|[?#/])")
PLAYLIST_USER_REGEX = re.compile(
    r"music\.yandex\.(?:ru|com)/users/([^/]+)/playlists/(\d+)"
)
PLAYLIST_UUID_REGEX = re.compile(
    r"music\.yandex\.(?:ru|com)/playlists/([a-zA-Z0-9_\-]+)"
)
ARTIST_REGEX = re.compile(r"music\.yandex\.(?:ru|com)/artist/(\d+)")
CHART_REGEX = re.compile(r"music\.yandex\.(?:ru|com)/chart")


class YandexMusicExtractor(BaseExtractor):
    def __init__(self, ytdl_fallback_extractor=None):
        self.ytdl_fallback = ytdl_fallback_extractor
        self._client: Optional[ClientAsync] = None
        self._init_lock = asyncio.Lock()

    async def _get_client(self) -> ClientAsync:
        if self._client is None:
            async with self._init_lock:
                if self._client is None:
                    token = config.yandex_music_token if config else None
                    client = ClientAsync(token=token)
                    await client.init()
                    self._client = client
        return self._client

    def can_handle(self, query: str) -> bool:
        q = query.strip().lower()
        if "music.yandex." in q:
            return True
        if q.startswith("ym:") or q.startswith("yandex:"):
            return True
        return False

    def _format_cover(self, cover_uri: Optional[str]) -> Optional[str]:
        if not cover_uri:
            return None
        if "%%" in cover_uri:
            return f"https://{cover_uri.replace('%%', '400x400')}"
        return cover_uri

    async def _resolve_direct_or_fallback(
        self, track_obj: Any, track_title: str, artist_name: str
    ) -> Optional[str]:
        # 1. Попытка получить прямую ссылку через API Яндекса (если есть токен с подпиской)
        try:
            download_info = await track_obj.get_download_info_async(get_direct_links=True)
            if download_info:
                # Сортируем по битрейту (наивысший в начале)
                sorted_info = sorted(
                    download_info, key=lambda x: getattr(x, "bitrate_in_kbps", 0), reverse=True
                )
                direct_link = getattr(sorted_info[0], "direct_link", None)
                if not direct_link:
                    direct_link = await sorted_info[0].get_direct_link_async()
                if direct_link:
                    return direct_link
        except Exception as e:
            logger.debug(f"Прямой стрим из Яндекс Музыки недоступен ({e}), переключаемся на YouTube fallback")

        # 2. Fallback на YouTube через YtDlpExtractor
        if self.ytdl_fallback:
            fallback_query = f"{artist_name} - {track_title}"
            return await self.ytdl_fallback._resolve_single_stream(f"ytsearch1:{fallback_query}")

        return None

    def _convert_ym_track(
        self, ym_track: Any, requester: str, requester_avatar: Optional[str]
    ) -> Track:
        title = ym_track.title or "Без названия"
        artists_str = ", ".join(a.name for a in (ym_track.artists or [])) or "Яндекс Музыка"
        duration = (ym_track.duration_ms or 0) // 1000
        cover_url = self._format_cover(ym_track.cover_uri)
        web_url = f"https://music.yandex.ru/album/{ym_track.albums[0].id if ym_track.albums else 0}/track/{ym_track.id}"

        async def stream_resolver() -> Optional[str]:
            return await self._resolve_direct_or_fallback(ym_track, title, artists_str)

        return Track(
            title=title,
            artist=artists_str,
            webpage_url=web_url,
            duration=duration,
            thumbnail=cover_url,
            source="yandex",
            requester=requester,
            requester_avatar=requester_avatar,
            _stream_resolver=stream_resolver,
        )

    async def extract(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        client = await self._get_client()
        query = query.strip()

        # 1. Поисковый запрос с префиксом (ym: или yandex:)
        if query.lower().startswith(("ym:", "yandex:")):
            clean_query = query.split(":", 1)[1].strip()
            search_res = await client.search(clean_query, type_="track")
            if search_res and search_res.tracks and search_res.tracks.results:
                top_track = search_res.tracks.results[0]
                # Получаем полную информацию о треке
                full_tracks = await client.tracks([top_track.id])
                if full_tracks:
                    track = self._convert_ym_track(full_tracks[0], requester, requester_avatar)
                    return ExtractionResult(
                        tracks=[track],
                        title=track.title,
                        is_playlist=False,
                        source_name="yandex",
                    )
            return ExtractionResult(tracks=[], is_playlist=False, source_name="yandex")

        # 2. Одиночный трек
        track_match = TRACK_REGEX.search(query)
        if track_match:
            track_id = track_match.group(2)
            full_tracks = await client.tracks([track_id])
            if full_tracks:
                track = self._convert_ym_track(full_tracks[0], requester, requester_avatar)
                return ExtractionResult(
                    tracks=[track],
                    title=track.title,
                    is_playlist=False,
                    source_name="yandex",
                )
            return ExtractionResult(tracks=[], is_playlist=False, source_name="yandex")

        # 3. Альбом
        album_match = ALBUM_REGEX.search(query)
        if album_match:
            album_id = int(album_match.group(1))
            album = await client.albums_with_tracks(album_id)
            if album and album.volumes:
                tracks: List[Track] = []
                for volume in album.volumes:
                    for t in volume:
                        tracks.append(self._convert_ym_track(t, requester, requester_avatar))
                album_title = f"Альбом: {album.title} ({album.artists[0].name if album.artists else ''})"
                return ExtractionResult(
                    tracks=tracks,
                    title=album_title,
                    is_playlist=True,
                    source_name="yandex_album",
                )
            return ExtractionResult(tracks=[], is_playlist=False, source_name="yandex")

        # 4. Пользовательский плейлист
        pl_match = PLAYLIST_USER_REGEX.search(query)
        if pl_match:
            user_id = pl_match.group(1)
            kind = int(pl_match.group(2))
            playlist = await client.users_playlists(kind, user_id)
            if playlist and playlist.tracks:
                track_ids = [t.track_id for t in playlist.tracks if hasattr(t, "track_id") and t.track_id]
                # Яндекс API позволяет запрашивать до 100 треков за раз
                tracks: List[Track] = []
                chunk_size = 50
                for i in range(0, min(len(track_ids), 200), chunk_size):
                    chunk = track_ids[i : i + chunk_size]
                    loaded = await client.tracks(chunk)
                    for t in loaded:
                        tracks.append(self._convert_ym_track(t, requester, requester_avatar))
                return ExtractionResult(
                    tracks=tracks,
                    title=f"Плейлист: {playlist.title}",
                    is_playlist=True,
                    source_name="yandex_playlist",
                )

        # 5. Чарты
        if CHART_REGEX.search(query):
            chart_info = await client.chart()
            if chart_info and chart_info.chart and chart_info.chart.tracks:
                tracks = []
                for chart_item in chart_info.chart.tracks[:50]:
                    if chart_item.track:
                        tracks.append(
                            self._convert_ym_track(chart_item.track, requester, requester_avatar)
                        )
                return ExtractionResult(
                    tracks=tracks,
                    title="Чарт Яндекс Музыки (Топ 50)",
                    is_playlist=True,
                    source_name="yandex_chart",
                )

        # 6. Исполнитель (топ треков)
        artist_match = ARTIST_REGEX.search(query)
        if artist_match:
            artist_id = int(artist_match.group(1))
            artist_tracks = await client.artists_tracks(artist_id)
            if artist_tracks and artist_tracks.tracks:
                tracks = [
                    self._convert_ym_track(t, requester, requester_avatar)
                    for t in artist_tracks.tracks[:50]
                ]
                return ExtractionResult(
                    tracks=tracks,
                    title="Топ треков артиста",
                    is_playlist=True,
                    source_name="yandex_artist",
                )

        return ExtractionResult(tracks=[], is_playlist=False, source_name="yandex")
