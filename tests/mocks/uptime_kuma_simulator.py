"""
Mock Uptime Kuma simulator for testing
"""
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import requests


class MockUptimeKuma:
    """Simulates Uptime Kuma webhook behavior"""
    
    def __init__(self, webhook_url: str = "http://localhost:5000/webhook"):
        self.webhook_url = webhook_url
        self.monitors = {}
        self.event_history = []
        self.running = False
        self._thread = None
        
    def add_monitor(self, name: str, monitor_type: str = "ping", 
                   interval: int = 30, initial_status: str = "up"):
        """Add a monitor to the simulator"""
        self.monitors[name] = {
            'name': name,
            'type': monitor_type,
            'interval': interval,
            'status': initial_status,
            'last_check': datetime.now(),
            'response_time': 20.0
        }
        return self
    
    def trigger_outage(self, monitor_name: str, response_time: float = 0):
        """Simulate a monitor going down"""
        if monitor_name not in self.monitors:
            raise ValueError(f"Monitor {monitor_name} not found")
        
        self.monitors[monitor_name]['status'] = 'down'
        self.monitors[monitor_name]['response_time'] = response_time
        self._send_webhook(monitor_name, 'down', response_time)
    
    def trigger_recovery(self, monitor_name: str, response_time: float = 25.0):
        """Simulate a monitor recovering"""
        if monitor_name not in self.monitors:
            raise ValueError(f"Monitor {monitor_name} not found")
        
        self.monitors[monitor_name]['status'] = 'up'
        self.monitors[monitor_name]['response_time'] = response_time
        self._send_webhook(monitor_name, 'up', response_time)
    
    def simulate_router_restart(self, recovery_time: int = 25):
        """Simulate a router restart scenario"""
        # Router and services go down
        self.trigger_outage("Router 192.168.1.1")
        time.sleep(0.5)
        self.trigger_outage("Google DNS")
        self.trigger_outage("Cloudflare DNS")
        
        # Wait for recovery time
        time.sleep(recovery_time)
        
        # Router recovers first
        self.trigger_recovery("Router 192.168.1.1", 15.0)
        time.sleep(0.5)
        # Then services
        self.trigger_recovery("Google DNS", 30.0)
        self.trigger_recovery("Cloudflare DNS", 28.0)
    
    def simulate_isp_outage(self, duration: int = 300):
        """Simulate an ISP outage"""
        # Router stays up but external services fail
        self._send_webhook("Router 192.168.1.1", "up", 10.0)
        time.sleep(0.5)
        
        # External services down
        for monitor in ["Google DNS", "Cloudflare DNS", "Google", "Cloudflare"]:
            self.trigger_outage(monitor)
            time.sleep(0.2)
        
        # Wait for duration
        time.sleep(duration)
        
        # Services recover
        for monitor in ["Google DNS", "Cloudflare DNS", "Google", "Cloudflare"]:
            self.trigger_recovery(monitor)
            time.sleep(0.2)
    
    def simulate_power_outage(self):
        """Simulate a power outage"""
        # Everything goes down at once
        for monitor_name in self.monitors:
            self.monitors[monitor_name]['status'] = 'down'
            self._send_webhook(monitor_name, 'down', 0)
    
    def simulate_flapping(self, monitor_name: str, count: int = 3, 
                         interval: int = 30):
        """Simulate a flapping service"""
        for i in range(count):
            self.trigger_outage(monitor_name)
            time.sleep(interval)
            self.trigger_recovery(monitor_name)
            time.sleep(interval)
    
    def simulate_pattern(self, pattern_name: str):
        """Run a predefined failure pattern"""
        patterns = {
            'router_restart': lambda: self.simulate_router_restart(25),
            'router_outage': lambda: self.simulate_router_restart(150),
            'isp_outage': lambda: self.simulate_isp_outage(300),
            'power_outage': lambda: self.simulate_power_outage(),
            'dns_flapping': lambda: self.simulate_flapping("Google DNS", 3, 20)
        }
        
        if pattern_name not in patterns:
            raise ValueError(f"Unknown pattern: {pattern_name}")
        
        patterns[pattern_name]()
    
    def _send_webhook(self, monitor_name: str, status: str, 
                     response_time: float = 0):
        """Send webhook to the configured URL"""
        payload = self._create_payload(monitor_name, status, response_time)
        
        # Store in history
        self.event_history.append({
            'timestamp': datetime.now(),
            'monitor': monitor_name,
            'status': status,
            'payload': payload
        })
        
        # Send webhook
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=5
            )
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Failed to send webhook: {e}")
            return False
    
    def _create_payload(self, monitor_name: str, status: str, 
                       response_time: float) -> Dict:
        """Create Uptime Kuma webhook payload"""
        monitor = self.monitors.get(monitor_name, {
            'name': monitor_name,
            'type': 'http'
        })
        
        status_code = 1 if status == "up" else 0
        
        return {
            "heartbeat": {
                "status": status_code,
                "time": datetime.now().isoformat(),
                "ping": response_time,
                "msg": f"{monitor_name} is {status}",
                "monitorID": hash(monitor_name) % 1000,
                "important": status == "down"
            },
            "monitor": {
                "name": monitor_name,
                "type": monitor['type'],
                "url": f"http://{monitor_name.lower().replace(' ', '-')}.example.com"
            },
            "msg": f"[{monitor_name}] is {status}"
        }
    
    def start_monitoring(self, check_interval: int = 30):
        """Start continuous monitoring simulation"""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._monitoring_loop, 
                                       args=(check_interval,))
        self._thread.daemon = True
        self._thread.start()
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _monitoring_loop(self, check_interval: int):
        """Main monitoring loop"""
        while self.running:
            for monitor_name, monitor in self.monitors.items():
                if monitor['status'] == 'up':
                    # Send heartbeat
                    self._send_webhook(monitor_name, 'up', 
                                     monitor['response_time'])
            
            time.sleep(check_interval)
    
    def get_event_history(self, monitor_name: Optional[str] = None) -> List[Dict]:
        """Get event history, optionally filtered by monitor"""
        if monitor_name:
            return [e for e in self.event_history if e['monitor'] == monitor_name]
        return self.event_history
    
    def clear_history(self):
        """Clear event history"""
        self.event_history = []
    
    def reset(self):
        """Reset all monitors to initial state"""
        for monitor in self.monitors.values():
            monitor['status'] = 'up'
            monitor['response_time'] = 20.0
        self.clear_history()


class MockUptimeKumaAsync:
    """Async version for testing with asyncio"""
    
    def __init__(self, webhook_callback: Callable):
        self.webhook_callback = webhook_callback
        self.monitors = {}
        self.event_history = []
    
    async def send_event(self, monitor_name: str, status: str, 
                        response_time: float = 20.0):
        """Send event through callback instead of HTTP"""
        payload = {
            "heartbeat": {
                "status": 1 if status == "up" else 0,
                "time": datetime.now().isoformat(),
                "ping": response_time,
                "msg": f"{monitor_name} is {status}"
            },
            "monitor": {
                "name": monitor_name,
                "type": "ping" if "192.168" in monitor_name else "http"
            },
            "msg": f"[{monitor_name}] is {status}"
        }
        
        self.event_history.append({
            'timestamp': datetime.now(),
            'monitor': monitor_name,
            'status': status
        })
        
        await self.webhook_callback(payload)