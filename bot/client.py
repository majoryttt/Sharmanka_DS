import logging
import discord
from discord.ext import commands

logger = logging.getLogger("sharmanka.client")


class SharmankaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",  # основной интерфейс через слэш-команды
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        # Загрузка расширений (cogs)
        initial_extensions = [
            "bot.cogs.general",
            "bot.cogs.music",
        ]

        for ext in initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Успешно загружен модуль: {ext}")
            except Exception as e:
                logger.error(f"Не удалось загрузить модуль {ext}: {e}", exc_info=True)

        # Синхронизация слэш-команд
        try:
            logger.info("Синхронизация слэш-команд с Discord API...")
            synced = await self.tree.sync()
            logger.info(f"Синхронизировано команд: {len(synced)}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации команд: {e}")

    async def on_ready(self):
        logger.info(f"Шарманка запущена и готова к работе! Авторизован как: {self.user} (ID: {self.user.id})")
        logger.info(f"Подключен к {len(self.guilds)} сервер(ам).")

        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="/play • Шарманка 📻",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)
