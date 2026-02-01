"""Audio generation and chunking for load testing."""
import numpy as np
from typing import Iterator, Optional
import io


class AudioGenerator:
    """Generates PCM audio chunks from WAV files or synthetic audio."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    BIT_DEPTH = 16
    CHUNK_DURATION_MS = 60
    CHUNK_SIZE_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 960 samples
    CHUNK_SIZE_BYTES = CHUNK_SIZE_SAMPLES * 2  # 1920 bytes

    def __init__(self, audio_file_path: Optional[str] = None):
        """
        Initialize audio generator.
        
        Args:
            audio_file_path: Path to WAV file. If None, generates sine wave.
        """
        self.audio_file_path = audio_file_path
        self.audio_data: Optional[np.ndarray] = None
        self.sample_rate: int = self.SAMPLE_RATE

        if audio_file_path:
            self._load_audio()
        else:
            self._generate_sine_wave()

    def _load_audio(self):
        """Loads and preprocesses audio file."""
        import soundfile as sf
        data, sr = sf.read(self.audio_file_path, dtype='int16')

        # Convert to mono if stereo
        if len(data.shape) > 1:
            data = data.mean(axis=1).astype('int16')

        # Resample if not 16kHz
        if sr != self.SAMPLE_RATE:
            from scipy import signal
            num_samples = int(len(data) * self.SAMPLE_RATE / sr)
            data = signal.resample(data, num_samples).astype('int16')

        self.audio_data = data

    def _generate_sine_wave(self, duration_sec: float = 5.0, frequency: float = 440.0):
        """Generates a sine wave for testing."""
        num_samples = int(self.SAMPLE_RATE * duration_sec)
        t = np.linspace(0, duration_sec, num_samples, dtype=np.float32)
        # Generate sine wave and convert to int16
        wave = np.sin(2 * np.pi * frequency * t) * 0.5
        self.audio_data = (wave * 32767).astype(np.int16)

    def generate_chunks(self, loop: bool = False) -> Iterator[bytes]:
        """
        Yields audio chunks of 60ms (1920 bytes).

        Args:
            loop: If True, loops audio indefinitely.

        Yields:
            bytes: Raw PCM data (1920 bytes per chunk).
        """
        if self.audio_data is None:
            raise ValueError("Audio not loaded")

        while True:
            for i in range(0, len(self.audio_data), self.CHUNK_SIZE_SAMPLES):
                chunk = self.audio_data[i:i + self.CHUNK_SIZE_SAMPLES]

                # Pad last chunk if necessary
                if len(chunk) < self.CHUNK_SIZE_SAMPLES:
                    chunk = np.pad(chunk, (0, self.CHUNK_SIZE_SAMPLES - len(chunk)), mode='constant')

                yield chunk.tobytes()

            if not loop:
                break

    @classmethod
    def from_bytes(cls, audio_bytes: bytes, sample_rate: int = 16000) -> 'AudioGenerator':
        """Creates AudioGenerator from raw PCM bytes."""
        instance = cls.__new__(cls)
        instance.audio_file_path = "<bytes>"
        instance.audio_data = np.frombuffer(audio_bytes, dtype='int16')
        instance.sample_rate = sample_rate
        return instance

    def get_duration(self) -> float:
        """Returns audio duration in seconds."""
        if self.audio_data is None:
            return 0.0
        return len(self.audio_data) / self.SAMPLE_RATE

    def get_total_chunks(self) -> int:
        """Returns total number of chunks."""
        if self.audio_data is None:
            return 0
        return (len(self.audio_data) + self.CHUNK_SIZE_SAMPLES - 1) // self.CHUNK_SIZE_SAMPLES
