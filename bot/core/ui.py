import logging
import discord
from typing import List, Optional
from .queue import LoopMode
from ..extractors.base import Track

logger = logging.getLogger("sharmanka.core.ui")

SOURCE_COLORS = {
    "yandex": 0xFFCC00,       # Желтый (Яндекс)
    "yandex_album": 0xFFCC00,
    "yandex_playlist": 0xFFCC00,
    "yandex_chart": 0xFFCC00,
    "yandex_artist": 0xFFCC00,
    "spotify": 0x1DB954,      # Зеленый (Spotify)
    "spotify_album": 0x1DB954,
    "spotify_playlist": 0x1DB954,
    "youtube": 0xFF0000,      # Красный (YouTube)
    "youtube_playlist": 0xFF0000,
    "soundcloud": 0xFF5500,   # Оранжевый (SoundCloud)
    "bandcamp": 0x629AA9,
    "twitch": 0x9146FF,
    "applemusic": 0xFC3C44,   # Розово-красный (Apple Music)
    "applemusic_album": 0xFC3C44,
    "applemusic_playlist": 0xFC3C44,
}

SOURCE_ICONS = {
    "yandex": "🟡 Яндекс Музыка",
    "yandex_album": "🟡 Яндекс Музыка (Альбом)",
    "yandex_playlist": "🟡 Яндекс Музыка (Плейлист)",
    "yandex_chart": "🟡 Яндекс Музыка (Чарт)",
    "yandex_artist": "🟡 Яндекс Музыка (Артист)",
    "spotify": "🟢 Spotify",
    "spotify_album": "🟢 Spotify (Альбом)",
    "spotify_playlist": "🟢 Spotify (Плейлист)",
    "applemusic": "🍎 Apple Music",
    "applemusic_album": "🍎 Apple Music (Альбом)",
    "applemusic_playlist": "🍎 Apple Music (Плейлист)",
    "youtube": "🔴 YouTube",
    "youtube_playlist": "🔴 YouTube (Плейлист)",
    "soundcloud": "🟠 SoundCloud",
    "bandcamp": "🔵 Bandcamp",
    "twitch": "🟣 Twitch",
}


def create_now_playing_embed(track: Track, player) -> discord.Embed:
    color = SOURCE_COLORS.get(track.source, 0x5865F2)
    source_name = SOURCE_ICONS.get(track.source, "🎵 Музыка")

    embed = discord.Embed(
        title=track.display_name,
        url=track.webpage_url if track.webpage_url.startswith("http") else None,
        color=color,
    )
    
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

    embed.add_field(name="⏱ Длительность", value=track.formatted_duration, inline=True)
    embed.add_field(name="📻 Источник", value=source_name, inline=True)
    embed.add_field(name="👤 Заказал(а)", value=track.requester, inline=True)

    loop_status = player.queue.loop_mode.label
    queue_len = len(player.queue)
    embed.add_field(name="🔁 Повтор", value=loop_status, inline=True)
    embed.add_field(
        name="📜 В очереди",
        value=f"{queue_len} трек(ов)" if queue_len > 0 else "Пусто",
        inline=True,
    )
    embed.add_field(name="🔊 Громкость", value=f"{player.volume}%", inline=True)

    embed.set_footer(
        text="Шарманка • Управляйте кнопками ниже",
        icon_url=track.requester_avatar or None,
    )
    return embed


def create_track_added_embed(track: Track, position: int) -> discord.Embed:
    color = SOURCE_COLORS.get(track.source, 0x5865F2)
    source_name = SOURCE_ICONS.get(track.source, "🎵 Музыка")

    embed = discord.Embed(
        title="✅ Трек добавлен в очередь",
        description=f"**[{track.display_name}]({track.webpage_url})**" if track.webpage_url.startswith("http") else f"**{track.display_name}**",
        color=color,
    )
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

    embed.add_field(name="⏱ Длительность", value=track.formatted_duration, inline=True)
    embed.add_field(name="📻 Источник", value=source_name, inline=True)
    embed.add_field(name="📍 Позиция", value=f"#{position}", inline=True)
    embed.set_footer(text=f"Заказал: {track.requester}")
    return embed


def create_playlist_added_embed(
    title: str, count: int, total_duration: str, source: str, requester: str
) -> discord.Embed:
    color = SOURCE_COLORS.get(source, 0x5865F2)
    source_name = SOURCE_ICONS.get(source, "🎵 Музыка")

    embed = discord.Embed(
        title="✅ Плейлист добавлен в очередь",
        description=f"**{title}**\nДобавлено **{count}** треков.",
        color=color,
    )
    embed.add_field(name="⏱ Общее время", value=total_duration, inline=True)
    embed.add_field(name="📻 Сервис", value=source_name, inline=True)
    embed.set_footer(text=f"Заказал: {requester}")
    return embed


def create_queue_embed(player, page: int = 1, per_page: int = 10) -> discord.Embed:
    queue = player.queue
    total_tracks = len(queue)
    total_pages = max(1, (total_tracks + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    embed = discord.Embed(
        title=f"📜 Очередь сервера {player.guild.name}",
        color=0x5865F2,
    )

    if queue.current_track:
        embed.add_field(
            name="▶️ Сейчас играет",
            value=f"**[{queue.current_track.display_name}]({queue.current_track.webpage_url})** ({queue.current_track.formatted_duration}) | *{queue.current_track.requester}*",
            inline=False,
        )

    if total_tracks == 0:
        embed.description = "В очереди больше нет треков. Используйте `/play`, чтобы добавить музыку!"
    else:
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_tracks = queue.tracks[start_idx:end_idx]

        lines = []
        for i, track in enumerate(page_tracks, start=start_idx + 1):
            url_part = f"[{track.display_name}]({track.webpage_url})" if track.webpage_url.startswith("http") else track.display_name
            lines.append(f"`{i}.` **{url_part}** (`{track.formatted_duration}`) — *{track.requester}*")

        embed.description = "\n".join(lines)

    embed.set_footer(
        text=f"Страница {page}/{total_pages} • Всего треков: {total_tracks} • Общее время: {queue.formatted_total_duration} • Повтор: {queue.loop_mode.label}"
    )
    return embed


class PlayerControlView(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        # Обновление кнопки Пауза/Возобновить
        if self.player.voice_client and self.player.voice_client.is_paused():
            self.pause_resume_btn.emoji = "▶️"
            self.pause_resume_btn.style = discord.ButtonStyle.success
        else:
            self.pause_resume_btn.emoji = "⏸️"
            self.pause_resume_btn.style = discord.ButtonStyle.secondary

        # Обновление кнопки повтора
        loop_mode = self.player.queue.loop_mode
        if loop_mode == LoopMode.OFF:
            self.loop_btn.style = discord.ButtonStyle.secondary
            self.loop_btn.emoji = "🔁"
        elif loop_mode == LoopMode.TRACK:
            self.loop_btn.style = discord.ButtonStyle.primary
            self.loop_btn.emoji = "🔂"
        elif loop_mode == LoopMode.QUEUE:
            self.loop_btn.style = discord.ButtonStyle.success
            self.loop_btn.emoji = "🔁"

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="sharmanka:pause_resume", row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.voice_client or not self.player.voice_client.is_connected():
            return await interaction.response.send_message("Бот не в голосовом канале.", ephemeral=True)

        if self.player.voice_client.is_paused():
            self.player.voice_client.resume()
            await interaction.response.send_message("▶️ Воспроизведение возобновлено", ephemeral=True)
        elif self.player.voice_client.is_playing():
            self.player.voice_client.pause()
            await interaction.response.send_message("⏸️ Воспроизведение приостановлено", ephemeral=True)
        else:
            await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

        self._update_buttons()
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="sharmanka:skip", row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.voice_client or not (self.player.voice_client.is_playing() or self.player.voice_client.is_paused()):
            return await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

        await interaction.response.send_message("⏭️ Трек пропущен", ephemeral=True)
        self.player.skip()

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="sharmanka:loop", row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_mode = self.player.queue.loop_mode
        if current_mode == LoopMode.OFF:
            self.player.queue.loop_mode = LoopMode.TRACK
        elif current_mode == LoopMode.TRACK:
            self.player.queue.loop_mode = LoopMode.QUEUE
        else:
            self.player.queue.loop_mode = LoopMode.OFF

        self._update_buttons()
        await interaction.response.send_message(
            f"Режим повтора изменен на: **{self.player.queue.loop_mode.label}**", ephemeral=True
        )
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="sharmanka:shuffle", row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.queue.is_empty:
            return await interaction.response.send_message("Очередь пуста, нечего перемешивать!", ephemeral=True)

        self.player.queue.shuffle()
        await interaction.response.send_message("🔀 Очередь перемешана!", ephemeral=True)

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary, custom_id="sharmanka:queue", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = create_queue_embed(self.player, page=1)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="sharmanka:stop", row=1)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏹️ Воспроизведение остановлено, очередь очищена.", ephemeral=True)
        await self.player.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        custom_id = getattr(item, "custom_id", "unknown")
        logger.error(f"Ошибка при взаимодействии с кнопкой '{custom_id}': {error}", exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Не удалось выполнить действие. Попробуйте еще раз.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Не удалось выполнить действие. Попробуйте еще раз.", ephemeral=True)
        except Exception:
            pass
