import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.handlers import setup_routers


RECONNECT_DELAY_SECONDS = 15


async def main() -> None:
    config = load_config()
    dp = Dispatcher(storage=MemoryStorage(), config=config)
    dp.include_router(setup_routers())

    while True:
        bot = Bot(token=config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        try:
            await dp.start_polling(bot)
        except TelegramNetworkError as error:
            logging.warning(
                "Telegram network error: %s. Reconnecting in %s seconds...",
                error,
                RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        finally:
            await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
