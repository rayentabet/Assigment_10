"""Local speech-to-text via faster-whisper."""

import asyncio
import os
from functools import lru_cache
from io import BytesIO

# Hugging Face's Xet download backend intermittently fails with a CAS
# middleware error in this environment; disabling it falls back to the
# plain HTTP downloader. Must be set before the first model download.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from faster_whisper import WhisperModel  # noqa: E402

from app.config import settings

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25MB is generous for a single voice message.


@lru_cache(maxsize=1)
def _get_model() -> WhisperModel:
    """Load the local Whisper model once and reuse it across requests."""

    return WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def _transcribe_sync(audio_bytes: bytes) -> str:
    model = _get_model()
    segments, _info = model.transcribe(BytesIO(audio_bytes), beam_size=5)
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe an audio clip to text with the local Whisper model.

    Runs in a worker thread: faster-whisper's transcribe() is a blocking,
    CPU-bound call, and awaiting it directly would stall the event loop for
    every other in-flight request.
    """

    if not audio_bytes:
        raise ValueError("Audio file is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError("Audio file is too large (max 25MB).")

    return await asyncio.to_thread(_transcribe_sync, audio_bytes)
