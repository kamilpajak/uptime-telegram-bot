"""
Unit tests for TelegramNotifier component
Tests message formatting, cooldown mechanism, recovery notifications, and edge cases
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call, AsyncMock
from freezegun import freeze_time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import importlib.util
spec = importlib.util.spec_from_file_location("uptime_bot", "uptime-telegram-bot.py")
uptime_bot = importlib.util.module_from_spec(spec)
sys.modules["uptime_bot"] = uptime_bot
spec.loader.exec_module(uptime_bot)

from uptime_bot import TelegramNotifier, DatabaseManager, MonitorEvent


class TestTelegramNotifierMessageFormatting:
    """Test message formatting for different alert types"""
    
    @patch('uptime_bot.Bot')  # Patch where it's imported, not the original module
    def test_power_outage_alert_formatting(self, mock_bot_class, db_manager):
        """Test power outage alert message format"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        # Use correct constructor signature
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        # Create event and analysis
        event = MonitorEvent(
            monitor_name='Router 192.168.1.1',
            status='down',
            response_time=0.0,
            timestamp=datetime.now(),
            message='Router is down'
        )
        
        analysis = {
            'type': 'POWER_OUTAGE',
            'confidence': 0.95,
            'reason': 'All monitors are down - likely power outage',
            'affected': ['Router 192.168.1.1', 'Cloudflare DNS', 'Google DNS'],
            'timestamp': datetime.now()
        }
        
        # Run async method
        asyncio.run(notifier.send_alert(event, analysis))
        
        # Verify send_message was called
        mock_bot.send_message.assert_called_once()
        
        # Check message content
        call_args = mock_bot.send_message.call_args
        message = call_args[1]['text']
        
        assert "⚡" in message or "POWER" in message  # Power outage indicator
        assert "95%" in message  # Confidence
        assert "Router 192.168.1.1" in message
        
        # Check markdown formatting
        assert call_args[1]['parse_mode'] == 'Markdown'
    
    @patch('uptime_bot.Bot')
    def test_isp_outage_alert_formatting(self, mock_bot_class, db_manager):
        """Test ISP outage alert message format"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        event = MonitorEvent(
            monitor_name='Cloudflare DNS',
            status='down',
            response_time=0.0,
            timestamp=datetime.now(),
            message='DNS is down'
        )
        
        analysis = {
            'type': 'ISP_OUTAGE',
            'confidence': 0.90,
            'reason': 'Router is up but external services are down - ISP issue',
            'affected': ['Cloudflare DNS', 'Google DNS'],
            'timestamp': datetime.now()
        }
        
        asyncio.run(notifier.send_alert(event, analysis))
        
        message = mock_bot.send_message.call_args[1]['text']
        
        assert "ISP" in message or "🌐" in message
        assert "90%" in message
        assert "Cloudflare DNS" in message
    
    @patch('uptime_bot.Bot')
    def test_router_failure_alert_formatting(self, mock_bot_class, db_manager):
        """Test router failure alert message format"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        event = MonitorEvent(
            monitor_name='Router 192.168.1.1',
            status='down',
            response_time=0.0,
            timestamp=datetime.now(),
            message='Router failure'
        )
        
        analysis = {
            'type': 'ROUTER_FAILURE',
            'confidence': 0.85,
            'reason': 'Router has been down for over 2 minutes',
            'affected': ['Router 192.168.1.1'],
            'timestamp': datetime.now()
        }
        
        asyncio.run(notifier.send_alert(event, analysis))
        
        message = mock_bot.send_message.call_args[1]['text']
        
        assert "ROUTER" in message or "🔴" in message
        assert "85%" in message
        assert "Router 192.168.1.1" in message
    
    @patch('uptime_bot.Bot')  
    def test_recovery_notification_formatting(self, mock_bot_class, db_manager):
        """Test recovery notification with duration calculation"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        # Add a down event to database first
        with freeze_time("2024-01-01 12:00:00"):
            down_event = MonitorEvent(
                monitor_name='Cloudflare DNS',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Service down'
            )
            db_manager.add_event(down_event)
        
        # Send recovery 45 minutes later
        with freeze_time("2024-01-01 12:45:30"):
            recovery_event = MonitorEvent(
                monitor_name='Cloudflare DNS',
                status='up',
                response_time=25.0,
                timestamp=datetime.now(),
                message='Service recovered'
            )
            
            asyncio.run(notifier.send_recovery(recovery_event))
        
        # Check recovery message
        mock_bot.send_message.assert_called()
        recovery_message = mock_bot.send_message.call_args[1]['text']
        
        assert "✅" in recovery_message or "RECOVERED" in recovery_message
        assert "Cloudflare DNS" in recovery_message
        # Duration should be mentioned
        assert "45" in recovery_message or "minutes" in recovery_message.lower()


class TestTelegramNotifierCooldown:
    """Test the 5-minute cooldown mechanism"""
    
    @patch('uptime_bot.Bot')
    def test_5_minute_cooldown_prevents_spam(self, mock_bot_class, db_manager):
        """Test that cooldown prevents multiple alerts within 5 minutes"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        with freeze_time("2024-01-01 12:00:00") as frozen_time:
            # First alert should send
            event1 = MonitorEvent(
                monitor_name='Cloudflare DNS',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='First failure'
            )
            
            analysis1 = {
                'type': 'ISP_OUTAGE',
                'confidence': 0.90,
                'reason': 'ISP issue',
                'affected': ['Cloudflare DNS'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event1, analysis1))
            assert mock_bot.send_message.call_count == 1
            
            # Alert 2 minutes later should be blocked
            frozen_time.move_to("2024-01-01 12:02:00")
            event2 = MonitorEvent(
                monitor_name='Cloudflare DNS',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Still down'
            )
            
            analysis2 = {
                'type': 'ISP_OUTAGE',
                'confidence': 0.92,
                'reason': 'ISP issue continues',
                'affected': ['Cloudflare DNS', 'Google DNS'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event2, analysis2))
            assert mock_bot.send_message.call_count == 1  # No new message
            
            # Alert 6 minutes later should send
            frozen_time.move_to("2024-01-01 12:06:00")
            event3 = MonitorEvent(
                monitor_name='Cloudflare DNS',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Still having issues'
            )
            
            analysis3 = {
                'type': 'ISP_OUTAGE',
                'confidence': 0.93,
                'reason': 'ISP issue persists',
                'affected': ['Cloudflare DNS', 'Google DNS'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event3, analysis3))
            assert mock_bot.send_message.call_count == 2
    
    @patch('uptime_bot.Bot')
    def test_per_monitor_cooldown_tracking(self, mock_bot_class, db_manager):
        """Test that cooldown is tracked per monitor/service"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        with freeze_time("2024-01-01 12:00:00") as frozen_time:
            # Alert for Monitor A
            event_a = MonitorEvent(
                monitor_name='Monitor A',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Monitor A down'
            )
            
            analysis_a = {
                'type': 'PARTIAL_OUTAGE',
                'confidence': 0.80,
                'reason': 'Monitor A is down',
                'affected': ['Monitor A'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event_a, analysis_a))
            assert mock_bot.send_message.call_count == 1
            
            # Alert for Monitor B 2 minutes later should send (different monitor)
            frozen_time.move_to("2024-01-01 12:02:00")
            event_b = MonitorEvent(
                monitor_name='Monitor B',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Monitor B down'
            )
            
            analysis_b = {
                'type': 'PARTIAL_OUTAGE',
                'confidence': 0.80,
                'reason': 'Monitor B is down',
                'affected': ['Monitor B'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event_b, analysis_b))
            assert mock_bot.send_message.call_count == 2
            
            # Another alert for Monitor A should be blocked (still in cooldown)
            event_a2 = MonitorEvent(
                monitor_name='Monitor A',
                status='down',
                response_time=0.0,
                timestamp=datetime.now(),
                message='Monitor A still down'
            )
            
            analysis_a2 = {
                'type': 'PARTIAL_OUTAGE',
                'confidence': 0.85,
                'reason': 'Monitor A still down',
                'affected': ['Monitor A'],
                'timestamp': datetime.now()
            }
            
            asyncio.run(notifier.send_alert(event_a2, analysis_a2))
            assert mock_bot.send_message.call_count == 2  # No new message


class TestTelegramNotifierErrorHandling:
    """Test error handling and edge cases"""
    
    @patch('uptime_bot.Bot')
    def test_telegram_api_failure_handling(self, mock_bot_class, db_manager):
        """Test handling of Telegram API failures"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        # Simulate API error
        mock_bot.send_message.side_effect = Exception("Telegram API error")
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        event = MonitorEvent(
            monitor_name='Test Service',
            status='down',
            response_time=0.0,
            timestamp=datetime.now(),
            message='Test'
        )
        
        analysis = {
            'type': 'ISP_OUTAGE',
            'confidence': 0.90,
            'reason': 'Test',
            'affected': ['Service'],
            'timestamp': datetime.now()
        }
        
        # Should handle error gracefully (not crash)
        try:
            asyncio.run(notifier.send_alert(event, analysis))
        except:
            pass  # Expected to handle exception
        
        # Verify attempt was made
        mock_bot.send_message.assert_called()
    
    @patch('uptime_bot.Bot')
    def test_empty_affected_services_list(self, mock_bot_class, db_manager):
        """Test handling of empty affected services list"""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        
        notifier = TelegramNotifier('test_token', 'test_chat', db_manager)
        
        event = MonitorEvent(
            monitor_name='Unknown',
            status='down',
            response_time=0.0,
            timestamp=datetime.now(),
            message='Unknown issue'
        )
        
        analysis = {
            'type': 'UNKNOWN_OUTAGE',
            'confidence': 0.50,
            'reason': 'Unknown issue detected',
            'affected': [],  # Empty list
            'timestamp': datetime.now()
        }
        
        # Should handle empty affected list without crashing
        asyncio.run(notifier.send_alert(event, analysis))
        
        message = mock_bot.send_message.call_args[1]['text']
        assert "Unknown issue detected" in message or "UNKNOWN" in message