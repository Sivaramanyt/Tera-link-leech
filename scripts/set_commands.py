# scripts/set_commands.py
import asyncio
import os
from telegram import BotCommand
from telegram.constants import BotCommandScopeDefault
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

async def main():
    bot = Bot(BOT_TOKEN)
    commands = [
        BotCommand("start", "Show help"),
        BotCommand("leech", "Leech a Terabox link"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    print("Commands set")

if __name__ == "__main__":
    asyncio.run(main())
