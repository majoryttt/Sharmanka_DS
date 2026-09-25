import asyncio
import logging
from typing import Optional
import discord

from .queue import MusicQueue, LoopMode
from .ui import create_now_playing_embed, PlayerControlView
from ..extractors.base import Track
from ..config import config

logger = logging.getLogger("sharmanka.core.player")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class GuildPlayer:
    def __init__(self, bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = MusicQueue()
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel] = None
        self.now_playing_message: Optional[discord.Message] = None

        self.volume: int = config.default_volume if config else 100
        self.next_track_event = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_connected()

    async def connect(self, voice_channel: discord.VoiceChannel, text_channel: Optional[discord.TextChannel] = None):
        if text_channel:
            self.text_channel = text_channel

        if not self.is_connected:
            self.voice_client = await voice_channel.connect(self_deaf=True)
        elif self.voice_client.channel != voice_channel:
            await self.voice_client.move_to(voice_channel)

        self._cancel_idle_timer()
        if not self._loop_task or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._playback_loop())

    def _cancel_idle_timer(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    def _start_idle_timer(self):
        self._cancel_idle_timer()
        self._idle_task = asyncio.create_task(self._idle_countdown())

    async def _idle_countdown(self):
        idle_seconds = config.idle_timeout_seconds if config else 300
        try:
            await asyncio.sleep(idle_seconds)
            if self.is_connected and not (self.voice_client.is_playing() or self.voice_client.is_paused()):
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"💤 Бот отключился из-за отсутствия активности ({idle_seconds // 60} мин)."
                        )
                    except Exception:
                        pass
                await self.destroy()
        except asyncio.CancelledError:
            pass

    async def _playback_loop(self):
        await self.bot.wait_until_ready()

        while True:
            self.next_track_event.clear()
            self._cancel_idle_timer()

            track: Optional[Track] = self.queue.next()
            if not track:
                # Очередь пуста — запускаем таймер ожидания
                self._start_idle_timer()
                # Ждем появления нового трека или внешнего сигнала
                try:
                    await asyncio.wait_for(self.next_track_event.wait(), timeout=3600)
                    continue
                except asyncio.TimeoutError:
                    continue

            # Получаем свежий stream URL непосредственно перед стартом
            stream_url = await track.get_stream_url()
            if not stream_url:
                logger.error(f"Не удалось получить аудиопоток для трека '{track.display_name}'. Пропускаем.")
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"⚠️ Не удалось загрузить аудио для **{track.display_name}**. Переход к следующему треку."
                        )
                    except Exception:
                        pass
                continue

            if not self.is_connected:
                logger.warning("Голосовое соединение разорвано перед стартом трека.")
                break

            try:
                raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                volume_source = discord.PCMVolumeTransformer(raw_source, volume=self.volume / 100.0)
            except Exception as e:
                logger.error(f"Ошибка создания FFmpeg аудио источника: {e}")
                if self.text_channel:
                    try:
                        await self.text_channel.send(f"❌ Ошибка декодирования трека **{track.display_name}**.")
                    except Exception:
                        pass
                continue

            def after_playback(error):
                if error:
                    logger.error(f"Ошибка воспроизведения: {error}")
                self.bot.loop.call_soon_threadsafe(self.next_track_event.set)

            self.voice_client.play(volume_source, after=after_playback)

            # Отправляем сообщение "Сейчас играет"
            await self._send_now_playing(track)

            # Ожидаем завершения воспроизведения или вызова skip
            await self.next_track_event.wait()

            # Удаляем старое Now Playing сообщение по завершении трека при желании
            if self.now_playing_message:
                try:
                    # Убираем интерактивные кнопки после завершения
                    await self.now_playing_message.edit(view=None)
                except Exception:
                    pass

    async def _send_now_playing(self, track: Track):
        if not self.text_channel:
            return

        embed = create_now_playing_embed(track, self)
        view = PlayerControlView(self)

        try:
            self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.warning(f"Не удалось отправить embed 'Сейчас играет': {e}")

    def skip(self):
        """Пропускает текущий трек."""
        if self.is_connected and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        else:
            self.next_track_event.set()

    def set_volume(self, volume: int):
        self.volume = max(1, min(150, volume))
        if self.voice_client and self.voice_client.source:
            if isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
                self.voice_client.source.volume = self.volume / 100.0

    async def stop(self):
        """Останавливает воспроизведение, очищает очередь и сбрасывает плеер."""
        self.queue.clear()
        self.queue.loop_mode = LoopMode.OFF
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        self.next_track_event.set()

    async def destroy(self):
        """Полная остановка и отключение от голосового канала."""
        await self.stop()
        self._cancel_idle_timer()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None

        if self.voice_client:
            try:
                await self.voice_client.disconnect(force=True)
            except Exception:
                pass
            self.voice_client = None
