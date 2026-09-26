import asyncio
import logging
import time
from typing import Optional, List
import discord

from .queue import MusicQueue, LoopMode
from .ui import create_now_playing_embed, PlayerControlView
from ..extractors.base import Track
from ..config import config

logger = logging.getLogger("sharmanka.core.player")

# Оптимизированные параметры FFmpeg:
# - reconnect: автопереподключение при сетевых сбоях
# - rw_timeout 15000000: таймаут чтения 15 сек (предотвращает вечное зависание FFmpeg)
# - analyzeduration 0 / probesize 32k: мгновенный старт (~50 мс)
# - threads 2: ограничение нагрузки на CPU
FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-rw_timeout 15000000 "
        "-nostdin "
        "-analyzeduration 0 -probesize 32k"
    ),
    "options": "-vn -threads 2",
}


class PacedAudioSource(discord.PCMVolumeTransformer):
    """
    Обертка над AudioSource, устраняющая эффект ускоренного воспроизведения (fast-forward).
    Сброс тайминга после чтения первого пакета восстанавливает точную задержку 20мс на пакет.
    Также гарантирует корректное завершение процесса FFmpeg при вызове cleanup().
    """

    def __init__(self, original: discord.AudioSource, voice_client: discord.VoiceClient, volume: float = 1.0):
        super().__init__(original, volume=volume)
        self.voice_client = voice_client
        self._synced = False

    def read(self) -> bytes:
        ret = super().read()
        if not self._synced and ret:
            self._synced = True
            if hasattr(self.voice_client, "_player") and self.voice_client._player:
                p = self.voice_client._player
                p.loops = 0
                p._start = time.perf_counter()
        return ret

    def cleanup(self):
        super().cleanup()
        if hasattr(self.original, "cleanup"):
            try:
                self.original.cleanup()
            except Exception:
                pass


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

        guild_vc = self.guild.voice_client
        if guild_vc and guild_vc.is_connected():
            self.voice_client = guild_vc
            if self.voice_client.channel != voice_channel:
                await self.voice_client.move_to(voice_channel)
        else:
            if guild_vc:
                try:
                    await guild_vc.disconnect(force=True)
                except Exception:
                    pass
            self.voice_client = await voice_channel.connect(self_deaf=True, timeout=15.0, reconnect=True)

        self._cancel_idle_timer()
        if not self._loop_task or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._playback_loop())

    def enqueue(self, track: Track) -> int:
        """Добавляет трек в очередь. Запускает проигрывание, только если бот сейчас ничего не играет."""
        self.queue.add(track)
        position = len(self.queue)
        if self.voice_client and not (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.next_track_event.set()
        else:
            self._prefetch_next_track()
        return position

    def enqueue_multiple(self, tracks: List[Track]) -> int:
        """Добавляет список треков в очередь."""
        self.queue.add_multiple(tracks)
        count = len(tracks)
        if self.voice_client and not (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.next_track_event.set()
        else:
            self._prefetch_next_track()
        return count

    def _prefetch_next_track(self):
        """Предварительно загружает ссылку на аудиопоток следующего трека в фоне для бесшовного перехода."""
        if len(self.queue) > 0:
            next_t = self.queue.tracks[0]
            if not next_t.stream_url and next_t._stream_resolver:
                async def _task():
                    try:
                        await next_t.get_stream_url()
                        logger.debug(f"Предзагружен stream URL для: {next_t.display_name}")
                    except Exception:
                        pass
                asyncio.create_task(_task())

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

    async def _set_voice_status(self, text: Optional[str]):
        """Устанавливает или сбрасывает статус голосового канала (Voice Channel Status)."""
        if not self.voice_client or not self.voice_client.channel:
            return
        channel = self.voice_client.channel
        try:
            await self.bot.http.edit_voice_channel_status(text, channel_id=channel.id)
        except Exception as e:
            logger.debug(f"Не удалось обновить статус голосового канала {channel.id}: {e}")

    async def _playback_loop(self):
        await self.bot.wait_until_ready()

        while True:
            try:
                self.next_track_event.clear()
                self._cancel_idle_timer()

                track: Optional[Track] = self.queue.next()
                if not track:
                    # Очередь пуста — сбрасываем статус канала и запускаем таймер ожидания
                    await self._set_voice_status(None)
                    if self.now_playing_message:
                        try:
                            await self.now_playing_message.edit(view=None)
                        except Exception:
                            pass
                    self._start_idle_timer()
                    try:
                        await asyncio.wait_for(self.next_track_event.wait(), timeout=3600)
                        continue
                    except asyncio.TimeoutError:
                        continue

                # Если предыдущее воспроизведение еще физически не завершилось — ждем
                while self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                    await asyncio.sleep(0.1)

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
                    # Даем шанс автопереподключению
                    try:
                        await asyncio.sleep(2.0)
                    except asyncio.CancelledError:
                        break
                    if not self.is_connected:
                        logger.warning("Голосовое соединение разорвано перед стартом трека.")
                        break

                try:
                    raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                    volume_source = PacedAudioSource(raw_source, self.voice_client, volume=self.volume / 100.0)
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

                # Предварительно загружаем следующий трек в фоне для нулевой задержки перехода
                self._prefetch_next_track()

                # Обновляем или отправляем сообщение "Сейчас играет"
                await self._send_now_playing(track)

                # Ожидаем завершения воспроизведения текущего трека или skip
                await self.next_track_event.wait()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в цикле воспроизведения: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _send_now_playing(self, track: Track):
        if not self.text_channel:
            return

        embed = create_now_playing_embed(track, self)
        view = PlayerControlView(self)

        # 1. Отображение играющей песни в статусе голосового канала
        status_text = f"🎶 {track.display_name}"[:100]
        await self._set_voice_status(status_text)

        # 2. Редактирование существующего сообщения активного плеера без дублирования
        if self.now_playing_message:
            try:
                await self.now_playing_message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.now_playing_message = None
            except Exception as e:
                logger.debug(f"Не удалось обновить сообщение плеера на месте: {e}")
                self.now_playing_message = None

        # Если старого сообщения нет (или оно удалено), отправляем новое
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
        await self._set_voice_status(None)
        if self.now_playing_message:
            try:
                await self.now_playing_message.edit(view=None)
            except Exception:
                pass
            self.now_playing_message = None

        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        self.next_track_event.set()

    async def destroy(self):
        """Полная остановка и отключение от голосового канала."""
        await self.stop()
        self._cancel_idle_timer()
        await self._set_voice_status(None)
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None

        if self.voice_client:
            try:
                await self.voice_client.disconnect(force=True)
            except Exception:
                pass
            self.voice_client = None
