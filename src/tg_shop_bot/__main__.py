from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import Settings, load_settings
from .db import Database
from .handlers import build_root_router

log = logging.getLogger("tg_shop_bot")


async def _runner(settings: Settings) -> None:
    db = Database(settings.db_path)
    await db.init()
    settings.proofs_dir.mkdir(parents=True, exist_ok=True)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Inject dependencies into all handlers via Dispatcher workflow_data.
    dp["settings"] = settings
    dp["db"] = db

    dp.include_router(build_root_router())

    me = await bot.get_me()
    log.info("Starting polling as @%s (id=%s)", me.username, me.id)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    settings = load_settings()
    try:
        asyncio.run(_runner(settings))
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")


if __name__ == "__main__":
    main()
