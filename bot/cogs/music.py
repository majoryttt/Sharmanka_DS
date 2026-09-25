import logging
from typing import Optional, Dict
import discord
from discord import app_commands
from discord.ext import commands

from ..core.player import GuildPlayer
from ..core.queue import LoopMode
from ..core.ui import (
    create_track_added_embed,
    create_playlist_added_embed,
    create_queue_embed,
    create_now_playing_embed,
    PlayerControlView,
)
from ..extractors.resolver import TrackResolver

logger = logging.getLogger("sharmanka.cogs.music")


class MusicCog(commands.Cog, name="Музыка"):
    """Основные музыкальные команды для воспроизведения и управления треками."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: Dict[int, GuildPlayer] = {}
        self.resolver = TrackResolver()

    def get_player(self, guild: discord.Guild) -> GuildPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildPlayer(self.bot, guild)
        return self.players[guild.id]

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        """Автоматическое отключение бота, если все пользователи вышли из голосового канала."""
        if member.id == self.bot.user.id:
            # Если самого бота отключили/кикнули из канала
            if before.channel and not after.channel:
                player = self.players.get(before.channel.guild.id)
                if player:
                    await player.destroy()
            return

        # Если пользователь вышел из канала, где находится бот
        guild = member.guild
        player = self.players.get(guild.id)
        if player and player.is_connected and player.voice_client.channel:
            bot_channel = player.voice_client.channel
            # Считаем не-ботов в канале
            non_bots = [m for m in bot_channel.members if not m.bot]
            if len(non_bots) == 0:
                logger.info(f"В канале {bot_channel.name} не осталось слушателей. Запуск таймера.")
                player._start_idle_timer()
            else:
                player._cancel_idle_timer()

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[GuildPlayer]:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(
                "❌ Для вызова этой команды вы должны находиться в голосовом канале!", ephemeral=True
            )
            return None

        voice_channel = interaction.user.voice.channel
        bot_member = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if bot_member:
            perms = voice_channel.permissions_for(bot_member)
            if not perms.connect:
                await interaction.followup.send(
                    f"❌ У бота нет прав для подключения к каналу **{voice_channel.name}** (`Connect`). Проверьте права роли бота!",
                    ephemeral=True,
                )
                return None
            if not perms.speak:
                await interaction.followup.send(
                    f"❌ У бота нет прав говорить в канале **{voice_channel.name}** (`Speak`). Проверьте права роли бота!",
                    ephemeral=True,
                )
                return None

        player = self.get_player(interaction.guild)

        try:
            if not player.is_connected:
                await player.connect(voice_channel, interaction.channel)
            elif player.voice_client.channel != voice_channel:
                listeners = [m for m in player.voice_client.channel.members if not m.bot]
                if len(listeners) == 0:
                    await player.connect(voice_channel, interaction.channel)
                else:
                    await interaction.followup.send(
                        f"❌ Бот уже используется в канале **{player.voice_client.channel.name}**!", ephemeral=True
                    )
                    return None
        except Exception as e:
            logger.error(f"Ошибка подключения к голосовому каналу {voice_channel.id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Не удалось подключиться к голосовому каналу (таймаут Discord Voice).**\n"
                "• Убедитесь, что у бота есть доступ к каналу.\n"
                "• Если бот работает в РФ, шлюз этого канала может блокироваться. Попробуйте в настройках канала (*Настройки канала -> Обзор -> Переопределение региона*) сменить регион на **Rotterdam** или **Frankfurt**.",
                ephemeral=True,
            )
            return None

        player.text_channel = interaction.channel
        return player

    @app_commands.command(name="play", description="Воспроизвести трек по названию или ссылке (Яндекс, YouTube, Spotify и др.)")
    @app_commands.describe(query="Ссылка (Яндекс Музыка, YouTube, Spotify, SoundCloud) или поисковый запрос")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)

        player = await self._ensure_voice(interaction)
        if not player:
            return

        requester_name = interaction.user.display_name
        requester_avatar = interaction.user.display_avatar.url if interaction.user.display_avatar else None

        result = await self.resolver.resolve(query, requester=requester_name, requester_avatar=requester_avatar)

        if not result.tracks:
            await interaction.followup.send(
                f"🔍 Ничего не удалось найти по запросу: `{query}`. Попробуйте уточнить название или передать прямую ссылку.",
                ephemeral=True,
            )
            return

        if result.is_playlist:
            player.enqueue_multiple(result.tracks)

            total_duration_str = player.queue.formatted_total_duration
            embed = create_playlist_added_embed(
                title=result.title or "Плейлист",
                count=len(result.tracks),
                total_duration=total_duration_str,
                source=result.source_name,
                requester=requester_name,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            track = result.tracks[0]
            is_currently_playing = bool(
                player.voice_client and (player.voice_client.is_playing() or player.voice_client.is_paused())
            )
            position = player.enqueue(track)

            if not is_currently_playing and position == 1:
                await interaction.followup.send(
                    f"🎶 Начинаем воспроизведение: **{track.display_name}**",
                    ephemeral=True,
                )
            else:
                embed = create_track_added_embed(track, position=position)
                await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="pause", description="Приостановить воспроизведение")
    async def pause(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_connected or not player.voice_client.is_playing():
            return await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

        player.voice_client.pause()
        await interaction.response.send_message("⏸️ Воспроизведение приостановлено.")

    @app_commands.command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_connected or not player.voice_client.is_paused():
            return await interaction.response.send_message("Плеер не находится на паузе.", ephemeral=True)

        player.voice_client.resume()
        await interaction.response.send_message("▶️ Воспроизведение возобновлено.")

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    async def skip(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_connected or not (player.voice_client.is_playing() or player.voice_client.is_paused()):
            return await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

        current = player.queue.current_track
        name = current.display_name if current else "Текущий трек"
        player.skip()
        await interaction.response.send_message(f"⏭️ Пропущен: **{name}**")

    @app_commands.command(name="skipto", description="Перейти сразу к треку под указанным номером в очереди")
    @app_commands.describe(position="Номер трека в очереди (/queue)")
    async def skipto(self, interaction: discord.Interaction, position: int):
        player = self.get_player(interaction.guild)
        if position < 1 or position > len(player.queue):
            return await interaction.response.send_message(
                f"Некорректная позиция. В очереди всего {len(player.queue)} трек(ов).", ephemeral=True
            )

        target_track = player.queue.tracks[position - 1]
        player.queue.skip_to(position)
        player.skip()
        await interaction.response.send_message(f"⏭️ Переход к треку #{position}: **{target_track.display_name}**")

    @app_commands.command(name="stop", description="Остановить музыку, очистить очередь и отключить бота")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_connected:
            return await interaction.response.send_message("Бот не находится в голосовом канале.", ephemeral=True)

        await player.destroy()
        await interaction.response.send_message("⏹️ Музыка остановлена, бот покинул голосовой канал.")

    @app_commands.command(name="queue", description="Показать текущую очередь воспроизведения")
    @app_commands.describe(page="Номер страницы (по умолчанию 1)")
    async def queue(self, interaction: discord.Interaction, page: Optional[int] = 1):
        player = self.get_player(interaction.guild)
        embed = create_queue_embed(player, page=page or 1)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Показать карточку текущего трека с кнопками управления")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_connected or not player.queue.current_track:
            return await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

        embed = create_now_playing_embed(player.queue.current_track, player)
        view = PlayerControlView(player)

        # Удаляем предыдущее сообщение, чтобы в канале всегда был ровно один активный плеер
        if player.now_playing_message:
            try:
                await player.now_playing_message.delete()
            except Exception:
                pass

        player.text_channel = interaction.channel
        await interaction.response.send_message(embed=embed, view=view)
        player.now_playing_message = await interaction.original_response()

    @app_commands.command(name="volume", description="Настроить громкость воспроизведения (1-150%)")
    @app_commands.describe(level="Уровень громкости в процентах от 1 до 150")
    async def volume(self, interaction: discord.Interaction, level: int):
        if level < 1 or level > 150:
            return await interaction.response.send_message("Громкость должна быть в диапазоне от 1 до 150%.", ephemeral=True)

        player = self.get_player(interaction.guild)
        player.set_volume(level)
        await interaction.response.send_message(f"🔊 Громкость установлена на **{level}%**.")

    @app_commands.command(name="shuffle", description="Перемешать треки в очереди")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if player.queue.is_empty:
            return await interaction.response.send_message("Очередь пуста, нечего перемешивать!", ephemeral=True)

        player.queue.shuffle()
        await interaction.response.send_message("🔀 Очередь успешно перемешана!")

    @app_commands.command(name="loop", description="Переключить режим повтора")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Выключен", value="off"),
            app_commands.Choice(name="Один трек", value="track"),
            app_commands.Choice(name="Вся очередь", value="queue"),
        ]
    )
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = self.get_player(interaction.guild)
        player.queue.loop_mode = LoopMode(mode.value)
        await interaction.response.send_message(f"🔁 Режим повтора установлен: **{player.queue.loop_mode.label}**")

    @app_commands.command(name="remove", description="Удалить трек из очереди по номеру")
    @app_commands.describe(position="Номер трека в очереди (/queue)")
    async def remove(self, interaction: discord.Interaction, position: int):
        player = self.get_player(interaction.guild)
        removed = player.queue.remove(position)
        if not removed:
            return await interaction.response.send_message(
                f"Трек под номером #{position} не найден в очереди.", ephemeral=True
            )

        await interaction.response.send_message(f"🗑️ Трек **{removed.display_name}** удален из очереди.")

    @app_commands.command(name="clear", description="Очистить все треки из очереди")
    async def clear(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        count = player.queue.clear()
        await interaction.response.send_message(f"🧹 Очередь очищена! Удалено треков: **{count}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
