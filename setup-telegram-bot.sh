#!/bin/bash
# Setup script for Uptime Telegram Bot

echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

echo "🔧 Setting up configuration..."
echo "Please edit uptime-telegram-bot.py and add:"
echo "  1. Your Telegram Bot Token (from @BotFather)"
echo "  2. Your Telegram Chat ID"
echo ""
echo "To get your Chat ID:"
echo "  1. Send a message to your bot"
echo "  2. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
echo "  3. Find 'chat':{'id':YOUR_CHAT_ID}"
echo ""

echo "📝 Configure Uptime Kuma webhook:"
echo "  1. Go to Uptime Kuma Settings → Notifications"
echo "  2. Add new Webhook notification"
echo "  3. URL: http://localhost:5000/webhook"
echo "  4. Method: POST"
echo "  5. Content Type: application/json"
echo ""

echo "🚀 To start the bot:"
echo "  python3 uptime-telegram-bot.py"
echo ""
echo "🔧 To install as service:"
echo "  sudo cp uptime-telegram-bot.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable uptime-telegram-bot"
echo "  sudo systemctl start uptime-telegram-bot"
echo ""
echo "📊 Bot commands:"
echo "  /status - Current system status"
echo "  /report - 24-hour report"
echo "  /uptime - 7-day uptime stats"
echo "  /help   - Show help"