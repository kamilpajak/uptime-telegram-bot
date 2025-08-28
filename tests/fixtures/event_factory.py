"""
Event factory for generating test data
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import random


class EventFactory:
    """Factory for creating realistic event sequences"""
    
    MONITORS = {
        'router': 'Router 192.168.1.1',
        'dns_google': 'Google DNS',
        'dns_cloudflare': 'Cloudflare DNS',
        'site_google': 'Google',
        'site_cloudflare': 'Cloudflare',
        'site_wikipedia': 'Wikipedia'
    }
    
    @classmethod
    def create_event(cls, monitor_name: str, status: str, 
                    timestamp: Optional[datetime] = None,
                    response_time: Optional[float] = None) -> Dict:
        """Create a single event"""
        if timestamp is None:
            timestamp = datetime.now()
        
        if response_time is None:
            response_time = random.uniform(10, 100) if status == 'up' else 0
        
        return {
            'monitor_name': monitor_name,
            'status': status,
            'timestamp': timestamp,
            'message': f"{monitor_name} is {status}",
            'response_time': response_time
        }
    
    @classmethod
    def router_restart_sequence(cls, start_time: datetime, 
                               recovery_seconds: int = 25) -> List[Dict]:
        """Generate events for a router restart scenario"""
        events = []
        
        # Router goes down
        events.append(cls.create_event(
            cls.MONITORS['router'], 'down', start_time
        ))
        
        # External services detect down shortly after
        for i, monitor in enumerate(['dns_google', 'dns_cloudflare']):
            events.append(cls.create_event(
                cls.MONITORS[monitor], 'down', 
                start_time + timedelta(seconds=2 + i)
            ))
        
        # Router comes back up quickly
        events.append(cls.create_event(
            cls.MONITORS['router'], 'up',
            start_time + timedelta(seconds=recovery_seconds)
        ))
        
        # Services recover shortly after
        for i, monitor in enumerate(['dns_google', 'dns_cloudflare']):
            events.append(cls.create_event(
                cls.MONITORS[monitor], 'up',
                start_time + timedelta(seconds=recovery_seconds + 2 + i)
            ))
        
        return events
    
    @classmethod
    def power_outage_sequence(cls, start_time: datetime) -> List[Dict]:
        """Generate events for a power outage"""
        events = []
        
        # All services go down simultaneously
        for monitor in cls.MONITORS.values():
            events.append(cls.create_event(
                monitor, 'down', start_time
            ))
        
        return events
    
    @classmethod
    def isp_outage_sequence(cls, start_time: datetime) -> List[Dict]:
        """Generate events for an ISP outage"""
        events = []
        
        # Router stays up
        events.append(cls.create_event(
            cls.MONITORS['router'], 'up', start_time
        ))
        
        # But external services are down
        for monitor in ['dns_google', 'dns_cloudflare', 'site_google']:
            events.append(cls.create_event(
                cls.MONITORS[monitor], 'down',
                start_time + timedelta(seconds=random.randint(1, 5))
            ))
        
        return events
    
    @classmethod
    def flapping_sequence(cls, start_time: datetime, 
                         monitor_name: str,
                         flap_count: int = 3,
                         interval_seconds: int = 30) -> List[Dict]:
        """Generate events for a flapping service"""
        events = []
        current_time = start_time
        
        for i in range(flap_count):
            # Service goes down
            events.append(cls.create_event(
                monitor_name, 'down', current_time
            ))
            current_time += timedelta(seconds=interval_seconds)
            
            # Service comes back up
            events.append(cls.create_event(
                monitor_name, 'up', current_time
            ))
            current_time += timedelta(seconds=interval_seconds)
        
        return events
    
    @classmethod
    def partial_recovery_sequence(cls, start_time: datetime) -> List[Dict]:
        """Generate events for partial recovery after outage"""
        events = []
        
        # All services go down
        for monitor in cls.MONITORS.values():
            events.append(cls.create_event(
                monitor, 'down', start_time
            ))
        
        # Only some recover within grace period
        recovery_time = start_time + timedelta(seconds=60)
        for monitor in ['router', 'dns_google']:
            events.append(cls.create_event(
                cls.MONITORS[monitor], 'up', recovery_time
            ))
        
        # Others recover much later
        late_recovery = start_time + timedelta(seconds=300)
        for monitor in ['dns_cloudflare', 'site_google']:
            events.append(cls.create_event(
                cls.MONITORS[monitor], 'up', late_recovery
            ))
        
        return events
    
    @classmethod
    def interleaved_outages_sequence(cls, start_time: datetime) -> List[Dict]:
        """Generate events for interleaved independent outages"""
        events = []
        
        # First, an external service fails
        events.append(cls.create_event(
            cls.MONITORS['site_wikipedia'], 'down', start_time
        ))
        
        # Then router restart happens
        router_events = cls.router_restart_sequence(
            start_time + timedelta(seconds=60)
        )
        events.extend(router_events)
        
        # Original service recovers much later
        events.append(cls.create_event(
            cls.MONITORS['site_wikipedia'], 'up',
            start_time + timedelta(seconds=600)
        ))
        
        return sorted(events, key=lambda x: x['timestamp'])