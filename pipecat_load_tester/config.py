"""Configuration management for Pipecat Load Tester.

Supports:
- YAML configuration files
- Environment variables
- CLI argument overrides
- Sensible defaults
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# Try to import yaml, fallback gracefully
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# Default configuration values
DEFAULTS = {
    # Server settings
    "host": "localhost:8000",
    "connect_endpoint": "/connect",
    "rtvi_client_version": "0.4.1",

    # Audio settings
    "sample_rate": 16000,
    "channels": 1,
    "bit_depth": 16,
    "chunk_duration_ms": 60,
    "default_audio_frequency": 440.0,
    "default_audio_duration": 5.0,

    # Connection settings
    "websocket_max_size": 10 * 1024 * 1024,  # 10MB
    "websocket_ping_interval": 20,
    "websocket_ping_timeout": 20,
    "pipeline_init_delay": 1.5,  # seconds to wait for pipeline init
    "connection_timeout": 30.0,  # seconds
    "disconnect_timeout": 1.0,

    # Retry settings
    "max_retries": 3,
    "retry_delay": 1.0,
    "retry_backoff_multiplier": 2.0,

    # Test defaults
    "default_connections": 10,
    "default_duration": 60,
    "default_output": "results.json",

    # Logging
    "log_level": "INFO",
    "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",

    # API server
    "api_host": "0.0.0.0",
    "api_port": 8080,
    "session_timeout": 300,  # 5 minutes idle timeout
    "max_sessions": 100,
}


@dataclass
class PipecatConfig:
    """Configuration for Pipecat Load Tester."""

    # Server settings
    host: str = DEFAULTS["host"]
    connect_endpoint: str = DEFAULTS["connect_endpoint"]
    rtvi_client_version: str = DEFAULTS["rtvi_client_version"]

    # Audio settings
    sample_rate: int = DEFAULTS["sample_rate"]
    channels: int = DEFAULTS["channels"]
    bit_depth: int = DEFAULTS["bit_depth"]
    chunk_duration_ms: int = DEFAULTS["chunk_duration_ms"]
    default_audio_frequency: float = DEFAULTS["default_audio_frequency"]
    default_audio_duration: float = DEFAULTS["default_audio_duration"]

    # Connection settings
    websocket_max_size: int = DEFAULTS["websocket_max_size"]
    websocket_ping_interval: int = DEFAULTS["websocket_ping_interval"]
    websocket_ping_timeout: int = DEFAULTS["websocket_ping_timeout"]
    pipeline_init_delay: float = DEFAULTS["pipeline_init_delay"]
    connection_timeout: float = DEFAULTS["connection_timeout"]
    disconnect_timeout: float = DEFAULTS["disconnect_timeout"]

    # Retry settings
    max_retries: int = DEFAULTS["max_retries"]
    retry_delay: float = DEFAULTS["retry_delay"]
    retry_backoff_multiplier: float = DEFAULTS["retry_backoff_multiplier"]

    # Test defaults
    default_connections: int = DEFAULTS["default_connections"]
    default_duration: int = DEFAULTS["default_duration"]
    default_output: str = DEFAULTS["default_output"]

    # Logging
    log_level: str = DEFAULTS["log_level"]
    log_format: str = DEFAULTS["log_format"]

    # API server
    api_host: str = DEFAULTS["api_host"]
    api_port: int = DEFAULTS["api_port"]
    session_timeout: int = DEFAULTS["session_timeout"]
    max_sessions: int = DEFAULTS["max_sessions"]

    # Audio file (optional)
    audio_file: Optional[str] = None

    @classmethod
    def from_env(cls) -> "PipecatConfig":
        """Create config from environment variables.

        Environment variables are prefixed with PIPECAT_.
        Example: PIPECAT_HOST=localhost:9000
        """
        config = cls()

        env_mappings = {
            "PIPECAT_HOST": "host",
            "PIPECAT_CONNECT_ENDPOINT": "connect_endpoint",
            "PIPECAT_RTVI_VERSION": "rtvi_client_version",
            "PIPECAT_SAMPLE_RATE": ("sample_rate", int),
            "PIPECAT_CHUNK_DURATION_MS": ("chunk_duration_ms", int),
            "PIPECAT_PIPELINE_INIT_DELAY": ("pipeline_init_delay", float),
            "PIPECAT_CONNECTION_TIMEOUT": ("connection_timeout", float),
            "PIPECAT_MAX_RETRIES": ("max_retries", int),
            "PIPECAT_RETRY_DELAY": ("retry_delay", float),
            "PIPECAT_LOG_LEVEL": "log_level",
            "PIPECAT_API_HOST": "api_host",
            "PIPECAT_API_PORT": ("api_port", int),
            "PIPECAT_AUDIO_FILE": "audio_file",
        }

        for env_var, mapping in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                if isinstance(mapping, tuple):
                    attr_name, type_fn = mapping
                    setattr(config, attr_name, type_fn(value))
                else:
                    setattr(config, mapping, value)

        return config

    @classmethod
    def from_yaml(cls, path: str) -> "PipecatConfig":
        """Load config from YAML file."""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is required for YAML config. Install with: pip install pyyaml")

        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data or {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipecatConfig":
        """Create config from dictionary."""
        config = cls()

        # Flatten nested dictionaries
        flat_data = {}
        for key, value in data.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat_data[sub_key] = sub_value
            else:
                flat_data[key] = value

        # Apply values
        for key, value in flat_data.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "PipecatConfig":
        """Load config with priority: CLI args > env vars > config file > defaults.

        Args:
            config_path: Path to YAML config file.

        Returns:
            Merged configuration.
        """
        # Start with defaults
        config = cls()

        # Load from config file if provided
        if config_path and Path(config_path).exists():
            file_config = cls.from_yaml(config_path)
            config = cls._merge(config, file_config)
        else:
            # Try default config locations
            default_paths = [
                Path("pipecat-config.yaml"),
                Path("pipecat-config.yml"),
                Path.home() / ".pipecat" / "config.yaml",
            ]
            for path in default_paths:
                if path.exists():
                    file_config = cls.from_yaml(str(path))
                    config = cls._merge(config, file_config)
                    break

        # Override with environment variables
        env_config = cls.from_env()
        config = cls._merge(config, env_config)

        return config

    @classmethod
    def _merge(cls, base: "PipecatConfig", override: "PipecatConfig") -> "PipecatConfig":
        """Merge two configs, with override taking precedence for non-default values."""
        result = cls()

        for field_name in base.__dataclass_fields__:
            base_value = getattr(base, field_name)
            override_value = getattr(override, field_name)
            default_value = DEFAULTS.get(field_name)

            # Use override value if it's different from default
            if override_value != default_value and override_value is not None:
                setattr(result, field_name, override_value)
            else:
                setattr(result, field_name, base_value)

        return result

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.host:
            errors.append("host is required")

        if self.sample_rate not in [8000, 16000, 22050, 44100, 48000]:
            errors.append(f"sample_rate {self.sample_rate} is not a standard audio rate")

        if self.chunk_duration_ms < 10 or self.chunk_duration_ms > 500:
            errors.append(f"chunk_duration_ms {self.chunk_duration_ms} should be between 10-500ms")

        if self.max_retries < 0:
            errors.append("max_retries must be >= 0")

        if self.pipeline_init_delay < 0:
            errors.append("pipeline_init_delay must be >= 0")

        if self.audio_file and not Path(self.audio_file).exists():
            errors.append(f"audio_file '{self.audio_file}' does not exist")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    def setup_logging(self):
        """Configure logging based on config."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format=self.log_format,
        )


def get_config(config_path: Optional[str] = None) -> PipecatConfig:
    """Get configuration singleton."""
    return PipecatConfig.load(config_path)
