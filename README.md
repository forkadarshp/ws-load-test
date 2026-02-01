# Pipecat Load Tester

A load testing tool for [Pipecat](https://github.com/pipecat-ai/pipecat) voice bots with RTVI protocol support.

## Features

- **Multiple test patterns**: Sustained, ramp-up, and spike load tests
- **RTVI protocol support**: Full handshake and message protocol implementation
- **Audio streaming**: Send real WAV files or synthetic audio
- **Rich CLI**: Progress bars, colored output, and detailed metrics
- **Configuration**: YAML config files, environment variables, or CLI args
- **Testing API**: REST API for programmatic test control
- **Docker support**: Run tests in containers

## Quick Start

### 1. Install

```bash
# Clone the repository
git clone https://github.com/forkadarshp/ws-load-test.git
cd ws-load-test

# Install with pip
pip install -e .

# Or with YAML config support
pip install -e ".[yaml]"
```

### 2. Run a Test

```bash
# Test against a local Pipecat server
pipecat-load-test sustained --host localhost:8000 -n 5 -d 30

# That's it! This runs 5 concurrent connections for 30 seconds.
```

### 3. View Results

Results are saved to `results.json` by default. The CLI also prints a summary:

```
┌──────────────────────────────────────────────────┐
│          Load Test Summary                       │
├─────────────────────────────┬────────────────────┤
│ Metric                      │ Value              │
├─────────────────────────────┼────────────────────┤
│ Total Connections Attempted │ 5                  │
│ Total Connections Successful│ 5                  │
│ Success Rate                │ 100%               │
│ Total Frames Sent           │ 2500               │
│ Total Errors                │ 0                  │
└─────────────────────────────┴────────────────────┘
```

## Installation Options

### pip (recommended)

```bash
pip install -e .
```

### With all features

```bash
pip install -e ".[all]"
```

### Docker

```bash
docker build -t pipecat-load-test .
docker run pipecat-load-test sustained --host host.docker.internal:8000 -n 10
```

## CLI Usage

### Commands

| Command | Description |
|---------|-------------|
| `sustained` | Maintain N connections for D seconds |
| `ramp` | Gradually increase connections over time |
| `spike` | Instantly create many connections |
| `init` | Create a sample config file |
| `show-config` | Display current configuration |

### Sustained Load Test

Tests steady-state performance with a constant number of connections.

```bash
# Basic usage
pipecat-load-test sustained

# Custom settings
pipecat-load-test sustained --host myserver:8000 -n 50 -d 120

# With audio file
pipecat-load-test sustained -a samples/greeting.wav -n 20
```

Options:
- `--host, -h`: Server host:port (default: localhost:8000)
- `--connections, -n`: Number of connections (default: 10)
- `--duration, -d`: Test duration in seconds (default: 60)
- `--audio, -a`: Path to WAV audio file
- `--output, -o`: Output file (default: results.json)

### Ramp Test

Gradually increases load to find capacity limits.

```bash
# Ramp from 10 to 100 connections
pipecat-load-test ramp --start 10 --end 100 --step 10 --interval 30
```

Options:
- `--start`: Starting connections (default: 10)
- `--end`: Maximum connections (default: 100)
- `--step`: Increment per interval (default: 10)
- `--interval`: Seconds between increments (default: 30)

### Spike Test

Tests handling of sudden load increases.

```bash
# Spike to 100 connections
pipecat-load-test spike -n 100 -d 60
```

### Global Options

```bash
# Verbose output (debug logging)
pipecat-load-test -v sustained

# Use config file
pipecat-load-test -c myconfig.yaml sustained

# Show help
pipecat-load-test --help
```

## Configuration

Configuration priority: CLI args > Environment variables > Config file > Defaults

### Environment Variables

```bash
export PIPECAT_HOST=myserver:8000
export PIPECAT_LOG_LEVEL=DEBUG
export PIPECAT_MAX_RETRIES=5

pipecat-load-test sustained
```

Available variables:
- `PIPECAT_HOST`: Server host:port
- `PIPECAT_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `PIPECAT_MAX_RETRIES`: Connection retry attempts
- `PIPECAT_RETRY_DELAY`: Delay between retries (seconds)
- `PIPECAT_PIPELINE_INIT_DELAY`: Wait time for pipeline init (seconds)
- `PIPECAT_AUDIO_FILE`: Default audio file path

### Config File

Create a config file:

```bash
pipecat-load-test init
```

This creates `pipecat-config.yaml`:

```yaml
# Server settings
server:
  host: localhost:8000
  connect_endpoint: /connect

# Test defaults
test:
  default_connections: 10
  default_duration: 60

# Connection settings
connection:
  pipeline_init_delay: 1.5
  max_retries: 3
  retry_delay: 1.0

# Logging
logging:
  log_level: INFO
```

Use it:

```bash
pipecat-load-test -c pipecat-config.yaml sustained
```

## Docker Usage

### Build and Run

```bash
# Build image
docker build -t pipecat-load-test .

# Run sustained test
docker run --rm pipecat-load-test sustained --host host.docker.internal:8000 -n 10

# Save results to host
docker run --rm -v $(pwd)/results:/results pipecat-load-test \
  sustained -n 20 -o /results/test.json
```

### Docker Compose

```bash
# Run load test
docker compose run load-tester

# Start API server
docker compose up api
```

## Testing API

The Testing API provides programmatic control over test sessions.

### Start the API

```bash
# Direct
uvicorn pipecat_load_tester.api.main:app --port 8080

# Docker
docker compose up api
```

### API Endpoints

```bash
# Create a session
curl -X POST http://localhost:8080/test/session/start \
  -H "Content-Type: application/json" \
  -d '{"bot_host": "localhost:8000"}'

# Returns: {"session_id": "abc123", "status": "connected"}

# Send text
curl -X POST http://localhost:8080/test/session/abc123/text \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, bot!"}'

# Send audio file
curl -X POST http://localhost:8080/test/session/abc123/audio \
  -F "audio=@samples/greeting.wav"

# Get messages from bot
curl http://localhost:8080/test/session/abc123/messages

# Check status
curl http://localhost:8080/test/session/abc123/status

# Close session
curl -X DELETE http://localhost:8080/test/session/abc123
```

## Programmatic Usage

```python
import asyncio
from pipecat_load_tester import (
    AudioGenerator,
    MetricsCollector,
    LoadOrchestrator,
    PipecatConfig
)

async def run_test():
    # Create config
    config = PipecatConfig(
        host="localhost:8000",
        max_retries=3
    )

    # Setup components
    audio_gen = AudioGenerator()  # Uses synthetic sine wave
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator("localhost:8000", audio_gen, metrics, config)

    # Run test
    await orchestrator.run_sustained(num_connections=10, duration=30)

    # Get results
    report = metrics.generate_report()
    print(f"Success rate: {report['summary']['success_rate']}%")
    print(f"Avg connect time: {report['performance']['avg_connect_time_ms']}ms")

asyncio.run(run_test())
```

## Audio Options

### Synthetic Audio (Default)

By default, the tool generates a 440Hz sine wave. No audio files needed.

### Custom Audio File

Use any WAV file:

```bash
pipecat-load-test sustained -a path/to/audio.wav
```

Requirements:
- Format: WAV
- Will be resampled to 16kHz mono if needed

### Generating Test Audio

```python
from pipecat_load_tester import AudioGenerator
import numpy as np

# Create custom sine wave
gen = AudioGenerator()
gen._generate_sine_wave(duration_sec=10.0, frequency=440.0)

# Save to file
import soundfile as sf
sf.write("test.wav", gen.audio_data, 16000)
```

## Understanding Results

### Summary Metrics

| Metric | Description |
|--------|-------------|
| `total_connections_attempted` | Total connection attempts |
| `total_connections_successful` | Successful connections |
| `success_rate` | Percentage of successful connections |
| `total_frames_sent` | Audio frames sent |
| `total_errors` | Total error count |

### Performance Metrics

| Metric | Description |
|--------|-------------|
| `avg_connect_time_ms` | Average time to establish connection |
| `min_connect_time_ms` | Fastest connection time |
| `max_connect_time_ms` | Slowest connection time |
| `throughput_frames_per_sec` | Frame sending rate |
| `throughput_mbps` | Data throughput |

## Troubleshooting

### Connection Refused

```
Connection 0: connect error - HTTP error: Cannot connect to host localhost:8000
```

**Solution**: Ensure your Pipecat server is running at the specified host:port.

### Bot Not Ready

```
Connection timed out waiting for bot-ready
```

**Solution**: Increase `pipeline_init_delay` in config (some bots need more startup time):

```bash
export PIPECAT_PIPELINE_INIT_DELAY=3.0
```

### Too Many Retries

**Solution**: Adjust retry settings:

```yaml
retry:
  max_retries: 5
  retry_delay: 2.0
  retry_backoff_multiplier: 1.5
```

### Debug Mode

For detailed logging:

```bash
pipecat-load-test -v sustained
```

Or set environment:

```bash
export PIPECAT_LOG_LEVEL=DEBUG
```

## Requirements

- Python 3.10+
- A running Pipecat server with RTVI protocol support

## License

BSD-2-Clause
