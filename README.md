# Uptime Telegram Bot

Advanced monitoring bot that analyzes Uptime Kuma alerts to distinguish between ISP outages and power failures.

## Features

- **Intelligent Pattern Analysis**
  - 🔌 Power outage detection (router + internet down)
  - 🌐 ISP outage detection (internet down, router up)
  - 📡 Router failure detection (only router affected)
  - ⚠️ Partial outage detection (specific services)

- **Smart Notifications**
  - 5-minute cooldown to prevent spam
  - Confidence scoring for analysis accuracy
  - Specific recommendations for each issue type

- **Telegram Commands**
  - `/status` - Current system status and analysis
  - `/report` - 24-hour detailed report
  - `/uptime` - 7-day uptime percentages
  - `/help` - Show available commands

- **Data Persistence**
  - SQLite database for historical analysis
  - Event tracking and pattern learning
  - Outage history with confidence scores

## Prerequisites

- Python 3.12+
- Uptime Kuma instance running
- Telegram Bot Token (from @BotFather)
- Network setup with local router monitoring
- python3-venv package (install with: `sudo apt install python3.12-venv`)

## Installation

### 1. Clone or Copy Project

```bash
cd /home/jacoren/projects/uptime-telegram-bot
```

### 2. Setup Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Bot

Copy the example environment file and edit it:

```bash
cp .env.example .env
nano .env  # or use your preferred editor
```

Update the values in `.env`:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE  # From @BotFather
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE      # Your Telegram user ID

# Webhook Configuration
WEBHOOK_PORT=5000

# Analysis Settings
ANALYSIS_WINDOW=5
```

### 4. Get Telegram Credentials

#### Bot Token:
1. Message @BotFather on Telegram
2. Send `/newbot`
3. Choose a name and username
4. Copy the token

#### Chat ID:
1. Message your new bot
2. Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id":YOUR_CHAT_ID}`

## Usage

### Manual Run

```bash
cd /home/jacoren/projects/uptime-telegram-bot
source venv/bin/activate
python3 uptime-telegram-bot.py
```

### Run as System Service

```bash
# Copy service file
sudo cp uptime-telegram-bot.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable uptime-telegram-bot
sudo systemctl start uptime-telegram-bot

# Check status
sudo systemctl status uptime-telegram-bot
```

### Configure Uptime Kuma

1. Open Uptime Kuma web interface
2. Go to **Settings** → **Notifications**
3. Add new **Webhook** notification:
   - **URL**: `http://localhost:5000/webhook`
   - **Method**: POST
   - **Content Type**: application/json
4. Assign notification to your monitors

## How It Works

### Analysis Logic

The bot analyzes patterns to determine outage types:

| Router Status | Internet Status | Analysis Result |
|--------------|-----------------|-----------------|
| ✅ UP | ❌ DOWN | ISP Outage (90% confidence) |
| ❌ DOWN | ❌ DOWN | Power Outage (95% confidence) |
| ❌ DOWN | ✅ UP | Router Failure (80% confidence) |
| ✅ UP | ✅ UP | All Operational |

### Alert Format

```
🌐 ISP OUTAGE DETECTED
━━━━━━━━━━━━━━━━━━━━
📊 Severity: HIGH
🎯 Confidence: 90%
⏰ Time: 2025-08-17 14:23:45

📝 Analysis:
Internet services down but router is up

🔍 Affected Services:
• Google DNS
• Cloudflare DNS
• External websites

💡 Recommendation:
Contact ISP for service status.
```

## File Structure

```
uptime-telegram-bot/
├── uptime-telegram-bot.py    # Main bot application
├── requirements.txt           # Python dependencies
├── venv/                     # Virtual environment
├── uptime_monitor.db         # SQLite database (created on first run)
├── uptime-telegram-bot.service # Systemd service file
├── setup-telegram-bot.sh     # Setup helper script
└── README.md                 # This file
```

## Monitoring Best Practices

1. **Monitor your router** (192.168.1.1) with 30-second intervals
2. **Monitor external services** with 60-120 second intervals
3. **Include multiple DNS servers** for redundancy
4. **Set up both internal and external monitors**

## Troubleshooting

### Bot not responding to commands
- Check bot token is correct
- Verify bot is running: `systemctl status uptime-telegram-bot`
- Check logs: `journalctl -u uptime-telegram-bot -f`

### Not receiving alerts
- Verify webhook URL in Uptime Kuma
- Check notification is assigned to monitors
- Ensure Chat ID is correct

### Database issues
- Database is created automatically on first run
- To reset: delete `uptime_monitor.db` and restart
- Location: `/home/jacoren/projects/uptime-telegram-bot/uptime_monitor.db`

## Security Notes

- Keep your bot token secret - never commit `.env` file to git
- The `.env` file is gitignored by default
- Use local webhook (localhost) to prevent external access
- Database contains monitoring history only, no sensitive data

## Dependencies

- `python-telegram-bot` - Telegram Bot API
- `flask` - Webhook server
- `flask-cors` - CORS support
- `nest-asyncio` - Async event loop compatibility
- `python-dotenv` - Environment variable management

## License

MIT

## Support

For issues or questions, check:
- Uptime Kuma logs
- Bot logs: `journalctl -u uptime-telegram-bot -f`
- Database: `sqlite3 uptime_monitor.db`