
from telegram import BotCommand

async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Help"),
        BotCommand("leech", "Leech terabox link"),
        BotCommand("verify", "Verify token for premium usage"),
    ]
    await application.bot.set_my_commands(commands)

