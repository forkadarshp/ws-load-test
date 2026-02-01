FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY pipecat_load_tester/ ./pipecat_load_tester/

# Install the package with all optional dependencies
RUN pip install --no-cache-dir -e ".[all]"

# Create directory for results
RUN mkdir -p /results

# Default command shows help
ENTRYPOINT ["pipecat-load-test"]
CMD ["--help"]
