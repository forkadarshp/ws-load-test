# Pipecat Load Tester

Load testing tool for Pipecat voice bots with RTVI protocol support.

## Installation

```bash
pip install -e .
```

## CLI Usage

```bash
# Sustained load test
pipecat-load-test sustained --host localhost:8000 --connections 10 --duration 60

# Ramp-up test
pipecat-load-test ramp --host localhost:8000 --start 10 --end 100 --step 10 --interval 30

# Spike test
pipecat-load-test spike --host localhost:8000 --connections 100 --duration 60
```

## Testing API

```bash
# Start API server
uvicorn pipecat_load_tester.api.main:app --port 8080

# Create session
curl -X POST http://localhost:8080/test/session/start -H "Content-Type: application/json" -d '{"bot_host": "localhost:8000"}'

# Send text
curl -X POST http://localhost:8080/test/session/{SESSION_ID}/text -H "Content-Type: application/json" -d '{"text": "Hello"}'

# Get messages
curl http://localhost:8080/test/session/{SESSION_ID}/messages

# Close session
curl -X DELETE http://localhost:8080/test/session/{SESSION_ID}
```

## Programmatic Usage

```python
import asyncio
from pipecat_load_tester import AudioGenerator, MetricsCollector, LoadOrchestrator

async def run_test():
    audio_gen = AudioGenerator()  # Uses synthetic sine wave
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator("localhost:8000", audio_gen, metrics)
    
    await orchestrator.run_sustained(num_connections=5, duration=30)
    
    metrics.print_summary()
    metrics.save_report("results.json")

asyncio.run(run_test())
```

## License

BSD-2-Clause
