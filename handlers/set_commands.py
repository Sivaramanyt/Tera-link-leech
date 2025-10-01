# handlers/set_commands.py (Double-check that this is PRECISELY what's in your file)
    import logging
    from telegram import BotCommand

    logger = logging.getLogger(__name__)

    logger.info("DEBUG: handlers/set_commands.py is being loaded.") # This should appear in your logs!

    async def set_bot_commands(application):
        logger.info("DEBUG: set_bot_commands function is being executed.")
        commands = [
            BotCommand("start", "Help"),
            BotCommand("leech", "Leech terabox link"),
            BotCommand("verify", "Verify token for premium usage"),
        ]
        await application.bot.set_my_commands(commands)
        logger.info("DEBUG: Bot commands successfully set.")

    # This print will tell us if the function object is valid right after its definition
    logger.info(f"DEBUG: set_bot_commands object type after definition: {type(set_bot_commands)}") # This should appear!
