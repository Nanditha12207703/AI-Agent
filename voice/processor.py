"""
voice/processor.py
------------------
Speech-to-text processing using OpenAI Whisper.

Supports:
  • File-based transcription (uploaded audio)
  • Real-time microphone recording + transcription
  • VAD (voice activity detection) for auto-stop recording
"""

import io
import os
import wave
import tempfile
import asyncio
from typing import Optional, BinaryIO
from pathlib import Path
from loguru import logger

from config.settings import settings


# Supported audio formats
SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".ogg",
    ".flac", ".webm", ".mpeg", ".mpga"
}


class WhisperTranscriber:
    """
    Wrapper around OpenAI Whisper for speech-to-text.
    Lazy-loads the model on first use.
    """

    def __init__(self, model_size: str = None):
        self.model_size = model_size or settings.whisper_model
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                import whisper
                logger.info(f"Loading Whisper model: {self.model_size}")
                self._model = whisper.load_model(self.model_size)
                logger.info("Whisper model loaded successfully")
            except ImportError:
                raise ImportError(
                    "openai-whisper is not installed. "
                    "Run: pip install openai-whisper"
                )
        return self._model

    def transcribe_file(self, audio_path: str,
                         language: str = None) -> dict:
        """
        Transcribe an audio file.
        Returns dict with 'text', 'language', 'segments'.
        """
        model = self._load_model()

        options = {}
        if language:
            options["language"] = language

        logger.info(f"Transcribing: {audio_path}")
        result = model.transcribe(audio_path, **options, fp16=False)
        logger.info(f"Transcription complete: {len(result['text'])} chars")
        return result

    def transcribe_bytes(self, audio_bytes: bytes,
                          suffix: str = ".wav",
                          language: str = None) -> str:
        """Transcribe raw audio bytes (e.g., from HTTP upload)."""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            result = self.transcribe_file(tmp_path, language=language)
            return result.get("text", "").strip()
        finally:
            os.unlink(tmp_path)

    async def transcribe_bytes_async(self, audio_bytes: bytes,
                                      suffix: str = ".wav") -> str:
        """Async wrapper for transcribe_bytes."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.transcribe_bytes, audio_bytes, suffix
        )


class RealtimeVoiceRecorder:
    """
    Records audio from the default microphone and returns a transcription.
    Uses webrtcvad for voice activity detection (auto-stop on silence).

    NOTE: This runs locally on the server. For browser-based real-time
    recording, audio should be captured client-side and POSTed as a file.
    """

    def __init__(self, transcriber: WhisperTranscriber,
                  sample_rate: int = 16000,
                  silence_duration_s: float = 2.0):
        self.transcriber = transcriber
        self.sample_rate = sample_rate
        self.silence_duration_s = silence_duration_s

    def record_and_transcribe(self) -> str:
        """
        Record until silence detected, then transcribe.
        Requires sounddevice, soundfile, webrtcvad.
        """
        try:
            import sounddevice as sd
            import soundfile as sf
            import webrtcvad

            vad = webrtcvad.Vad(2)  # Aggressiveness 0-3
            chunk_duration_ms = 30
            chunk_samples = int(self.sample_rate * chunk_duration_ms / 1000)

            frames = []
            silent_chunks = 0
            max_silent_chunks = int(
                self.silence_duration_s * 1000 / chunk_duration_ms
            )

            logger.info("Recording... (speak now)")

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=chunk_samples,
            ) as stream:
                while True:
                    audio_chunk, _ = stream.read(chunk_samples)
                    raw_bytes = audio_chunk.tobytes()
                    frames.append(raw_bytes)

                    is_speech = vad.is_speech(raw_bytes, self.sample_rate)
                    if not is_speech:
                        silent_chunks += 1
                    else:
                        silent_chunks = 0

                    if silent_chunks >= max_silent_chunks and len(frames) > 10:
                        logger.info("Silence detected – stopping recording")
                        break

            # Write WAV to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                with wave.open(tmp.name, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(b"".join(frames))
                tmp_path = tmp.name

            try:
                result = self.transcriber.transcribe_file(tmp_path)
                return result.get("text", "").strip()
            finally:
                os.unlink(tmp_path)

        except ImportError as e:
            raise ImportError(
                f"Realtime recording requires: sounddevice, soundfile, webrtcvad. {e}"
            )


# ── Singleton ─────────────────────────────────────────────────────────────────

_transcriber: Optional[WhisperTranscriber] = None


def get_transcriber() -> WhisperTranscriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber()
    return _transcriber
