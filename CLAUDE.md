# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the Bot
```bash
# Activate virtual environment and run bot
cd /path/to/uptime-telegram-bot
source venv/bin/activate
python3 uptime-telegram-bot.py
```

### Development Setup
```bash
# Install dependencies in virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Service Management
```bash
# Check service status
sudo systemctl status uptime-telegram-bot

# View logs
sudo journalctl -u uptime-telegram-bot -f

# Restart service after code changes
sudo systemctl restart uptime-telegram-bot
```

### Database Operations
```bash
# Access SQLite database
sqlite3 uptime_monitor.db

# Common queries
.tables  # List tables
.schema events  # Show events table structure
SELECT * FROM events ORDER BY timestamp DESC LIMIT 10;  # Recent events
```

### Testing (when implemented)
```bash
# Run all tests (future implementation)
pytest tests/

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test category
pytest tests/unit/  # Unit tests
pytest tests/integration/  # Integration tests
pytest tests/e2e/  # End-to-end tests
```

## Architecture

### Core Components

The bot is structured as a monolithic Python application with these main components:

1. **MonitorEvent** (Line 58): Data class representing Uptime Kuma webhook events
   - Handles status, response time, and timestamp data
   - Validates incoming webhook payloads

2. **DatabaseManager** (Line 66): SQLite persistence layer
   - Stores monitoring events in `events` table
   - Provides queries for uptime calculations, reports, and outage history
   - Handles automatic database initialization

3. **OutageAnalyzer** (Line 162): Core analysis engine
   - Determines outage types: POWER_OUTAGE, ISP_OUTAGE, ROUTER_FAILURE, PARTIAL_OUTAGE
   - Calculates confidence scores based on monitor patterns
   - Analyzes events within 5-minute windows
   - Router up + Internet down = ISP issue (90% confidence)
   - All down = Power issue (95% confidence)

4. **TelegramNotifier** (Line 236): Notification system
   - Sends formatted alerts to specified chat
   - Implements 5-minute cooldown to prevent spam
   - Tracks last notification times per monitor
   - Formats recovery notifications with downtime duration

5. **Flask Webhook Server** (Line 401): Receives Uptime Kuma webhooks
   - Runs on port 5000 (configurable via WEBHOOK_PORT)
   - Processes POST requests to `/webhook` endpoint
   - Validates and parses Uptime Kuma JSON payloads

6. **Telegram Bot Commands** (Lines 454-636):
   - `/status`: Current analysis and system state
   - `/report`: 24-hour detailed statistics
   - `/uptime`: 7-day uptime percentages
   - `/downtime`: Recent outages with durations
   - `/help`: Command documentation

### Threading Model

The application runs two concurrent threads:
- **Flask Thread**: Webhook server for receiving Uptime Kuma events
- **Telegram Thread**: Bot for handling commands and sending notifications

Both threads share:
- `DatabaseManager` instance for data persistence
- `OutageAnalyzer` for pattern analysis
- `TelegramNotifier` for alert management

### Data Flow

1. Uptime Kuma sends webhook to Flask server
2. Flask validates and creates MonitorEvent
3. Event stored in SQLite database
4. OutageAnalyzer examines recent events (5-min window)
5. If pattern detected, TelegramNotifier sends alert
6. Recovery notifications sent when services restore

### Configuration

Environment variables (in `.env` file):
- `TELEGRAM_BOT_TOKEN`: Bot authentication token
- `TELEGRAM_CHAT_ID`: Target chat for notifications
- `WEBHOOK_PORT`: Flask server port (default: 5000)
- `ANALYSIS_WINDOW`: Minutes to analyze for patterns (default: 5)

### Uptime Kuma Monitor Settings

**IMPORTANT**: All monitors must use the same polling interval to prevent false positives during router restarts.

Recommended settings:
- **Interval**: 30 seconds for all monitors (synchronized polling)
- **Heartbeat Interval**: 60 seconds
- **Retries**: 2 (before marking as down)
- **Retry Interval**: 20 seconds

To update all monitors to 30-second intervals:
```bash
./update_monitor_intervals.sh
```

### Database Schema

Single `events` table:
- `id`: Primary key
- `monitor_name`: Service identifier
- `status`: up/down state
- `response_time`: Latency in ms
- `timestamp`: Event time
- `message`: Uptime Kuma message

### Key Analysis Logic

The bot distinguishes outage types by monitor patterns:
- **Router Monitor**: Should be named with IP (e.g., "Router 192.168.1.1")
- **Internet Services**: External DNS/websites
- Pattern matching in `OutageAnalyzer.analyze_pattern()` determines issue type
- Confidence scores help prioritize likely causes

### Security Considerations

- Bot token and chat ID stored in environment variables
- Webhook binds to localhost by default
- No authentication on webhook endpoint (relies on network isolation)
- Database contains only monitoring data, no credentials

## Important Notes

- The bot expects at least 3 monitors: Router + 2 external services
- Router monitor name must contain IP address for proper detection
- 5-minute cooldown prevents notification spam during flapping
- Database auto-creates on first run in working directory
- Virtual environment required for dependency isolation
- Service file should be configured with correct installation path