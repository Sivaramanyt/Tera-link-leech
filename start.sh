# start.sh
set -e

# Start health endpoint in background
python3 scripts/health.py &

# Run bot
python3 bot.py
