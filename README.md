<!-- README.md -->
# Terabox Leech Telegram Bot

Single-command bot to leech Terabox share links and upload to Telegram.

## Commands
- /start — Help
- /leech <terabox_link> — Resolve and send the file

## Deploy (Koyeb)
1) Create a new Koyeb app from Dockerfile.
2) Set environment variables from config/.env.example.
3) Expose port 8080 for health. Start command: `bash start.sh`.

## Notes
- Files over Telegram’s limit are not uploaded; a message is shown.
- Only Terabox links are supported; other sources removed.

## Dev
- Python 3.11
- `pip install -r requirements.txt`
- `python scripts/set_commands.py`
- `python bot.py`
- 
