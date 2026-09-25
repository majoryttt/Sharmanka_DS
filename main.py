import sys
import logging
import asyncio
import discord

from bot.config import config
from bot.client import SharmankaBot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("sharmanka.main")


def ensure_opus():
    """Проверяет и загружает кодек Opus для передачи звука в Discord."""
    if not discord.opus.is_loaded():
        candidates = [
            "libopus.so.0",
            "libopus.so",
            "opus",
            "libopus-0.x64.dll",
            "libopus-0.dll",
            "/usr/lib/libopus.so.0",
            "/usr/local/lib/libopus.dylib",
        ]
        for candidate in candidates:
            try:
                discord.opus.load_opus(candidate)
                if discord.opus.is_loaded():
                    logger.info(f"Кодек Opus успешно загружен из: {candidate}")
                    return
            except Exception:
                continue

        if not discord.opus.is_loaded():
            logger.warning("Библиотека libopus не была найдена автоматически. Голосовые каналы могут работать нестабильно.")
    else:
        logger.info("Кодек Opus уже загружен.")


def main():
    if not config or not config.discord_token:
        logger.error(
            "Не задан DISCORD_TOKEN! Пожалуйста, создайте файл .env на основе .env.example и укажите токен вашего бота."
        )
        sys.exit(1)

    ensure_opus()

    bot = SharmankaBot()

    try:
        bot.run(config.discord_token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы...")
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска бота: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
