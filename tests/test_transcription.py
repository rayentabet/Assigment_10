import pytest

from app import transcription


@pytest.mark.asyncio
async def test_transcribe_audio_rejects_empty_bytes() -> None:
    with pytest.raises(ValueError, match="empty"):
        await transcription.transcribe_audio(b"")


@pytest.mark.asyncio
async def test_transcribe_audio_rejects_oversized_file(monkeypatch) -> None:
    monkeypatch.setattr(transcription, "MAX_AUDIO_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        await transcription.transcribe_audio(b"x" * 11)


@pytest.mark.asyncio
async def test_transcribe_audio_runs_the_model_in_a_thread(monkeypatch) -> None:
    calls = []

    def fake_transcribe_sync(audio_bytes: bytes) -> str:
        calls.append(audio_bytes)
        return "hello robot"

    monkeypatch.setattr(transcription, "_transcribe_sync", fake_transcribe_sync)

    result = await transcription.transcribe_audio(b"fake-audio-bytes")

    assert result == "hello robot"
    assert calls == [b"fake-audio-bytes"]
