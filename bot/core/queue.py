import random
from enum import Enum
from typing import List, Optional
from ..extractors.base import Track


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"

    @property
    def label(self) -> str:
        if self == LoopMode.OFF:
            return "Выключен"
        elif self == LoopMode.TRACK:
            return "Один трек 🔂"
        elif self == LoopMode.QUEUE:
            return "Вся очередь 🔁"
        return self.value


class MusicQueue:
    def __init__(self):
        self._tracks: List[Track] = []
        self.current_track: Optional[Track] = None
        self.history: List[Track] = []
        self.loop_mode: LoopMode = LoopMode.OFF

    def add(self, track: Track) -> None:
        self._tracks.append(track)

    def add_multiple(self, tracks: List[Track]) -> None:
        self._tracks.extend(tracks)

    def next(self) -> Optional[Track]:
        # Если режим повтора одного трека
        if self.loop_mode == LoopMode.TRACK and self.current_track:
            return self.current_track

        # Если режим повтора всей очереди
        if self.loop_mode == LoopMode.QUEUE and self.current_track:
            self._tracks.append(self.current_track)

        if self.current_track and self.loop_mode != LoopMode.TRACK:
            self.history.append(self.current_track)
            # Ограничиваем историю 50 треками
            if len(self.history) > 50:
                self.history.pop(0)

        if not self._tracks:
            self.current_track = None
            return None

        self.current_track = self._tracks.pop(0)
        return self.current_track

    def skip(self) -> Optional[Track]:
        """Принудительный пропуск текущего трека (игнорируя режим повтора одного трека)."""
        if self.current_track:
            if self.loop_mode == LoopMode.QUEUE:
                self._tracks.append(self.current_track)
            self.history.append(self.current_track)
            if len(self.history) > 50:
                self.history.pop(0)

        if not self._tracks:
            self.current_track = None
            return None

        self.current_track = self._tracks.pop(0)
        return self.current_track

    def skip_to(self, index: int) -> Optional[Track]:
        """Переходит сразу к треку под номером index (1-based)."""
        if 1 <= index <= len(self._tracks):
            # Удаляем предшествующие треки
            for _ in range(index - 1):
                skipped = self._tracks.pop(0)
                self.history.append(skipped)
            return self.skip()
        return None

    def shuffle(self) -> None:
        random.shuffle(self._tracks)

    def remove(self, index: int) -> Optional[Track]:
        """Удаляет трек из очереди по индексу (1-based)."""
        if 1 <= index <= len(self._tracks):
            return self._tracks.pop(index - 1)
        return None

    def clear(self) -> int:
        """Очищает ожидающие треки очереди. Возвращает количество удаленных треков."""
        count = len(self._tracks)
        self._tracks.clear()
        return count

    @property
    def is_empty(self) -> bool:
        return len(self._tracks) == 0

    @property
    def tracks(self) -> List[Track]:
        return list(self._tracks)

    def __len__(self) -> int:
        return len(self._tracks)

    @property
    def total_duration(self) -> int:
        return sum(t.duration for t in self._tracks)

    @property
    def formatted_total_duration(self) -> str:
        total = self.total_duration
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours > 0:
            return f"{hours} ч {minutes} мин"
        return f"{minutes} мин {seconds} сек"
