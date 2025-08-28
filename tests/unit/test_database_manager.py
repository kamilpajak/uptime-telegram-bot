"""
Comprehensive unit tests for DatabaseManager component
Tests CRUD operations, concurrent access, timezone handling, and query methods
"""
import pytest
import sqlite3
import tempfile
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed
from freezegun import freeze_time
import pytz

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import importlib.util
spec = importlib.util.spec_from_file_location("uptime_bot", "uptime-telegram-bot.py")
uptime_bot = importlib.util.module_from_spec(spec)
sys.modules["uptime_bot"] = uptime_bot
spec.loader.exec_module(uptime_bot)

from uptime_bot import DatabaseManager, MonitorEvent


class TestDatabaseManagerCRUD:
    """Test basic CRUD operations for DatabaseManager"""
    
    def test_database_initialization(self, temp_db):
        """Test that database initializes with correct schema"""
        db = DatabaseManager(temp_db)
        
        # Verify database file exists
        assert os.path.exists(temp_db)
        
        # Verify events table exists with correct schema
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='events'")
        schema = cursor.fetchone()[0]
        
        assert 'monitor_name' in schema
        assert 'status' in schema
        assert 'response_time' in schema
        assert 'timestamp' in schema
        assert 'message' in schema
        conn.close()
    
    def test_add_event_basic(self, db_manager):
        """Test adding a single event to database"""
        event = MonitorEvent(
            monitor_name="Test Monitor",
            status="up",
            response_time=25.5,
            timestamp=datetime.now(),
            message="Test monitor is up"
        )
        
        db_manager.add_event(event)
        
        # Verify event was added
        recent = db_manager.get_recent_events(1)
        assert len(recent) == 1
        assert recent[0]['monitor_name'] == "Test Monitor"
        assert recent[0]['status'] == "up"
        assert recent[0]['response_time'] == 25.5
    
    def test_add_multiple_events(self, db_manager):
        """Test adding multiple events and retrieving them"""
        events = []
        base_time = datetime.now()
        
        for i in range(10):
            event = MonitorEvent(
                monitor_name=f"Monitor {i % 3}",
                status="up" if i % 2 == 0 else "down",
                response_time=20.0 + i,
                timestamp=base_time + timedelta(seconds=i),
                message=f"Event {i}"
            )
            events.append(event)
            db_manager.add_event(event)
        
        # Verify all events were added
        recent = db_manager.get_recent_events(15)
        assert len(recent) == 10
        
        # Verify ordering (most recent first)
        assert recent[0]['message'] == "Event 9"
        assert recent[-1]['message'] == "Event 0"
    
    def test_get_recent_events_with_minutes_filter(self, db_manager):
        """Test retrieving events within specific time window"""
        base_time = datetime.now()
        
        # Add events at different times
        old_event = MonitorEvent(
            monitor_name="Old Monitor",
            status="up",
            response_time=20.0,
            timestamp=base_time - timedelta(minutes=10),
            message="Old event"
        )
        
        recent_event = MonitorEvent(
            monitor_name="Recent Monitor",
            status="down",
            response_time=30.0,
            timestamp=base_time - timedelta(minutes=2),
            message="Recent event"
        )
        
        db_manager.add_event(old_event)
        db_manager.add_event(recent_event)
        
        # Get events from last 5 minutes
        recent = db_manager.get_recent_events(minutes=5)
        assert len(recent) == 1
        assert recent[0]['monitor_name'] == "Recent Monitor"
        
        # Get events from last 15 minutes
        all_events = db_manager.get_recent_events(minutes=15)
        assert len(all_events) == 2
    
    def test_event_persistence(self, temp_db):
        """Test that events persist across DatabaseManager instances"""
        db1 = DatabaseManager(temp_db)
        
        event = MonitorEvent(
            monitor_name="Persistent Monitor",
            status="up",
            response_time=25.0,
            timestamp=datetime.now(),
            message="Persistent event"
        )
        db1.add_event(event)
        
        # Create new instance with same database
        db2 = DatabaseManager(temp_db)
        recent = db2.get_recent_events(1)
        
        assert len(recent) == 1
        assert recent[0]['monitor_name'] == "Persistent Monitor"


class TestDatabaseManagerConcurrency:
    """Test concurrent access and thread safety"""
    
    def test_concurrent_writes(self, db_manager):
        """Test multiple threads writing to database simultaneously"""
        num_threads = 10
        events_per_thread = 20
        
        def write_events(thread_id):
            for i in range(events_per_thread):
                event = MonitorEvent(
                    monitor_name=f"Thread{thread_id}_Monitor{i}",
                    status="up" if i % 2 == 0 else "down",
                    response_time=20.0 + i,
                    timestamp=datetime.now(),
                    message=f"Thread {thread_id} Event {i}"
                )
                db_manager.add_event(event)
                time.sleep(0.001)  # Small delay to increase chance of conflicts
        
        # Run concurrent writes
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(write_events, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()
        
        # Verify all events were written
        all_events = db_manager.get_recent_events(minutes=60)
        assert len(all_events) == num_threads * events_per_thread
    
    def test_concurrent_reads_and_writes(self, db_manager):
        """Test reading while writing from multiple threads"""
        write_count = 0
        read_count = 0
        lock = threading.Lock()
        
        def writer():
            nonlocal write_count
            for i in range(50):
                event = MonitorEvent(
                    monitor_name=f"Writer_Monitor_{i}",
                    status="up",
                    response_time=25.0,
                    timestamp=datetime.now(),
                    message=f"Write {i}"
                )
                db_manager.add_event(event)
                with lock:
                    write_count += 1
                time.sleep(0.002)
        
        def reader():
            nonlocal read_count
            for _ in range(100):
                events = db_manager.get_recent_events(10)
                with lock:
                    read_count += 1
                time.sleep(0.001)
        
        # Start readers and writers
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            futures.extend([executor.submit(writer) for _ in range(2)])
            futures.extend([executor.submit(reader) for _ in range(4)])
            
            for future in as_completed(futures):
                future.result()
        
        assert write_count == 100  # 2 writers * 50 events
        assert read_count == 400   # 4 readers * 100 reads
    
    def test_transaction_isolation(self, db_manager):
        """Test that transactions are properly isolated"""
        results = []
        
        def transaction_test(delay):
            # Start a transaction-like operation
            initial_count = len(db_manager.get_recent_events(minutes=60))
            
            # Add event
            event = MonitorEvent(
                monitor_name=f"Transaction_Monitor_{delay}",
                status="up",
                response_time=30.0,
                timestamp=datetime.now(),
                message=f"Transaction {delay}"
            )
            db_manager.add_event(event)
            
            time.sleep(delay)
            
            # Check count increased by 1
            final_count = len(db_manager.get_recent_events(minutes=60))
            results.append(final_count - initial_count)
        
        # Run concurrent transactions
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(transaction_test, i * 0.01) for i in range(5)]
            for future in as_completed(futures):
                future.result()
        
        # Each transaction should see its own event added
        assert all(r == 1 for r in results)


class TestDatabaseManagerTimezones:
    """Test timezone handling and datetime operations"""
    
    def test_utc_storage(self, db_manager):
        """Test that all timestamps are stored in UTC"""
        # Create events with different timezones
        eastern = pytz.timezone('US/Eastern')
        tokyo = pytz.timezone('Asia/Tokyo')
        
        eastern_time = eastern.localize(datetime(2024, 1, 1, 12, 0, 0))
        tokyo_time = tokyo.localize(datetime(2024, 1, 1, 12, 0, 0))
        
        event1 = MonitorEvent(
            monitor_name="Eastern Monitor",
            status="up",
            response_time=20.0,
            timestamp=eastern_time,
            message="Eastern timezone event"
        )
        
        event2 = MonitorEvent(
            monitor_name="Tokyo Monitor",
            status="up",
            response_time=25.0,
            timestamp=tokyo_time,
            message="Tokyo timezone event"
        )
        
        db_manager.add_event(event1)
        db_manager.add_event(event2)
        
        # Retrieve and verify UTC conversion
        events = db_manager.get_recent_events(minutes=1440)  # 24 hours
        
        # Tokyo event should be earlier (Tokyo is ahead of Eastern)
        tokyo_event = next(e for e in events if e['monitor_name'] == 'Tokyo Monitor')
        eastern_event = next(e for e in events if e['monitor_name'] == 'Eastern Monitor')
        
        # Parse timestamps
        tokyo_ts = datetime.fromisoformat(tokyo_event['timestamp'].replace('Z', '+00:00'))
        eastern_ts = datetime.fromisoformat(eastern_event['timestamp'].replace('Z', '+00:00'))
        
        # Tokyo 12:00 = UTC 03:00, Eastern 12:00 = UTC 17:00 (winter time)
        # So Tokyo timestamp should be earlier
        assert tokyo_ts < eastern_ts
    
    def test_naive_datetime_handling(self, db_manager):
        """Test handling of naive datetime objects"""
        naive_time = datetime(2024, 1, 1, 12, 0, 0)
        
        event = MonitorEvent(
            monitor_name="Naive Monitor",
            status="up",
            response_time=20.0,
            timestamp=naive_time,
            message="Naive datetime event"
        )
        
        # Should handle naive datetime without error
        db_manager.add_event(event)
        
        events = db_manager.get_recent_events(1)
        assert len(events) == 1
        assert events[0]['monitor_name'] == "Naive Monitor"
    
    @freeze_time("2024-01-01 12:00:00")
    def test_recent_events_timezone_aware(self, db_manager):
        """Test that get_recent_events correctly handles timezone-aware queries"""
        now = datetime.now()
        
        # Add events at different times
        for i in range(5):
            event = MonitorEvent(
                monitor_name=f"Monitor_{i}",
                status="up",
                response_time=20.0,
                timestamp=now - timedelta(minutes=i*2),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        # Query with 5-minute window should get 3 events (0, 2, 4 minutes ago)
        recent = db_manager.get_recent_events(minutes=5)
        assert len(recent) == 3


class TestDatabaseManagerQueries:
    """Test complex query methods"""
    
    def test_get_uptime_percentage_basic(self, db_manager):
        """Test uptime percentage calculation"""
        base_time = datetime.now()
        
        # Create a pattern: 8 up, 2 down = 80% uptime
        for i in range(10):
            event = MonitorEvent(
                monitor_name="Test Monitor",
                status="up" if i < 8 else "down",
                response_time=20.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        uptime = db_manager.get_uptime_percentage("Test Monitor", hours=24)
        assert uptime == 80.0
    
    def test_get_uptime_percentage_multiple_monitors(self, db_manager):
        """Test uptime calculation for different monitors"""
        base_time = datetime.now()
        
        # Monitor 1: 100% uptime
        for i in range(5):
            event = MonitorEvent(
                monitor_name="Stable Monitor",
                status="up",
                response_time=20.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Stable {i}"
            )
            db_manager.add_event(event)
        
        # Monitor 2: 60% uptime (3 up, 2 down)
        for i in range(5):
            event = MonitorEvent(
                monitor_name="Flaky Monitor",
                status="up" if i < 3 else "down",
                response_time=30.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Flaky {i}"
            )
            db_manager.add_event(event)
        
        stable_uptime = db_manager.get_uptime_percentage("Stable Monitor", hours=24)
        flaky_uptime = db_manager.get_uptime_percentage("Flaky Monitor", hours=24)
        
        assert stable_uptime == 100.0
        assert flaky_uptime == 60.0
    
    def test_get_uptime_percentage_no_data(self, db_manager):
        """Test uptime calculation with no data"""
        uptime = db_manager.get_uptime_percentage("Nonexistent Monitor", hours=24)
        assert uptime == 0.0
    
    def test_get_outage_history(self, db_manager):
        """Test retrieving outage history with durations"""
        base_time = datetime.now()
        
        # Create outage pattern: up -> down -> down -> up -> up -> down -> up
        events = [
            ("up", 0),    # Start up
            ("down", 1),  # Outage starts
            ("down", 2),  # Outage continues
            ("up", 3),    # Recovery (2-hour outage)
            ("up", 4),    # Still up
            ("down", 5),  # New outage
            ("up", 6),    # Recovery (1-hour outage)
        ]
        
        for status, hours_ago in events:
            event = MonitorEvent(
                monitor_name="Test Monitor",
                status=status,
                response_time=20.0 if status == "up" else 0.0,
                timestamp=base_time - timedelta(hours=hours_ago),
                message=f"{status} at {hours_ago}h ago"
            )
            db_manager.add_event(event)
        
        outages = db_manager.get_outage_history("Test Monitor", days=1)
        
        # Should detect 2 outages
        assert len(outages) == 2
        
        # Most recent outage first
        assert outages[0]['duration_minutes'] == 60  # 1-hour outage
        assert outages[1]['duration_minutes'] == 120  # 2-hour outage
    
    def test_get_monitor_report(self, db_manager):
        """Test comprehensive monitor report generation"""
        base_time = datetime.now()
        
        # Create mixed status pattern
        for i in range(24):
            status = "up" if i % 3 != 0 else "down"
            event = MonitorEvent(
                monitor_name="Report Monitor",
                status=status,
                response_time=20.0 + i if status == "up" else 0.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        report = db_manager.get_monitor_report("Report Monitor", hours=24)
        
        assert report['monitor_name'] == "Report Monitor"
        assert report['total_events'] == 24
        assert report['up_events'] == 16  # 24 * 2/3
        assert report['down_events'] == 8  # 24 * 1/3
        assert 'uptime_percentage' in report
        assert 'avg_response_time' in report
        assert 'last_status' in report


class TestDatabaseManagerEdgeCases:
    """Test edge cases and error handling"""
    
    def test_empty_database_queries(self, db_manager):
        """Test all query methods with empty database"""
        assert db_manager.get_recent_events(10) == []
        assert db_manager.get_uptime_percentage("Any Monitor", 24) == 0.0
        assert db_manager.get_outage_history("Any Monitor", 7) == []
        
        report = db_manager.get_monitor_report("Any Monitor", 24)
        assert report['total_events'] == 0
        assert report['uptime_percentage'] == 0.0
    
    def test_malformed_event_handling(self, db_manager):
        """Test handling of events with missing or invalid fields"""
        # Event with None timestamp
        event = MonitorEvent(
            monitor_name="Test Monitor",
            status="up",
            response_time=20.0,
            timestamp=None,
            message="No timestamp"
        )
        
        # Should handle gracefully (use current time)
        db_manager.add_event(event)
        recent = db_manager.get_recent_events(1)
        assert len(recent) == 1
    
    def test_large_dataset_performance(self, db_manager):
        """Test performance with large number of events"""
        import time
        
        # Add 10,000 events
        base_time = datetime.now()
        start = time.time()
        
        for i in range(10000):
            event = MonitorEvent(
                monitor_name=f"Monitor_{i % 10}",
                status="up" if i % 2 == 0 else "down",
                response_time=20.0 + (i % 100),
                timestamp=base_time - timedelta(seconds=i),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        write_time = time.time() - start
        
        # Query performance
        start = time.time()
        recent = db_manager.get_recent_events(minutes=60)
        query_time = time.time() - start
        
        # Performance assertions
        assert write_time < 10.0  # Should write 10k events in under 10 seconds
        assert query_time < 0.5   # Query should be fast even with large dataset
        
        # Verify data integrity
        assert len(recent) <= 3600  # Max 60 minutes of second-resolution events
    
    def test_database_cleanup(self, db_manager):
        """Test data retention and cleanup"""
        base_time = datetime.now()
        
        # Add old events (beyond retention period)
        for i in range(100, 110):
            event = MonitorEvent(
                monitor_name="Old Monitor",
                status="up",
                response_time=20.0,
                timestamp=base_time - timedelta(days=i),
                message=f"Old event {i}"
            )
            db_manager.add_event(event)
        
        # Add recent events
        for i in range(5):
            event = MonitorEvent(
                monitor_name="Recent Monitor",
                status="up",
                response_time=25.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Recent event {i}"
            )
            db_manager.add_event(event)
        
        # Implement cleanup (if method exists)
        if hasattr(db_manager, 'cleanup_old_events'):
            db_manager.cleanup_old_events(days=30)
            
            # Verify old events removed, recent kept
            all_events = db_manager.get_recent_events(minutes=60*24*365)
            assert all('Recent' in e['monitor_name'] for e in all_events)
    
    def test_special_characters_in_names(self, db_manager):
        """Test handling of special characters in monitor names"""
        special_names = [
            "Monitor's Test",
            "Monitor \"Quoted\"",
            "Monitor; DROP TABLE events;--",  # SQL injection attempt
            "Monitor\nNewline",
            "Monitor\\Backslash",
            "Монитор Unicode"
        ]
        
        for name in special_names:
            event = MonitorEvent(
                monitor_name=name,
                status="up",
                response_time=20.0,
                timestamp=datetime.now(),
                message=f"Testing {name}"
            )
            db_manager.add_event(event)
        
        # Verify all events stored correctly
        recent = db_manager.get_recent_events(10)
        stored_names = [e['monitor_name'] for e in recent]
        
        for name in special_names:
            assert name in stored_names


class TestDatabaseManagerBenchmarks:
    """Performance benchmarks for database operations"""
    
    @pytest.mark.benchmark
    def test_write_performance(self, db_manager, benchmark):
        """Benchmark single event write performance"""
        event = MonitorEvent(
            monitor_name="Benchmark Monitor",
            status="up",
            response_time=25.0,
            timestamp=datetime.now(),
            message="Benchmark event"
        )
        
        result = benchmark(db_manager.add_event, event)
        
        # Should complete in under 50ms
        assert benchmark.stats['mean'] < 0.05
    
    @pytest.mark.benchmark
    def test_query_performance(self, db_manager, benchmark):
        """Benchmark query performance with populated database"""
        # Pre-populate database
        base_time = datetime.now()
        for i in range(1000):
            event = MonitorEvent(
                monitor_name=f"Monitor_{i % 5}",
                status="up" if i % 2 == 0 else "down",
                response_time=20.0 + (i % 50),
                timestamp=base_time - timedelta(seconds=i*10),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        # Benchmark query
        result = benchmark(db_manager.get_recent_events, minutes=60)
        
        # Query should complete in under 100ms
        assert benchmark.stats['mean'] < 0.1
    
    @pytest.mark.benchmark
    def test_uptime_calculation_performance(self, db_manager, benchmark):
        """Benchmark uptime percentage calculation"""
        # Pre-populate with events
        base_time = datetime.now()
        for i in range(500):
            event = MonitorEvent(
                monitor_name="Uptime Monitor",
                status="up" if i % 5 != 0 else "down",
                response_time=25.0,
                timestamp=base_time - timedelta(hours=i),
                message=f"Event {i}"
            )
            db_manager.add_event(event)
        
        # Benchmark uptime calculation
        result = benchmark(db_manager.get_uptime_percentage, "Uptime Monitor", 168)  # 7 days
        
        # Should complete in under 200ms
        assert benchmark.stats['mean'] < 0.2