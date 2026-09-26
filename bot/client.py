import logging
import discord
from discord import app_commands
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
        # Глобальный обработчик ошибок слэш-команд
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            cmd_name = interaction.command.name if interaction.command else "unknown"
            logger.error(f"Ошибка выполнения слэш-команды '{cmd_name}': {error}", exc_info=error)

            error_message = "❌ Произошла непредвиденная ошибка при выполнении команды."
            if isinstance(error, app_commands.CommandOnCooldown):
                error_message = f"⏳ Команда на перезарядке. Попробуйте через {error.retry_after:.1f} сек."
            elif isinstance(error, app_commands.MissingPermissions):
                error_message = "❌ У вас недостаточно прав для выполнения этой команды."
            elif isinstance(error, app_commands.BotMissingPermissions):
                missing = ", ".join(error.missing_permissions)
                error_message = f"❌ У бота недостаточно прав: {missing}."
            elif isinstance(error, app_commands.CheckFailure):
                error_message = "❌ Вы не можете использовать эту команду здесь."

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(error_message, ephemeral=True)
                else:
                    await interaction.response.send_message(error_message, ephemeral=True)
            except Exception as send_err:
                logger.debug(f"Не удалось отправить сообщение об ошибке: {send_err}")

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
