from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Callable, Awaitable, Any


@dataclass
class Track:
    title: str
    artist: str
    webpage_url: str
    duration: int  # в секундах (0 если неизвестно / live stream)
    thumbnail: Optional[str] = None
    source: str = "unknown"  # "yandex", "youtube", "soundcloud", "spotify", etc.
    requester: str = "Пользователь"
    requester_avatar: Optional[str] = None
    stream_url: Optional[str] = None
    
    # Ленивый резолвер для получения свежего stream_url непосредственно перед воспроизведением
    _stream_resolver: Optional[Callable[[], Awaitable[Optional[str]]]] = None

    @property
    def formatted_duration(self) -> str:
        if self.duration <= 0:
            return "🔴 Прямой эфир"
        hours = self.duration // 3600
        minutes = (self.duration % 3600) // 60
        seconds = self.duration % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def display_name(self) -> str:
        if self.artist and self.artist.lower() not in self.title.lower():
            return f"{self.artist} — {self.title}"
        return self.title

    async def get_stream_url(self) -> Optional[str]:
        if self._stream_resolver:
            try:
                resolved = await self._stream_resolver()
                if resolved:
                    self.stream_url = resolved
                    return self.stream_url
            except Exception:
                pass
        return self.stream_url


@dataclass
class ExtractionResult:
    tracks: List[Track]
    title: Optional[str] = None
    is_playlist: bool = False
    source_name: str = "unknown"


class BaseExtractor(ABC):
    @abstractmethod
    def can_handle(self, query: str) -> bool:
        """Проверяет, подходит ли ссылка или запрос для этого экстрактора."""
        pass

    @abstractmethod
    async def extract(
        self, query: str, requester: str, requester_avatar: Optional[str] = None
    ) -> ExtractionResult:
        """Извлекает трек или список треков (плейлист, альбом) из запроса."""
        pass
