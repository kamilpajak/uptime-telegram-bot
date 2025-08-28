"""
Shared pytest fixtures and configuration for all tests
"""
import pytest
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the main application components
import importlib.util
spec = importlib.util.spec_from_file_location("uptime_bot", "uptime-telegram-bot.py")
uptime_bot = importlib.util.module_from_spec(spec)
sys.modules["uptime_bot"] = uptime_bot
spec.loader.exec_module(uptime_bot)

from uptime_bot import DatabaseManager, OutageAnalyzer, MonitorEvent, TelegramNotifier


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def db_manager(temp_db):
    """Create a DatabaseManager instance with temporary database"""
    return DatabaseManager(temp_db)


@pytest.fixture
def analyzer(db_manager):
    """Create an OutageAnalyzer instance"""
    return OutageAnalyzer(db_manager)


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot to prevent actual messages"""
    with patch('uptime_bot.Bot') as mock_bot:
        mock_instance = MagicMock()
        mock_bot.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def notifier(db_manager, mock_telegram_bot):
    """Create a TelegramNotifier with mocked bot"""
    with patch.dict(os.environ, {
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'TELEGRAM_CHAT_ID': 'test_chat'
    }):
        return TelegramNotifier(db_manager, mock_telegram_bot)


@pytest.fixture
def flask_app():
    """Create Flask test client"""
    with patch.dict(os.environ, {
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'TELEGRAM_CHAT_ID': 'test_chat',
        'DB_PATH': ':memory:'
    }):
        from uptime_bot import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def sample_events():
    """Factory for creating sample monitor events"""
    def create_event(monitor_name, status, timestamp=None, response_time=20.0):
        if timestamp is None:
            timestamp = datetime.now()
        return MonitorEvent(
            monitor_name=monitor_name,
            status=status,
            timestamp=timestamp,
            response_time=response_time,
            message=f"{monitor_name} is {status}"
        )
    return create_event


@pytest.fixture
def webhook_payload_factory():
    """Factory for creating Uptime Kuma webhook payloads"""
    def create_payload(monitor_name="Test Monitor", status="down", 
                      timestamp=None, response_time=50.0):
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        status_code = 0 if status == "down" else 1
        
        return {
            "heartbeat": {
                "status": status_code,
                "time": timestamp,
                "ping": response_time,
                "msg": f"{monitor_name} is {status}"
            },
            "monitor": {
                "name": monitor_name,
                "type": "ping" if "192.168" in monitor_name else "http"
            },
            "msg": f"[{monitor_name}] is {status}"
        }
    return create_payload


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables for each test"""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_telegram_send():
    """Mock the telegram send_message method"""
    with patch('telegram.Bot.send_message') as mock_send:
        mock_send.return_value = MagicMock(message_id=123)
        yield mock_send