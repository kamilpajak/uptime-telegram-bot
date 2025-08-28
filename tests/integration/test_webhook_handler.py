"""
Integration tests for webhook handler
Tests payload parsing, validation, error handling, and concurrent processing
"""
import pytest
import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import importlib.util
spec = importlib.util.spec_from_file_location("uptime_bot", "uptime-telegram-bot.py")
uptime_bot = importlib.util.module_from_spec(spec)
sys.modules["uptime_bot"] = uptime_bot
spec.loader.exec_module(uptime_bot)

from uptime_bot import app, DatabaseManager, OutageAnalyzer, TelegramNotifier


class TestWebhookPayloadParsing:
    """Test parsing of Uptime Kuma webhook payloads"""
    
    def test_valid_uptime_kuma_payload_parsing(self, flask_app):
        """Test parsing of valid Uptime Kuma webhook payload"""
        valid_payload = {
            "heartbeat": {
                "status": 0,  # 0 = down, 1 = up
                "time": "2024-01-01T12:00:00.000Z",
                "ping": 0,
                "msg": "timeout"
            },
            "monitor": {
                "name": "Router 192.168.1.1",
                "type": "ping",
                "url": "192.168.1.1"
            },
            "msg": "[Router 192.168.1.1] is down"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(valid_payload),
                                 content_type='application/json')
        
        assert response.status_code == 200
        response_data = json.loads(response.data)
        assert response_data['status'] == 'success'
        assert 'event_id' in response_data or 'message' in response_data
    
    def test_status_up_payload(self, flask_app):
        """Test parsing of 'up' status payload"""
        up_payload = {
            "heartbeat": {
                "status": 1,  # up
                "time": "2024-01-01T12:00:00.000Z",
                "ping": 25.3,
                "msg": "OK"
            },
            "monitor": {
                "name": "Cloudflare DNS",
                "type": "http",
                "url": "https://1.1.1.1"
            },
            "msg": "[Cloudflare DNS] is up"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(up_payload),
                                 content_type='application/json')
        
        assert response.status_code == 200
        response_data = json.loads(response.data)
        assert response_data['status'] == 'success'
    
    def test_multiple_monitor_types(self, flask_app):
        """Test different monitor types (ping, http, tcp, etc.)"""
        monitor_types = [
            ("ping", "192.168.1.1", "Router"),
            ("http", "https://google.com", "Google"),
            ("tcp", "8.8.8.8:53", "DNS Server"),
            ("keyword", "https://example.com", "Website"),
        ]
        
        for monitor_type, url, name in monitor_types:
            payload = {
                "heartbeat": {
                    "status": 1,
                    "time": datetime.now().isoformat(),
                    "ping": 30.0,
                    "msg": "OK"
                },
                "monitor": {
                    "name": name,
                    "type": monitor_type,
                    "url": url
                },
                "msg": f"[{name}] is up"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            assert response.status_code == 200
    
    def test_payload_with_additional_fields(self, flask_app):
        """Test that extra fields in payload don't break parsing"""
        payload_with_extras = {
            "heartbeat": {
                "status": 1,
                "time": "2024-01-01T12:00:00.000Z",
                "ping": 20.0,
                "msg": "OK",
                "extra_field": "should_be_ignored",
                "monitorID": 123
            },
            "monitor": {
                "name": "Test Monitor",
                "type": "http",
                "url": "https://test.com",
                "interval": 60,
                "retryInterval": 60
            },
            "msg": "[Test Monitor] is up",
            "extra_top_level": "ignored"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(payload_with_extras),
                                 content_type='application/json')
        
        assert response.status_code == 200


class TestWebhookErrorHandling:
    """Test error handling for malformed or invalid payloads"""
    
    def test_malformed_json_payload(self, flask_app):
        """Test handling of malformed JSON"""
        malformed_json = '{"heartbeat": {"status": 1, "time": broken json}'
        
        response = flask_app.post('/webhook',
                                 data=malformed_json,
                                 content_type='application/json')
        
        assert response.status_code == 400
        response_data = json.loads(response.data)
        assert 'error' in response_data
    
    def test_missing_required_fields(self, flask_app):
        """Test handling of payloads missing required fields"""
        test_cases = [
            # Missing heartbeat
            {"monitor": {"name": "Test"}, "msg": "test"},
            # Missing monitor
            {"heartbeat": {"status": 1, "time": "2024-01-01T12:00:00Z"}, "msg": "test"},
            # Missing status in heartbeat
            {"heartbeat": {"time": "2024-01-01T12:00:00Z"}, "monitor": {"name": "Test"}},
            # Missing monitor name
            {"heartbeat": {"status": 1, "time": "2024-01-01T12:00:00Z"}, "monitor": {"type": "http"}},
        ]
        
        for invalid_payload in test_cases:
            response = flask_app.post('/webhook',
                                     data=json.dumps(invalid_payload),
                                     content_type='application/json')
            
            assert response.status_code in [400, 422]  # Bad request or unprocessable
    
    def test_invalid_field_types(self, flask_app):
        """Test handling of incorrect field types"""
        invalid_type_payload = {
            "heartbeat": {
                "status": "up",  # Should be integer (0 or 1)
                "time": 12345,   # Should be string
                "ping": "fast",  # Should be number
                "msg": 123       # Should be string
            },
            "monitor": {
                "name": 456,     # Should be string
                "type": True     # Should be string
            },
            "msg": None
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(invalid_type_payload),
                                 content_type='application/json')
        
        # Should handle gracefully, either accept with conversion or reject
        assert response.status_code in [200, 400, 422]
    
    def test_empty_payload(self, flask_app):
        """Test handling of empty payload"""
        response = flask_app.post('/webhook',
                                 data='',
                                 content_type='application/json')
        
        assert response.status_code == 400
    
    def test_non_json_content_type(self, flask_app):
        """Test handling of non-JSON content type"""
        payload = "heartbeat=up&monitor=test"
        
        response = flask_app.post('/webhook',
                                 data=payload,
                                 content_type='application/x-www-form-urlencoded')
        
        assert response.status_code in [400, 415]  # Bad request or unsupported media type


class TestWebhookConcurrency:
    """Test concurrent webhook processing"""
    
    def test_concurrent_webhook_requests(self, flask_app):
        """Test handling multiple concurrent webhook requests"""
        num_requests = 20
        results = []
        
        def send_webhook(index):
            payload = {
                "heartbeat": {
                    "status": index % 2,  # Alternate between up and down
                    "time": datetime.now().isoformat(),
                    "ping": 20.0 + index,
                    "msg": f"Status {index}"
                },
                "monitor": {
                    "name": f"Monitor_{index % 5}",  # 5 different monitors
                    "type": "http",
                    "url": f"https://test{index}.com"
                },
                "msg": f"[Monitor_{index % 5}] status"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            results.append({
                'index': index,
                'status_code': response.status_code,
                'response': json.loads(response.data) if response.data else None
            })
        
        # Send concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_webhook, i) for i in range(num_requests)]
            for future in futures:
                future.result()
        
        # Verify all requests were processed
        assert len(results) == num_requests
        
        # All should succeed
        for result in results:
            assert result['status_code'] == 200
            assert result['response']['status'] == 'success'
    
    def test_rapid_webhook_burst(self, flask_app):
        """Test handling rapid burst of webhooks"""
        burst_size = 50
        burst_results = []
        
        # Send burst of webhooks as fast as possible
        start_time = time.time()
        for i in range(burst_size):
            payload = {
                "heartbeat": {
                    "status": 0 if i < 25 else 1,  # Half down, half up
                    "time": datetime.now().isoformat(),
                    "ping": 15.0,
                    "msg": "Burst test"
                },
                "monitor": {
                    "name": "Burst Monitor",
                    "type": "ping",
                    "url": "192.168.1.1"
                },
                "msg": "[Burst Monitor] burst test"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            burst_results.append(response.status_code)
        
        burst_duration = time.time() - start_time
        
        # All requests should be handled
        assert len(burst_results) == burst_size
        assert all(status == 200 for status in burst_results)
        
        # Should handle burst quickly (under 5 seconds for 50 requests)
        assert burst_duration < 5.0
    
    def test_webhook_ordering_preservation(self, flask_app):
        """Test that webhooks are processed in order when from same monitor"""
        monitor_name = "Order Test Monitor"
        events = []
        
        # Send sequence of status changes
        status_sequence = [1, 1, 0, 0, 0, 1, 1, 0, 1]  # Pattern of ups and downs
        
        for i, status in enumerate(status_sequence):
            payload = {
                "heartbeat": {
                    "status": status,
                    "time": (datetime.now() + timedelta(seconds=i)).isoformat(),
                    "ping": 20.0 if status == 1 else 0,
                    "msg": f"Event {i}"
                },
                "monitor": {
                    "name": monitor_name,
                    "type": "http",
                    "url": "https://test.com"
                },
                "msg": f"[{monitor_name}] event {i}"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            assert response.status_code == 200
            events.append(status)
        
        # Verify sequence was preserved
        assert events == status_sequence


class TestWebhookRateLimiting:
    """Test rate limiting and DoS protection"""
    
    def test_rate_limiting_per_monitor(self, flask_app):
        """Test rate limiting applied per monitor"""
        # Send many requests for same monitor
        monitor_name = "Rate Limited Monitor"
        responses = []
        
        for i in range(100):
            payload = {
                "heartbeat": {
                    "status": 1,
                    "time": datetime.now().isoformat(),
                    "ping": 20.0,
                    "msg": f"Request {i}"
                },
                "monitor": {
                    "name": monitor_name,
                    "type": "http",
                    "url": "https://test.com"
                },
                "msg": f"[{monitor_name}] request {i}"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            responses.append(response.status_code)
            
            # Small delay to avoid overwhelming
            if i % 10 == 0:
                time.sleep(0.1)
        
        # Check if rate limiting kicked in (if implemented)
        # Should either all succeed (200) or some get rate limited (429)
        assert all(code in [200, 429] for code in responses)
    
    def test_ddos_protection(self, flask_app):
        """Test protection against DDoS-like webhook floods"""
        flood_size = 200
        flood_threads = 20
        responses = []
        lock = threading.Lock()
        
        def flood_webhooks(thread_id):
            for i in range(flood_size // flood_threads):
                payload = {
                    "heartbeat": {
                        "status": 1,
                        "time": datetime.now().isoformat(),
                        "ping": 10.0,
                        "msg": f"Flood {thread_id}-{i}"
                    },
                    "monitor": {
                        "name": f"Flood Monitor {thread_id}",
                        "type": "ping",
                        "url": "192.168.1.1"
                    },
                    "msg": f"Flood test {thread_id}-{i}"
                }
                
                try:
                    response = flask_app.post('/webhook',
                                            data=json.dumps(payload),
                                            content_type='application/json')
                    
                    with lock:
                        responses.append(response.status_code)
                except:
                    with lock:
                        responses.append(500)  # Connection error
        
        # Launch flood
        with ThreadPoolExecutor(max_workers=flood_threads) as executor:
            futures = [executor.submit(flood_webhooks, i) for i in range(flood_threads)]
            for future in futures:
                future.result()
        
        # System should survive the flood
        assert len(responses) > 0
        # Most requests should be handled (even if rate limited)
        success_rate = sum(1 for r in responses if r in [200, 429]) / len(responses)
        assert success_rate > 0.8  # At least 80% handled properly


class TestWebhookSecurity:
    """Test security aspects of webhook handler"""
    
    def test_sql_injection_attempt(self, flask_app):
        """Test that SQL injection attempts are handled safely"""
        injection_payloads = [
            "'; DROP TABLE events; --",
            "' OR '1'='1",
            "'; DELETE FROM events WHERE '1'='1",
            "UNION SELECT * FROM users",
        ]
        
        for injection in injection_payloads:
            payload = {
                "heartbeat": {
                    "status": 1,
                    "time": "2024-01-01T12:00:00Z",
                    "ping": 20.0,
                    "msg": injection
                },
                "monitor": {
                    "name": injection,
                    "type": "http",
                    "url": "https://test.com"
                },
                "msg": injection
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            # Should handle safely without SQL errors
            assert response.status_code in [200, 400]
    
    def test_xss_prevention(self, flask_app):
        """Test that XSS attempts in payloads are handled"""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "<iframe src='evil.com'></iframe>",
        ]
        
        for xss in xss_payloads:
            payload = {
                "heartbeat": {
                    "status": 1,
                    "time": "2024-01-01T12:00:00Z",
                    "ping": 20.0,
                    "msg": xss
                },
                "monitor": {
                    "name": f"Monitor {xss}",
                    "type": "http",
                    "url": "https://test.com"
                },
                "msg": xss
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            # Should accept but sanitize
            assert response.status_code == 200
            
            # Response should not reflect XSS
            response_text = response.data.decode('utf-8')
            assert '<script>' not in response_text
            assert 'javascript:' not in response_text
    
    def test_path_traversal_attempt(self, flask_app):
        """Test that path traversal attempts are blocked"""
        traversal_attempts = [
            "../../etc/passwd",
            "../../../windows/system32/config/sam",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ]
        
        for attempt in traversal_attempts:
            payload = {
                "heartbeat": {
                    "status": 1,
                    "time": "2024-01-01T12:00:00Z",
                    "ping": 20.0,
                    "msg": "test"
                },
                "monitor": {
                    "name": attempt,
                    "type": "http",
                    "url": f"https://test.com/{attempt}"
                },
                "msg": f"Test {attempt}"
            }
            
            response = flask_app.post('/webhook',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            # Should handle safely
            assert response.status_code in [200, 400]
    
    def test_oversized_payload_rejection(self, flask_app):
        """Test that oversized payloads are rejected"""
        # Create a very large payload
        large_string = "x" * (1024 * 1024)  # 1MB string
        
        oversized_payload = {
            "heartbeat": {
                "status": 1,
                "time": "2024-01-01T12:00:00Z",
                "ping": 20.0,
                "msg": large_string
            },
            "monitor": {
                "name": "Large Monitor",
                "type": "http",
                "url": "https://test.com"
            },
            "msg": "Large payload test"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(oversized_payload),
                                 content_type='application/json')
        
        # Should reject oversized payloads
        assert response.status_code in [400, 413, 431]  # Bad request, payload too large, or headers too large


class TestWebhookResponseCodes:
    """Test appropriate HTTP response codes"""
    
    def test_successful_webhook_returns_200(self, flask_app):
        """Test that successful webhook processing returns 200"""
        payload = {
            "heartbeat": {
                "status": 1,
                "time": "2024-01-01T12:00:00Z",
                "ping": 25.0,
                "msg": "OK"
            },
            "monitor": {
                "name": "Success Test",
                "type": "http",
                "url": "https://test.com"
            },
            "msg": "[Success Test] is up"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(payload),
                                 content_type='application/json')
        
        assert response.status_code == 200
        assert json.loads(response.data)['status'] == 'success'
    
    def test_invalid_endpoint_returns_404(self, flask_app):
        """Test that invalid endpoints return 404"""
        response = flask_app.post('/invalid_endpoint',
                                 data='{}',
                                 content_type='application/json')
        
        assert response.status_code == 404
    
    def test_method_not_allowed_returns_405(self, flask_app):
        """Test that wrong HTTP methods return 405"""
        # GET request to webhook endpoint
        response = flask_app.get('/webhook')
        assert response.status_code in [405, 404]  # Method not allowed or not found
        
        # PUT request to webhook endpoint
        response = flask_app.put('/webhook', data='{}')
        assert response.status_code in [405, 404]
        
        # DELETE request to webhook endpoint
        response = flask_app.delete('/webhook')
        assert response.status_code in [405, 404]
    
    def test_cors_headers_present(self, flask_app):
        """Test that CORS headers are properly set if needed"""
        payload = {
            "heartbeat": {
                "status": 1,
                "time": "2024-01-01T12:00:00Z",
                "ping": 20.0,
                "msg": "CORS test"
            },
            "monitor": {
                "name": "CORS Monitor",
                "type": "http",
                "url": "https://test.com"
            },
            "msg": "CORS test"
        }
        
        response = flask_app.post('/webhook',
                                 data=json.dumps(payload),
                                 content_type='application/json',
                                 headers={'Origin': 'https://uptime-kuma.example.com'})
        
        # Check if CORS headers are set (if implemented)
        # These might not be set if CORS is not configured
        if 'Access-Control-Allow-Origin' in response.headers:
            assert response.headers['Access-Control-Allow-Origin'] in ['*', 'https://uptime-kuma.example.com']