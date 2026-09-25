import discord
from discord import app_commands
from discord.ext import commands


class GeneralCog(commands.Cog, name="Основное"):
    """Общие команды информации и помощи."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Проверить задержку бота и Discord API")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Понг! Задержка шлюза: **{latency_ms} ms**")

    @app_commands.command(name="help", description="Показать справку по командам и поддерживаемым сервисам")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Справка бота «Шарманка»",
            description="Музыкальный бот для Discord с качественным звучанием и поддержкой всех ключевых музыкальных сервисов.",
            color=0x5865F2,
        )

        embed.add_field(
            name="📻 Поддерживаемые сервисы",
            value=(
                "• **🟡 Яндекс Музыка**: ссылки на треки, альбомы, плейлисты, чарт или поиск через `ym: запрос`.\n"
                "• **🔴 YouTube & Music**: ссылки на видео, плейлисты, Shorts, трансляции или обычный текст.\n"
                "• **🟢 Spotify**: треки, альбомы, плейлисты.\n"
                "• **🟠 SoundCloud**: треки и сеты.\n"
                "• **🌐 Прямые потоки**: MP3, OGG, FLAC, веб-радио (.m3u8, Icecast)."
            ),
            inline=False,
        )

        embed.add_field(
            name="🎶 Воспроизведение",
            value=(
                "`/play <запрос/ссылка>` — воспроизвести трек или плейлист.\n"
                "`/pause` / `/resume` — пауза и возобновление.\n"
                "`/skip` — пропустить текущий трек.\n"
                "`/skipto <номер>` — перейти к треку из очереди.\n"
                "`/stop` — остановить воспроизведение и отключить бота."
            ),
            inline=False,
        )

        embed.add_field(
            name="📜 Очередь и управление",
            value=(
                "`/queue [страница]` — просмотреть текущую очередь.\n"
                "`/nowplaying` — карточка текущего трека с интерактивными кнопками.\n"
                "`/loop <режим>` — повтор (выкл, один трек, вся очередь).\n"
                "`/shuffle` — перемешать очередь треков.\n"
                "`/volume <1-150>` — регулировка громкости.\n"
                "`/remove <номер>` — удалить конкретный трек.\n"
                "`/clear` — очистить очередь."
            ),
            inline=False,
        )

        embed.add_field(
            name="🎮 Интерактивные кнопки",
            value=(
                "Под сообщением `/nowplaying` доступны кнопки быстрого управления: "
                "`⏯ Пауза` • `⏭ Пропуск` • `🔁 Повтор` • `🔀 Перемешать` • `📜 Очередь` • `⏹ Стоп`."
            ),
            inline=False,
        )

        embed.set_footer(text="Шарманка • Приятного прослушивания!")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
