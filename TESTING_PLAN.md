# Comprehensive Testing Strategy for Uptime Telegram Bot

## Overview
This document outlines a complete testing strategy for the Uptime Telegram Bot to ensure reliability across various failure scenarios.

## 1. Test Structure
- Create `tests/` directory with organized test modules
- Use pytest framework for test execution
- Add test coverage reporting with pytest-cov
- Create mock Uptime Kuma simulator for testing

## 2. Unit Tests (`tests/unit/`)

### a) OutageAnalyzer Tests
- Test POWER_OUTAGE detection (router + services down)
- Test ISP_OUTAGE detection (router up, services down)
- Test PARTIAL_OUTAGE detection (some services down)
- Test ROUTER_FAILURE detection (only router down)
- Test edge cases with missing/incomplete data
- Test confidence score calculations
- Test affected services list generation

### b) DatabaseManager Tests
- Test event storage and retrieval
- Test date/time handling with different timezones
- Test query performance with large datasets (100k+ events)
- Test concurrent access scenarios
- Test database migration/schema updates
- Test data retention policies

### c) MonitorEvent Tests
- Test data validation
- Test serialization/deserialization
- Test response time calculations
- Test status transitions (up->down, down->up)

### d) TelegramNotifier Tests
- Test message formatting for each alert type
- Test cooldown mechanism
- Test recovery duration calculations
- Test notification queuing

## 3. Integration Tests (`tests/integration/`)

### a) Webhook Handler Tests
- Test parsing real Uptime Kuma webhook payloads
- Test handling malformed requests
- Test concurrent webhook processing
- Test rate limiting behavior
- Test different Uptime Kuma versions compatibility

### b) Telegram Integration Tests
- Mock Telegram API responses
- Test command handlers (/status, /report, /uptime, /downtime)
- Test notification formatting with markdown
- Test cooldown mechanism (5-minute window)
- Test recovery notifications with correct timestamps
- Test error handling for Telegram API failures

### c) Flask Application Tests
- Test webhook endpoint security
- Test CORS configuration
- Test request validation
- Test response formats
- Test error handling

## 4. End-to-End Test Scenarios (`tests/e2e/`)

### Scenario 1: ISP Outage
```python
def test_isp_outage_scenario():
    # 1. Router responds (UP)
    # 2. Multiple DNS fail (DOWN)
    # 3. Expect ISP_OUTAGE alert with 90% confidence
    # 4. Services recover after 5 minutes
    # 5. Expect recovery notification with duration
```

### Scenario 2: Power Outage
```python
def test_power_outage_scenario():
    # 1. All monitors go DOWN simultaneously
    # 2. Expect POWER_OUTAGE alert (95% confidence)
    # 3. No further notifications (system is down)
    # 4. Services gradually recover
    # 5. Track recovery sequence
```

### Scenario 3: Intermittent Failures
```python
def test_flapping_services():
    # 1. Services flapping (up/down/up in 2-minute intervals)
    # 2. Test cooldown prevents spam
    # 3. Verify accurate uptime calculations
    # 4. Test notification aggregation
```

### Scenario 4: Long Outage
```python
def test_extended_outage():
    # 1. Service down for 2+ hours
    # 2. Test database performance with continuous events
    # 3. Verify /downtime accuracy
    # 4. Test report generation with large datasets
```

### Scenario 5: Cascade Failure
```python
def test_cascade_failure():
    # 1. Router fails first
    # 2. Then DNS services fail
    # 3. Then external sites fail
    # 4. Verify correct analysis at each stage
```

## 5. Test Data Generator (`tests/fixtures/`)

### Webhook Payload Generator
```python
def generate_webhook_payload(monitor_name, status, timestamp):
    return {
        "heartbeat": {
            "status": 0 if status == "down" else 1,
            "ping": random.uniform(10, 100),
            "timestamp": timestamp.isoformat()
        },
        "monitor": {
            "name": monitor_name,
            "type": "ping" if "192.168" in monitor_name else "http"
        },
        "msg": f"{monitor_name} is {status}"
    }
```

### Outage Sequence Simulator
```python
def simulate_outage_sequence(outage_type, duration_minutes):
    """Generate realistic event sequences for each outage type"""
    events = []
    
    if outage_type == "POWER_OUTAGE":
        # All services down simultaneously
        for monitor in ["Router 192.168.1.1", "Google DNS", "Cloudflare DNS"]:
            events.append(create_down_event(monitor))
    
    elif outage_type == "ISP_OUTAGE":
        # Router up, external services down
        events.append(create_up_event("Router 192.168.1.1"))
        events.append(create_down_event("Google DNS"))
        events.append(create_down_event("Cloudflare DNS"))
    
    return events
```

## 6. Performance & Load Tests

### High Volume Tests
- Test with 100+ monitors reporting simultaneously
- Simulate rapid webhook bursts (10+ per second)
- Test database with 1M+ events
- Memory leak detection over 24-hour runs
- Response time benchmarks (webhook < 100ms)

### Resource Usage Tests
- CPU usage under load
- Memory consumption patterns
- Database size growth
- Network bandwidth usage

## 7. Chaos Engineering Tests

### System Failures
- Kill Flask mid-request
- Corrupt database temporarily
- Network timeouts to Telegram API
- Docker container restarts
- System clock changes
- Disk space exhaustion

### Network Conditions
- High latency (500ms+)
- Packet loss (10-30%)
- Connection drops
- DNS failures

## 8. Mock Uptime Kuma Simulator

Create `tests/mock_uptime_kuma.py`:
```python
class MockUptimeKuma:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.monitors = {}
    
    def add_monitor(self, name, initial_status="up"):
        self.monitors[name] = {
            "name": name,
            "status": initial_status,
            "response_time": 20.0
        }
    
    def trigger_outage(self, monitor_name):
        """Simulate monitor going down"""
        self.send_webhook(monitor_name, "down")
    
    def trigger_recovery(self, monitor_name):
        """Simulate monitor recovering"""
        self.send_webhook(monitor_name, "up")
    
    def simulate_pattern(self, pattern_name):
        """Simulate complex failure patterns"""
        patterns = {
            "isp_outage": self.simulate_isp_outage,
            "power_outage": self.simulate_power_outage,
            "flapping": self.simulate_flapping
        }
        patterns[pattern_name]()
```

## 9. Test Automation

### CI/CD Pipeline (.github/workflows/test.yml)
```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.10, 3.11, 3.12]
    
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt
    - name: Run unit tests
      run: pytest tests/unit/ -v
    - name: Run integration tests
      run: pytest tests/integration/ -v
    - name: Run E2E tests
      run: pytest tests/e2e/ -v
    - name: Generate coverage report
      run: pytest --cov=. --cov-report=xml
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

### Local Testing Commands
```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific scenario
pytest tests/e2e/test_power_outage.py -v

# Run with live monitoring
pytest tests/ --tb=short --capture=no

# Run performance tests
pytest tests/performance/ -v --benchmark-only

# Run chaos tests (requires Docker)
pytest tests/chaos/ --docker
```

## 10. Test Monitoring Dashboard

### Simple Web Dashboard (`tests/dashboard.py`)
```python
from flask import Flask, render_template
import json

app = Flask(__name__)

@app.route('/')
def dashboard():
    return render_template('dashboard.html', 
                         current_scenario=get_current_scenario(),
                         monitor_states=get_monitor_states(),
                         recent_alerts=get_recent_alerts())

@app.route('/api/timeline')
def timeline():
    """Return event timeline for visualization"""
    return json.dumps(get_event_timeline())
```

Features:
- Current test scenario running
- Simulated monitor states (UP/DOWN)
- Generated alerts in real-time
- Bot responses log
- Timeline visualization of events
- Test coverage metrics

## 11. Test Documentation

### Test Case Documentation
Each test should include:
- Purpose and scenario description
- Prerequisites
- Expected outcomes
- Actual results logging
- Performance metrics

### Test Report Generation
- Automated test reports after each run
- Include success/failure rates
- Performance regression detection
- Coverage trends over time

## 12. Implementation Priority

### Phase 1: Core Testing (Week 1)
1. Unit tests for OutageAnalyzer (critical logic)
2. Integration tests for webhook handling
3. Basic E2E scenarios (ISP, Power outage)

### Phase 2: Comprehensive Testing (Week 2)
4. Mock Uptime Kuma simulator
5. Additional E2E scenarios
6. Telegram integration tests

### Phase 3: Advanced Testing (Week 3)
7. Performance tests
8. Chaos engineering tests
9. Test dashboard
10. CI/CD pipeline setup

## 13. Testing Requirements

### Dependencies (requirements-test.txt)
```
pytest==7.4.0
pytest-cov==4.1.0
pytest-asyncio==0.21.0
pytest-mock==3.11.1
pytest-benchmark==4.0.0
faker==19.2.0
responses==0.23.1
freezegun==1.2.2
```

## 14. Success Metrics

- Code coverage > 80%
- All E2E scenarios passing
- Webhook response time < 100ms
- No memory leaks in 24-hour test
- Zero false positives in outage detection
- Correct downtime calculations ±1 second

## Next Steps

1. Create tests/ directory structure
2. Implement unit tests for core components
3. Set up pytest configuration
4. Create mock data generators
5. Implement first E2E scenario
6. Set up CI/CD pipeline

This comprehensive testing strategy ensures the Uptime Telegram Bot is reliable, performant, and accurate in detecting and reporting various outage scenarios.