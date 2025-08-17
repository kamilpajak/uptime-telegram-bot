#!/usr/bin/env python3
"""
Uptime Kuma Telegram Bot - Advanced ISP vs Power Outage Analyzer
Receives webhooks from Uptime Kuma and provides intelligent analysis via Telegram
"""

import os
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Fix for Python 3.12 sqlite3 datetime deprecation
sqlite3.register_adapter(datetime, lambda val: val.isoformat())
sqlite3.register_converter("DATETIME", lambda val: datetime.fromisoformat(val.decode()))
from typing import Dict, List, Optional
from dataclasses import dataclass
from collections import defaultdict

from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get project directory
PROJECT_DIR = Path(__file__).parent

# Configuration from environment variables
CONFIG = {
    'TELEGRAM_BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN'),
    'TELEGRAM_CHAT_ID': os.getenv('TELEGRAM_CHAT_ID'),
    'WEBHOOK_PORT': int(os.getenv('WEBHOOK_PORT', '5000')),
    'DB_PATH': os.getenv('DB_PATH', str(PROJECT_DIR / 'uptime_monitor.db')),
    'ANALYSIS_WINDOW': int(os.getenv('ANALYSIS_WINDOW', '5')),
}

# Validate required configuration
if not CONFIG['TELEGRAM_BOT_TOKEN']:
    raise ValueError("TELEGRAM_BOT_TOKEN is required. Set it in .env file")
if not CONFIG['TELEGRAM_CHAT_ID']:
    raise ValueError("TELEGRAM_CHAT_ID is required. Set it in .env file")

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class MonitorEvent:
    """Represents a monitor status event"""
    monitor_name: str
    status: str
    timestamp: datetime
    message: str = ""
    response_time: float = 0.0

class DatabaseManager:
    """Handles all database operations"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_name TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                message TEXT,
                response_time REAL,
                analysis_type TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS outage_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outage_type TEXT NOT NULL,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                duration_minutes INTEGER,
                affected_monitors TEXT,
                confidence_score REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_event(self, event: MonitorEvent, analysis_type: str = None) -> int:
        """Add new event to database"""
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO events (monitor_name, status, timestamp, message, response_time, analysis_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (event.monitor_name, event.status, event.timestamp, 
              event.message, event.response_time, analysis_type))
        
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return event_id
    
    def get_recent_events(self, minutes: int = 5) -> List[Dict]:
        """Get events from last N minutes"""
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = conn.cursor()
        
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        cursor.execute('''
            SELECT monitor_name, status, timestamp, message, response_time
            FROM events
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        ''', (cutoff_time,))
        
        events = []
        for row in cursor.fetchall():
            events.append({
                'monitor_name': row[0],
                'status': row[1],
                'timestamp': row[2],
                'message': row[3],
                'response_time': row[4]
            })
        
        conn.close()
        return events
    
    def record_outage(self, outage_type: str, start_time: datetime, 
                      affected_monitors: List[str], confidence: float):
        """Record analyzed outage"""
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO outage_analysis 
            (outage_type, start_time, affected_monitors, confidence_score)
            VALUES (?, ?, ?, ?)
        ''', (outage_type, start_time, json.dumps(affected_monitors), confidence))
        
        conn.commit()
        conn.close()

class OutageAnalyzer:
    """Analyzes patterns to determine outage type"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def analyze_pattern(self, recent_events: List[Dict]) -> Dict:
        """Analyze events to determine outage type"""
        
        if not recent_events:
            return {'type': 'UNKNOWN', 'confidence': 0.0, 'reason': 'No recent events'}
        
        # Group events by monitor
        monitor_status = defaultdict(list)
        for event in recent_events:
            monitor_status[event['monitor_name']].append(event['status'])
        
        # Check status patterns
        router_down = self._is_monitor_down(monitor_status.get('Router 192.168.1.1', []))
        dns_monitors_down = sum(1 for name in monitor_status 
                                if 'DNS' in name and self._is_monitor_down(monitor_status[name]))
        external_sites_down = sum(1 for name in monitor_status 
                                  if name in ['Google', 'Cloudflare', 'Wikipedia'] 
                                  and self._is_monitor_down(monitor_status[name]))
        
        # Analyze pattern
        if router_down:
            if dns_monitors_down >= 2 or external_sites_down >= 2:
                return {
                    'type': 'POWER_OUTAGE',
                    'confidence': 0.95,
                    'reason': 'Router and external services are down',
                    'affected': list(monitor_status.keys())
                }
            else:
                return {
                    'type': 'ROUTER_FAILURE',
                    'confidence': 0.80,
                    'reason': 'Only router is down',
                    'affected': ['Router 192.168.1.1']
                }
        elif dns_monitors_down >= 2 or external_sites_down >= 2:
            return {
                'type': 'ISP_OUTAGE',
                'confidence': 0.90,
                'reason': 'Internet services down but router is up',
                'affected': [name for name in monitor_status 
                            if self._is_monitor_down(monitor_status[name])]
            }
        else:
            down_monitors = [name for name in monitor_status 
                            if self._is_monitor_down(monitor_status[name])]
            if down_monitors:
                return {
                    'type': 'PARTIAL_OUTAGE',
                    'confidence': 0.70,
                    'reason': f'Only specific services affected',
                    'affected': down_monitors
                }
            else:
                return {
                    'type': 'ALL_OPERATIONAL',
                    'confidence': 1.0,
                    'reason': 'All services operational',
                    'affected': []
                }
    
    def _is_monitor_down(self, statuses: List[str]) -> bool:
        """Check if monitor is considered down based on recent statuses"""
        if not statuses:
            return False
        # If last status is down or majority of recent statuses are down
        return statuses[0] == 'down' or statuses.count('down') > len(statuses) / 2

class TelegramNotifier:
    """Handles Telegram notifications"""
    
    def __init__(self, bot_token: str, chat_id: str, db_manager: DatabaseManager):
        self.bot = Bot(bot_token)
        self.chat_id = chat_id
        self.db = db_manager
        self.analyzer = OutageAnalyzer(db_manager)
        self.last_notification = {}
        self.notification_cooldown = 300  # 5 minutes cooldown for same type
    
    async def send_alert(self, event: MonitorEvent, analysis: Dict):
        """Send formatted alert to Telegram"""
        
        # Check cooldown
        alert_key = f"{analysis['type']}:{event.monitor_name}"
        now = datetime.now()
        if alert_key in self.last_notification:
            if (now - self.last_notification[alert_key]).seconds < self.notification_cooldown:
                return  # Skip notification due to cooldown
        
        # Format message based on analysis type
        if analysis['type'] == 'POWER_OUTAGE':
            icon = "🔌"
            title = "POWER OUTAGE DETECTED"
            severity = "CRITICAL"
        elif analysis['type'] == 'ISP_OUTAGE':
            icon = "🌐"
            title = "ISP OUTAGE DETECTED"
            severity = "HIGH"
        elif analysis['type'] == 'ROUTER_FAILURE':
            icon = "📡"
            title = "ROUTER FAILURE"
            severity = "HIGH"
        elif analysis['type'] == 'PARTIAL_OUTAGE':
            icon = "⚠️"
            title = "PARTIAL OUTAGE"
            severity = "MEDIUM"
        else:
            icon = "ℹ️"
            title = "SERVICE UPDATE"
            severity = "INFO"
        
        message = f"""
{icon} **{title}**
━━━━━━━━━━━━━━━━━━━━
📊 **Severity:** {severity}
🎯 **Confidence:** {analysis['confidence']*100:.0f}%
⏰ **Time:** {now.strftime('%Y-%m-%d %H:%M:%S')}

📝 **Analysis:**
{analysis['reason']}

🔍 **Affected Services:**
{self._format_affected_list(analysis.get('affected', []))}

💡 **Recommendation:**
{self._get_recommendation(analysis['type'])}
━━━━━━━━━━━━━━━━━━━━
"""
        
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode='Markdown'
        )
        
        # Update last notification time
        self.last_notification[alert_key] = now
    
    def _format_affected_list(self, affected: List[str]) -> str:
        """Format affected services list"""
        if not affected:
            return "• None"
        return "\n".join([f"• {service}" for service in affected[:5]])
    
    def _get_recommendation(self, outage_type: str) -> str:
        """Get recommendation based on outage type"""
        recommendations = {
            'POWER_OUTAGE': 'Check main power supply and circuit breakers. UPS recommended for critical infrastructure.',
            'ISP_OUTAGE': 'Contact ISP for service status. Consider backup internet connection.',
            'ROUTER_FAILURE': 'Restart router. Check cable connections and router logs.',
            'PARTIAL_OUTAGE': 'Monitor affected services. May be temporary or service-specific issue.',
            'ALL_OPERATIONAL': 'All systems operational. No action required.'
        }
        return recommendations.get(outage_type, 'Monitor situation and gather more data.')

# Flask webhook receiver
app = Flask(__name__)
CORS(app)

# Global instances
db_manager = None
telegram_notifier = None
telegram_app = None

@app.route('/webhook', methods=['POST'])
def receive_webhook():
    """Receive webhook from Uptime Kuma"""
    try:
        data = request.json
        
        # Parse webhook data
        event = MonitorEvent(
            monitor_name=data.get('monitorName', 'Unknown'),
            status=data.get('status', 'unknown'),
            timestamp=datetime.now(),
            message=data.get('msg', ''),
            response_time=data.get('ping', 0.0)
        )
        
        # Store event
        db_manager.add_event(event)
        
        # Analyze pattern
        recent_events = db_manager.get_recent_events(CONFIG['ANALYSIS_WINDOW'])
        analyzer = OutageAnalyzer(db_manager)
        analysis = analyzer.analyze_pattern(recent_events)
        
        # Send notification if needed
        if analysis['type'] != 'ALL_OPERATIONAL':
            asyncio.run(telegram_notifier.send_alert(event, analysis))
        
        return jsonify({'status': 'success', 'analysis': analysis}), 200
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Telegram bot commands
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    recent_events = db_manager.get_recent_events(10)
    analyzer = OutageAnalyzer(db_manager)
    analysis = analyzer.analyze_pattern(recent_events)
    
    status_text = f"""
📊 **CURRENT STATUS**
━━━━━━━━━━━━━━━━━━━━
🔍 **Analysis:** {analysis['type']}
🎯 **Confidence:** {analysis['confidence']*100:.0f}%
📝 **Details:** {analysis['reason']}

📈 **Recent Events:** {len(recent_events)}
⏰ **Analysis Window:** {CONFIG['ANALYSIS_WINDOW']} minutes
━━━━━━━━━━━━━━━━━━━━
"""
    
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report command - generate daily report"""
    conn = sqlite3.connect(CONFIG['DB_PATH'], detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    
    # Get last 24 hours statistics
    yesterday = datetime.now() - timedelta(days=1)
    cursor.execute('''
        SELECT 
            COUNT(*) as total_events,
            SUM(CASE WHEN status = 'down' THEN 1 ELSE 0 END) as down_events,
            AVG(response_time) as avg_response
        FROM events
        WHERE timestamp > ?
    ''', (yesterday,))
    
    stats = cursor.fetchone()
    
    # Get outage analysis
    cursor.execute('''
        SELECT outage_type, COUNT(*) as count, AVG(confidence_score) as avg_confidence
        FROM outage_analysis
        WHERE start_time > ?
        GROUP BY outage_type
    ''', (yesterday,))
    
    outages = cursor.fetchall()
    conn.close()
    
    report_text = f"""
📊 **24-HOUR REPORT**
━━━━━━━━━━━━━━━━━━━━
📅 **Period:** {yesterday.strftime('%Y-%m-%d %H:%M')} - Now

📈 **Statistics:**
• Total Events: {stats[0] or 0}
• Down Events: {stats[1] or 0}
• Uptime: {((stats[0]-stats[1])/stats[0]*100) if stats[0] and stats[0] > 0 else 100:.1f}%
• Avg Response: {(stats[2] or 0):.1f}ms

🔍 **Outage Analysis:**
"""
    
    for outage in outages:
        report_text += f"• {outage[0]}: {outage[1]} incidents (confidence: {outage[2]*100:.0f}%)\n"
    
    report_text += "━━━━━━━━━━━━━━━━━━━━"
    
    await update.message.reply_text(report_text, parse_mode='Markdown')

async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /uptime command - show current uptime percentages"""
    conn = sqlite3.connect(CONFIG['DB_PATH'], detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    
    # Calculate uptime for each monitor
    cursor.execute('''
        SELECT 
            monitor_name,
            COUNT(*) as total_checks,
            SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) as up_checks
        FROM events
        WHERE timestamp > datetime('now', '-7 days')
        GROUP BY monitor_name
    ''')
    
    monitors = cursor.fetchall()
    conn.close()
    
    uptime_text = """
⏱️ **7-DAY UPTIME**
━━━━━━━━━━━━━━━━━━━━
"""
    
    for monitor in monitors:
        uptime_pct = (monitor[2] / monitor[1] * 100) if monitor[1] > 0 else 0
        status_icon = "✅" if uptime_pct > 99 else "⚠️" if uptime_pct > 95 else "❌"
        uptime_text += f"{status_icon} **{monitor[0]}:** {uptime_pct:.2f}%\n"
    
    uptime_text += "━━━━━━━━━━━━━━━━━━━━"
    
    await update.message.reply_text(uptime_text, parse_mode='Markdown')

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🤖 **UPTIME MONITOR BOT**
━━━━━━━━━━━━━━━━━━━━

**Available Commands:**
• /status - Current system status
• /report - 24-hour detailed report
• /uptime - 7-day uptime percentages
• /help - Show this help message

**Alert Types:**
🔌 Power Outage - All services down
🌐 ISP Outage - Internet down, router up
📡 Router Failure - Only router affected
⚠️ Partial Outage - Some services affected

**Features:**
• Intelligent pattern analysis
• Automatic ISP vs Power detection
• 5-minute alert cooldown
• Historical data tracking
━━━━━━━━━━━━━━━━━━━━
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

def run_flask():
    """Run Flask webhook server in separate thread"""
    import nest_asyncio
    nest_asyncio.apply()
    app.run(host='0.0.0.0', port=CONFIG['WEBHOOK_PORT'], debug=False, use_reloader=False)

def run_telegram_bot():
    """Run Telegram bot in main thread"""
    global db_manager, telegram_notifier, telegram_app
    
    # Initialize database
    db_manager = DatabaseManager(CONFIG['DB_PATH'])
    
    # Initialize Telegram notifier
    telegram_notifier = TelegramNotifier(
        CONFIG['TELEGRAM_BOT_TOKEN'],
        CONFIG['TELEGRAM_CHAT_ID'],
        db_manager
    )
    
    # Initialize Telegram bot
    telegram_app = Application.builder().token(CONFIG['TELEGRAM_BOT_TOKEN']).build()
    
    # Add command handlers
    telegram_app.add_handler(CommandHandler("status", cmd_status))
    telegram_app.add_handler(CommandHandler("report", cmd_report))
    telegram_app.add_handler(CommandHandler("uptime", cmd_uptime))
    telegram_app.add_handler(CommandHandler("help", cmd_help))
    telegram_app.add_handler(CommandHandler("start", cmd_help))
    
    logger.info(f"🚀 Bot started! Webhook on port {CONFIG['WEBHOOK_PORT']}")
    logger.info("📱 Telegram bot ready for commands")
    
    # Start bot polling
    telegram_app.run_polling()

if __name__ == '__main__':
    # Start Flask in separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run Telegram bot in main thread
    run_telegram_bot()